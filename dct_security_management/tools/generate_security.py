"""Developer utility: deterministic ACL/rule generation; not executed by Odoo."""
from pathlib import Path
import ast
import csv
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
finance = {'dct.security.billing', 'dct.security.billing.line', 'dct.security.compensation', 'dct.security.payroll', 'dct.security.payroll.line', 'dct.security.payroll.adjustment'}
config = {'dct.security.site','dct.security.post','dct.security.qualification', 'dct.security.shift.template','dct.security.incident.category','dct.security.patrol.route','dct.security.patrol.checkpoint','dct.security.inspection.template','dct.security.inspection.item'}
spec = {}
for folder in ('models', 'wizards'):
    for path in (ROOT / folder).glob('*.py'):
        if '--foundation' in sys.argv and path.name != 'foundation.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            if any(isinstance(base, ast.Attribute) and base.attr == 'AbstractModel' for base in cls.bases):
                continue
            fields = {t.id: n.value for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
            name = fields.get('_name')
            if not isinstance(name, ast.Constant) or not str(name.value).startswith('dct.security.') or name.value in ('dct.security.mixin','dct.security.dashboard'):
                continue
            spec[name.value] = fields

rows = [['id','name','model_id:id','group_id:id','perm_read','perm_write','perm_create','perm_unlink']]
rules = ['<odoo>']
def acl(model, group, write=False, create=False, unlink=False, external=None):
    key=model.replace('.','_')
    rows.append([f'access_{key}_{group}',f'{model} {group}',external or f'model_{key}',f'group_{group}',1,int(write),int(create),int(unlink)])
def rule(key, model_ref, domain, groups=None):
    rule_fields=f'<field name="name">DCT {key}</field><field name="model_id" ref="{model_ref}"/><field name="domain_force">{escape(domain)}</field>'
    if groups:
        rule_fields += '<field name="groups" eval="[' + ','.join(f"(4, ref('group_{g}'))" for g in groups) + ']"/>'
    rules.append(f'<record id="rule_{key}" model="ir.rule">{rule_fields}</record>')
for name, fields in sorted(spec.items()):
    key=name.replace('.','_')
    is_finance=name in finance or any(x in name for x in ('billing.', 'payroll.'))
    if is_finance:
        acl(name,'finance',True,True,True)
    else:
        acl(name,'readonly')
        acl(name,'manager',name != 'dct.security.contract.line',name != 'dct.security.contract.line',name != 'dct.security.contract.line')
        if name not in config and name not in ('dct.security.contract', 'dct.security.contract.line', 'dct.security.guard.qualification'):
            if name != 'dct.security.attendance.period':
                acl(name,'supervisor',True,True,'generate.roster' in name or 'replace.guard' in name)
            acl(name,'hr',True,True,'generate.roster' in name or 'replace.guard' in name)
        if name in ('dct.security.contract','dct.security.contract.line'):
            acl(name,'finance',True,True,True)
        if name == 'dct.security.guard.qualification':
            acl(name,'hr',True,True,True)
    company = "[('company_id', 'in', company_ids)]"
    if name.endswith('generate.roster.line'):
        company = "[('wizard_id.company_id', 'in', company_ids)]"
    rule(key+'_company',f'model_{key}',company)
    scope = None
    if name == 'dct.security.site':
        scope = "[('supervisor_ids', 'in', [user.id])]"
    elif 'site_id' in fields:
        scope = "[('site_id.supervisor_ids', 'in', [user.id])]"
    elif 'site_ids' in fields:
        scope = "['!', ('site_ids', 'any', [('supervisor_ids', 'not in', [user.id])])]"
    elif 'employee_id' in fields:
        scope = "[('employee_id.security_site_ids.supervisor_ids', 'in', [user.id])]"
    elif name.endswith('generate.roster.line'):
        scope = "[('wizard_id.template_id.site_id.supervisor_ids', 'in', [user.id])]"
    if scope:
        rule(key+'_scope',f'model_{key}',f"{scope} if user._dct_site_limited() else [(1,'=',1)]")

for model, ref in [('hr.employee','hr.model_hr_employee'),('hr.employee.public','hr.model_hr_employee_public')]:
    rule(model.replace('.','_')+'_guard_scope', ref, 'user._dct_employee_domain()')
for group in ('readonly','manager','supervisor','hr','finance'):
    acl('hr.employee',group,group in ('manager','hr'),group in ('manager','hr'),False,'hr.model_hr_employee')
for group in ('manager','hr'):
    acl('resource.resource',group,True,True,False,'resource.model_resource_resource')
rule('hr_attendance_guard_scope','hr_attendance.model_hr_attendance',"user._dct_employee_domain('employee_id.')")
rule('hr_attendance_dct_allow','hr_attendance.model_hr_attendance',"[('employee_id.is_security_guard','=',True)]",['readonly'])
for group in ('readonly','manager','supervisor','hr','finance'):
    acl('hr.attendance',group,group in ('manager','supervisor','hr'),group in ('manager','supervisor','hr'),False,'hr_attendance.model_hr_attendance')
rules.append('</odoo>')
(ROOT/'security/rules.xml').write_text('\n'.join(rules)+'\n', encoding='utf-8')
with (ROOT/'security/ir.model.access.csv').open('w',newline='',encoding='utf-8') as f:
    csv.writer(f).writerows(rows)
print(f'{len(spec)} models; {len(rows)-1} ACLs; {len(rules)-2} rules')
