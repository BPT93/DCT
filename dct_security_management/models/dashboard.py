from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class SecurityDashboard(models.AbstractModel):
    _name = 'dct.security.dashboard'
    _description = 'Permission-filtered Security Operations Overview'

    def _filters(self, date_start=False, date_end=False, site_id=False, company_id=False):
        if not any(self.env.user.has_group('dct_security_management.' + g) for g in
                   ('group_manager', 'group_supervisor', 'group_hr', 'group_finance', 'group_readonly')):
            raise AccessError(_('Security Operations access is required.'))
        company = self.env['res.company'].browse(int(company_id)) if company_id else self.env.company
        if company not in self.env.companies:
            raise AccessError(_('This company is not in your allowed companies.'))
        start = fields.Date.to_date(date_start) if date_start else fields.Date.today().replace(day=1)
        end = fields.Date.to_date(date_end) if date_end else fields.Date.today()
        if not start or not end or end < start or (end - start).days > 366:
            raise ValidationError(_('Choose an ordered reporting period of no more than 366 days.'))
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_dt = tz.localize(datetime.combine(start, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end_dt = tz.localize(datetime.combine(end + timedelta(days=1), time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        sites = self.env['dct.security.site'].search([('company_id', '=', company.id)])
        selected = self.env['dct.security.site']
        if site_id:
            selected = sites.filtered(lambda s: s.id == int(site_id))
            if not selected:
                raise AccessError(_('This site is outside your operational scope.'))
        base = [('company_id', '=', company.id)]
        if selected:
            base += [('site_id', '=', selected.id)]
        return company, sites, selected, start, end, start_dt, end_dt, base

    def _action(self, model, domain, name):
        views = [(False, 'list'), (False, 'form')]
        if model == 'hr.employee':
            views = [(self.env.ref('dct_security_management.view_guard_list').id, 'list'),
                     (self.env.ref('dct_security_management.view_guard_form').id, 'form')]
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'views': views, 'domain': domain}

    @api.model
    def get_guard_form(self, employee_id):
        self._filters()
        guard = self.env['hr.employee'].browse(int(employee_id)).exists()
        guard.ensure_one()
        guard.check_access('read')
        if not guard.is_security_guard:
            raise AccessError(_('Select a security guard.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.employee', 'res_id': guard.id,
                'views': [(self.env.ref('dct_security_management.view_guard_form').id, 'form')]}

    @api.model
    def get_overview(self, date_start=False, date_end=False, site_id=False, company_id=False):
        company, sites, selected, start, end, start_dt, end_dt, base = self._filters(date_start, date_end, site_id, company_id)
        now = fields.Datetime.now()
        A = self.env['dct.security.assignment']
        S = self.env['dct.security.shift']
        period = base + [('start', '>=', start_dt), ('start', '<', end_dt)]
        live_domain = base + [('state', '=', 'published'), ('start', '<=', now), ('end', '>', now)]
        all_live = A.search(live_domain)
        current_leave_ids = set(all_live.employee_id._security_current_leave_ids(now))
        live = all_live.filtered(lambda a: not a.leave_conflict and a.employee_id.id not in current_leave_ids)
        live_guard_ids = live.employee_id.ids
        valid_attendance = self.env['hr.attendance'].search([
            ('employee_id', 'in', live_guard_ids), ('check_out', '=', False),
            ('check_in', '<=', now), ('check_in', '>=', now - timedelta(hours=company.dct_max_open_hours or 16))])
        present_ids = set(valid_attendance.employee_id.ids)
        live_counts = defaultdict(lambda: {'required': 0, 'assigned': 0, 'present': 0})
        for shift in S.search(live_domain):
            live_counts[shift.site_id.id]['required'] += shift.required_guards
        for assignment in live:
            live_counts[assignment.site_id.id]['assigned'] += 1
            live_counts[assignment.site_id.id]['present'] += int(assignment.employee_id.id in present_ids)
        guard_domain = [('company_id', '=', company.id), ('is_security_guard', '=', True)]
        if selected:
            guard_domain += [('security_site_ids', 'in', selected.ids)]
        incident_domain = base + [('state', 'not in', ['resolved', 'closed'])]
        contract_domain = [('company_id', '=', company.id), ('state', '=', 'active'), ('date_start', '<=', fields.Date.today()), ('date_end', '>=', fields.Date.today())]
        if selected:
            contract_domain += [('site_ids', 'in', selected.ids)]
        shifts = S.search(period + [('state', '=', 'published')])
        shortage_ids = shifts.filtered(lambda s: s.missing_guards > 0).ids
        assignments = A.search(period + [('state', '=', 'published')])
        exceptions = assignments.filtered(lambda a: a.attendance_state in ['late', 'missing_checkout', 'suspected_absence'])
        scoped_guards = self.env['hr.employee'].search(guard_domain)
        leave_guard_ids = list(scoped_guards._security_current_leave_ids(now))
        patrol_domain = base + [('planned_start', '>=', start_dt), ('planned_start', '<', end_dt), ('state', '!=', 'cancelled')]
        rounds = self.env['dct.security.patrol.round'].search(patrol_domain)
        completed = rounds.filtered(lambda r: r.state == 'closed')

        def card(key, title, value, model, domain, period_type, definition):
            return {'key': key, 'title': title, 'value': value, 'period_type': period_type,
                    'definition': definition, 'action': self._action(model, domain, title)}

        cards = [
            card('guards', _('Guards'), self.env['hr.employee'].search_count(guard_domain), 'hr.employee', guard_domain, 'now', _('Active guard records in your permitted company/site scope.')),
            card('present', _('On duty now'), len(present_ids), 'dct.security.assignment', live_domain + [('employee_id', 'in', list(present_ids))], 'now', _('Guards on a published current assignment with a valid open attendance within the maximum open-hours policy.')),
            card('leave', _('Guards on leave'), len(leave_guard_ids), 'hr.employee', [('id', 'in', leave_guard_ids)], 'now', _('Scoped guards with approved leave covering the current time, including guards without a scheduled shift.')),
            card('sites', _('Active sites'), len(sites.filtered(lambda s: s.state == 'active' and (not selected or s == selected))), 'dct.security.site', [('id', 'in', selected.ids or sites.ids), ('state', '=', 'active')], 'now', _('Sites with active operational status.')),
            card('contracts', _('Active contracts'), self.env['dct.security.contract'].search_count(contract_domain), 'dct.security.contract', contract_domain, 'now', _('Active contracts effective today.')),
            card('incidents', _('Open incidents'), self.env['dct.security.incident'].search_count(incident_domain), 'dct.security.incident', incident_domain, 'now', _('Incidents which have not been resolved or closed.')),
            card('shortages', _('Uncovered shifts'), len(shortage_ids), 'dct.security.shift', [('id', 'in', shortage_ids)], 'period', _('Published shifts starting in the period with fewer valid assignments than required guards.')),
            card('exceptions', _('Attendance exceptions'), len(exceptions), 'dct.security.assignment', [('id', 'in', exceptions.ids)], 'period', _('Published assignments starting in the period marked late, missing checkout, or suspected absence. Review is required before financial consequences.')),
            card('patrols', _('Closed patrol rounds'), len(completed), 'dct.security.patrol.round', patrol_domain + [('state', '=', 'closed')], 'period', _('Closed rounds out of %s planned rounds in the period. Exceptions do not count as completed checkpoints.', len(rounds))),
        ]
        trends = defaultdict(lambda: {'scheduled': 0, 'worked': 0, 'approved': 0})
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        for a in assignments:
            day = pytz.utc.localize(a.start).astimezone(tz).date().isoformat()
            trends[day]['scheduled'] += a.scheduled_hours
            trends[day]['worked'] += a.worked_hours
            trends[day]['approved'] += a.approved_hours
        recent = []
        for model_name in ('dct.security.incident', 'dct.security.patrol.round', 'dct.security.visit'):
            model = self.env[model_name]
            state_labels = dict(model._fields['state']._description_selection(self.env))
            for rec in model.search(base, order='write_date desc', limit=6):
                recent.append({'id': rec.id, 'key': '%s,%s' % (model_name, rec.id), 'model': model_name,
                               'name': rec.name, 'site': rec.site_id.name, 'state': rec.state,
                               'state_label': state_labels[rec.state], 'updated_at': fields.Datetime.to_string(rec.write_date)})
        recent.sort(key=lambda item: item['updated_at'], reverse=True)
        data = {'cards': cards, 'sites': [{'id': s.id, 'name': s.name} for s in sites],
                'companies': [{'id': c.id, 'name': c.name} for c in self.env.companies],
                'company_id': company.id, 'company_name': company.name,
                'date_start': start.isoformat(), 'date_end': end.isoformat(),
                'generated_at': fields.Datetime.to_string(now), 'timezone': self.env.user.tz or 'UTC',
                'trends': [{'date': day, **{k: round(v, 2) for k, v in vals.items()}} for day, vals in sorted(trends.items())],
                'recent': recent[:6],
                'staffing': [{'id': s.id, 'name': s.name, **live_counts[s.id], 'missing': max(0, live_counts[s.id]['required'] - live_counts[s.id]['present'])} for s in (selected or sites)],
                'finance': []}
        if self.env.user.has_group('dct_security_management.group_finance') and self.env['account.move'].has_access('read'):
            data['finance'] = self._finance_rows(company, start, end, selected)
        return data

    def _finance_rows(self, company, start, end, site):
        try:
            rows = self.env['dct.security.billing']._dashboard_figures(company, start, end, site)
        except AccessError:
            return []
        for row in rows:
            row['action'] = self._action('account.move', [('id', 'in', row['invoice_ids'])], _('Security customer invoices'))
            row['cash_action'] = self._action('account.move', [('id', 'in', row['cash_move_ids'])], _('Security cash settlements'))
            row['cost_action'] = self._action('dct.security.payroll', [('id', 'in', row['payroll_ids'])], _('Approved payroll cost sources'))
            row['site_partial'] = bool(site)
        return rows
    @api.model
    def get_week(self, date_start=False, site_id=False, company_id=False):
        start = fields.Date.to_date(date_start) if date_start else fields.Date.today()
        start -= timedelta(days=start.weekday())
        company, sites, selected, start, end, start_dt, end_dt, base = self._filters(start, start + timedelta(days=6), site_id, company_id)
        domain = [('company_id', '=', company.id), ('is_security_guard', '=', True)]
        if selected:
            domain += [('security_site_ids', 'in', selected.ids)]
        guards = self.env['hr.employee'].search(domain, order='name', limit=151)
        assignments = self.env['dct.security.assignment'].search(base + [('employee_id', 'in', guards[:150].ids), ('start', '<', end_dt), ('end', '>', start_dt), ('state', 'not in', ['cancelled', 'replaced'])], order='start', limit=1001)
        assignment_states = dict(self.env['dct.security.assignment']._fields['state']._description_selection(self.env))
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        rows = {g.id: {'id': g.id, 'name': g.name, 'days': [[] for _ in range(7)]} for g in guards[:150]}
        for a in assignments[:1000]:
            local_start = pytz.utc.localize(a.start).astimezone(tz)
            local_end = pytz.utc.localize(a.end).astimezone(tz)
            for offset in range(7):
                day = start + timedelta(days=offset)
                if local_start.date() <= day <= (local_end - timedelta(microseconds=1)).date():
                    rows[a.employee_id.id]['days'][offset].append({'id': a.id, 'shift_id': a.shift_id.id, 'site': a.site_id.name, 'state': a.state, 'state_label': assignment_states[a.state], 'time': local_start.strftime('%d/%m %H:%M') + ' – ' + local_end.strftime('%d/%m %H:%M'), 'warning': a.attendance_state in ['on_leave', 'late', 'missing_checkout', 'suspected_absence']})
        return {'rows': list(rows.values()), 'days': [(start + timedelta(days=i)).isoformat() for i in range(7)],
                'sites': [{'id': s.id, 'name': s.name} for s in sites], 'company_id': company.id,
                'timezone': self.env.user.tz or 'UTC', 'truncated': len(guards) > 150 or len(assignments) > 1000,
                'can_plan': any(self.env.user.has_group('dct_security_management.' + g) for g in ['group_manager', 'group_supervisor']),
                'shortage_action': self._action('dct.security.shift', base + [('start', '>=', start_dt), ('start', '<', end_dt), ('state', '=', 'published'), ('missing_guards', '>', 0)], _('Uncovered shifts'))}

    @api.model
    def get_map(self, company_id=False):
        company, sites, _, *_rest = self._filters(company_id=company_id)
        now = fields.Datetime.now()
        counts = defaultdict(lambda: {'required': 0, 'assigned': 0})
        for site, quantity in self.env['dct.security.shift']._read_group([('company_id', '=', company.id), ('state', '=', 'published'), ('start', '<=', now), ('end', '>', now)], ['site_id'], ['required_guards:sum']):
            counts[site.id]['required'] = quantity
        for site, quantity in self.env['dct.security.assignment']._read_group([('company_id', '=', company.id), ('state', '=', 'published'), ('leave_conflict', '=', False), ('start', '<=', now), ('end', '>', now)], ['site_id'], ['__count']):
            counts[site.id]['assigned'] = quantity
        return {'tile_url': company.dct_map_tile_url or '', 'attribution': company.dct_map_attribution or '',
                'generated_at': fields.Datetime.to_string(now), 'sites': [{'id': s.id, 'name': s.name, 'latitude': s.latitude, 'longitude': s.longitude, 'has_coordinates': s.has_coordinates, **counts[s.id]} for s in sites]}


class OperationsReport(models.AbstractModel):
    _name = 'dct.security.report.helper'
    _description = 'Security Report Values'

    def _values(self, model, docids, financial=False):
        if financial and not self.env.user.has_group('dct_security_management.group_finance'):
            raise AccessError(_('Finance Officer access is required for this report.'))
        records = self.env[model].browse(docids).exists()
        records.check_access('read')
        return {'doc_ids': records.ids, 'doc_model': model, 'docs': records,
                'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                'report_timezone': self.env.user.tz or 'UTC'}


class CoverageReport(models.AbstractModel):
    _name = 'report.dct_security_management.coverage_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Daily Site Coverage Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.shift', docids)


class RosterReport(models.AbstractModel):
    _name = 'report.dct_security_management.roster_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Guard Roster Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.assignment', docids)


class AttendanceReport(models.AbstractModel):
    _name = 'report.dct_security_management.attendance_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Attendance and Overtime Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.assignment', docids)


class IncidentReport(models.AbstractModel):
    _name = 'report.dct_security_management.incident_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Incident Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.incident', docids)


class PatrolReport(models.AbstractModel):
    _name = 'report.dct_security_management.patrol_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Patrol Completion Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.patrol.round', docids)


class VisitReport(models.AbstractModel):
    _name = 'report.dct_security_management.visit_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Supervisor Visit Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.visit', docids)


class PayrollReport(models.AbstractModel):
    _name = 'report.dct_security_management.payroll_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Payroll Worksheet Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.payroll', docids, financial=True)


class BillingReport(models.AbstractModel):
    _name = 'report.dct_security_management.billing_document'
    _inherit = 'dct.security.report.helper'
    _description = 'Contract Billing Report'
    def _get_report_values(self, docids, data=None):
        return self._values('dct.security.billing', docids, financial=True)
