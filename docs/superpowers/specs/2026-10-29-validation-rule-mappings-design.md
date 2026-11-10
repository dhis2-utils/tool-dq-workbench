# Per-Rule Validation Counts (Rule Mappings) — Design Spec

## Goal

Let a `validation_rules` stage store violation counts **per validation rule** (or per ad-hoc set of rules)
in DHIS2 data elements, without creating a validation rule group for each rule.

## Context

A client wants a violation count for each validation rule. Today a `validation_rules` stage maps one
validation rule group (`validation_rule_group`) onto one data element (`destination_data_element`), so a
per-rule count needs a one-rule group per rule — a lot of metadata that only exists to work around the API,
and potentially hundreds of stages.

DHIS2 core is gaining an optional `vr` parameter on `POST /api/dataAnalysis/validationRules`
(DHIS2-22371, backported to 2.41 in `feat/DHIS2-22371-single-validation-rule-analysis-2.41`):

- `vr`: a JSON list of validation rule UIDs, at most **50** per request
- `vr` and `vrg` together → 400; unknown rule UIDs in `vr` → 404 listing the missing ids
- an unknown `vrg` now → 404 (previously it silently evaluated every rule in the system)
- `vr` resolves periods exactly like `vrg` (`periodService.getPeriodsBetweenDates`), so a rule gives the
  same results whether selected via `vr` or via a group containing it

Each result row already carries `validationRuleId`, `organisationUnitId` and `periodId`.

## Scope

- **In:** CLI / analyzer behaviour, config structure and structural validation.
- **Out (later):** web UI for creating/editing mappings. The UI must not corrupt mapping stages in the
  meantime (see §5).
- **Unchanged:** group-based stages (`validation_rule_group` + `destination_data_element`) behave exactly as
  today.

## Design

### 1. Config shape

A `validation_rules` stage uses **either** the group form **or** the new `rule_mappings` form — never both.

```yaml
- name: HMIS per-rule counts
  type: validation_rules
  params:
    destination_dataset: YJmdEDTe6Em
    duration: 12 months
    level: 2
    aggregation_level: 3          # optional, as today
    max_results: 5000             # optional, as today
    rule_mappings:
      - validation_rule: DjYp4akRsCn
        data_element: aaaaaaaaaaa
      - validation_rule: KEncIyxziLd
        data_element: aaaaaaaaaaa   # many rules -> one DE: counts are summed (ad-hoc group)
      - validation_rule: KEncIyxziLd
        data_element: bbbbbbbbbbb   # one rule -> many DEs: counted in each
```

Semantics:

- Each entry is a (rule, data element) pair. A data element's value for an org unit/period is the number of
  violations of all rules mapped to it.
- **Many-to-one** is allowed (decided): several rules feeding one data element act as an ad-hoc group.
- **One-to-many** is allowed (decided): a rule may feed several data elements and is counted in each.
- Duplicate (rule, data element) pairs are a config error (they would double count).

### 2. Structural validation (`ConfigManager._validate_stage_params`)

For `validation_rules` stages:

- `level` and `duration` are always required.
- Exactly one of:
  - group form: `validation_rule_group` **and** `destination_data_element` (as today), or
  - mapping form: `rule_mappings`, a non-empty list.
- Specifying `rule_mappings` together with `validation_rule_group` or `destination_data_element` is an error.
- Each mapping must be a dict with non-empty string `validation_rule` and `data_element`.
- No duplicate (`validation_rule`, `data_element`) pairs.
- `_validate_aggregation_level` applies unchanged.

Errors use the existing `ValueError` style naming the stage, e.g.
`"Stage 'X': rule_mappings cannot be combined with validation_rule_group/destination_data_element"`.

No extra runtime checks against the server (rule/DE existence, DE membership in `destination_dataset`) —
group stages don't do this today, and the server reports unknown rules with a 404 (§3) and unassigned
DEs via the import summary.

### 3. Analysis requests (`ValidationRuleAnalyzer.run_stage`)

For a mapping-form stage:

1. Collect the distinct rule UIDs from `rule_mappings`, sorted, and split them into batches of at most
   `MAX_RULES_PER_REQUEST = 50` (the server limit).
2. For each org unit at `level` (or `stage['organisation_unit']`, as today) and each batch, POST
   `/api/dataAnalysis/validationRules` with `vr: [batch]` instead of `vrg`. All other body fields
   (`ou`, `startDate`, `endDate`, `maxResults`, `persist: False`, `notification: False`) as today.
   Requests share the existing semaphore.
3. Count violations per (rule, org unit, period).
4. **Unsupported-server guard:** if a response contains any row whose `validationRuleId` is not in the
   requested batch, the server ignored `vr` (pre-DHIS2-22371 build, which falls back to evaluating all
   rules). Treat that request as failed with an error like
   `"Server returned results for rules not requested — it does not support 'vr' (requires DHIS2-22371)"`.
   Never write counts from such a response.
5. Fan out to data values: for each mapping (rule → DE), each (org unit, period) count of that rule adds to
   the (DE, org unit, period) total. Output values use `self.default_coc` and the same dict shape as today.

Group-form stages keep the current single `vrg` request per org unit.

The same per-request result handling (exceptions collected into `errors`) applies to both forms; a failed
batch adds an error and contributes no values.

**Delete safety when a request fails:** if any analysis request for the stage failed, existing values for
that stage must not be deleted on the basis of missing results (a failed batch would otherwise wipe
those rules' counts). Rule (decided, applies to **both** group and mapping forms): when any analysis
request for the stage failed, return no deletions — upserts still go through, and the skipped deletion is
reported as a stage error so the run summary explains it. Counts are only wiped when the stage has
complete results.

### 4. Existing values, rollup, classification

- `fetch_existing_datvalues` / `data_values_urls_for_orgunits` must fetch existing values for **all**
  destination data elements of the stage: the single `destination_data_element` for group form, or the
  distinct data elements in `rule_mappings`. `/api/dataValueSets` accepts repeated `dataElement`
  parameters; chunk the data elements (e.g. 50 per URL) to keep URLs a sane length.
- `rollup_to_level` already keys on `dataElement`, so `aggregation_level` works per data element unchanged.
- `classify_data` already keys on (dataElement, orgUnit, period, coc) — unchanged. Values for a rule that
  no longer violates are deleted; changed counts are upserted (existing behaviour).
- `destination_dataset` tagging (`_dataset`) unchanged.

### 5. Web UI guard (until mapping UI exists)

- The stage list must render mapping-form stages without errors (show them; no group name available).
- The validation-rule stage edit route must not open a mapping-form stage in the group form, because saving
  it would write empty `validation_rule_group`/`destination_data_element` alongside `rule_mappings`.
  Instead redirect back with a flash message: "This stage uses rule mappings and can only be edited in the
  configuration file for now."
- Running a mapping-form stage from the UI goes through the analyzer and should just work.

### 6. Truncation warning fix (both forms)

`_fetch_validation_rule_analysis_async` only warns when `len(response_data) == max_results`. DHIS2 overshoots
`maxResults` (observed: 758 rows returned for `maxResults: 500`, with most violations missing). Change to
`>=` and surface it as a stage error (not just a log line) so the run summary shows it.

## Testing

Unit tests (no live server), in `tests/test_rule_analyzer.py` and a config-validation test module:

- config: valid mapping form; both forms together rejected; empty list rejected; malformed entries
  rejected; duplicate pair rejected; group form unchanged.
- batching: 120 distinct rules → 3 requests (50/50/20) per org unit, with correct `vr` bodies and no `vrg`.
- fan-out: many-to-one sums; one-to-many counts in each DE; rollup with `aggregation_level` per DE.
- unsupported-server guard: response containing an unrequested rule → stage error, no values from it.
- delete safety: a failed batch (mapping form) or failed org unit request (group form) → no deletions returned, error recorded.
- existing values fetched for all mapped DEs (chunked URLs).
- truncation: `len == max_results` and `len > max_results` both produce a stage error.
- web: edit route redirects for a mapping-form stage; index renders it.

## Left to the builder

- Function/helper names and how the two request forms are factored.
- Exact error/flash wording beyond the examples above.
- Chunk size for existing-value URLs.
