# tests/test_web_index.py
import os

import pytest
import yaml

from app.web.app import create_app


@pytest.fixture
def blank_config(tmp_path):
    """A config file with an empty server section — simulates first run."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.dump({
        'server': {
            'base_url': '',
            'd2_token': '',
            'logging_level': 'INFO',
            'max_concurrent_requests': 5,
            'max_results': 500,
        },
        'analyzer_stages': [],
    }))
    return str(cfg)


@pytest.fixture
def populated_config(tmp_path):
    """A config file with real (fake) server credentials."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.dump({
        'server': {
            'base_url': 'https://dhis2.example.org',
            'd2_token': 'fake-token',
            'logging_level': 'INFO',
            'max_concurrent_requests': 5,
            'max_results': 500,
        },
        'analyzer_stages': [],
    }))
    return str(cfg)


@pytest.fixture
def client_blank(blank_config):
    app = create_app(blank_config, skip_validation=True)
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def client_populated(populated_config):
    app = create_app(populated_config, skip_validation=True)
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_blank_config_redirects_to_edit_server(client_blank):
    """First run with empty credentials should redirect to the server config page."""
    response = client_blank.get('/', follow_redirects=False)
    assert response.status_code == 302
    assert '/api/edit-server' in response.headers['Location']


def test_blank_config_redirect_shows_welcome_flash(client_blank):
    """The first-run redirect must include the welcome flash message."""
    response = client_blank.get('/', follow_redirects=True)
    assert b'Welcome' in response.data
    assert b'DHIS2 server details' in response.data


def test_populated_config_renders_dashboard(client_populated):
    """A config with real credentials should render the dashboard, not redirect."""
    response = client_populated.get('/', follow_redirects=False)
    assert response.status_code == 200


def test_edit_server_get_with_blank_config(client_blank):
    """GET /api/edit-server must render without crashing when config has empty fields."""
    response = client_blank.get('/api/edit-server')
    assert response.status_code == 200
    assert b'Edit Server Configuration' in response.data


def test_onboarding_post_flow(client_blank):
    """Complete onboarding: fill in credentials via POST, then / renders the dashboard."""
    post_response = client_blank.post('/api/edit-server', data={
        'base_url': 'https://dhis2.example.org',
        'd2_token': 'fake-token',
        'logging_level': 'INFO',
        'max_concurrent_requests': '5',
        'max_results': '500',
        'min_max_bulk_api_disabled': 'false',
    }, follow_redirects=False)
    assert post_response.status_code == 302

    # After saving credentials, visiting / should render the dashboard (not redirect again)
    index_response = client_blank.get('/', follow_redirects=False)
    assert index_response.status_code == 200


def test_edit_server_shows_config_path(client_blank, blank_config):
    """GET /api/edit-server must display the absolute config file path."""
    response = client_blank.get('/api/edit-server')
    assert os.path.abspath(blank_config).encode() in response.data


def test_startup_warning_redirects_to_edit_server(client_blank):
    """STARTUP_WARNING pre-set → 302 redirect to edit-server with flash message."""
    with client_blank.application.app_context():
        client_blank.application.config['STARTUP_WARNING'] = (
            "Could not reach the DHIS2 server — check that your base URL is correct.",
            'warning',
        )
    response = client_blank.get('/', follow_redirects=True)
    assert b'Could not reach' in response.data


def test_startup_warning_cleared_after_first_request(client_blank):
    """STARTUP_WARNING is consumed on first request and not shown on the second."""
    with client_blank.application.app_context():
        client_blank.application.config['STARTUP_WARNING'] = (
            "Could not reach the DHIS2 server — check that your base URL is correct.",
            'warning',
        )
    client_blank.get('/', follow_redirects=True)  # first request consumes it
    response = client_blank.get('/', follow_redirects=True)  # second request
    assert b'Could not reach' not in response.data


def test_startup_warning_fires_before_welcome_redirect(client_blank):
    """STARTUP_WARNING takes priority over the generic 'Welcome' redirect when both apply."""
    with client_blank.application.app_context():
        client_blank.application.config['STARTUP_WARNING'] = (
            "Your API token was rejected.",
            'warning',
        )
    response = client_blank.get('/', follow_redirects=True)
    assert b'rejected' in response.data
    assert b'Welcome' not in response.data


def test_edit_server_resilient_to_unparseable_config(tmp_path):
    """GET /api/edit-server must not crash when the config file has invalid YAML."""
    bad_cfg = tmp_path / "config.yml"
    bad_cfg.write_text(": bad yaml: [unclosed")
    app = create_app(str(bad_cfg), skip_validation=True)
    app.config['TESTING'] = True
    with app.test_client() as client:
        response = client.get('/api/edit-server')
    assert response.status_code == 200
    assert b'Edit Server Configuration' in response.data


def _post_validation_stage(client, url, **extra):
    form = {
        'stage_name': 'Plausibility', 'orgunit_level': '2', 'duration': '3 years',
        'validation_rule_group': 'vrg00000001', 'destination_data_element': 'deUID000001',
        'active': 'on', **extra,
    }
    return client.post(url, data=form)


def test_validation_stage_form_saves_and_clears_aggregation_level(client_populated, populated_config, monkeypatch):
    from app.core.config_loader import ConfigManager
    monkeypatch.setattr(ConfigManager, '_validate_api_token', staticmethod(lambda base_url, token: None))
    _post_validation_stage(client_populated, '/api/validation-rule-stage', aggregation_level='3')
    with open(populated_config) as f:
        params = yaml.safe_load(f)['analyzer_stages'][0]['params']
    assert params['aggregation_level'] == 3

    _post_validation_stage(client_populated, '/api/validation-rule-stage/0', aggregation_level='')
    with open(populated_config) as f:
        params = yaml.safe_load(f)['analyzer_stages'][0]['params']
    assert 'aggregation_level' not in params


@pytest.fixture
def mapping_config(tmp_path, monkeypatch):
    """A config with one validation rule stage that uses rule_mappings."""
    from app.core.config_loader import ConfigManager
    monkeypatch.setattr(ConfigManager, '_validate_api_token', staticmethod(lambda base_url, d2_token: None))
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.dump({
        'server': {
            'base_url': 'https://dhis2.example.org',
            'd2_token': 'fake-token',
            'logging_level': 'INFO',
            'max_concurrent_requests': 5,
            'max_results': 500,
        },
        'analyzer_stages': [{
            'name': 'Per rule',
            'type': 'validation_rules',
            'active': True,
            'params': {'level': 2, 'duration': '12 months',
                       'rule_mappings': [{'validation_rule': 'rule0000001', 'data_element': 'de000000001'}]},
        }],
    }))
    return str(cfg)


def _client_for(config_path):
    app = create_app(config_path, skip_validation=True)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.mark.parametrize('method', ['get', 'post'])
def test_edit_route_redirects_for_rule_mapping_stage(mapping_config, method):
    before = open(mapping_config).read()
    with _client_for(mapping_config) as client:
        resp = getattr(client, method)('/api/validation-rule-stage/0', follow_redirects=True)
    assert b'rule mappings' in resp.data
    assert open(mapping_config).read() == before


def test_index_lists_rule_mapping_stage(mapping_config):
    with _client_for(mapping_config) as client:
        resp = client.get('/')
    assert resp.status_code == 200
    assert b'Per rule' in resp.data
