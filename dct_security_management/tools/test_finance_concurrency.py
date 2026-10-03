"""Run with Odoo shell ONLY on a disposable dct_security_test_* database.

    odoo-bin shell -d dct_security_test_full --no-http < tools/test_finance_concurrency.py

Creates committed fictional fixtures to exercise independent PostgreSQL cursors.
The test database must be dropped after verification. Nothing is cleaned by
deleting confirmed business records. Standard Odoo transaction retries are
simulated for PostgreSQL serialization failures.
"""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from psycopg2.errors import SerializationFailure, DeadlockDetected
from odoo import api, Command, SUPERUSER_ID
from odoo.exceptions import ValidationError


assert env.cr.dbname.startswith('dct_security_test_'), 'Use a disposable dct_security_test_* database only'
assert env['ir.module.module'].search_count([('name', '=', 'dct_security_management'), ('state', '=', 'installed')])
registry = env.registry
suffix = uuid.uuid4().hex[:8]
company = env['res.company'].create({'name': 'DCT Fictional Concurrency ' + suffix})
fixture_env = api.Environment(env.cr, SUPERUSER_ID, {'allowed_company_ids': company.ids})
customer = fixture_env['res.partner'].create({'name': 'Fictional concurrent customer', 'company_id': company.id})
site = fixture_env['dct.security.site'].create({'name': 'Fictional concurrency site', 'company_id': company.id, 'partner_id': customer.id, 'tz': 'UTC'})
employee = fixture_env['hr.employee'].create({'name': 'Fictional concurrency guard', 'company_id': company.id, 'is_security_guard': True,
    'guard_code': 'RACE-' + suffix, 'security_site_ids': [Command.set(site.ids)]})
accounts = {}
for key, code, account_type in [('income', '4100', 'income'), ('receivable', '1100', 'asset_receivable'), ('expense', '5100', 'expense'), ('payable', '2100', 'liability_current')]:
    accounts[key] = fixture_env['account.account'].create({'name': 'Concurrency ' + key, 'code': code, 'account_type': account_type,
        'reconcile': key == 'receivable', 'company_ids': [Command.set(company.ids)]})
customer.property_account_receivable_id = accounts['receivable']
fixture_env['account.journal'].create({'name': 'Concurrency sales', 'code': 'RACE', 'type': 'sale', 'company_id': company.id, 'default_account_id': accounts['income'].id})
journal = fixture_env['account.journal'].create({'name': 'Concurrency payroll', 'code': 'PAY', 'type': 'general', 'company_id': company.id})
product = fixture_env['product.product'].create({'name': 'Concurrency security service', 'type': 'service', 'company_id': company.id,
    'property_account_income_id': accounts['income'].id, 'taxes_id': [Command.clear()]})
contract = fixture_env['dct.security.contract'].create({'name': 'Concurrency contract', 'company_id': company.id, 'partner_id': customer.id,
    'site_ids': [Command.set(site.ids)], 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
fixture_env['dct.security.contract.line'].create({'name': 'Fixed service', 'contract_id': contract.id, 'site_id': site.id,
    'date_start': '2026-01-01', 'date_end': '2026-12-31', 'billing_basis': 'fixed', 'rate': 1000,
    'product_id': product.id, 'account_id': accounts['income'].id})
contract.action_activate()
bills = fixture_env['dct.security.billing'].create([{'contract_id': contract.id, 'date_start': '2026-01-01', 'date_end': '2026-01-31'} for _ in range(2)])
fixture_env['dct.security.compensation'].create({'employee_id': employee.id, 'company_id': company.id,
    'date_start': '2026-01-01', 'date_end': '2026-12-31', 'basis': 'monthly', 'rate': 1000, 'overtime_rate': 0,
    'journal_id': journal.id, 'expense_account_id': accounts['expense'].id, 'payable_account_id': accounts['payable'].id})
company_id, employee_id, contract_id, bill_ids = company.id, employee.id, contract.id, bills.ids
env.cr.commit()


def race(label, operation):
    barrier = threading.Barrier(2)

    def worker(index):
        retried = 0
        for attempt in range(5):
            with registry.cursor() as cursor:
                local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
                try:
                    # Establish both transaction snapshots before either mutation.
                    local['dct.security.contract'].browse(contract_id).read(['name'])
                    if attempt == 0:
                        barrier.wait(timeout=30)
                    value = operation(local, index)
                    cursor.commit()
                    return {'status': 'ok', 'id': value, 'retries': retried}
                except (SerializationFailure, DeadlockDetected):
                    cursor.rollback()
                    retried += 1
                except ValidationError as exc:
                    cursor.rollback()
                    return {'status': 'rejected', 'reason': str(exc), 'retries': retried}
        raise AssertionError(label + ': transaction retry budget exceeded')

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, (0, 1)))
    print(json.dumps({'test': label, 'results': results}))
    return results


def approve_billing(local, index):
    record = local['dct.security.billing'].browse(bill_ids[index])
    record.action_approve()
    return record.id


approval = race('overlapping billing approvals', approve_billing)
assert sorted(r['status'] for r in approval) == ['ok', 'rejected'], approval
winner_bill = next(r['id'] for r in approval if r['status'] == 'ok')


def create_invoice(local, index):
    record = local['dct.security.billing'].browse(winner_bill)
    record.action_create_invoice()
    return record.invoice_id.id


invoices = race('repeated invoice creation', create_invoice)
assert all(r['status'] == 'ok' for r in invoices) and invoices[0]['id'] == invoices[1]['id'], invoices


def create_payroll(local, index):
    return local['dct.security.payroll'].create({'employee_id': employee_id, 'company_id': company_id,
        'date_start': '2026-01-01', 'date_end': '2026-01-31'}).id


payrolls = race('overlapping payroll creation', create_payroll)
assert sorted(r['status'] for r in payrolls) == ['ok', 'rejected'], payrolls
winner_payroll = next(r['id'] for r in payrolls if r['status'] == 'ok')
with registry.cursor() as cursor:
    local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
    worksheet = local['dct.security.payroll'].browse(winner_payroll)
    worksheet.action_review()
    worksheet.action_approve()
    cursor.commit()


def create_entry(local, index):
    record = local['dct.security.payroll'].browse(winner_payroll)
    record.action_create_entry()
    return record.move_id.id


entries = race('repeated payroll journal creation', create_entry)
assert all(r['status'] == 'ok' for r in entries) and entries[0]['id'] == entries[1]['id'], entries
print('DCT_FINANCE_CONCURRENCY_PASS: 4 independent-cursor races passed')
