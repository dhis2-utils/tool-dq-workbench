from app.web.routes.edit_integrity_stage import _build_de_payload


def test_integrity_de_uses_last_in_period_so_zero_counts_do_not_show_old_values():
    payload = _build_de_payload({
        'code': 'VRGS',
        'name': 'validation_rule_groups_scarce',
        'displayName': 'Validation rule should have at least two members.',
    })

    assert payload['aggregationType'] == 'LAST_IN_PERIOD'
    assert payload['zeroIsSignificant'] is True
    assert payload['code'] == 'MI_VRGS'
    assert payload['valueType'] == 'INTEGER'
