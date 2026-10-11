# app/core/org_unit_filter.py

from datetime import datetime
from app.core.period_utils import Dhis2PeriodUtils

def _parse_date(date_str):
    if not date_str:
        return None
    return datetime.strptime(date_str[:10], "%Y-%m-%d")

def should_keep_data_value(dv, opening_date, closed_date, period_utils=None):
    """
    Keep a data value if its period overlaps at all with the org unit's open window .
    A period that only partially overlaps (e.g. the org unit opens or closes mid-period)
    still counts as kept, because there could be valid data produced in that period
    """

    period_utils = period_utils or Dhis2PeriodUtils()

    opening = _parse_date(opening_date)
    closed = _parse_date(closed_date)

    period_start = period_utils.get_start_date_from_period(dv['period'])
    period_end = period_utils.get_end_date_from_period(dv['period'])

    if opening and period_end < opening:
        return False
    if closed and period_start > closed:
        return False
    return True

async def filter_and_fetch_closed_org_units(api_utils, data_values, session):
    """Fetch org unit dates for all org units referenced in data_values,
    then keep only the values whose period overlaps that org unit's open
    window (per should_keep_data_value)."""
    if not data_values:
        return [], []

    org_unit_ids = {dv['orgUnit'] for dv in data_values}
    ou_dates = await api_utils.get_organisation_unit_dates_bulk(org_unit_ids, session)

    kept, dropped = [], []
    for dv in data_values:
        ou = ou_dates.get(dv['orgUnit'], {})
        if should_keep_data_value(dv, ou.get('openingDate'), ou.get('closedDate')):
            kept.append(dv)
        else:
            dropped.append(dv)

    return kept, dropped