from app.analyzers.integrity_analyzer import IntegrityCheckAnalyzer


def _stage(data_element_map):
    return {'params': {
        'dataset': 'ds1',
        'current_period': '20261108',
        'orgunit': 'ou1',
        'data_element_map': data_element_map,
    }}


def _analyzer():
    # process_results needs no server state, so skip __init__
    return IntegrityCheckAnalyzer.__new__(IntegrityCheckAnalyzer)


def test_process_results_skips_check_that_failed_on_server():
    stage = _stage({'check_failed': {'id': 'deFailed'}, 'check_ok': {'id': 'deOk'}})
    results = {
        'check_failed': {'code': 'check_failed', 'count': -1, 'error': 'ERROR: relation does not exist'},
        'check_ok': {'code': 'check_ok', 'count': 3},
    }

    payload = _analyzer().process_results(results, stage)

    assert payload['dataValues'] == [{'dataElement': 'deOk', 'value': '3'}]


def test_process_results_sends_zero_for_check_missing_from_results():
    stage = _stage({'check_missing': {'id': 'deMissing'}})

    payload = _analyzer().process_results({}, stage)

    assert payload['dataValues'] == [{'dataElement': 'deMissing', 'value': '0'}]


def test_process_results_sends_zero_for_blank_count():
    stage = _stage({'check_blank': {'id': 'deBlank'}})
    results = {'check_blank': {'code': 'check_blank', 'count': None}}

    payload = _analyzer().process_results(results, stage)

    assert payload['dataValues'] == [{'dataElement': 'deBlank', 'value': '0'}]
