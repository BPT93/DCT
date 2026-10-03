from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


def _staff(records, manager=False):
    allowed = ['group_manager'] if manager else ['group_manager', 'group_supervisor']
    if not records.env.su and not any(records.env.user.has_group('dct_security_management.' + group) for group in allowed):
        raise AccessError(_('This action requires an authorized operations officer.'))


def _alert(record, summary):
    """Only notify responsible authorized users; avoid duplicate pending activities."""
    users = record.site_id.supervisor_ids
    if 'investigator_id' in record._fields and record.investigator_id:
        users |= record.investigator_id
    for user in users:
        if record.company_id not in user.company_ids or not (
            user.has_group('dct_security_management.group_manager') or
            user.has_group('dct_security_management.group_supervisor')
        ):
            continue
        record._activity_once(user, summary)


class IncidentCategory(models.Model):
    _name = 'dct.security.incident.category'
    _inherit = 'dct.security.mixin'
    _description = 'Incident Category'
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)


class Incident(models.Model):
    _name = 'dct.security.incident'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Security Incident'
    _order = 'occurred_at desc, id desc'
    _check_company_auto = True

    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False, index=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, index=True, tracking=True)
    post_id = fields.Many2one('dct.security.post', check_company=True, tracking=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True, tracking=True)
    reported_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    reporter_id = fields.Many2one('res.users', default=lambda s: s.env.user, required=True, readonly=True)
    guard_ids = fields.Many2many('hr.employee', string='Involved Guards', check_company=True, tracking=True)
    category_id = fields.Many2one('dct.security.incident.category', check_company=True, required=True, tracking=True)
    severity = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')], required=True, default='medium', tracking=True)
    description = fields.Text(required=True, tracking=True)
    investigator_id = fields.Many2one('res.users', tracking=True)
    deadline = fields.Date(tracking=True, index=True)
    corrective_actions = fields.Text(tracking=True)
    resolution = fields.Text(tracking=True)
    reopen_reason = fields.Text(copy=False)
    state = fields.Selection([('new', 'New'), ('acknowledged', 'Acknowledged'), ('investigating', 'Investigating'), ('resolved', 'Resolved'), ('closed', 'Closed')], default='new', required=True, readonly=True, tracking=True, index=True, copy=False)

    @api.constrains('site_id', 'post_id', 'guard_ids', 'investigator_id', 'company_id')
    def _check_relationships(self):
        for rec in self:
            if rec.post_id and rec.post_id.site_id != rec.site_id:
                raise ValidationError(_('The post must belong to the incident site.'))
            if any(not g.is_security_guard or g.company_id != rec.company_id for g in rec.guard_ids):
                raise ValidationError(_('Involved employees must be guards in the incident company.'))
            if rec.investigator_id and (rec.company_id not in rec.investigator_id.company_ids or not (
                rec.investigator_id.has_group('dct_security_management.group_manager') or
                rec.investigator_id in rec.site_id.supervisor_ids
            )):
                raise ValidationError(_('The investigator must be an authorized manager or supervisor of this site.'))

    @api.model_create_multi
    def create(self, vals_list):
        _staff(self)
        for vals in vals_list:
            if vals.get('state', 'new') != 'new':
                raise AccessError(_('Create incidents in the New state.'))
            vals.update(name=self.env['ir.sequence'].next_by_code('dct.security.incident') or _('New'),
                        reporter_id=self.env.uid, reported_at=fields.Datetime.now())
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: r.severity == 'critical'):
            _alert(rec, _('Critical security incident'))
        return records

    def write(self, vals):
        _staff(self)
        if set(vals) & {'state', 'name', 'reporter_id', 'reported_at'}:
            raise AccessError(_('Use the incident workflow buttons.'))
        if any(r.state == 'closed' for r in self) and set(vals) - {'reopen_reason', 'message_follower_ids', 'activity_ids'}:
            raise UserError(_('Reopen a closed incident before changing it.'))
        result = super().write(vals)
        if vals.get('severity') == 'critical':
            for rec in self:
                _alert(rec, _('Critical security incident'))
        return result

    def _transition(self, source, target):
        _staff(self)
        self._lock()
        if any(r.state not in source for r in self):
            raise UserError(_('This incident transition is not available.'))
        if target in ('resolved', 'closed') and any(not (r.resolution or '').strip() for r in self):
            raise ValidationError(_('Enter a resolution before resolving or closing an incident.'))
        return super(Incident, self).write({'state': target})

    def action_acknowledge(self):
        return self._transition(['new'], 'acknowledged')

    def action_investigate(self):
        return self._transition(['acknowledged'], 'investigating')

    def action_resolve(self):
        return self._transition(['investigating'], 'resolved')

    def action_close(self):
        return self._transition(['resolved'], 'closed')

    def action_reopen(self):
        _staff(self, manager=True)
        if any(not (r.reopen_reason or '').strip() for r in self):
            raise ValidationError(_('Record why the incident is being reopened.'))
        self._transition(['closed', 'resolved'], 'investigating')
        for rec in self:
            rec.message_post(body=_('Incident reopened: %s', rec.reopen_reason))
        return super(Incident, self).write({'reopen_reason': False})

    def unlink(self):
        _staff(self, manager=True)
        if any(r.state != 'new' for r in self):
            raise UserError(_('Incident history must be retained.'))
        return super().unlink()

    @api.model
    def _cron_alerts(self):
        if not self.env.company.dct_automation_enabled:
            return
        for record in self.search([('company_id', '=', self.env.company.id), ('state', 'not in', ['closed', 'resolved']), ('deadline', '<', fields.Date.today())], limit=1000):
            _alert(record, _('Overdue security incident'))


class PatrolRoute(models.Model):
    _name = 'dct.security.patrol.route'
    _inherit = 'dct.security.mixin'
    _description = 'Patrol Route'
    _check_company_auto = True
    name = fields.Char(required=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, index=True)
    active = fields.Boolean(default=True)
    instructions = fields.Text()
    checkpoint_ids = fields.One2many('dct.security.patrol.checkpoint', 'route_id', copy=True)


class PatrolCheckpoint(models.Model):
    _name = 'dct.security.patrol.checkpoint'
    _inherit = 'dct.security.mixin'
    _description = 'Route Checkpoint'
    _order = 'sequence, id'
    name = fields.Char(required=True)
    route_id = fields.Many2one('dct.security.patrol.route', required=True, ondelete='cascade', index=True)
    site_id = fields.Many2one(related='route_id.site_id', store=True, index=True)
    company_id = fields.Many2one(related='route_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    required = fields.Boolean(default=True)
    instructions = fields.Text()
    window_start_minutes = fields.Integer(default=0, help='Minutes after the planned round start.')
    window_end_minutes = fields.Integer(default=60, help='Minutes after the planned round start.')

    @api.constrains('window_start_minutes', 'window_end_minutes')
    def _check_window(self):
        for rec in self:
            if rec.window_start_minutes < 0 or rec.window_end_minutes < rec.window_start_minutes:
                raise ValidationError(_('Checkpoint timing windows must be ordered and nonnegative.'))


class PatrolRound(models.Model):
    _name = 'dct.security.patrol.round'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Patrol Round (Manual Entry)'
    _order = 'planned_start desc'
    _check_company_auto = True
    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False)
    route_id = fields.Many2one('dct.security.patrol.route', required=True, check_company=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, index=True)
    assignment_id = fields.Many2one('dct.security.assignment', check_company=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True)
    planned_start = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    planned_end = fields.Datetime(required=True, index=True)
    actual_start = fields.Datetime(readonly=True, copy=False)
    actual_end = fields.Datetime(readonly=True, copy=False)
    instructions_snapshot = fields.Text(readonly=True, copy=False)
    result_ids = fields.One2many('dct.security.patrol.result', 'round_id', copy=False)
    completion_percent = fields.Float(compute='_compute_completion', store=True)
    missed_count = fields.Integer(compute='_compute_completion', store=True)
    state = fields.Selection([('draft', 'Draft'), ('running', 'In Progress'), ('closed', 'Closed'), ('cancelled', 'Cancelled')], required=True, default='draft', readonly=True, tracking=True, index=True, copy=False)

    @api.depends('result_ids.state')
    def _compute_completion(self):
        for rec in self:
            results = rec.result_ids
            rec.completion_percent = 100 * len(results.filtered(lambda r: r.state == 'done')) / len(results) if results else 0
            rec.missed_count = len(results.filtered(lambda r: r.state == 'pending'))

    @api.onchange('route_id', 'assignment_id')
    def _onchange_route(self):
        if self.route_id:
            self.site_id = self.route_id.site_id
        if self.assignment_id:
            self.employee_id = self.assignment_id.employee_id

    @api.constrains('route_id', 'site_id', 'employee_id', 'company_id', 'assignment_id', 'planned_start', 'planned_end')
    def _check_round(self):
        for rec in self:
            if rec.route_id.site_id != rec.site_id:
                raise ValidationError(_('The route must belong to the patrol site.'))
            if not rec.employee_id.is_security_guard or rec.employee_id.company_id != rec.company_id:
                raise ValidationError(_('Choose a guard from the patrol company.'))
            if rec.site_id not in rec.employee_id.security_site_ids:
                raise ValidationError(_('The guard must be authorized for the patrol site.'))
            if rec.planned_end <= rec.planned_start:
                raise ValidationError(_('The patrol end must be after its start.'))
            if rec.assignment_id and (rec.assignment_id.site_id != rec.site_id or rec.assignment_id.employee_id != rec.employee_id or rec.assignment_id.start > rec.planned_start or rec.assignment_id.end < rec.planned_end):
                raise ValidationError(_('The assignment must cover this guard, site, and patrol interval.'))

    @api.model_create_multi
    def create(self, vals_list):
        _staff(self)
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or any(k in vals for k in ('result_ids', 'actual_start', 'actual_end', 'instructions_snapshot')):
                raise AccessError(_('Create a draft patrol and use Start to capture its checkpoints.'))
            vals['name'] = self.env['ir.sequence'].next_by_code('dct.security.patrol.round') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        _staff(self)
        if set(vals) & {'state', 'name', 'actual_start', 'actual_end', 'result_ids', 'instructions_snapshot'}:
            raise AccessError(_('Use the patrol workflow buttons.'))
        if any(rec.state != 'draft' for rec in self) and set(vals) - {'message_follower_ids', 'activity_ids'}:
            raise UserError(_('Started patrol details are frozen to preserve history.'))
        return super().write(vals)

    def action_start(self):
        _staff(self)
        self._lock()
        for rec in self:
            if rec.state != 'draft' or not rec.route_id.checkpoint_ids:
                raise UserError(_('Start a draft patrol with at least one checkpoint.'))
            if not rec.employee_id.security_eligible or (rec.assignment_id and rec.assignment_id.state != 'published'):
                raise UserError(_('A patrol requires an eligible guard and a published assignment when linked.'))
            self.env['dct.security.patrol.result']._create_snapshots(rec)
            super(PatrolRound, rec).write({'state': 'running', 'actual_start': fields.Datetime.now(), 'instructions_snapshot': rec.route_id.instructions})
        return True

    def action_close(self):
        _staff(self)
        self._lock()
        for rec in self:
            if rec.state != 'running':
                raise UserError(_('Only an in-progress patrol can be closed.'))
            if rec.result_ids.filtered(lambda r: r.required and r.state == 'pending'):
                raise UserError(_('Complete every required checkpoint or obtain a manager-approved exception.'))
            super(PatrolRound, rec).write({'state': 'closed', 'actual_end': fields.Datetime.now()})
        return True

    def action_cancel(self):
        _staff(self, manager=True)
        self._lock()
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Only draft patrol rounds can be cancelled.'))
        return super(PatrolRound, self).write({'state': 'cancelled'})

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Patrol history must be retained.'))
        return super().unlink()

    @api.model
    def _cron_alerts(self):
        if not self.env.company.dct_automation_enabled:
            return
        for rec in self.search([('company_id', '=', self.env.company.id), ('state', 'in', ['draft', 'running']), ('planned_end', '<', fields.Datetime.now())], limit=1000):
            _alert(rec, _('Overdue patrol round'))


class PatrolResult(models.Model):
    _name = 'dct.security.patrol.result'
    _inherit = 'dct.security.mixin'
    _description = 'Manual Patrol Checkpoint Result'
    _order = 'sequence, id'
    round_id = fields.Many2one('dct.security.patrol.round', required=True, ondelete='cascade', index=True)
    site_id = fields.Many2one(related='round_id.site_id', store=True, index=True)
    company_id = fields.Many2one(related='round_id.company_id', store=True)
    name = fields.Char(required=True, readonly=True)
    sequence = fields.Integer(readonly=True)
    required = fields.Boolean(readonly=True)
    instructions = fields.Text(readonly=True)
    window_start_minutes = fields.Integer(readonly=True)
    window_end_minutes = fields.Integer(readonly=True)
    state = fields.Selection([('pending', 'Pending / Missed'), ('done', 'Completed'), ('exception', 'Approved Exception')], default='pending', required=True, readonly=True)
    completed_at = fields.Datetime(readonly=True)
    actor_id = fields.Many2one('res.users', readonly=True)
    entry_source = fields.Selection([('manual', 'Manual backend entry')], default='manual', readonly=True)
    notes = fields.Text()
    evidence = fields.Binary(attachment=True)
    evidence_name = fields.Char()
    exception_reason = fields.Text()
    exception_approved_by = fields.Many2one('res.users', readonly=True)
    exception_approved_at = fields.Datetime(readonly=True)
    outside_window = fields.Boolean(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Checkpoint snapshots are generated by starting the patrol.'))

    @api.model
    def _create_snapshots(self, patrol):
        return super(PatrolResult, self).create([{
            'round_id': patrol.id, 'name': c.name, 'sequence': c.sequence,
            'required': c.required, 'instructions': c.instructions,
            'window_start_minutes': c.window_start_minutes,
            'window_end_minutes': c.window_end_minutes,
        } for c in patrol.route_id.checkpoint_ids])

    def write(self, vals):
        _staff(self)
        if set(vals) - {'notes', 'evidence', 'evidence_name', 'exception_reason'}:
            raise AccessError(_('Checkpoint snapshots and audit fields are protected.'))
        if any(r.round_id.state != 'running' or r.state != 'pending' for r in self):
            raise UserError(_('Only pending checkpoints of an open patrol can be edited.'))
        return super().write(vals)

    def action_complete(self):
        _staff(self)
        self.round_id._lock()
        self.invalidate_recordset()
        for rec in self:
            if rec.round_id.state != 'running' or rec.state != 'pending':
                raise UserError(_('This checkpoint is already processed or its patrol is closed.'))
            earlier = rec.round_id.result_ids.filtered(lambda r: r.sequence < rec.sequence and r.required and r.state == 'pending')
            if earlier:
                raise UserError(_('Complete earlier required checkpoints first.'))
            now = fields.Datetime.now()
            minutes = (now - rec.round_id.planned_start).total_seconds() / 60
            super(PatrolResult, rec).write({'state': 'done', 'completed_at': now, 'actor_id': self.env.uid,
                                          'outside_window': not rec.window_start_minutes <= minutes <= rec.window_end_minutes})
        return True

    def action_open(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new'}

    def action_approve_exception(self):
        _staff(self, manager=True)
        self.round_id._lock()
        self.invalidate_recordset()
        if any(r.state != 'pending' or r.round_id.state != 'running' or not (r.exception_reason or '').strip() for r in self):
            raise UserError(_('An open, pending checkpoint and an exception reason are required.'))
        return super(PatrolResult, self).write({'state': 'exception', 'exception_approved_by': self.env.uid,
                                              'exception_approved_at': fields.Datetime.now()})

    def unlink(self):
        raise AccessError(_('Historical checkpoint snapshots cannot be deleted.'))


class InspectionTemplate(models.Model):
    _name = 'dct.security.inspection.template'
    _inherit = 'dct.security.mixin'
    _description = 'Supervisor Inspection Checklist'
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    item_ids = fields.One2many('dct.security.inspection.item', 'template_id', copy=True)


class InspectionItem(models.Model):
    _name = 'dct.security.inspection.item'
    _inherit = 'dct.security.mixin'
    _description = 'Inspection Checklist Item'
    _order = 'sequence, id'
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    required = fields.Boolean(default=True)
    template_id = fields.Many2one('dct.security.inspection.template', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='template_id.company_id', store=True)


class SupervisorVisit(models.Model):
    _name = 'dct.security.visit'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Supervisor Site Visit'
    _order = 'planned_at desc'
    _check_company_auto = True
    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, index=True)
    supervisor_id = fields.Many2one('hr.employee', required=True, check_company=True)
    template_id = fields.Many2one('dct.security.inspection.template', check_company=True, required=True)
    planned_at = fields.Datetime(required=True, default=fields.Datetime.now)
    actual_start = fields.Datetime(readonly=True, copy=False)
    actual_end = fields.Datetime(readonly=True, copy=False)
    findings = fields.Text(tracking=True)
    followup_actions = fields.Text(tracking=True)
    photo = fields.Image(attachment=True)
    incident_id = fields.Many2one('dct.security.incident', check_company=True)
    incident_category_id = fields.Many2one('dct.security.incident.category', check_company=True)
    result_ids = fields.One2many('dct.security.visit.result', 'visit_id', copy=False)
    state = fields.Selection([('planned', 'Planned'), ('in_progress', 'In Progress'), ('done', 'Completed'), ('cancelled', 'Cancelled')], default='planned', required=True, readonly=True, tracking=True, index=True, copy=False)

    @api.constrains('supervisor_id', 'site_id', 'incident_id')
    def _check_visit(self):
        for rec in self:
            if rec.incident_id and rec.incident_id.site_id != rec.site_id:
                raise ValidationError(_('The linked incident must belong to the visit site.'))
            if rec.supervisor_id.company_id != rec.company_id:
                raise ValidationError(_('The supervisor must belong to the visit company.'))

    @api.model_create_multi
    def create(self, vals_list):
        _staff(self)
        for vals in vals_list:
            if vals.get('state', 'planned') != 'planned' or set(vals) & {'actual_start', 'actual_end', 'result_ids'}:
                raise AccessError(_('Create a planned visit and use Start Inspection.'))
            vals['name'] = self.env['ir.sequence'].next_by_code('dct.security.visit') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        _staff(self)
        if set(vals) & {'state', 'name', 'actual_start', 'actual_end', 'result_ids'}:
            raise AccessError(_('Use the visit workflow buttons.'))
        if any(r.state != 'planned' for r in self) and set(vals) & {'site_id', 'company_id', 'supervisor_id', 'template_id', 'planned_at'}:
            raise UserError(_('Started inspection details are frozen.'))
        if any(r.state in ['done', 'cancelled'] for r in self) and set(vals) - {'incident_id', 'message_follower_ids', 'activity_ids'}:
            raise UserError(_('Completed inspection evidence is frozen.'))
        return super().write(vals)

    def action_start(self):
        _staff(self)
        self._lock()
        for rec in self:
            if rec.state != 'planned' or not rec.template_id.item_ids:
                raise UserError(_('Start a planned visit with a configured checklist.'))
            self.env['dct.security.visit.result']._create_snapshots(rec)
            super(SupervisorVisit, rec).write({'state': 'in_progress', 'actual_start': fields.Datetime.now()})
        return True

    def action_complete(self):
        _staff(self)
        self._lock()
        for rec in self:
            if rec.state != 'in_progress' or rec.result_ids.filtered(lambda r: r.required and r.result == 'pending'):
                raise UserError(_('Complete the required inspection items before finishing the visit.'))
            super(SupervisorVisit, rec).write({'state': 'done', 'actual_end': fields.Datetime.now()})
        return True

    def action_cancel(self):
        _staff(self)
        self._lock()
        if any(r.state != 'planned' for r in self):
            raise UserError(_('Only planned visits may be cancelled.'))
        return super(SupervisorVisit, self).write({'state': 'cancelled'})

    def action_create_incident(self):
        _staff(self)
        self.ensure_one()
        self._lock()
        if not self.incident_id:
            if not self.findings or not self.incident_category_id:
                raise UserError(_('Provide findings and an incident category first.'))
            incident = self.env['dct.security.incident'].create({
                'company_id': self.company_id.id, 'site_id': self.site_id.id,
                'category_id': self.incident_category_id.id, 'description': self.findings,
                'occurred_at': self.actual_start or self.planned_at,
            })
            self.write({'incident_id': incident.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'dct.security.incident', 'res_id': self.incident_id.id, 'view_mode': 'form', 'views': [(False, 'form')]}

    def unlink(self):
        if any(r.state != 'planned' for r in self):
            raise UserError(_('Inspection history must be retained.'))
        return super().unlink()


class VisitResult(models.Model):
    _name = 'dct.security.visit.result'
    _inherit = 'dct.security.mixin'
    _description = 'Inspection Result Snapshot'
    _order = 'sequence, id'
    visit_id = fields.Many2one('dct.security.visit', required=True, ondelete='cascade', index=True)
    site_id = fields.Many2one(related='visit_id.site_id', store=True, index=True)
    company_id = fields.Many2one(related='visit_id.company_id', store=True)
    name = fields.Char(readonly=True, required=True)
    sequence = fields.Integer(readonly=True)
    required = fields.Boolean(readonly=True)
    result = fields.Selection([('pending', 'Pending'), ('pass', 'Pass'), ('fail', 'Fail'), ('na', 'Not Applicable')], required=True, default='pending')
    notes = fields.Text()
    actor_id = fields.Many2one('res.users', readonly=True)
    recorded_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Inspection snapshots are generated when a visit starts.'))

    @api.model
    def _create_snapshots(self, visit):
        return super(VisitResult, self).create([{'visit_id': visit.id, 'name': item.name, 'sequence': item.sequence, 'required': item.required} for item in visit.template_id.item_ids])

    def write(self, vals):
        _staff(self)
        self.visit_id._lock()
        self.invalidate_recordset()
        if set(vals) - {'result', 'notes'}:
            raise AccessError(_('Inspection snapshot audit fields are protected.'))
        if any(r.visit_id.state != 'in_progress' for r in self):
            raise UserError(_('Only an in-progress inspection can be edited.'))
        vals = dict(vals, actor_id=self.env.uid, recorded_at=fields.Datetime.now())
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Inspection snapshots cannot be deleted.'))

    def action_open(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new'}
