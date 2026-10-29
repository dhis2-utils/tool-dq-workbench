import asyncio
import logging
from datetime import datetime
from app.analyzers.stage_analyzer import StageAnalyzer

class ValidationRuleAnalyzer(StageAnalyzer):
    MAX_RULES_PER_REQUEST = 50

    def __init__(self, config, base_url, headers):
        super().__init__(config, base_url, headers)
        
    async def data_values_urls_for_orgunits(self,stage,session, semaphore):
        urls = []
        start_date = self.get_start_date(stage)
        params = stage['params']
        data_element = params['destination_data_element']

        organisation_unit = stage.get('organisation_unit')
        if isinstance(organisation_unit, list):
            ous = organisation_unit
        else:
            ous = await self.get_organisation_units_at_level(params['level'], session, semaphore)

        params = {
            'dataElement': data_element,
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': datetime.now().strftime('%Y-%m-%d'),
            'children': 'true'}
        
        for ou in ous:
            params['orgUnit'] = ou
            query_string = '&'.join(f"{key}={value}" for key, value in params.items())
            url = f"{self.base_url}/api/dataValueSets.json?{query_string}"
            urls.append(url)
        return urls

    async def fetch_existing_datvalues(self,stage, session, semaphore):
        urls = await self.data_values_urls_for_orgunits(stage, session, semaphore)
        tasks = [
              self.fetch_datavalues_async(
                session, url, semaphore
            )
            for url in urls
        ]

        results = await asyncio.gather(*tasks)

        data_values = []
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Error fetching data values: {result}")
            elif isinstance(result, dict):
                data_values.extend(result.get('dataValues', []))
            else:
                logging.warning(f"Unexpected result type: {type(result)} from fetch_existing_datvalues")
        return data_values
    

    def _data_value_key(self, dv):
        return dv['dataElement'], dv['orgUnit'], dv['period'], dv.get('categoryOptionCombo', self.default_coc)

    @staticmethod
    def _same_value(a, b):
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return a == b

    def classify_data(self, existing_data_values, calculated_data_values):
        existing_by_key = {self._data_value_key(dv): dv for dv in existing_data_values}
        calculated_by_key = {self._data_value_key(dv): dv for dv in calculated_data_values}

        # New keys, plus existing keys whose count changed (e.g. a school fixed one of two violations)
        upsert_values = [
            dv for key, dv in calculated_by_key.items()
            if key not in existing_by_key or not self._same_value(existing_by_key[key].get('value'), dv.get('value'))
        ]
        delete_values = [dv for key, dv in existing_by_key.items() if key not in calculated_by_key]

        #Return the original length of data
        calculated_data_length = len(calculated_data_values)
        return upsert_values, delete_values, calculated_data_length

    @staticmethod
    def rollup_to_level(data_values, org_unit_paths, level):
        """Sum data values onto each org unit's ancestor at the given hierarchy level.

        Returns (rolled_up_values, skipped_values). Values whose org unit sits above the target level, or
        whose path is unknown, cannot be rolled up and are returned as skipped.
        """
        totals = {}
        templates = {}
        skipped = []
        for dv in data_values:
            path = org_unit_paths.get(dv['orgUnit'])
            ancestors = path.strip('/').split('/') if path else []
            if len(ancestors) < level:
                skipped.append(dv)
                continue
            key = (dv['dataElement'], ancestors[level - 1], dv['period'], dv.get('categoryOptionCombo'))
            totals[key] = totals.get(key, 0) + int(dv['value'])
            templates.setdefault(key, dv)

        rolled_up = [
            {**templates[key], 'orgUnit': key[1], 'value': str(total)}
            for key, total in totals.items()
        ]
        return rolled_up, skipped

    async def fetch_org_unit_paths(self, org_unit_ids, session, semaphore, chunk_size=100):
        ids = sorted(set(org_unit_ids))
        paths = {}
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            url = (f"{self.base_url}/api/organisationUnits.json?filter=id:in:[{','.join(chunk)}]"
                   f"&fields=id,path&paging=false")
            async with semaphore:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json()
            paths.update({ou['id']: ou['path'] for ou in data.get('organisationUnits', [])})
        return paths


    @staticmethod
    def rule_batches(rule_ids, size=None):
        """Split distinct rule UIDs (sorted) into batches the analysis API accepts in one 'vr' request."""
        size = size or ValidationRuleAnalyzer.MAX_RULES_PER_REQUEST
        ids = sorted(set(rule_ids))
        return [ids[i:i + size] for i in range(0, len(ids), size)]

    async def _fetch_validation_rule_analysis_async(self, session, ou, start_date, max_results, semaphore,
                                                    vrg=None, vr=None):
        """Run validation rule analysis for one org unit and return the raw result rows.

        Rules are selected by group (vrg) or by a list of rule UIDs (vr). Errors are returned, not raised.
        """
        url = f'{self.base_url}/api/dataAnalysis/validationRules'
        body = {
            'notification': False,
            'persist': False,
            'ou': ou,
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': datetime.now().strftime('%Y-%m-%d'),
            'maxResults': max_results
        }
        if vr is not None:
            body['vr'] = vr
        else:
            body['vrg'] = vrg

        try:
            async with semaphore:
                logging.debug("Running validation rule analysis for ou '%s' with %s", ou,
                              f"{len(vr)} rules" if vr is not None else f"vrg '{vrg}'")
                logging.debug("Making POST request to URL: %s", url)
                logging.debug("Request body: %s", body)
                async with session.post(url, json=body) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise RuntimeError(f"{response.status} from DHIS2: {response.url} — {text.strip()}")
                    response_data = await response.json()
        except Exception as e:
            logging.error(f"Error fetching validation rule analysis: {e}")
            return e

        if not isinstance(response_data, list):
            logging.warning(f"Expected list from DHIS2 validation API but got {type(response_data)}: {response_data}")
            return []

        if vr is not None:
            # A server without 'vr' support ignores it and evaluates every rule in the system
            unexpected = {row.get('validationRuleId') for row in response_data} - set(vr)
            if unexpected:
                return RuntimeError(
                    f"Server returned results for rules not requested ({len(unexpected)} rules) for ou '{ou}' — "
                    f"it does not support 'vr' (requires DHIS2-22371)")

        return response_data

    def _violation_values(self, counts):
        return [{
            'dataElement': data_element,
            'orgUnit': ou_id,
            'period': period_id,
            'categoryOptionCombo': self.default_coc,
            'value': str(count)
        } for (data_element, ou_id, period_id), count in counts.items()]

    @staticmethod
    def _well_formed(row, keys):
        if all(row.get(key) for key in keys):
            return True
        logging.warning(f"Skipping malformed result: {row}")
        return False

    def count_group_violations(self, rows, data_element):
        counts = {}
        for row in rows:
            if not self._well_formed(row, ('organisationUnitId', 'periodId')):
                continue
            key = (data_element, row['organisationUnitId'], row['periodId'])
            counts[key] = counts.get(key, 0) + 1
        return self._violation_values(counts)

    def count_mapped_violations(self, rows, rule_mappings):
        data_elements_by_rule = {}
        for mapping in rule_mappings:
            data_elements_by_rule.setdefault(mapping['validation_rule'], []).append(mapping['data_element'])

        counts = {}
        for row in rows:
            if not self._well_formed(row, ('validationRuleId', 'organisationUnitId', 'periodId')):
                continue
            for data_element in data_elements_by_rule.get(row['validationRuleId'], []):
                key = (data_element, row['organisationUnitId'], row['periodId'])
                counts[key] = counts.get(key, 0) + 1
        return self._violation_values(counts)
    

    async def run_stage(self, stage, session, semaphore):
        logging.info(f"Running validation rule stage '{stage['name']}'")

        start_date = self.get_start_date(stage)
        params = stage['params']
        vrg = params['validation_rule_group']
        max_results = params.get('max_results', self.config['server'].get('max_results', 500))
        data_element = params['destination_data_element']

        organisation_unit = stage.get('organisation_unit')
        ous = []
        if isinstance(organisation_unit, list):
            ous = organisation_unit
        else:
            ous = await self.get_organisation_units_at_level(params['level'], session, semaphore)

        tasks = [
            self._fetch_validation_rule_analysis_async(
                session, ou, start_date, max_results, semaphore, vrg=vrg
            )
            for ou in ous
        ]

        results_nested = await asyncio.gather(*tasks)
        results = []
        errors = []

        for result in results_nested:
            if isinstance(result, Exception):
                logging.error(f"Validation rule analysis failed: {result}")
                errors.append(str(result))
            elif isinstance(result, list):
                results.extend(self.count_group_violations(result, data_element))
            else:
                msg = f"Unexpected result in validation rule analysis: {type(result)}"
                logging.warning(msg)
                errors.append(msg)

        aggregation_level = params.get('aggregation_level')
        if aggregation_level and results:
            paths = await self.fetch_org_unit_paths([dv['orgUnit'] for dv in results], session, semaphore)
            results, skipped = self.rollup_to_level(results, paths, aggregation_level)
            logging.info(f"Rolled up violations to {len(results)} values at level {aggregation_level}")
            if skipped:
                msg = (f"Skipped {len(skipped)} violation counts in stage '{stage['name']}' for org units above "
                       f"aggregation level {aggregation_level}: {sorted({dv['orgUnit'] for dv in skipped})}")
                logging.warning(msg)
                errors.append(msg)

        destination_dataset = params.get('destination_dataset')
        if destination_dataset:
            for dv in results:
                dv['_dataset'] = destination_dataset

        existing_data_values = await self.fetch_existing_datvalues(stage, session, semaphore)
        upserts, deletions, calculated_data_length = self.classify_data(existing_data_values, results)

        return {
            'dataValues': upserts,
            'deletions': deletions,
            'calculated_data_length' : calculated_data_length,
            'errors': errors
        }

