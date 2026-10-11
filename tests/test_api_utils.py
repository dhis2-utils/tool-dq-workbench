import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import requests

from app.core.api_utils import Dhis2ApiUtils

def _mock_session_with_responses(payloads):
    """An aiohttp.ClientSession stand-in whose .get() returns a different
    payload on each successive call, in the order given. No real network
    access occurs."""
    session = MagicMock()
    call_urls = []

    def fake_get(url, *args, **kwargs):
        call_urls.append(url)
        payload = payloads[len(call_urls) - 1]

        response = AsyncMock()
        response.raise_for_status = MagicMock()
        response.json = AsyncMock(return_value=payload)

        cm = AsyncMock()
        cm.__aenter__.return_value = response
        return cm

    session.get = MagicMock(side_effect=fake_get)
    session.call_urls = call_urls
    return session


async def test_get_organisation_unit_dates_bulk_chunks_large_id_lists():
    """With more org unit IDs than chunk_size, the method should split into
    multiple requests and merge all results into one dict."""
    api = _make_utils()

    org_unit_ids = [f'ou{i:09d}' for i in range(5)]  # 5 fake IDs
    chunk_size = 2  # forces 3 chunks: [2, 2, 1]

    responses = [
        {'organisationUnits': [
            {'id': 'ou000000000', 'openingDate': '2020-01-01', 'closedDate': None},
            {'id': 'ou000000001', 'openingDate': '2020-01-01', 'closedDate': None},
        ]},
        {'organisationUnits': [
            {'id': 'ou000000002', 'openingDate': '2020-01-01', 'closedDate': None},
            {'id': 'ou000000003', 'openingDate': '2020-01-01', 'closedDate': None},
        ]},
        {'organisationUnits': [
            {'id': 'ou000000004', 'openingDate': '2020-01-01', 'closedDate': None},
        ]},
    ]
    mock_session = _mock_session_with_responses(responses)

    result = await api.get_organisation_unit_dates_bulk(org_unit_ids, mock_session, chunk_size=chunk_size)

    # Three separate requests were made, not one giant one
    assert mock_session.get.call_count == 3

    # All five org units ended up in the merged result
    assert set(result.keys()) == set(org_unit_ids)
    assert result['ou000000004']['openingDate'] == '2020-01-01'


async def test_get_organisation_unit_dates_bulk_single_chunk_when_small():
    """With fewer IDs than chunk_size, only one request should be made."""
    api = _make_utils()

    org_unit_ids = ['hZpaU5uFSDm']
    mock_session = _mock_session_with_responses([
        {'organisationUnits': [
            {'id': 'hZpaU5uFSDm', 'openingDate': '2003-01-16', 'closedDate': '2026-02-16'},
        ]}
    ])

    result = await api.get_organisation_unit_dates_bulk(org_unit_ids, mock_session, chunk_size=200)

    assert mock_session.get.call_count == 1
    assert result['hZpaU5uFSDm']['closedDate'] == '2026-02-16'



def _make_utils():
    return Dhis2ApiUtils('https://dhis2.example.org', 'fake-token')


def test_ping_ok():
    """HTTP 200 → ('ok', None)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch('requests.get', return_value=mock_resp):
        status, reason = _make_utils().ping()
    assert status == 'ok'
    assert reason is None


def test_ping_auth_failed():
    """HTTP 401 → ('auth_failed', reason string)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch('requests.get', return_value=mock_resp):
        status, reason = _make_utils().ping()
    assert status == 'auth_failed'
    assert '401' in reason


def test_ping_unreachable():
    """ConnectionError → ('unreachable', reason string)."""
    with patch('requests.get', side_effect=requests.exceptions.ConnectionError('refused')):
        status, reason = _make_utils().ping()
    assert status == 'unreachable'
    assert reason is not None
