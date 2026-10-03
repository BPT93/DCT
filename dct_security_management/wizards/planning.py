from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from ..models.planning import Assignment, _REPLACEMENT_TOKEN


class GenerateRoster(models.TransientModel):
    _name = 'dct.security.generate.roster'
    _description = 'Preview and Generate Draft Roster'

    template_id = fields.Many2one('dct.security.shift.template', required=True)
    company_id = fields.Many2one(related='template_id.company_id')
    date_from = fields.Date(required=True, default=fields.Date.today)
    date_to = fields.Date(required=True, default=fields.Date.today)
    line_ids = fields.One2many('dct.security.generate.roster.line', 'wizard_id', readonly=True)
    preview_signature = fields.Char(readonly=True)

    def _rows(self):
        self.ensure_one()
        template = self.template_id
        template.check_access('read')
        if self.date_to < self.date_from or (self.date_to - self.date_from).days > 365:
            raise ValidationError(_('Select a date range of at most 366 days.'))
        zone = pytz.timezone(template.site_id.tz or 'UTC')
        weekdays = {int(value.strip()) for value in template.weekday_ids.split(',')}
        rows = []
        date = self.date_from
        while date <= self.date_to:
            if date.weekday() in weekdays:
                key = 'template:%s:%s' % (template.id, date.isoformat())
                start_local = datetime.combine(date, time.min) + timedelta(hours=template.start_hour)
                end_local = datetime.combine(date, time.min) + timedelta(hours=template.end_hour)
                if end_local <= start_local:
                    end_local += timedelta(days=1)
                row = {'local_date': date, 'generation_key': key}
                try:
                    row['start'] = zone.localize(start_local, is_dst=None).astimezone(pytz.utc).replace(tzinfo=None)
                    row['end'] = zone.localize(end_local, is_dst=None).astimezone(pytz.utc).replace(tzinfo=None)
                    row['status'] = 'exists' if self.env['dct.security.shift'].search_count([('generation_key', '=', key)]) else 'ready'
                except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                    row.update({'status': 'invalid', 'warning': _('Ambiguous or nonexistent local time. Create an explicit UTC shift for this date.')})
                rows.append(row)
            date += timedelta(days=1)
        return rows

    def _signature(self):
        self.ensure_one()
        template = self.template_id
        return repr((template.id, template.write_date, self.date_from, self.date_to, template.site_id.tz))

    def action_preview(self):
        self.env['dct.security.shift']._check_role('group_manager', 'group_supervisor')
        self.ensure_one()
        self.write({'line_ids': [(5, 0, 0)] + [(0, 0, row) for row in self._rows()], 'preview_signature': self._signature()})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    def action_generate(self):
        self.env['dct.security.shift']._check_role('group_manager', 'group_supervisor')
        self.ensure_one()
        template = self.template_id
        template.check_access('read')
        # Generating drafts needs read access to the template, not permission to change its policy.
        template.flush_recordset()
        self.env.cr.execute('SELECT id FROM dct_security_shift_template WHERE id=%s FOR UPDATE', [template.id])
        self.env.cr.execute('UPDATE dct_security_shift_template SET lock_version=COALESCE(lock_version,0)+1 WHERE id=%s', [template.id])
        template.invalidate_recordset()
        if self.preview_signature != self._signature():
            raise UserError(_('Preview the current template and date range before generating.'))
        rows = self._rows()
        if any(row['status'] == 'invalid' for row in rows):
            raise UserError(_('Resolve the daylight-saving warnings before generating this date range.'))
        shifts = self.env['dct.security.shift']
        for row in rows:
            existing = shifts.search([('generation_key', '=', row['generation_key'])], limit=1)
            if existing:
                continue
            shifts.create({'name': '%s — %s' % (template.name, row['local_date']), 'site_id': template.site_id.id,
                           'post_id': template.post_id.id, 'company_id': template.company_id.id,
                           'start': row['start'], 'end': row['end'], 'required_guards': template.required_guards,
                           'break_hours': template.break_hours, 'qualification_ids': [(6, 0, template.qualification_ids.ids)],
                           'template_id': template.id, 'generation_key': row['generation_key']})
        return {'type': 'ir.actions.act_window', 'name': _('Generated Draft Shifts'), 'res_model': 'dct.security.shift', 'view_mode': 'list,calendar,form', 'domain': [('generation_key', 'in', [row['generation_key'] for row in rows])]}


class GenerateRosterLine(models.TransientModel):
    _name = 'dct.security.generate.roster.line'
    _description = 'Roster Generation Preview'

    wizard_id = fields.Many2one('dct.security.generate.roster', required=True, ondelete='cascade')
    local_date = fields.Date()
    start = fields.Datetime()
    end = fields.Datetime()
    generation_key = fields.Char()
    status = fields.Selection([('ready', 'New draft'), ('exists', 'Already generated'), ('invalid', 'Needs explicit time')])
    warning = fields.Char()


class ReplaceGuard(models.TransientModel):
    _name = 'dct.security.replace.guard'
    _description = 'Replace Scheduled Guard'

    assignment_id = fields.Many2one('dct.security.assignment', required=True)
    company_id = fields.Many2one(related='assignment_id.company_id')
    employee_id = fields.Many2one('hr.employee', required=True)
    reason = fields.Text(required=True)
    override_reason = fields.Text()

    def action_replace(self):
        self.ensure_one()
        old = self.assignment_id
        old._check_role('group_manager', 'group_supervisor')
        old.shift_id._lock()
        old._lock()
        if old.state != 'published' or old.shift_id.state != 'published':
            raise UserError(_('Only a published assignment can be replaced.'))
        if not self.reason.strip() or old.employee_id == self.employee_id:
            raise ValidationError(_('Select another guard and record a replacement reason.'))
        if old.allocation_ids:
            raise UserError(_('This assignment already has worked attendance. Create a separate shift for the remaining interval to preserve its history.'))
        employee_ids = tuple(sorted((old.employee_id | self.employee_id).ids))
        self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [employee_ids])
        self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [employee_ids])
        super(Assignment, old).write({'state': 'replaced'})
        new = super(Assignment, self.env['dct.security.assignment']).create({'shift_id': old.shift_id.id,
            'employee_id': self.employee_id.id, 'company_id': old.company_id.id, 'override_reason': self.override_reason})
        new._publish()
        self.env['dct.security.replacement'].with_context(dct_replacement_token=_REPLACEMENT_TOKEN).create({'old_assignment_id': old.id, 'new_assignment_id': new.id,
            'company_id': old.company_id.id, 'reason': self.reason})
        old.message_post(body=_('Guard replaced. Reason: %s', self.reason))
        return {'type': 'ir.actions.act_window', 'res_model': 'dct.security.assignment', 'res_id': new.id, 'view_mode': 'form'}
