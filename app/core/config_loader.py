import os
import re
import yaml

from app.core.api_utils import Dhis2ApiUtils
from app.core.time_unit import TimeUnit
import logging
from typing import Any, Dict, Sequence
from app.core.period_utils import Dhis2PeriodUtils


class ConfigManager:
    def __init__(self, config_path, config, validate_structure=True, validate_runtime=True):
        if config_path:
            with open(config_path, 'r') as stream:
                config = yaml.safe_load(stream)

        if config is None or not isinstance(config, dict):
            raise ValueError("Config must be provided and be a dictionary after loading.")

        self._resolve_env_vars(config)
        self.config: Dict[str, Any] = config

        server = self.config.get('server')
        if not isinstance(server, dict):
            raise ValueError("Missing or invalid 'server' section in config.")
        self.server: Dict[str, Any] = server

        if validate_structure:
            self.validate_structure(self.config)
        if validate_runtime:
            self._validate_runtime(self.config)


    @staticmethod
    def _resolve_env_vars(config: dict) -> None:
        """Replace ``${VAR_NAME}`` placeholders in server config string values
        with the corresponding environment variable.  Raises ``ValueError`` if
        a referenced variable is not set."""
        _placeholder = re.compile(r'^\$\{([^}]+)\}$')
        server = config.get('server', {})
        for key, value in server.items():
            if not isinstance(value, str):
                continue
            match = _placeholder.match(value)
            if match:
                var_name = match.group(1)
                resolved = os.environ.get(var_name)
                if resolved is None:
                    raise ValueError(
                        f"Environment variable '{var_name}' referenced in server.{key} is not set."
                    )
                server[key] = resolved

    def save (self, config_path):
        try:
            self.validate_structure(self.config)
        except ValueError as e:
            logging.error(f"Failed to validate config before saving: {e}")
            raise ValueError(f"Configuration validation failed: {e}")
        with open(config_path, 'w') as f:
            yaml.dump(self.config, f)

    @classmethod
    def _validate_runtime(cls, config):
        # Check base_url format
        url = config['server'].get('base_url', '')
        if not url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid base URL: '{url}'. Must start with http:// or https://")
        if url.endswith('/'):
            raise ValueError("Base URL should not end with a slash")

        # Attempt to ping the server
        api_utils = Dhis2ApiUtils(url, config['server'].get('d2_token', ''))
        status, reason = api_utils.ping()
        if status == 'unreachable':
            raise ValueError(f"DHIS2 server is unreachable: {reason}")
        if status == 'auth_failed':
            raise ValueError(f"API token was rejected by the server: {reason}")

        cls._validate_max_results(api_utils, config)
        cls._validate_default_coc(config)

    @classmethod
    def _validate_max_results(cls, api_utils, config):
        max_results = cls._validate_max_results_within_bounds(config)
        system_settings = api_utils.fetch_system_settings()
        if system_settings:
            key_data_quality_max_limit = system_settings.get('keyDataQualityMaxLimit', 500)
            if key_data_quality_max_limit < max_results:
                raise ValueError(
                    f"Configured max_results ({max_results}) exceeds system setting keyDataQualityMaxLimit ({key_data_quality_max_limit})"
                )

    @classmethod
    def _validate_max_results_within_bounds(cls, config):
        # Check the keyDataQualityMaxLimit in system settings is greater than or equal to the configured max_results
        max_results = config['server'].get('max_results', 500)
        if not (500 <= max_results <= 50000):
            raise ValueError(f"max_results must be between 500 and 50000, got {max_results}")
        return max_results


    def validate_structure(self, config: dict):
        self._validate_base_url(config['server']['base_url'])
        self._validate_api_token(config['server']['base_url'], config['server']['d2_token'])
        self._validate_max_results_within_bounds(config)
        #We need at least analyzer_stages or min_max_stages
        if 'analyzer_stages' not in config and 'min_max_stages' not in config:
            #Log a warning, but do not raise an error
            logging.warning("No analyzer_stages or min_max_stages defined in config. This is not an error, but no analysis will be performed.")
            return
        self._validate_unique_stage_name(config)

        if 'analyzer_stages' in config:
            for stage in config['analyzer_stages']:
                self._validate_stage(stage)
                self._validate_stage_params(stage)
                if stage['type'] in ['validation_rules', 'outlier']:
                    self._is_valid_duration(stage['params']['duration'], stage['name'])

        # Validate min_max stages
        if 'min_max_stages' in config:
            for stage in config['min_max_stages']:
                self._validate_min_max_stages(stage)


    @staticmethod
    def _validate_unique_stage_name(config):
        stage_names = [stage['name'] for stage in config['analyzer_stages']]
        duplicates = {name for i, name in enumerate(stage_names) if name in stage_names[:i]}
        if duplicates:
            raise ValueError(f"Duplicate stage names found: {', '.join(duplicates)}")

    def _validate_stage_params(self, stage):
        params = stage['params']
        stage_type = stage['type']
        if stage_type == 'validation_rules':
            if 'rule_mappings' in params:
                self._validate_rule_mappings(stage)
                required = ['level', 'duration']
            else:
                required = ['validation_rule_group', 'destination_data_element', 'level', 'duration']
            self._validate_aggregation_level(stage)
        elif stage_type == 'outlier':
            required = ['dataset', 'algorithm', 'destination_data_element', 'level', 'duration']
            self._validate_outlier_start_end_dates(stage)
        elif stage_type == 'min_max':
            required = ['dataset', 'destination_data_element']
        elif stage_type == 'integrity_checks':
            required = ['monitoring_group', 'dataset']
        else:
            raise ValueError(f"Unknown stage type '{stage_type}' in stage '{stage['name']}'")
        for param in required:
            if param not in params:
                raise ValueError(f"Missing parameter '{param}' in stage '{stage['name']}' of type '{stage_type}'")

    @staticmethod
    def _validate_rule_mappings(stage):
        params = stage['params']
        name = stage['name']
        if 'validation_rule_group' in params or 'destination_data_element' in params:
            raise ValueError(
                f"Stage '{name}': rule_mappings cannot be combined with "
                f"validation_rule_group/destination_data_element"
            )
        mappings = params['rule_mappings']
        if not isinstance(mappings, list) or not mappings:
            raise ValueError(f"Stage '{name}': rule_mappings must be a non-empty list")
        pairs = set()
        for mapping in mappings:
            if not isinstance(mapping, dict) or not all(
                    isinstance(mapping.get(key), str) and mapping.get(key)
                    for key in ('validation_rule', 'data_element')):
                raise ValueError(
                    f"Stage '{name}': each entry in rule_mappings needs a validation_rule and a data_element, "
                    f"got {mapping!r}"
                )
            pair = (mapping['validation_rule'], mapping['data_element'])
            if pair in pairs:
                raise ValueError(
                    f"Stage '{name}': duplicate rule mapping {pair[0]} -> {pair[1]} would be counted twice"
                )
            pairs.add(pair)

    @staticmethod
    def _validate_aggregation_level(stage):
        params = stage['params']
        aggregation_level = params.get('aggregation_level')
        if aggregation_level is None:
            return
        # Existing values are looked up as descendants of the org units at 'level', so results must not
        # be rolled up above that level or stale values would never be found and deleted.
        level = params.get('level')
        if (not isinstance(aggregation_level, int) or isinstance(aggregation_level, bool)
                or not isinstance(level, int) or aggregation_level < level):
            raise ValueError(
                f"Invalid aggregation_level '{aggregation_level}' in stage '{stage['name']}': "
                f"must be an integer greater than or equal to level ({level})"
            )

    @staticmethod
    def _validate_stage(stage):
        if 'name' not in stage:
            raise ValueError("Stage missing 'name'")
        if 'type' not in stage:
            raise ValueError(f"Stage '{stage.get('name', 'UNKNOWN')}' missing 'type'")
        if 'params' not in stage:
            raise ValueError(f"Stage '{stage['name']}' missing 'params' section")


    @staticmethod
    def _validate_default_coc(config):
        api_utils = Dhis2ApiUtils(
            base_url=config['server']['base_url'],
            d2_token=config['server']['d2_token']
        )
        default_coc = config['server'].get('default_coc')
        #This can be blank, but then we need to check to see if HllvX50cXC0 exists as this is the default
        if not default_coc:
            default_coc = 'HllvX50cXC0'
        if not api_utils.fetch_category_option_combo_by_id(default_coc):
            raise ValueError(f"Default category option combo '{default_coc}' does not exist in the system.")


    @staticmethod
    def _is_valid_duration(value: str, stage_name: str) -> None:
        logging.debug("Validating duration for stage '%s': '%s'", stage_name, value)
        match = re.match(r"^\s*(\d+)\s+(\w+)\s*$", value.strip(), re.IGNORECASE)
        if not match:
            raise ValueError(
                f"Invalid duration format in stage '{stage_name}': '{value}'. "
                "Expected format like '12 months', '1 years', etc."
            )
        amount, unit = match.groups()
        if int(amount) <= 0:
            raise ValueError(f"Duration must be > 0 in stage '{stage_name}'")
        if unit.lower() not in TimeUnit.list():
            raise ValueError(
                f"Invalid period type '{unit}' in stage '{stage_name}'. "
                f"Must be one of: {', '.join(TimeUnit.list())}"
            )
    @staticmethod
    def _validate_base_url(url: str):
        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError(f"Base URL must start with http:// or https://: '{url}'")
        if url.endswith("/"):
            raise ValueError(f"Base URL must not end with a trailing slash: '{url}'")

    @staticmethod
    def _validate_api_token(base_url: str, d2_token: str):
        import requests
        try:
            headers = {'Authorization': f'ApiToken {d2_token}'}
            url = f"{base_url}/api/me"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code != 200:
                raise ValueError(f"Invalid DHIS2 API token or server unreachable: {url}")
        except requests.RequestException as e:
            raise ValueError(f"Failed to connect to DHIS2 API: {e}")

    @staticmethod
    def _validate_outlier_start_end_dates(stage):
        start_date = None
        end_date = None
        start_date_offset = stage['params'].get('start_date_offset', None)
        end_date_offset = stage['params'].get('end_date_offset', None)
        if start_date_offset:
            ConfigManager._is_valid_duration(start_date_offset, stage['name'])
            start_date = Dhis2PeriodUtils.get_start_date_from_today(start_date_offset)
        if end_date_offset:
            ConfigManager._is_valid_duration(end_date_offset, stage['name'])
            end_date = Dhis2PeriodUtils.get_start_date_from_today(end_date_offset)
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError(
                    f"Start date offset '{start_date_offset}' must be greater than end date offset '{end_date_offset}' in stage '{stage['name']}'"
                )

    def _api_utils(self) -> Dhis2ApiUtils:
        return Dhis2ApiUtils(
            base_url=self.config['server']['base_url'],
            d2_token=self.config['server']['d2_token'],
        )

    def _validate_datasets_exist(self, datasets: Sequence[str]) -> None:
        api = self._api_utils()
        for dataset in datasets:
            if not api.fetch_dataset_by_id(dataset):
                raise ValueError(f"Dataset '{dataset}' does not exist in the system.")

    def _validate_data_element_groups_exist(self, groups: Sequence[str]) -> None:
        api = self._api_utils()
        for group in groups:
            if not api.fetch_data_element_group_by_id(group):
                raise ValueError(f"Data element group '{group}' does not exist in the system.")

    def _validate_data_elements_exist(self, data_elements: Sequence[str]) -> None:
        api = self._api_utils()
        for de in data_elements:
            if not api.fetch_data_element_by_id(de):
                raise ValueError(f"Data element '{de}' does not exist in the system.")

    def _validate_org_units_exist(self, org_units: Sequence[str]) -> None:
        api = self._api_utils()
        for ou in org_units:
            if not api.fetch_organisation_unit_by_id(ou):
                raise ValueError(f"Organisation unit '{ou}' does not exist in the system.")

    def _validate_min_max_stages(self, stage):
        """Validate a min_max stage dict; raises ValueError on problems."""
        name = stage.get('name', '<unnamed>')

        # Optional: normalize legacy singular 'dataset' -> 'datasets' list
        if 'datasets' not in stage and 'dataset' in stage:
            ds = stage.get('dataset')
            stage['datasets'] = [ds] if isinstance(ds, str) else ds

        # Required keys (now includes 'datasets')
        required = [
            'name', 'org_units', 'previous_periods',
            'completeness_threshold', 'groups', 'datasets'
        ]
        missing = [k for k in required if k not in stage]
        if missing:
            raise ValueError(f"Missing {', '.join(repr(k) for k in missing)} in min_max_stage '{name}'")

        # datasets: required non-empty list + existence check
        datasets = stage.get('datasets')
        if not isinstance(datasets, list) or not datasets:
            raise ValueError(f"'datasets' must be a non-empty list in min_max_stage '{name}'")
        self._validate_datasets_exist(datasets)

        # Optional list fields: if present, must be non-empty lists and must exist
        optional_lists = {
            'data_element_groups': self._validate_data_element_groups_exist,
            'data_elements': self._validate_data_elements_exist,
        }
        for key, validator in optional_lists.items():
            vals = stage.get(key)
            if not isinstance(vals, list):
                raise ValueError(f"'{key}' must be a list in min_max_stage '{name}'")
            if not vals:
                continue
            validator(vals)

        # Org units + duration checks
        org_units = stage.get('org_units')
        if org_units is None:
            raise ValueError(f"Organisation units must be specified in min_max_stage '{name}'")
        self._validate_org_units_exist(org_units)


