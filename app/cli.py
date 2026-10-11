import argparse
import asyncio
import logging
import sys
from datetime import datetime
import os

import aiohttp

from app.analyzers.integrity_analyzer import IntegrityCheckAnalyzer
from app.analyzers.outlier_analyzer import OutlierAnalyzer
from app.analyzers.rule_analyzer import ValidationRuleAnalyzer
from app.core.config_loader import ConfigManager
from app.core.api_utils import Dhis2ApiUtils

from app.core.org_unit_filter import filter_and_fetch_closed_org_units


def _format_duration(delta) -> str:
    total = delta.total_seconds()
    if total < 60:
        return f"{total:.1f}s"
    mins, secs = divmod(total, 60)
    return f"{int(mins)}m {secs:.0f}s"


class DataQualityMonitor:
    def __init__(self, config):
        self.config = config

        self.base_url = config['server']['base_url']
        self.d2_token = config['server']['d2_token']
        self.max_concurrent_requests = config['server'].get('max_concurrent_requests', 10)
        self.request_headers = {
            'Authorization': f'ApiToken {self.d2_token}',
            'Content-Type': 'application/json'
        }

        # Map stage types to analyzer instances
        self.analyzers = {
            'outlier': OutlierAnalyzer(config, self.base_url, self.request_headers),
            'validation_rules': ValidationRuleAnalyzer(config, self.base_url, self.request_headers),
            'integrity_checks': IntegrityCheckAnalyzer(config, self.base_url, self.request_headers)
        }

        self.api_utils = Dhis2ApiUtils(self.base_url, self.d2_token)

        log_file = config['server'].get("log_file")
        log_level = config['server'].get("logging_level", "INFO").upper()

        handlers = [logging.StreamHandler(sys.stdout)]
        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handlers.append(logging.FileHandler(log_file))

        # Force reconfiguration so logs appear even if something configured logging earlier
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers,
            force=True,
        )

    async def run_stage(self, session, stage, semaphore):
        try:
            stage_type = stage.get('type')
            if stage_type not in self.analyzers:
                raise ValueError(f"Unsupported stage type: {stage_type}")

            analyzer = self.analyzers[stage_type]
            logging.info(f"Dispatching stage '{stage['name']}' of type '{stage_type}'")
            return await analyzer.run_stage(stage, session, semaphore)

        except Exception as e:
            logging.error(f"Error running stage '{stage.get('name', '<unnamed>')}': {e}")
            return []

    async def run_all_stages(self):
        semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        async with aiohttp.ClientSession(headers=self.request_headers) as session:
            logging.info(f"Running all stages with max {self.max_concurrent_requests} concurrent requests")
            clock_start = datetime.now()
            stage_names = [stage['name'] for stage in self.config['analyzer_stages']]
            tasks = [
                self.run_stage(session, stage, semaphore)
                for stage in self.config['analyzer_stages']
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            combined_import_summary, num_upserts, num_deletes, errors = await self._process_tasks(results, session, stage_names)

            clock_end = datetime.now()
            logging.info("All stages completed")
            logging.info(f"Process took: {clock_end - clock_start}")

        return {
            "errors": errors,
            "data_values_posted": num_upserts,
            "data_values_deleted": num_deletes,
            "duration": _format_duration(clock_end - clock_start),
            "import_summary": combined_import_summary or {}
        }

    async def _process_tasks(self, results, session, stage_names):
        upserts = []
        deletes = []
        integrity_payloads = []  # header-style dataValueSet payloads (e.g. from integrity stages)
        errors = []
        for name, result in zip(stage_names, results):
            if isinstance(result, Exception):
                logging.error(f"Task failed with exception: {result}")
                errors.append(f"{name}: {str(result)}")
            elif isinstance(result, dict):
                upserts.extend(result.get("dataValues", []))
                deletes.extend(result.get("deletions", []))
                errors.extend(result.get("errors", []))
                if result.get("dataValueSet"):
                    integrity_payloads.append(result["dataValueSet"])
            else:
                msg = f"Unexpected result type from stage '{name}': {type(result)}"
                logging.warning(msg)
                errors.append(msg)

        if upserts:
            upserts, dropped_closed = await filter_and_fetch_closed_org_units(
                self.api_utils, upserts, session
            )
            if dropped_closed:
                logging.warning(f"Skipping {len(dropped_closed)} data value(s) for closed org units")
                errors.extend(
                    f"Skipped (org unit closed): {dv['orgUnit']}/{dv['period']}"
                    for dv in dropped_closed
                )

        import_summary = None
        delete_import_summary = None
        integrity_import_summary = None

        if upserts:
            logging.info(f"Posting {len(upserts)} data value upserts")
            try:
                groups = {}
                for dv in upserts:
                    ds = dv.pop('_dataset', None)
                    groups.setdefault(ds, []).append(dv)

                group_summaries = []
                for ds, values in groups.items():
                    payload = {'dataValues': values}
                    if ds:
                        payload['dataSet'] = ds
                    response = await self.api_utils.post_data_value_set(payload, session)
                    group_summaries.append(Dhis2ApiUtils.parse_import_summary(response))
                import_summary = self._merge_import_summaries(*group_summaries) if group_summaries else None
            except Exception as post_err:
                logging.error(f"Error posting data values: {post_err}")
                errors.append(f"Post failed: {post_err}")

        if deletes:
            logging.info(f"Posting {len(deletes)} data value deletes")
            try:
                response = await self.api_utils.post_data_value_set(
                    {'dataValues': deletes}, session, {'importStrategy': 'DELETE'}
                )
                delete_import_summary = Dhis2ApiUtils.parse_import_summary(response)
            except Exception as delete_err:
                logging.error(f"Error deleting data values: {delete_err}")
                errors.append(f"Delete failed: {delete_err}")

        for payload in integrity_payloads:
            num_values = len(payload.get('dataValues', []))
            logging.info(f"Posting integrity dataValueSet with {num_values} values "
                         f"(dataSet={payload.get('dataSet')}, period={payload.get('period')}, "
                         f"orgUnit={payload.get('orgUnit')})")
            try:
                response = await self.api_utils.post_data_value_set(payload, session)
                integrity_import_summary = Dhis2ApiUtils.parse_import_summary(response)
            except Exception as integrity_err:
                logging.error(f"Error posting integrity data values: {integrity_err}")
                errors.append(f"Integrity post failed: {integrity_err}")

        combined_import_summary = self._merge_import_summaries(
            delete_import_summary, import_summary, integrity_import_summary
        )
        num_deletes = len(deletes)
        num_upserts = len(upserts) + sum(len(p.get('dataValues', [])) for p in integrity_payloads)
        return combined_import_summary, num_upserts, num_deletes, errors

    @staticmethod
    def _merge_import_summaries(*summaries):
        combined = {"imported": 0, "updated": 0, "deleted": 0, "ignored": 0, "status": "OK"}
        for s in summaries:
            if not s:
                continue
            combined["imported"] += s.get("imported", 0)
            combined["updated"] += s.get("updated", 0)
            combined["deleted"] += s.get("deleted", 0)
            combined["ignored"] += s.get("ignored", 0)
            if s.get("status") != "OK":
                combined["status"] = s.get("status")
        return combined


def run_main():
    parser = argparse.ArgumentParser(description='Run DQ Workbench stages from a configuration file')
    parser.add_argument('--config', required=True, help='Path to configuration file')
    parser.add_argument('--log-level', help='Override logging level (DEBUG, INFO, WARNING, ERROR)')
    parser.add_argument('--log-file', help='Override log file path')
    args = parser.parse_args()

    # Load and validate configuration
    config_manager = ConfigManager(config_path=args.config, config=None, validate_structure=True, validate_runtime=True)
    if not config_manager.config:
        logging.error("Failed to load configuration.")
        sys.exit(1)
    config = config_manager.config

    # Apply CLI overrides for logging without editing the file
    if args.log_level:
        config.setdefault('server', {})['logging_level'] = args.log_level
    if args.log_file:
        config.setdefault('server', {})['log_file'] = args.log_file

    monitor = DataQualityMonitor(config)
    asyncio.run(monitor.run_all_stages())

if __name__ == '__main__':
    run_main()
