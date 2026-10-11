# tests/test_org_unit_filter.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.api_utils import Dhis2ApiUtils
from app.core.org_unit_filter import should_keep_data_value, filter_and_fetch_closed_org_units

@pytest.fixture
def mock_session():
    """
    An aiohttp.ClientSession stand-in whose .get() is an async context manager. Call the
    .set_response(json_payload) to control what it returns. No real network access is made
    anywhere in this module
    """
    response = AsyncMock()
    response.raise_for_status = MagicMock()

    get_cm = AsyncMock()
    get_cm.__aenter__.return_value = response

    session = MagicMock()
    session.get = MagicMock(return_value=get_cm)
    session.set_response = lambda payload:setattr(response, 'json', AsyncMock(return_value=payload))

    return session

# Representative periods spanning the window, including 202601 specifically
# to catch the "opening date falls inside this period" boundary.
PERIODS = ['202507', '202512', '202601', '202602', '202603', '202606']


def kept_periods(opening_date, closed_date):
    """Helper: which of PERIODS does should_keep_data_value keep, given one
    opening/closed date pair? Returns a set of period strings."""
    return {
        p for p in PERIODS
        if should_keep_data_value({'orgUnit': 'hZpaU5uFSDm', 'period': p}, opening_date, closed_date)
    }


def test_closed_before_window_drops_everything():
    """Org unit was already closed before the window even starts -> nothing
    in the window should be kept."""
    opening_date = '2003-01-16'
    closed_date = '2025-02-16'  # before window_start (202507)

    assert kept_periods(opening_date, closed_date) == set()


def test_closes_during_window_keeps_only_periods_before_closure():
    """Org unit closes partway through the window -> periods up to closure
    kept, periods after dropped."""
    opening_date = '2003-01-16'
    closed_date = '2026-02-16'  # closes during the window, mid-February

    assert kept_periods(opening_date, closed_date) == {'202507', '202512', '202601', '202602'}


def test_opens_and_closes_during_window_keeps_only_the_overlap():
    """Org unit both opens and closes inside the window -> only periods
    overlapping [opening_date, closed_date] are kept, including the exact
    opening month."""
    opening_date = '2025-07-16'  # during window, mid-July -> falls in period 202507
    closed_date = '2026-02-16'   # during window, mid-February

    assert kept_periods(opening_date, closed_date) == {'202507', '202512', '202601', '202602'}


def test_opens_during_window_closes_after_window_keeps_periods_from_opening_onward():
    """Org unit opens partway through the window, and closedDate is set in
    the future beyond the window end (UI allows future dates) -> periods
    from the opening month through the end of the window are kept."""
    opening_date = '2026-01-16'  # during window, mid-January -> falls in period 202601
    closed_date = '2028-02-16'   # after window_end (future-dated)

    assert kept_periods(opening_date, closed_date) == {'202601', '202602', '202603', '202606'}


def test_opens_after_window_drops_everything():
    """Org unit doesn't open until after the window ends entirely (also
    future-dated) -> nothing in the window should be kept."""
    opening_date = '2028-01-16'
    closed_date = '2030-02-16'

    assert kept_periods(opening_date, closed_date) == set()




async def test_closed_org_unit_excluded_via_bulk_lookup(mock_session):
    """
    The bulk org unit lookup used with should_keep_data_value together should
    exclude a post-closure data value before it gets posted
    """
    mock_session.set_response({'organisationUnits': [
        {'id': 'hZpaU5uFSDm', 'openingDate': '2003-01-16', 'closedDate': '2026-02-16'},
    ]})

    before_closure = {'orgUnit': 'hZpaU5uFSDm', 'period': '202512', 'value': '1'}
    after_closure = {'orgUnit': 'hZpaU5uFSDm', 'period': '202604', 'value': '2'}

    kept, dropped = await filter_and_fetch_closed_org_units(
        api_utils=Dhis2ApiUtils('https://dummy-url.com', 'dummy-token'),
        data_values=[before_closure, after_closure],
        session=mock_session,
    )

    assert kept == [before_closure]
    assert dropped == [after_closure]