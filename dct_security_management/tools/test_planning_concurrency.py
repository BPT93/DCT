"""Independent PostgreSQL transaction races on a disposable test database only.

Run via Odoo shell:
    odoo-bin shell -d dct_security_test_full --no-http < tools/test_planning_concurrency.py

Fixtures are deliberately committed so independent cursors can see them. Drop
the disposable database after testing. The retry loop mirrors Odoo's handling
of Repeatable Read serialization failures; no confirmed records are deleted.
"""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from psycopg2.errors import DeadlockDetected, SerializationFailure
from odoo import api, Command, SUPERUSER_ID
from odoo.exceptions import UserError


assert env.cr.dbname.startswith('dct_security_test_'), 'Use a disposable dct_security_test_* database only'
assert env['ir.module.module'].search_count([('name', '=', 'dct_security_management'), ('state', '=', 'installed')])
registry = env.registry
suffix = uuid.uuid4().hex[:8]
company = env['res.company'].create({'name': 'DCT Fictional Planning Race ' + suffix, 'dct_rest_hours': 0})
fixture = api.Environment(env.cr, SUPERUSER_ID, {'allowed_company_ids': company.ids})
customer = fixture['res.partner'].create({'name': 'Fictional Planning Race Customer', 'company_id': company.id})
site = fixture['dct.security.site'].create({'name': 'Fictional Planning Race Site', 'company_id': company.id,
    'partner_id': customer.id, 'tz': 'UTC'})
post = fixture['dct.security.post'].create({'name': 'Gate', 'site_id': site.id, 'company_id': company.id})
guard = fixture['hr.employee'].create({'name': 'Fictional Planning Race Guard', 'company_id': company.id,
    'is_security_guard': True, 'guard_code': 'PLAN-RACE-' + suffix, 'security_site_ids': [Command.set(site.ids)]})
shifts = fixture['dct.security.shift'].create([{'name': 'Concurrent candidate %s' % index, 'company_id': company.id,
    'site_id': site.id, 'post_id': post.id, 'start': '2032-01-05 08:00:00', 'end': '2032-01-05 16:00:00',
    'required_guards': 1} for index in (1, 2)])
template = fixture['dct.security.shift.template'].create({'name': 'Concurrent generation', 'company_id': company.id,
    'site_id': site.id, 'post_id': post.id, 'start_hour': 8, 'end_hour': 16})
publish_shift = fixture['dct.security.shift'].create({'name': 'Concurrent publication', 'company_id': company.id,
    'site_id': site.id, 'post_id': post.id, 'start': '2032-03-01 08:00:00', 'end': '2032-03-01 16:00:00', 'required_guards': 1})
wizards = fixture['dct.security.generate.roster'].create([{'template_id': template.id, 'date_from': '2032-02-01',
    'date_to': '2032-02-03'} for _ in (1, 2)])
company_id, guard_id, shift_ids, template_id, wizard_ids = company.id, guard.id, shifts.ids, template.id, wizards.ids
publish_shift_id = publish_shift.id
env.cr.commit()


def race(label, operation):
    barrier = threading.Barrier(2)

    def worker(index):
        retries = 0
        for attempt in range(5):
            with registry.cursor() as cursor:
                local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
                try:
                    # Both snapshots exist before either worker writes.
                    local['hr.employee'].browse(guard_id).read(['name'])
                    if attempt == 0:
                        barrier.wait(timeout=30)
                    result = operation(local, index)
                    cursor.commit()
                    return {'status': 'ok', 'value': result, 'retries': retries}
                except (SerializationFailure, DeadlockDetected):
                    cursor.rollback()
                    retries += 1
                except UserError as exc:
                    cursor.rollback()
                    return {'status': 'rejected', 'reason': str(exc), 'retries': retries}
        raise AssertionError(label + ': transaction retry budget exceeded')

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, (0, 1)))
    print(json.dumps({'test': label, 'results': results}))
    return results


def create_assignment(local, index):
    return local['dct.security.assignment'].create({'shift_id': shift_ids[index], 'employee_id': guard_id,
        'company_id': company_id}).id


assignments = race('overlapping guard assignments', create_assignment)
assert sorted(result['status'] for result in assignments) == ['ok', 'rejected'], assignments
winner_assignment = next(result['value'] for result in assignments if result['status'] == 'ok')
with registry.cursor() as cursor:
    local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
    assignment = local['dct.security.assignment'].browse(winner_assignment)
    assert local['dct.security.assignment'].search_count([('employee_id', '=', guard_id)]) == 1
    assignment.shift_id.action_publish()
    attendance = local['hr.attendance'].create({'employee_id': guard_id, 'check_in': assignment.start, 'check_out': assignment.end})
    attendance_id = attendance.id
    cursor.commit()


def create_allocation(local, index):
    return local['dct.security.allocation'].create({'assignment_id': winner_assignment, 'attendance_id': attendance_id,
        'company_id': company_id, 'start': '2032-01-05 08:00:00', 'end': '2032-01-05 12:00:00'}).id


allocations = race('overlapping attendance allocations', create_allocation)
assert sorted(result['status'] for result in allocations) == ['ok', 'rejected'], allocations


def generate_roster(local, index):
    wizard = local['dct.security.generate.roster'].browse(wizard_ids[index])
    wizard.action_preview()
    wizard.action_generate()
    return sorted(local['dct.security.shift'].search([('template_id', '=', template_id)]).ids)


generated = race('repeated roster generation', generate_roster)
assert all(result['status'] == 'ok' for result in generated), generated
assert generated[0]['value'] == generated[1]['value'] and len(generated[0]['value']) == 3, generated
with registry.cursor() as cursor:
    local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
    assert local['dct.security.allocation'].search_count([('attendance_id', '=', attendance_id)]) == 1
    assert local['dct.security.shift'].search_count([('template_id', '=', template_id)]) == 3


def publish_or_add(local, index):
    shift = local['dct.security.shift'].browse(publish_shift_id)
    if index == 0:
        shift.action_publish()
        return shift.id
    return local['dct.security.assignment'].create({'shift_id': shift.id, 'employee_id': guard_id,
        'company_id': company_id}).id


publication = race('publication versus adding a guard', publish_or_add)
assert publication[0]['status'] == 'ok', publication
with registry.cursor() as cursor:
    local = api.Environment(cursor, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
    published = local['dct.security.shift'].browse(publish_shift_id)
    assert published.state == 'published'
    assert all(assignment.state == 'published' for assignment in published.assignment_ids), published.assignment_ids.read(['state'])
print('DCT_PLANNING_CONCURRENCY_PASS: 4 independent-cursor races passed')
