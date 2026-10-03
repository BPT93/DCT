"""Explicit fictional acceptance fixture. Refuses any non-test database."""
import json
from pathlib import Path
from datetime import timedelta
from odoo import fields, Command
from odoo.modules.module import get_module_path

assert env.cr.dbname.startswith('dct_security_test_')
root = Path(get_module_path('dct_security_management'))
folder = root / '.validation'
folder.mkdir(exist_ok=True)
assert not env['dct.security.site'].search_count([('name','=','Fictional Acceptance Campus')]), 'Acceptance fixture already exists; reuse fixture.json'
company = env.ref('base.main_company')
env = env(context=dict(env.context, allowed_company_ids=company.ids, mail_create_nosubscribe=True, tracking_disable=True))
admin = env.ref('base.user_admin')
admin.write({'group_ids':[Command.link(env.ref('dct_security_management.'+g).id) for g in ('group_manager','group_hr','group_finance')], 'tz':'Asia/Baghdad'})
# Local disposable test login only; never used in a live or production database.
admin.password = 'dct-local-acceptance'
customer = env['res.partner'].create({'name':'Fictional Acceptance Customer / عميل تجريبي','company_id':company.id})
site = env['dct.security.site'].create({'name':'Fictional Acceptance Campus','partner_id':customer.id,'company_id':company.id,'city':'Baghdad','tz':'Asia/Baghdad','supervisor_ids':[Command.link(admin.id)],'has_coordinates':True,'latitude':33.3152,'longitude':44.3661,'instructions':'Fictional training site. Manual checks only.'})
post = env['dct.security.post'].create({'name':'Main Gate / البوابة الرئيسية','site_id':site.id,'company_id':company.id})
guards = env['hr.employee'].create([{'name':name,'company_id':company.id,'is_security_guard':True,'guard_code':f'ACCEPT-{i}','security_site_ids':[Command.link(site.id)]} for i,name in enumerate(['Guard Normal / حارس منتظم','Guard Late / حارس متأخر','Guard Missing / خروج مفقود','Guard Absent / حارس غائب'],1)])
supervisor = env['hr.employee'].create({'name':'Fictional Site Supervisor / مشرف الموقع','company_id':company.id,'is_security_supervisor':True,'security_site_ids':[Command.link(site.id)]})
now = fields.Datetime.now().replace(microsecond=0)
live = env['dct.security.shift'].create({'name':'Current two-guard coverage','site_id':site.id,'post_id':post.id,'company_id':company.id,'start':now-timedelta(hours=4),'end':now+timedelta(hours=4),'required_guards':2})
assignments = env['dct.security.assignment'].create([{'shift_id':live.id,'employee_id':g.id,'company_id':company.id} for g in guards[:2]])
live.action_publish()
env['hr.attendance'].create({'employee_id':guards[0].id,'check_in':now-timedelta(hours=4)})
env['hr.attendance'].create({'employee_id':guards[1].id,'check_in':now-timedelta(hours=3,minutes=30)})
past = env['dct.security.shift'].create({'name':'Prior approved day coverage','site_id':site.id,'post_id':post.id,'company_id':company.id,'start':now-timedelta(days=2,hours=4),'end':now-timedelta(days=2)+timedelta(hours=4),'required_guards':2})
past_assignments = env['dct.security.assignment'].create([{'shift_id':past.id,'employee_id':g.id,'company_id':company.id} for g in guards[:2]])
past.action_publish()
for index, guard in enumerate(guards[:2]):
    env['hr.attendance'].create({'employee_id':guard.id,'check_in':past.start+timedelta(minutes=index*30),'check_out':past.end})
past_assignments.action_reconcile_attendance()
past_assignments.allocation_ids.action_approve()
overnight = env['dct.security.shift'].create({'name':'Cross-month overnight coverage','site_id':site.id,'post_id':post.id,'company_id':company.id,'start':'2026-09-30 17:00:00','end':'2026-10-01 05:00:00','required_guards':2})
night_assignment = env['dct.security.assignment'].create({'shift_id':overnight.id,'employee_id':guards[2].id,'company_id':company.id})
overnight.action_publish()
env['dct.security.replace.guard'].create({'assignment_id':night_assignment.id,'employee_id':guards[3].id,'reason':'Reviewed overnight coverage replacement for acceptance testing.'}).action_replace()
env['hr.attendance'].create({'employee_id':guards[2].id,'check_in':now-timedelta(hours=20)})
missing_shift = env['dct.security.shift'].create({'name':'Missing checkout and absence review','site_id':site.id,'post_id':post.id,'company_id':company.id,'start':now-timedelta(hours=3),'end':now+timedelta(hours=5),'required_guards':2})
env['dct.security.assignment'].create([{'shift_id':missing_shift.id,'employee_id':g.id,'company_id':company.id} for g in guards[2:]])
missing_shift.action_publish()
category = env['dct.security.incident.category'].create({'name':'Access control / التحكم بالدخول','company_id':company.id})
incident = env['dct.security.incident'].create({'site_id':site.id,'company_id':company.id,'category_id':category.id,'description':'A loose gate latch was identified during the manual patrol.','guard_ids':[Command.link(guards[0].id)],'investigator_id':admin.id})
incident.action_acknowledge(); incident.action_investigate()
incident.resolution = 'The latch was repaired and checked by the supervisor.'
incident.action_resolve(); incident.action_close()
route = env['dct.security.patrol.route'].create({'name':'Perimeter route','site_id':site.id,'company_id':company.id,'checkpoint_ids':[Command.create({'name':'Gate','sequence':10}),Command.create({'name':'Reception','sequence':20})]})
patrol = env['dct.security.patrol.round'].create({'route_id':route.id,'site_id':site.id,'company_id':company.id,'employee_id':guards[0].id,'planned_start':now,'planned_end':now+timedelta(hours=1)})
patrol.action_start()
for result in patrol.result_ids.sorted('sequence'):
    result.notes = 'Manual backend observation recorded by authorized staff.'
    result.action_complete()
patrol.action_close()
checklist = env['dct.security.inspection.template'].create({'name':'Daily supervision','company_id':company.id,'item_ids':[Command.create({'name':'Post instructions available'}),Command.create({'name':'Gate secured'})]})
visit = env['dct.security.visit'].create({'site_id':site.id,'company_id':company.id,'supervisor_id':supervisor.id,'template_id':checklist.id,'findings':'Manual checks completed; instructions and gate are in place.'})
visit.action_start(); visit.result_ids.write({'result':'pass'}); visit.action_complete()
accounts = {}
for key, code, kind in [('income','AC410','income'),('receivable','AC110','asset_receivable'),('expense','AC510','expense'),('payable','AC210','liability_current')]:
    accounts[key] = env['account.account'].create({'name':'Acceptance '+key,'code':code,'account_type':kind,'company_ids':[Command.set(company.ids)],'reconcile':key=='receivable'})
customer.property_account_receivable_id = accounts['receivable']
env['account.journal'].create({'name':'Acceptance Sales','code':'ACS','type':'sale','company_id':company.id,'default_account_id':accounts['income'].id})
journal = env['account.journal'].create({'name':'Acceptance Guard Accrual','code':'ACP','type':'general','company_id':company.id})
product = env['product.product'].create({'name':'Guard Coverage Service','type':'service','property_account_income_id':accounts['income'].id,'taxes_id':[Command.clear()]})
contract = env['dct.security.contract'].create({'name':'Fictional Campus Service Agreement','partner_id':customer.id,'site_ids':[Command.set(site.ids)],'company_id':company.id,'date_start':'2026-01-01','date_end':'2026-12-31'})
env['dct.security.contract.line'].create({'name':'Two-guard gate service','contract_id':contract.id,'site_id':site.id,'post_id':post.id,'date_start':'2026-01-01','date_end':'2026-12-31','billing_basis':'fixed','rate':6200,'required_guards':2,'product_id':product.id,'account_id':accounts['income'].id})
contract.action_activate()
bill = env['dct.security.billing'].create({'contract_id':contract.id,'date_start':'2026-09-01','date_end':'2026-09-30'})
bill.action_approve(); bill.action_create_invoice()
env['dct.security.compensation'].create({'employee_id':guards[0].id,'company_id':company.id,'date_start':'2026-01-01','date_end':'2026-12-31','basis':'monthly','rate':1800,'overtime_rate':15,'allowance':100,'journal_id':journal.id,'expense_account_id':accounts['expense'].id,'payable_account_id':accounts['payable'].id})
payroll = env['dct.security.payroll'].create({'employee_id':guards[0].id,'company_id':company.id,'date_start':past.start.date(),'date_end':past.end.date()})
payroll.action_review(); payroll.action_approve()
company.dct_automation_enabled = True
env['dct.security.attendance.exception']._cron_attendance_exceptions()
company.dct_automation_enabled = False
ids = {'site':site.id,'shift':live.id,'assignment':past_assignments[0].id,'incident':incident.id,'patrol':patrol.id,'visit':visit.id,'payroll':payroll.id,'billing':bill.id,'company':company.id}
(folder/'fixture.json').write_text(json.dumps(ids),encoding='utf-8')
env.cr.commit()
print('ACCEPTANCE_FIXTURE_CREATED',json.dumps(ids))
