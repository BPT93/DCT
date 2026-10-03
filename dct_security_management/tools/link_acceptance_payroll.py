"""Extend the isolated fixture with a worksheet consuming its approved work."""
import json
from pathlib import Path
from odoo.modules.module import get_module_path
assert env.cr.dbname.startswith('dct_security_test_')
path = Path(get_module_path('dct_security_management'))/'.validation/fixture.json'
ids = json.loads(path.read_text())
assignment = env['dct.security.assignment'].browse(ids['assignment'])
payroll = env['dct.security.payroll'].search([('employee_id','=',assignment.employee_id.id),('date_start','=',assignment.start.date()),('date_end','=',assignment.end.date())],limit=1)
if not payroll:
    payroll = env['dct.security.payroll'].create({'employee_id':assignment.employee_id.id,'company_id':assignment.company_id.id,'date_start':assignment.start.date(),'date_end':assignment.end.date()})
    payroll.action_review(); payroll.action_approve()
assert payroll.approved_hours == assignment.approved_hours == 8
period = env['dct.security.attendance.period'].search([('employee_id','=',assignment.employee_id.id),('start','=',assignment.start),('end','=',assignment.end)],limit=1)
if not period:
    period = env['dct.security.attendance.period'].create({'name':'Acceptance reviewed work period','employee_id':assignment.employee_id.id,'company_id':assignment.company_id.id,'start':assignment.start,'end':assignment.end})
    period.action_approve()
ids['payroll'] = payroll.id
path.write_text(json.dumps(ids))
env.cr.commit()
print('APPROVED_WORK_LINKED_TO_WORKSHEET_AND_PERIOD_LOCK',payroll.approved_hours)
