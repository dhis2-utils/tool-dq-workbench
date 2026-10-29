# Validation Rule Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `validation_rules` stages map individual validation rules onto data elements (`rule_mappings`) using the new DHIS2 `vr` analysis parameter.

**Architecture:** `ConfigManager` accepts either the group form or the mapping form. `ValidationRuleAnalyzer` fetches raw analysis rows per org unit (one `vrg` request, or one `vr` request per batch of ≤50 rules), then turns rows into data values with a counting helper per form. Existing-value lookup, rollup and classification stay keyed on data element. Incomplete results suppress deletions.

**Tech Stack:** Python 3.10, aiohttp, Flask, pytest (no pytest-asyncio — drive coroutines with `asyncio.run`).

**Spec:** `docs/superpowers/specs/2026-10-29-validation-rule-mappings-design.md`

## Global Constraints

- Group-form stages (`validation_rule_group` + `destination_data_element`) keep today's request shape and output.
- `MAX_RULES_PER_REQUEST = 50` (server limit for `vr`).
- Mapping entries are `{validation_rule: <uid>, data_element: <uid>}`; (rule, DE) pairs unique; many-to-one sums; one-to-many counts in each.
- Never write counts from a `vr` response containing a `validationRuleId` that was not requested.
- Any failed or truncated analysis request → no deletions for the stage, plus a stage error saying so.
- Truncation check is `len(rows) >= max_results` and is a stage error.
- Follow existing test style in `tests/test_rule_analyzer.py` (module-level helpers, plain functions).

## Review Focus

- Org unit with zero violations for every mapped rule → no values for it; existing values for it are deleted (only when the stage is complete). Covered in Task 3 `test_run_stage_deletes_vanished_values_when_complete`.
- Mapping stage where every rule batch fails (e.g. old server returning 404/400) → no upserts, no deletions, errors listed. Task 3 `test_run_stage_skips_deletions_when_a_request_fails`.
- `vr` response rows missing `validationRuleId` → treated as malformed and skipped, not counted under `None`. Task 2 `test_count_mapped_violations_skips_rows_without_rule_id`.
- Rule UIDs repeated across mappings → requested once per batch, not duplicated in `vr`. Task 2 `test_rule_batches_dedupes_and_sorts`.
- Mapping stage opened in the web editor → redirect, config file untouched. Task 4.

---

### Task 1: Config validation for `rule_mappings`

**Files:**
- Modify: `app/core/config_loader.py` (`_validate_stage_params`, new `_validate_rule_mappings`)
- Modify: `docs/validation_rule_stages.rst` (new "Rule mappings" section with the YAML example from the spec §1 and its semantics)
- Modify: `config/sample_config.yml` (add one commented-out mapping-form stage)
- Test: `tests/test_rule_analyzer.py`

**Interfaces:**
- Produces: `ConfigManager._validate_rule_mappings(stage: dict) -> None` (staticmethod, raises `ValueError`).

- [ ] **Step 1: Write the failing tests** (reuse `_vr_stage` / `_config_manager`; add a helper `_mapping_stage(mappings, **params)` that builds params `{'rule_mappings': mappings, 'level': 2, 'duration': '3 years', **params}` with no group keys)

```python
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
```

(`MAPPING = {'validation_rule': 'rule0000001', 'data_element': DE}` at module level.)

- [ ] **Step 2: Run** `pytest tests/test_rule_analyzer.py -k "config" -v` — new tests FAIL (mapping stage reported as missing `validation_rule_group`).

- [ ] **Step 3: Implement.** In `_validate_stage_params`, for `validation_rules`: if `'rule_mappings' in params`, call `_validate_rule_mappings(stage)` and require only `['level', 'duration']`; otherwise keep today's required list. `_validate_aggregation_level` runs for both. Error messages name the stage and contain `rule_mappings` (combination/shape errors) or `duplicate` (pairs).

- [ ] **Step 4: Run** `pytest tests/test_rule_analyzer.py -v` — all PASS.

- [ ] **Step 5: Update docs and sample config**, then commit:

```bash
git add app/core/config_loader.py tests/test_rule_analyzer.py docs/validation_rule_stages.rst config/sample_config.yml
git commit -m "feat: Validate rule_mappings in validation rule stages"
```

---

### Task 2: Analysis requests, batching and counting

**Files:**
- Modify: `app/analyzers/rule_analyzer.py`
- Test: `tests/test_rule_analyzer.py`

**Interfaces:**
- Produces (all on `ValidationRuleAnalyzer`):
  - `MAX_RULES_PER_REQUEST = 50` (class constant)
  - `rule_batches(rule_ids: Iterable[str], size: int = MAX_RULES_PER_REQUEST) -> list[list[str]]` — staticmethod; distinct ids, sorted, chunked.
  - `async _fetch_validation_rule_analysis_async(self, session, ou: str, start_date, max_results: int, semaphore, vrg: str | None = None, vr: list[str] | None = None) -> list[dict] | Exception` — returns the raw result rows. Body has `vrg` **or** `vr` (never both). When `vr` is given and any row's `validationRuleId` is not in `vr`, returns `RuntimeError` whose message contains `does not support 'vr'`. No counting, no truncation logging here any more.
  - `count_group_violations(self, rows: list[dict], data_element: str) -> list[dict]` — today's per-(ou, period) counting moved out of the fetch.
  - `count_mapped_violations(self, rows: list[dict], rule_mappings: list[dict]) -> list[dict]` — per (DE, ou, period) totals via the mappings; rows missing `validationRuleId`, `organisationUnitId` or `periodId` are skipped with a warning.
  - Data value dict shape for both: `{'dataElement', 'orgUnit', 'period', 'categoryOptionCombo': self.default_coc, 'value': str(count)}`.

- [ ] **Step 1: Write the failing tests.** Add a fake aiohttp session to the test module:

```python
class _FakeResponse:
    def __init__(self, status, body): self.status, self._body, self.url = status, body, 'fake'
    async def json(self): return self._body
    async def text(self): return str(self._body)
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

class _FakeSession:
    """Records POST bodies; `responder(body) -> (status, json)` decides the reply."""
    def __init__(self, responder): self.responder, self.bodies = responder, []
    def post(self, url, json):
        self.bodies.append(json)
        return _FakeResponse(*self.responder(json))

def _row(rule, ou, period):
    return {'validationRuleId': rule, 'organisationUnitId': ou, 'periodId': period}
```

Tests (drive coroutines with `asyncio.run`, semaphore `asyncio.Semaphore(5)` created inside the coroutine):

```python
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
```

(`_run_fetch(session, **kw)` calls `_analyzer()._fetch_validation_rule_analysis_async(session, 'ou1', date(2026, 1, 1), 500, sem, **kw)` inside `asyncio.run`.)

- [ ] **Step 2: Run** `pytest tests/test_rule_analyzer.py -v` — new tests FAIL (missing attributes / signature).

- [ ] **Step 3: Implement** the interfaces above. Keep `run_stage` working for the group form by calling the new fetch with `vrg=` and `count_group_violations` (full rewiring is Task 3).

- [ ] **Step 4: Run** `pytest -q` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/analyzers/rule_analyzer.py tests/test_rule_analyzer.py
git commit -m "feat: Fetch validation analysis by rule batches and count per mapping"
```

---

### Task 3: `run_stage` wiring, existing values, truncation and delete safety

**Files:**
- Modify: `app/analyzers/rule_analyzer.py` (`run_stage`, `data_values_urls_for_orgunits`)
- Test: `tests/test_rule_analyzer.py`

**Interfaces:**
- Consumes: Task 2 interfaces.
- Produces: `destination_data_elements(params: dict) -> list[str]` (staticmethod; `[destination_data_element]` for group form, distinct sorted DEs from `rule_mappings` otherwise). `data_values_urls_for_orgunits` emits one URL per (org unit, chunk of ≤50 DEs) with repeated `dataElement=` query params. `run_stage` return dict keeps its keys (`dataValues`, `deletions`, `calculated_data_length`, `errors`).

`run_stage` behaviour:
- Group form: one fetch per org unit with `vrg`. Mapping form: one fetch per (org unit, batch from `rule_batches`) with `vr`.
- A request is **incomplete** if it returned an Exception, or `len(rows) >= max_results` (error text contains `truncated` and suggests increasing `max_results`).
- Counting, `aggregation_level` rollup and `_dataset` tagging as today, applied to the combined values.
- If any request was incomplete: `deletions = []` and add an error containing `Skipped deletions`.

- [ ] **Step 1: Write the failing tests.** Stub org units and existing values with `monkeypatch.setattr(analyzer, 'get_organisation_units_at_level', AsyncMock(return_value=['ou1', 'ou2']))` and `fetch_existing_datvalues` likewise; drive `run_stage` with `_FakeSession` via `asyncio.run`.

```python
def test_destination_data_elements_for_both_forms():
    assert ValidationRuleAnalyzer.destination_data_elements({'destination_data_element': DE}) == [DE]
    assert ValidationRuleAnalyzer.destination_data_elements({'rule_mappings': [
        {'validation_rule': 'r1', 'data_element': 'deB'}, {'validation_rule': 'r2', 'data_element': 'deA'},
        {'validation_rule': 'r3', 'data_element': 'deB'}]}) == ['deA', 'deB']

def test_existing_value_urls_repeat_data_element_param_in_chunks():
    # rule_mappings with 60 distinct DEs, organisation_unit=['ou1'] on the stage
    urls = asyncio.run(...data_values_urls_for_orgunits(stage, None, sem))
    assert len(urls) == 2 and urls[0].count('dataElement=') == 50 and urls[1].count('dataElement=') == 10

def test_run_stage_mapping_form_batches_per_org_unit():
    # 120 rules mapped, 2 org units → 6 POSTs, each with vr and no vrg
    assert len(session.bodies) == 6 and all('vr' in b and 'vrg' not in b for b in session.bodies)

def test_run_stage_group_form_unchanged():
    # group stage, 2 org units → 2 POSTs with vrg; values counted per (ou, period) into DE

def test_run_stage_skips_deletions_when_a_request_fails():
    # responder returns 500 for ou2; an existing value for ou2 is not calculated
    assert result['deletions'] == []
    assert any('Skipped deletions' in e for e in result['errors'])
    assert result['dataValues']  # ou1 upserts still present

def test_run_stage_flags_truncation_when_results_reach_or_exceed_max_results():
    # max_results=500 in params; responder returns 758 rows for ou1
    assert any('truncated' in e for e in result['errors']) and result['deletions'] == []

def test_run_stage_deletes_vanished_values_when_complete():
    # all requests succeed; existing value for (deA, ou2, p1) not in results → in deletions
```

- [ ] **Step 2: Run** `pytest tests/test_rule_analyzer.py -k "run_stage or destination or existing_value" -v` — FAIL.

- [ ] **Step 3: Implement** per the behaviour list above.

- [ ] **Step 4: Run** `pytest -q` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/analyzers/rule_analyzer.py tests/test_rule_analyzer.py
git commit -m "feat: Run validation rule stages from rule mappings and guard deletions"
```

---

### Task 4: Web UI guard for mapping-form stages

**Files:**
- Modify: `app/web/routes/edit_validation_rule_stage.py` (right after the `stage.get('type') != 'validation_rules'` check)
- Test: `tests/test_web_index.py`

**Interfaces:**
- Consumes: config with a `rule_mappings` stage (valid per Task 1).

- [ ] **Step 1: Write the failing tests** using a `mapping_config` fixture modelled on `populated_config`, with one mapping-form stage named `Per rule`:

```python
def test_edit_route_redirects_for_rule_mapping_stage(mapping_config):
    app = create_app(mapping_config, skip_validation=True); app.config['TESTING'] = True
    before = open(mapping_config).read()
    with app.test_client() as client:
        resp = client.get('/api/validation-rule-stage/0', follow_redirects=True)
    assert b'rule mappings' in resp.data
    assert open(mapping_config).read() == before

def test_index_lists_rule_mapping_stage(mapping_config):
    # GET '/' → 200 and b'Per rule' in resp.data
```

- [ ] **Step 2: Run** `pytest tests/test_web_index.py -v` — the edit test FAILS (form renders).

- [ ] **Step 3: Implement:** when `'rule_mappings' in stage['params']`, `flash('This stage uses rule mappings and can only be edited in the configuration file for now.', 'warning')` and redirect to `ui.index`. Applies to GET and POST.

- [ ] **Step 4: Run** `pytest -q` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web/routes/edit_validation_rule_stage.py tests/test_web_index.py
git commit -m "feat: Keep rule mapping stages out of the validation stage editor"
```
