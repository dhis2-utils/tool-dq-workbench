import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.analyzers.rule_analyzer import ValidationRuleAnalyzer
from app.core.config_loader import ConfigManager

DE = 'deUID000001'
COC = 'HllvX50cXC0'


def _analyzer():
    config = {'server': {'base_url': 'https://dhis2.example.org', 'd2_token': 'fake-token'}}
    return ValidationRuleAnalyzer(config, config['server']['base_url'], {})


def _dv(ou, period, value):
    return {'dataElement': DE, 'orgUnit': ou, 'period': period,
            'categoryOptionCombo': COC, 'value': str(value)}


PATHS = {
    'school00001': '/nigeria0001/state000001/lga00000001/ward0000001/school00001',
    'school00002': '/nigeria0001/state000001/lga00000001/ward0000002/school00002',
    'school00003': '/nigeria0001/state000001/lga00000002/ward0000003/school00003',
    'lga00000001': '/nigeria0001/state000001/lga00000001',
    'state000001': '/nigeria0001/state000001',
}


def test_rollup_sums_counts_per_ancestor_and_period():
    values = [_dv('school00001', '2024', 2), _dv('school00002', '2024', 3),
              _dv('school00002', '2025', 1), _dv('school00003', '2024', 4)]

    rolled, skipped = ValidationRuleAnalyzer.rollup_to_level(values, PATHS, 3)

    assert skipped == []
    assert sorted((dv['orgUnit'], dv['period'], dv['value']) for dv in rolled) == [
        ('lga00000001', '2024', '5'),
        ('lga00000001', '2025', '1'),
        ('lga00000002', '2024', '4'),
    ]
    assert all(dv['dataElement'] == DE and dv['categoryOptionCombo'] == COC for dv in rolled)


def test_rollup_keeps_org_unit_already_at_target_level():
    rolled, skipped = ValidationRuleAnalyzer.rollup_to_level([_dv('lga00000001', '2024', 7)], PATHS, 3)

    assert [(dv['orgUnit'], dv['value']) for dv in rolled] == [('lga00000001', '7')]
    assert skipped == []


def test_rollup_skips_org_units_above_target_level_or_without_path():
    values = [_dv('state000001', '2024', 1), _dv('unknown0001', '2024', 1), _dv('school00001', '2024', 2)]

    rolled, skipped = ValidationRuleAnalyzer.rollup_to_level(values, PATHS, 3)

    assert [(dv['orgUnit'], dv['value']) for dv in rolled] == [('lga00000001', '2')]
    assert sorted(dv['orgUnit'] for dv in skipped) == ['state000001', 'unknown0001']


def test_classify_upserts_existing_value_whose_count_changed():
    existing = [_dv('lga00000001', '2024', 2), _dv('lga00000002', '2024', 4)]
    calculated = [_dv('lga00000001', '2024', 1), _dv('lga00000002', '2024', 4)]

    upserts, deletes, _ = _analyzer().classify_data(existing, calculated)

    assert [(dv['orgUnit'], dv['value']) for dv in upserts] == [('lga00000001', '1')]
    assert deletes == []


def test_classify_treats_numerically_equal_values_as_unchanged():
    existing = [{**_dv('lga00000001', '2024', 0), 'value': '3.0'}]
    calculated = [_dv('lga00000001', '2024', 3)]

    upserts, deletes, _ = _analyzer().classify_data(existing, calculated)

    assert upserts == [] and deletes == []


def test_classify_inserts_new_and_deletes_vanished_keys():
    existing = [_dv('lga00000001', '2024', 2)]
    calculated = [_dv('lga00000002', '2024', 1)]

    upserts, deletes, _ = _analyzer().classify_data(existing, calculated)

    assert [dv['orgUnit'] for dv in upserts] == ['lga00000002']
    assert [dv['orgUnit'] for dv in deletes] == ['lga00000001']


def _vr_stage(**params):
    base = {'validation_rule_group': 'vrg00000001', 'destination_data_element': DE,
            'level': 2, 'duration': '3 years'}
    return {'name': 'vr', 'type': 'validation_rules', 'params': {**base, **params}}


def _config_manager():
    config = {'server': {'base_url': 'https://dhis2.example.org', 'd2_token': 'fake-token'}}
    return ConfigManager(None, config, validate_structure=False, validate_runtime=False)


def test_config_accepts_aggregation_level_at_or_below_query_level():
    _config_manager()._validate_stage_params(_vr_stage(aggregation_level=3))
    _config_manager()._validate_stage_params(_vr_stage(aggregation_level=2))


@pytest.mark.parametrize('bad', [1, 0, 'three', True])
def test_config_rejects_aggregation_level_above_query_level_or_not_int(bad):
    with pytest.raises(ValueError, match='aggregation_level'):
        _config_manager()._validate_stage_params(_vr_stage(aggregation_level=bad))


MAPPING = {'validation_rule': 'rule0000001', 'data_element': DE}


def _mapping_stage(mappings, **params):
    return {'name': 'per rule', 'type': 'validation_rules',
            'params': {'rule_mappings': mappings, 'level': 2, 'duration': '3 years', **params}}


def test_config_accepts_rule_mappings_including_many_to_one_and_one_to_many():
    _config_manager()._validate_stage_params(_mapping_stage([
        {'validation_rule': 'rule0000001', 'data_element': 'de000000001'},
        {'validation_rule': 'rule0000002', 'data_element': 'de000000001'},
        {'validation_rule': 'rule0000001', 'data_element': 'de000000002'},
    ]))


@pytest.mark.parametrize('extra', [{'validation_rule_group': 'vrg00000001'}, {'destination_data_element': DE}])
def test_config_rejects_rule_mappings_combined_with_group_form(extra):
    with pytest.raises(ValueError, match='rule_mappings'):
        _config_manager()._validate_stage_params(_mapping_stage([MAPPING], **extra))


@pytest.mark.parametrize('mappings', [[], 'rule0000001', [{'validation_rule': 'rule0000001'}],
                                      [{'validation_rule': '', 'data_element': DE}], ['rule0000001']])
def test_config_rejects_empty_or_malformed_rule_mappings(mappings):
    with pytest.raises(ValueError, match='rule_mappings'):
        _config_manager()._validate_stage_params(_mapping_stage(mappings))


def test_config_rejects_duplicate_rule_mapping_pairs():
    with pytest.raises(ValueError, match='duplicate'):
        _config_manager()._validate_stage_params(_mapping_stage([MAPPING, dict(MAPPING)]))


def test_config_still_requires_group_and_data_element_without_rule_mappings():
    stage = _vr_stage()
    del stage['params']['destination_data_element']
    with pytest.raises(ValueError, match='destination_data_element'):
        _config_manager()._validate_stage_params(stage)


class _FakeResponse:
    def __init__(self, status, body):
        self.status, self._body, self.url = status, body, 'fake'

    async def json(self):
        return self._body

    async def text(self):
        return str(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records POST bodies; `responder(body) -> (status, json)` decides the reply."""

    def __init__(self, responder):
        self.responder, self.bodies = responder, []

    def post(self, url, json):
        self.bodies.append(json)
        return _FakeResponse(*self.responder(json))


def _row(rule, ou, period):
    return {'validationRuleId': rule, 'organisationUnitId': ou, 'periodId': period}


def _run_fetch(session, **kwargs):
    async def run():
        return await _analyzer()._fetch_validation_rule_analysis_async(
            session, 'ou1', date(2026, 1, 1), 500, asyncio.Semaphore(5), **kwargs)
    return asyncio.run(run())


def test_rule_batches_dedupes_and_sorts():
    assert ValidationRuleAnalyzer.rule_batches(['b', 'a', 'b', 'c'], size=2) == [['a', 'b'], ['c']]


def test_rule_batches_default_size_is_50():
    batches = ValidationRuleAnalyzer.rule_batches([f'rule{i:07d}' for i in range(120)])
    assert [len(b) for b in batches] == [50, 50, 20]


def test_fetch_sends_vr_without_vrg():
    session = _FakeSession(lambda body: (200, [_row('r1', 'ou1', '202607')]))
    rows = _run_fetch(session, vr=['r1', 'r2'])
    assert rows == [_row('r1', 'ou1', '202607')]
    assert session.bodies[0]['vr'] == ['r1', 'r2'] and 'vrg' not in session.bodies[0]


def test_fetch_sends_vrg_without_vr():
    session = _FakeSession(lambda body: (200, []))
    _run_fetch(session, vrg='vrg00000001')
    assert session.bodies[0]['vrg'] == 'vrg00000001' and 'vr' not in session.bodies[0]


def test_fetch_rejects_rows_for_unrequested_rules():
    session = _FakeSession(lambda body: (200, [_row('r1', 'ou1', 'p'), _row('other', 'ou1', 'p')]))
    result = _run_fetch(session, vr=['r1'])
    assert isinstance(result, Exception) and "does not support 'vr'" in str(result)


def test_fetch_returns_exception_on_http_error():
    result = _run_fetch(_FakeSession(lambda body: (404, {'message': 'Validation rules not found: x'})), vr=['x'])
    assert isinstance(result, Exception) and '404' in str(result)


def test_count_group_violations_counts_per_org_unit_and_period():
    rows = [_row('r1', 'ou1', 'p1'), _row('r2', 'ou1', 'p1'), _row('r1', 'ou2', 'p1')]
    values = _analyzer().count_group_violations(rows, DE)
    assert sorted((v['orgUnit'], v['value']) for v in values) == [('ou1', '2'), ('ou2', '1')]
    assert all(v['dataElement'] == DE and v['period'] == 'p1' for v in values)


def test_count_mapped_violations_sums_many_to_one_and_fans_out_one_to_many():
    mappings = [{'validation_rule': 'r1', 'data_element': 'deA'},
                {'validation_rule': 'r2', 'data_element': 'deA'},
                {'validation_rule': 'r1', 'data_element': 'deB'}]
    rows = [_row('r1', 'ou1', 'p1'), _row('r2', 'ou1', 'p1'), _row('r3', 'ou1', 'p1')]
    values = _analyzer().count_mapped_violations(rows, mappings)
    assert sorted((v['dataElement'], v['orgUnit'], v['value']) for v in values) == [
        ('deA', 'ou1', '2'), ('deB', 'ou1', '1')]
    assert all(v['categoryOptionCombo'] == COC for v in values)


def test_count_mapped_violations_skips_rows_without_rule_id():
    rows = [{'organisationUnitId': 'ou1', 'periodId': 'p1'}, _row('r1', 'ou1', 'p1')]
    values = _analyzer().count_mapped_violations(rows, [{'validation_rule': 'r1', 'data_element': 'deA'}])
    assert [(v['dataElement'], v['value']) for v in values] == [('deA', '1')]


def _rules_stage(rule_count, data_elements=('deA',), **params):
    mappings = [{'validation_rule': f'rule{i:07d}', 'data_element': data_elements[i % len(data_elements)]}
                for i in range(rule_count)]
    return _mapping_stage(mappings, **params)


def _run_stage(stage, responder, existing=(), org_units=('ou1', 'ou2')):
    analyzer = _analyzer()
    analyzer.get_organisation_units_at_level = AsyncMock(return_value=list(org_units))
    analyzer.fetch_existing_datvalues = AsyncMock(return_value=list(existing))
    session = _FakeSession(responder)

    async def run():
        return await analyzer.run_stage(stage, session, asyncio.Semaphore(5))
    return asyncio.run(run()), session


def test_destination_data_elements_for_both_forms():
    assert ValidationRuleAnalyzer.destination_data_elements({'destination_data_element': DE}) == [DE]
    assert ValidationRuleAnalyzer.destination_data_elements({'rule_mappings': [
        {'validation_rule': 'r1', 'data_element': 'deB'}, {'validation_rule': 'r2', 'data_element': 'deA'},
        {'validation_rule': 'r3', 'data_element': 'deB'}]}) == ['deA', 'deB']


def test_existing_value_urls_repeat_data_element_param_in_chunks():
    stage = _rules_stage(60, data_elements=tuple(f'de{i:09d}' for i in range(60)))
    stage['organisation_unit'] = ['ou1']

    async def run():
        return await _analyzer().data_values_urls_for_orgunits(stage, None, asyncio.Semaphore(5))
    urls = asyncio.run(run())

    assert len(urls) == 2
    assert urls[0].count('dataElement=') == 50 and urls[1].count('dataElement=') == 10
    assert all('orgUnit=ou1' in url and 'children=true' in url for url in urls)


def test_run_stage_mapping_form_batches_per_org_unit():
    result, session = _run_stage(_rules_stage(120), lambda body: (200, [_row(body['vr'][0], body['ou'], 'p1')]))

    assert len(session.bodies) == 6
    assert all('vr' in b and 'vrg' not in b for b in session.bodies)
    assert sorted((dv['orgUnit'], dv['value']) for dv in result['dataValues']) == [('ou1', '3'), ('ou2', '3')]
    assert result['errors'] == []


def test_run_stage_group_form_unchanged():
    result, session = _run_stage(_vr_stage(), lambda body: (200, [_row('r1', body['ou'], 'p1'),
                                                                 _row('r2', body['ou'], 'p1')]))

    assert [b['vrg'] for b in session.bodies] == ['vrg00000001', 'vrg00000001']
    assert all('vr' not in b for b in session.bodies)
    assert sorted((dv['dataElement'], dv['orgUnit'], dv['value']) for dv in result['dataValues']) == [
        (DE, 'ou1', '2'), (DE, 'ou2', '2')]


def _existing(data_element, ou, period, value):
    return {'dataElement': data_element, 'orgUnit': ou, 'period': period,
            'categoryOptionCombo': COC, 'value': str(value)}


def test_run_stage_skips_deletions_when_a_request_fails():
    def responder(body):
        if body['ou'] == 'ou2':
            return 500, {'message': 'boom'}
        return 200, [_row('rule0000000', 'ou1', 'p1')]

    result, _ = _run_stage(_rules_stage(1), responder, existing=[_existing('deA', 'ou2', 'p1', 4)])

    assert result['deletions'] == []
    assert any('Skipped deletions' in e for e in result['errors'])
    assert [(dv['orgUnit'], dv['value']) for dv in result['dataValues']] == [('ou1', '1')]


@pytest.mark.parametrize('returned', [500, 758])
def test_run_stage_flags_truncation_when_results_reach_or_exceed_max_results(returned):
    def responder(body):
        rows = [_row('rule0000000', body['ou'], f'p{i}') for i in range(returned)] if body['ou'] == 'ou1' else []
        return 200, rows

    result, _ = _run_stage(_rules_stage(1, max_results=500), responder,
                           existing=[_existing('deA', 'ou2', 'p1', 1)])

    assert any('truncated' in e for e in result['errors'])
    assert result['deletions'] == []


def test_run_stage_deletes_vanished_values_when_complete():
    result, _ = _run_stage(_rules_stage(1), lambda body: (200, [_row('rule0000000', 'ou1', 'p1')]
                                                           if body['ou'] == 'ou1' else []),
                           existing=[_existing('deA', 'ou2', 'p1', 2)])

    assert [(dv['dataElement'], dv['orgUnit']) for dv in result['deletions']] == [('deA', 'ou2')]
    assert result['errors'] == []
