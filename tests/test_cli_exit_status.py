import sys

import pytest

import app.cli as cli


class _FakeConfigManager:
    def __init__(self, *args, **kwargs):
        self.config = {'server': {}, 'analyzer_stages': []}


def _run_main_with_result(monkeypatch, result):
    class _FakeMonitor:
        def __init__(self, config):
            pass

        async def run_all_stages(self):
            return result

    monkeypatch.setattr(cli, 'ConfigManager', _FakeConfigManager)
    monkeypatch.setattr(cli, 'DataQualityMonitor', _FakeMonitor)
    monkeypatch.setattr(sys, 'argv', ['dq_monitor.py', '--config', 'unused.yml'])
    with pytest.raises(SystemExit) as exit_info:
        cli.run_main()
    return exit_info.value.code


def test_run_main_exits_zero_when_run_is_clean(monkeypatch):
    result = {'errors': [], 'import_summary': {'status': 'OK'}}
    assert _run_main_with_result(monkeypatch, result) == 0


def test_run_main_exits_one_when_a_stage_reports_errors(monkeypatch):
    result = {'errors': ["Skipped deletions of 4632 values in stage 'x'"], 'import_summary': {'status': 'OK'}}
    assert _run_main_with_result(monkeypatch, result) == 1


def test_run_main_exits_one_when_an_import_is_not_ok(monkeypatch):
    result = {'errors': [], 'import_summary': {'status': 'WARNING'}}
    assert _run_main_with_result(monkeypatch, result) == 1


def test_run_main_exits_zero_when_nothing_was_imported(monkeypatch):
    # No upserts or deletes: _merge_import_summaries still reports OK, an empty summary is fine too
    result = {'errors': [], 'import_summary': {}}
    assert _run_main_with_result(monkeypatch, result) == 0
