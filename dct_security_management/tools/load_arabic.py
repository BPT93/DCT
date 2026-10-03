"""Install the real Arabic catalogs in a disposable acceptance database."""
from odoo import Command
from odoo.tools.translate import load_language

assert env.cr.dbname.startswith('dct_security_test_')
load_language(env.cr, 'ar_001')
admin = env.ref('base.user_admin')
user = env['res.users'].with_context(no_reset_password=True).search([('login','=','dct_arabic_acceptance')])
if not user:
    user = env['res.users'].with_context(no_reset_password=True).create({
        'name':'Fictional Arabic Acceptance Reviewer', 'login':'dct_arabic_acceptance',
        'password':'dct-local-acceptance', 'lang':'ar_001', 'tz':'Asia/Baghdad',
        'company_id':admin.company_id.id, 'company_ids':[Command.set(admin.company_ids.ids)],
        'group_ids':[Command.set(admin.group_ids.ids)],
    })
env.cr.commit()
print('ARABIC_LANGUAGE_AND_TEST_REVIEWER_READY')
