import asyncio

import logging
from app.core.api_utils import Dhis2ApiUtils
from urllib.parse import urlencode
from app.core.period_utils import Dhis2PeriodUtils

import requests.exceptions

from app.analyzers.stage_analyzer import StageAnalyzer

class IntegrityCheckAnalyzer(StageAnalyzer):
    def __init__(self, config, base_url, headers):
        super().__init__(config, base_url, headers)

        #Define a period utils instance for this class
        self.api_utils = Dhis2ApiUtils(base_url, d2_token=self.d2_token)
        self.period_utils = Dhis2PeriodUtils()

    async def _prepare_params(self, stage, session, semaphore):
        """Fetch and attach runtime params (data_element_map, current_period, orgunit) to stage."""
        dataset = stage.get('params', {}).get('dataset')
        if not dataset:
            raise ValueError("Dataset must be specified in the stage params")

        de_group = stage.get('params', {}).get('monitoring_group')
        data_element_map = await self.fetch_data_elements_to_monitor(session, {'monitoring_group': de_group}, semaphore)
        stage['params']['data_element_map'] = data_element_map

        period_type = await self.api_utils.fetch_dataset_period_type(dataset, session, semaphore)
        if not period_type:
            raise ValueError(f"Dataset '{dataset}' has no periodType defined")
        supported = {'Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly'}
        if period_type not in supported:
            raise ValueError(
                f"Dataset '{dataset}' has period type '{period_type}' which is not supported by this tool"
            )
        stage['params']['current_period'] = self.period_utils.get_current_period(period_type)

        root_org_unit = self.config['server'].get('root_org_unit')
        if root_org_unit:
            stage['params']['orgunit'] = root_org_unit
        else:
            orgunits = await self.api_utils.get_organisation_units_at_level(1, session, semaphore)
            if not orgunits:
                raise ValueError("No level one organisation unit found")
            if len(orgunits) > 1:
                raise ValueError(
                    "Multiple level 1 organisation units found. "
                    "Set 'root_org_unit' in the server config to specify which one to use."
                )
            stage['params']['orgunit'] = orgunits[0]

    async def trigger_only_async(self, stage, session, semaphore):
        """Prepare params and trigger the DHIS2 integrity job. Returns immediately without waiting."""
        await self._prepare_params(stage, session, semaphore)
        await self._trigger_metadata_integrity_summaries_async(session, stage, semaphore)

    async def collect_results_async(self, stage, session, semaphore):
        """Fetch completed results and build the dataValueSet (call after job finishes)."""
        await self._prepare_params(stage, session, semaphore)
        results = await self._fetch_completed_summaries_async(session, stage, semaphore)
        return self.process_results(results, stage)

    async def run_stage(self, stage, session, semaphore):
        try:
            logging.info(f"Running metadata integrity stage '{stage['name']}'")
            await self._prepare_params(stage, session, semaphore)
            results = await self._fetch_summary_results_async(session, stage, semaphore)
            data_value_set = self.process_results(results, stage)
            return {
                'dataValueSet': data_value_set,
                'errors': []
            }

        except Exception as e:
            logging.error(f"Error running integrity stage '{stage['name']}': {e}")
            return []

    async def fetch_data_elements_to_monitor(self, session, params, semaphore):
        """
        Fetches data elements from the specified group and maps them by normalized code (without 'MI_' prefix).
        """
        url = f'{self.base_url}/api/dataElementGroups'

        if 'monitoring_group' in params:
            fields_to_get = "dataElements[id,code]"
            url = f'{url}/{params["monitoring_group"]}?fields={fields_to_get}'

        async with semaphore:
            async with session.get(url) as response:
                if response.status == 200:
                    payload = await response.json()
                    raw_elements = payload.get("dataElements", [])

                    # Normalize and include both codes
                    normalized_map = {}
                    for de in raw_elements:
                        original_code = de.get("code", "")
                        if original_code.startswith("MI_"):
                            check_code = original_code[3:]  # Strip 'MI_'
                            normalized_map[check_code] = {
                                "id": de["id"],
                                "de_code": original_code,
                                "check_code": check_code,
                                "name": de.get("name", "")
                            }
                    return normalized_map
                else:
                    raise requests.exceptions.RequestException(
                        f"Failed to fetch data elements to monitor: {response.status}")

    async def _trigger_metadata_integrity_summaries_async(self, session, stage, semaphore):
        # POST /api/dataIntegrity/summary?checks=<name1>,<name2>
        check_codes = list(stage.get('params', {}).get("data_element_map", {}).keys())
        url = f'{self.base_url}/api/dataIntegrity/summary'
        if check_codes:
            query = urlencode({'checks': ','.join(check_codes)})
            url = f'{url}?{query}'

        async with semaphore:
            async with session.post(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise requests.exceptions.RequestException(f"Failed to trigger metadata integrity summaries: {response.status}")

    async def _poll_running_summaries_async(self, session,semaphore):
        # GET /api/dataIntegrity/summary/running
        url = f'{self.base_url}/api/dataIntegrity/summary/running'
        async with semaphore:
            async with session.get(url) as response:
                if response.status == 200:
                   response = await response.json()
                   return response
                else:
                    raise requests.exceptions.RequestException(f"Failed to poll running summaries: {response.status}")

    async def _fetch_completed_summaries_async(self, session, stage, semaphore):
        # GET /api/dataIntegrity/summary/completed
        params = stage.get('params', {}).get("data_element_map", {}).keys()
        url = f'{self.base_url}/api/dataIntegrity/summary'
        if params is not None:
            query = urlencode({'checks': ','.join(params)})
            url = f'{url}?{query}'
        async with semaphore:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise requests.exceptions.RequestException(f"Failed to fetch completed summaries: {response.status}")

    async def _fetch_summary_results_async(self, session, stage, semaphore):
        await self._trigger_metadata_integrity_summaries_async(session, stage, semaphore)
        await asyncio.sleep(5)
        running = await self._poll_running_summaries_async(session, semaphore)
        timeout = 600
        while running and timeout > 0:
            await asyncio.sleep(5)
            running = await self._poll_running_summaries_async(session, semaphore)
            timeout -= 5
        results =  await self._fetch_completed_summaries_async(session, stage, semaphore)
        return results

    @staticmethod
    def transform_integrity_check_to_data_value(result, dataelement_uid):
        """Build a single data value entry (dataElement + value only; period/orgUnit go in the payload header)."""
        if result is None:
            return None
        value = result.get("count")
        if value is None or value == "":
            logging.warning(f"Result was blank for {dataelement_uid}")
            return None
        try:
            value_int = int(value)
            if value_int < 0:
                logging.error(f"Value {value} is less than 0 for {dataelement_uid}")
                return None
        except ValueError:
            logging.error(f"Failed to convert '{value}' to int for {dataelement_uid}")
            return None
        return {
            "dataElement": dataelement_uid,
            "value": str(value_int),
        }

    @staticmethod
    def _check_failed(result):
        if not result:
            return False
        try:
            return int(result.get("count")) < 0
        except (TypeError, ValueError):
            return False

    def process_results(self, results, stage):
        """Build a header-style dataValueSet payload with dataSet, period, and orgUnit at the top level.

        Every data element in the monitoring group is always included in the payload, falling back to
        "0" when the API returns null or omits a check entirely. This prevents stale non-zero values
        from persisting across runs.
        """
        params = stage.get('params', {})
        dataset = params.get('dataset')
        current_period = params.get('current_period')
        orgunit = params.get('orgunit')
        data_element_map = params.get('data_element_map')

        # Index API results by check code for fast lookup
        results_by_code = {v.get("code"): v for v in results.values() if v.get("code")}

        data_values = []
        for check_code, data_element in data_element_map.items():
            de_id = data_element.get('id')
            api_result = results_by_code.get(check_code)
            if self._check_failed(api_result):
                # DHIS2 reports a check that threw as count -1; keep the last good value rather than zero it
                logging.error(f"Integrity check '{check_code}' failed on the server, skipping DE {de_id}: "
                              f"{api_result.get('error') or 'no error message'}")
                continue
            data_value = self.transform_integrity_check_to_data_value(api_result, de_id)
            if data_value is None:
                # API returned null/missing — explicitly zero out to avoid stale values
                logging.debug(f"No result for check '{check_code}', sending zero for DE {de_id}")
                data_value = {"dataElement": de_id, "value": "0"}
            data_values.append(data_value)

        return {
            "dataSet": dataset,
            "period": current_period,
            "orgUnit": orgunit,
            "dataValues": data_values,
        }


    def _fetch_existing_integrity_des(self):
        filters = ["name:$like:[MI]"]
        return self.api_utils.fetch_data_elements(filters=filters, fields=["id", "name", "code"])


    def get_integrity_checks_no_data_elements(self):
        checks = self.api_utils.get_metadata_integrity_checks()
        checks = [check for check in checks if not check["isSlow"]]
        des = self._fetch_existing_integrity_des()
        existing_codes = {de["code"][3:] for de in des if de.get("code", "").startswith("MI_")}
        existing_names = {de["name"] for de in des if de.get("name")}
        return [
            check for check in checks
            if check["code"] not in existing_codes
            and f"[MI] {check.get('displayName', '')}" not in existing_names
        ]
