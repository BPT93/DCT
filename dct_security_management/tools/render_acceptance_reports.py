"""Render actual installed QWeb reports from the fictional test fixture."""
import json
from pathlib import Path
from odoo.modules.module import get_module_path

assert env.cr.dbname.startswith('dct_security_test_')
root = Path(get_module_path('dct_security_management'))
folder = root / '.validation/reports'
folder.mkdir(parents=True,exist_ok=True)
ids = json.loads((root/'.validation/fixture.json').read_text())
env['ir.config_parameter'].set_param('report.url','http://127.0.0.1:18080')
env['ir.config_parameter'].set_param('web.base.url','http://127.0.0.1:18080')
env.cr.commit()
languages = ['en_US']
if env['res.lang'].search_count([('code','=','ar_001'),('active','=',True)]):
    languages.append('ar_001')
for language in languages:
    reports = env['ir.actions.report'].with_user(env.ref('base.user_admin')).with_context(lang=language,tz='Asia/Baghdad')
    for name, fixture in [('coverage','shift'),('roster','assignment'),('attendance','assignment'),('incident','incident'),('patrol','patrol'),('visit','visit'),('payroll','payroll'),('billing','billing')]:
        binary, fmt = reports._render_qweb_pdf('dct_security_management.report_'+name,[ids[fixture]])
        assert fmt=='pdf' and binary.startswith(b'%PDF'), (name,fmt)
        path = folder / f'{name}-{language}.pdf'
        path.write_bytes(binary)
        print('PDF_RENDERED',path.name,len(binary),flush=True)
print('ALL_ACCEPTANCE_REPORTS_RENDERED',flush=True)
