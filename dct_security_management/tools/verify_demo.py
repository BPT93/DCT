from odoo.tools.convert import convert_file

assert env.cr.dbname.startswith('dct_security_test_')
assert not env.ref('dct_security_management.demo_customer', raise_if_not_found=False)
convert_file(env,'dct_security_management','demo/security_demo.xml',{},mode='init',noupdate=True)
assert env.ref('dct_security_management.demo_day_template').required_guards == 2
assert env.ref('dct_security_management.demo_guard_1').is_security_guard
assert not env['dct.security.billing'].search_count([('contract_id.partner_id','=',env.ref('dct_security_management.demo_customer').id)])
env.cr.rollback()
print('OPT_IN_DEMO_LOADED_AND_VALIDATED; transaction rolled back; no demo data retained')
