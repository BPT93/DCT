from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = "hr.payslip.run"

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    payslip_count = fields.Integer(
        string="Payslip Count",
        compute="_compute_enterprise_totals",
        store=True,
    )
    employer_cost = fields.Monetary(
        string="Employer Cost",
        compute="_compute_enterprise_totals",
        currency_field="currency_id",
        store=True,
    )
    gross_pay = fields.Monetary(
        string="Gross",
        compute="_compute_enterprise_totals",
        currency_field="currency_id",
        store=True,
    )
    net_pay = fields.Monetary(
        string="Net",
        compute="_compute_enterprise_totals",
        currency_field="currency_id",
        store=True,
    )
    dct_status = fields.Selection(
        [("ready", "Ready"), ("done", "Done"), ("paid", "Paid")],
        string="Pay Run Status",
        compute="_compute_enterprise_totals",
        store=True,
    )

    @api.depends(
        "state",
        "slip_ids",
        "slip_ids.gross_pay",
        "slip_ids.net_pay",
        "slip_ids.employer_cost",
        "slip_ids.paid",
    )
    def _compute_enterprise_totals(self):
        for pay_run in self:
            pay_run.payslip_count = len(pay_run.slip_ids)
            pay_run.gross_pay = sum(pay_run.slip_ids.mapped("gross_pay"))
            pay_run.net_pay = sum(pay_run.slip_ids.mapped("net_pay"))
            pay_run.employer_cost = sum(pay_run.slip_ids.mapped("employer_cost"))
            if pay_run.slip_ids and all(pay_run.slip_ids.mapped("paid")):
                pay_run.dct_status = "paid"
            elif pay_run.state == "close":
                pay_run.dct_status = "done"
            else:
                pay_run.dct_status = "ready"

    def action_create_draft_entries(self):
        for pay_run in self:
            if not pay_run.slip_ids:
                raise UserError(_("Add at least one payslip before processing the pay run."))
            drafts = pay_run.slip_ids.filtered(lambda slip: slip.state == "draft")
            if drafts:
                drafts.compute_sheet()
            waiting = pay_run.slip_ids.filtered(lambda slip: slip.state == "verify")
            if waiting:
                waiting.action_create_draft_entry()
            pay_run.write({"state": "close"})
        return True

    def action_mark_paid(self):
        for pay_run in self:
            payable = pay_run.slip_ids.filtered(
                lambda slip: slip.state == "done" and not slip.paid
            )
            if payable:
                payable.action_mark_paid()
        return True

    def draft_payslip_run(self):
        if any(self.mapped("slip_ids.paid")):
            raise UserError(_("A paid pay run cannot be reverted."))
        return super().draft_payslip_run()

    def action_download_payment_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/dct_payroll/payment-report/pay-run/{self.id}",
            "target": "download",
        }
