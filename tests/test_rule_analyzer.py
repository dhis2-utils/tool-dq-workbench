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
