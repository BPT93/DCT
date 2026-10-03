import logging
from datetime import timedelta
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SecurityAutomation(models.Model):
    _inherit = 'dct.security.site'

    @api.model
    def _cron_security_operations(self):
        """Company opt-in dispatcher; per-operation savepoints retain diagnostics."""
        for company in self.env['res.company'].search([('dct_automation_enabled', '=', True)]):
            scoped = self.with_context(allowed_company_ids=company.ids).with_company(company)
            jobs = (
                ('dct.security.shift.template', '_cron_generate_rosters'),
                ('dct.security.attendance.exception', '_cron_attendance_exceptions'),
                ('dct.security.incident', '_cron_alerts'),
                ('dct.security.patrol.round', '_cron_alerts'),
                ('dct.security.contract', '_cron_draft_billing'),
                ('dct.security.site', '_cron_expiry_reminders'),
            )
            for model, method in jobs:
                try:
                    with self.env.cr.savepoint():
                        getattr(scoped.env[model], method)()
                except Exception:
                    _logger.exception('DCT security automation failed: company=%s model=%s method=%s', company.id, model, method)

    @api.model
    def _cron_expiry_reminders(self):
        company = self.env.company
        if not company.dct_automation_enabled:
            return
        today = fields.Date.today()
        until = today + timedelta(days=company.dct_reminder_days)
        for qualification in self.env['dct.security.guard.qualification'].search([
                ('company_id', '=', company.id), ('expiry_date', '<=', until)], limit=200):
            users = qualification.employee_id.security_site_ids.supervisor_ids
            for user in users:
                qualification._activity_once(user, _('Guard qualification expires'),
                    _('Review the qualification expiry date before publishing new assignments.'), qualification.expiry_date)
        for contract in self.env['dct.security.contract'].search([
                ('company_id', '=', company.id), ('state', 'in', ('active', 'suspended')), ('date_end', '<=', until)], limit=200):
            for user in contract.site_ids.supervisor_ids:
                contract._activity_once(user, _('Service contract expires'),
                    _('Review service continuity and successor contract terms.'), contract.date_end)


class SecurityAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.constrains('res_model', 'res_id', 'public', 'access_token')
    def _check_security_attachment_sharing(self):
        from odoo.exceptions import AccessError
        for record in self:
            if (record.res_model or '').startswith('dct.security.') and (record.public or record.access_token):
                raise AccessError(_('Security operations attachments must stay private and cannot use public access tokens.'))
