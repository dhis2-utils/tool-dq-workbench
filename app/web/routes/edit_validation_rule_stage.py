import logging

from flask import Blueprint, current_app, request, render_template, redirect, url_for, flash
from copy import deepcopy
import requests

from app.core.api_utils import Dhis2ApiUtils
from app.core.config_loader import ConfigManager
from app.web.utils.config_helpers import save_config
from app.web.routes.api import api_bp
from app.core.uid_utils import UidUtils
from app.core.period_type import PeriodType
@api_bp.route('/validation-rule-stage', methods=['GET', 'POST'], endpoint='new_validation_rule_stage')
@api_bp.route('/validation-rule-stage/<int:stage_index>', methods=['GET', 'POST'], endpoint='edit_validation_rule_stage')
def validation_rule_stage_view(stage_index=None):
    config_path = current_app.config['CONFIG_PATH']
    config = ConfigManager(config_path, config=None, validate_structure=True, validate_runtime=False).config
    is_edit = stage_index is not None

    if is_edit:
        stage = config['analyzer_stages'][stage_index]
        if stage.get('type') != 'validation_rules':
            flash('Only validation rule stages can be edited here.', 'danger')
            return redirect(url_for('ui.index'))
    else:
        stage = {
            'name': '',
            'type': 'validation_rules',
            'params': {
                'level': 1,
                'duration': '12 months',
                'validation_rule_group': '',
                'destination_data_element': '',
                'destination_dataset': ''
            },
            'active': True
        }

    data_element_name = ''
    validation_rule_group_name = ''
    destination_dataset_name = ''

    api_utils = Dhis2ApiUtils(
        base_url=config['server']['base_url'],
        d2_token=config['server']['d2_token']
    )

    if is_edit:
        de_uid = stage['params'].get('destination_data_element')
        vrg_uid = stage['params'].get('validation_rule_group')

        try:
            data_element_name = api_utils.fetch_data_element_by_id(de_uid)['name']
            if not data_element_name:
                data_element_name = de_uid
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException):
            data_element_name = de_uid
            flash(f"Warning: Failed to fetch data element name for {de_uid}", 'warning')

        try:
            validation_rule_group_name = api_utils.fetch_validation_rule_group_by_id(vrg_uid)['name']
            if not validation_rule_group_name:
                validation_rule_group_name = vrg_uid
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException):
            validation_rule_group_name = vrg_uid
            flash(f"Warning: Failed to fetch validation rule group name for {vrg_uid}", 'warning')

        dest_ds_uid = stage['params'].get('destination_dataset')
        if dest_ds_uid:
            try:
                result = api_utils.fetch_dataset_by_id(dest_ds_uid)
                destination_dataset_name = (result or {}).get('name') or dest_ds_uid
            except requests.exceptions.RequestException:
                destination_dataset_name = dest_ds_uid
                flash(f"Warning: Failed to fetch destination dataset name for {dest_ds_uid}", 'warning')

    if request.method == 'POST':
        # Common updates
        stage['name'] = request.form['stage_name']
        stage['params']['level'] = int(request.form['orgunit_level'])
        stage['params']['duration'] = request.form['duration']
        stage['params']['validation_rule_group'] = request.form['validation_rule_group']
        stage['params']['destination_data_element'] = request.form['destination_data_element']
        stage['params']['destination_dataset'] = request.form.get('destination_dataset') or None
        aggregation_level = request.form.get('aggregation_level', '').strip()
        if aggregation_level:
            stage['params']['aggregation_level'] = int(aggregation_level)
        else:
            stage['params'].pop('aggregation_level', None)
        stage['uid'] = request.form.get('uid', '').strip() or UidUtils.generate_uid()
        stage['active'] = request.form.get('active', 'off') == 'on'

        # Append only if new
        if not is_edit:
            config.setdefault('analyzer_stages', []).append(stage)

        try:
            save_config(config_path, config)
            flash(f"{'Updated' if is_edit else 'New'} validation rule stage saved.", 'success')
            return redirect(url_for('ui.index'))
        except ValueError as e:
            flash(f"Error saving config: {e}", 'danger')

    return render_template(
        "stage_form_validation_rule.html",
        stage=deepcopy(stage),
        edit=is_edit,
        data_element_name=data_element_name,
        validation_rule_group_name=validation_rule_group_name,
        destination_dataset_name=destination_dataset_name
    )
