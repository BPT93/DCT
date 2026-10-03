"""Read-only installation smoke checks for a disposable Odoo 19 database.

Run after installation/upgrade finishes:
    bash tools/run_shell.sh dct_security_test_DATABASE tools/check_installation.py

Checks database references and server compilation of action views. It does not
execute server actions, create business data, render PDFs, or claim browser or
role-security acceptance. The dedicated cursor is explicitly READ ONLY.
"""
import json
import re

from lxml import etree

from odoo import api, SUPERUSER_ID


assert env.cr.dbname.startswith('dct_security_test_'), 'Use a disposable dct_security_test_* database only'
MODULE = 'dct_security_management'
REPORTS = {
    'coverage': 'dct.security.shift',
    'roster': 'dct.security.assignment',
    'attendance': 'dct.security.assignment',
    'incident': 'dct.security.incident',
    'patrol': 'dct.security.patrol.round',
    'visit': 'dct.security.visit',
    'payroll': 'dct.security.payroll',
    'billing': 'dct.security.billing',
}
TOP_MENUS = ('overview', 'guards', 'sites', 'contracts', 'planning', 'attendance',
             'patrols', 'incidents', 'visits', 'payroll', 'billing', 'reports', 'configuration')
CLIENT_TAGS = {
    'dct_security_management.dashboard',
    'dct_security_management.weekly_board',
    'dct_security_management.site_map',
}
summary = {'database': env.cr.dbname, 'menus': 0, 'window_actions': 0,
           'loaded_view_modes': 0, 'client_actions': 0, 'reports': 0,
           'paperformats': 0, 'readonly': True}


def resolve(local, xmlid, expected_model=None):
    record = local.ref(xmlid, raise_if_not_found=True)
    assert record.exists(), 'Dangling XML ID: ' + xmlid
    if expected_model:
        assert record._name == expected_model, (xmlid, record._name, expected_model)
    return record


with env.registry.cursor() as cursor:
    # Set the transaction access mode before any ORM query in this cursor.
    cursor.execute('SET TRANSACTION READ ONLY')
    cursor.execute('SHOW transaction_read_only')
    assert cursor.fetchone()[0] == 'on'
    admin = api.Environment(cursor, SUPERUSER_ID, {'lang': 'en_US', 'tz': 'UTC'})
    companies = admin['res.company'].search([])
    admin = admin(context=dict(admin.context, allowed_company_ids=companies.ids))
    assert admin['ir.module.module'].search_count([('name', '=', MODULE), ('state', '=', 'installed')]) == 1

    root = resolve(admin, MODULE + '.menu_security_root', 'ir.ui.menu')
    for name in TOP_MENUS:
        menu = resolve(admin, MODULE + '.menu_' + name, 'ir.ui.menu')
        assert menu.parent_id == root, (name, 'Unexpected top-level menu parent')

    metadata = admin['ir.model.data'].search([('module', '=', MODULE)])
    menu_metadata = metadata.filtered(lambda item: item.model == 'ir.ui.menu')
    for item in menu_metadata.sorted('name'):
        xmlid = MODULE + '.' + item.name
        menu = resolve(admin, xmlid, 'ir.ui.menu')
        if menu != root:
            assert menu.parent_id.exists(), (xmlid, 'Missing parent menu')
        if menu.action:
            assert menu.action.exists(), (xmlid, 'Missing action')
            assert menu.action._name.startswith('ir.actions.'), (xmlid, menu.action._name)
            assert menu.action.type == menu.action._name, (xmlid, 'Action type does not match its model')
        assert all(group.exists() for group in menu.group_ids), (xmlid, 'Missing menu group')
        summary['menus'] += 1

    actions = metadata.filtered(lambda item: item.model == 'ir.actions.act_window')
    for item in actions.sorted('name'):
        xmlid = MODULE + '.' + item.name
        action = resolve(admin, xmlid, 'ir.actions.act_window')
        assert action.res_model in admin.registry, (xmlid, 'Missing model', action.res_model)
        model = admin[action.res_model]
        declared_modes = [mode.strip() for mode in action.view_mode.split(',') if mode.strip()]
        assert declared_modes and len(declared_modes) == len(set(declared_modes)), (xmlid, 'Invalid view modes')
        assert 'tree' not in declared_modes, (xmlid, 'Odoo 19 uses list views')
        selected_views = list(action.views)
        assert set(declared_modes).issubset({mode for _, mode in selected_views}), (xmlid, selected_views)
        for view_id, mode in selected_views:
            if view_id:
                view = admin['ir.ui.view'].browse(view_id).exists()
                assert view and view.model == action.res_model and view.type == mode, (xmlid, view_id, mode)
        if not any(mode == 'search' for _, mode in selected_views):
            selected_views.append((action.search_view_id.id or False, 'search'))

        # Odoo 19 returns {views: {type: {arch, id, model}}, models: ...}.
        # This invokes the same server API used by the web client and compiles
        # inherited views, nested subviews, fields, modifiers and toolbars.
        result = model.get_views(selected_views, options={
            'action_id': action.id, 'toolbar': True, 'load_filters': True,
        })
        assert 'views' in result and 'models' in result, (xmlid, 'Invalid get_views response')
        loaded = []
        for _, mode in selected_views:
            compiled = result['views'].get(mode)
            assert compiled and compiled.get('arch'), (xmlid, mode, 'Empty compiled view')
            assert compiled.get('model') == action.res_model, (xmlid, mode, 'Wrong model')
            node = etree.fromstring(compiled['arch'].encode('utf-8'))
            assert node.tag == mode, (xmlid, mode, 'Wrong XML root', node.tag)
            loaded.append(mode)
            summary['loaded_view_modes'] += 1
        if action.res_id:
            assert model.browse(action.res_id).exists(), (xmlid, 'Missing default record')
        summary['window_actions'] += 1
        print(json.dumps({'window_action': xmlid, 'model': action.res_model, 'loaded': loaded}), flush=True)

    client_metadata = metadata.filtered(lambda item: item.model == 'ir.actions.client')
    actual_tags = set()
    for item in client_metadata:
        action = resolve(admin, MODULE + '.' + item.name, 'ir.actions.client')
        assert action.tag in CLIENT_TAGS, ('Unexpected client action tag', action.tag)
        actual_tags.add(action.tag)
        summary['client_actions'] += 1
    assert actual_tags == CLIENT_TAGS, ('Missing client actions', CLIENT_TAGS - actual_tags)

    paperformat = resolve(admin, MODULE + '.paperformat_security', 'report.paperformat')
    assert paperformat.format == 'A4' and paperformat.orientation == 'Portrait'
    assert min(paperformat.margin_top, paperformat.margin_bottom, paperformat.margin_left, paperformat.margin_right) >= 0
    summary['paperformats'] = 1
    report_metadata = metadata.filtered(lambda item: item.model == 'ir.actions.report')
    assert len(report_metadata) == len(REPORTS), ('Expected eight report actions', len(report_metadata))
    for suffix, model_name in REPORTS.items():
        xmlid = MODULE + '.report_' + suffix
        report = resolve(admin, xmlid, 'ir.actions.report')
        assert report.model == model_name and model_name in admin.registry, (xmlid, 'Wrong report model')
        assert report.report_type == 'qweb-pdf', (xmlid, report.report_type)
        assert report.binding_type == 'report' and report.binding_model_id.model == model_name, (xmlid, 'Invalid report binding')
        assert report.paperformat_id == paperformat, (xmlid, 'Missing or unexpected paper format')
        assert report.report_name == MODULE + '.' + suffix + '_document', (xmlid, report.report_name)
        template = resolve(admin, report.report_name, 'ir.ui.view')
        assert template.type == 'qweb', (xmlid, 'Report template is not QWeb')
        arch = template.get_combined_arch()
        if isinstance(arch, str):
            arch = etree.fromstring(arch.encode('utf-8'))
        for called in arch.xpath('//@t-call'):
            if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*', called):
                resolve(admin, called, 'ir.ui.view')
        helper = 'report.' + report.report_name
        assert helper in admin.registry and callable(getattr(admin[helper], '_get_report_values', None)), (xmlid, 'Missing report values model')
        if suffix in ('payroll', 'billing'):
            assert resolve(admin, MODULE + '.group_finance', 'res.groups') in report.group_ids, (xmlid, 'Missing finance restriction')
        summary['reports'] += 1
        print(json.dumps({'report': xmlid, 'template': report.report_name, 'model': model_name,
                          'paperformat': MODULE + '.paperformat_security'}), flush=True)
    cursor.rollback()

print('DCT_INSTALLATION_CHECK_PASS ' + json.dumps(summary, sort_keys=True), flush=True)
