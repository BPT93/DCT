from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        compute="_compute_department_id",
        store=True,
        readonly=True,
        index=True,
    )
    dct_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("verify", "Waiting"),
            ("done", "Done"),
            ("paid", "Paid"),
            ("cancel", "Rejected"),
        ],
        string="Payroll Status",
        compute="_compute_dct_status",
        store=True,
    )
    basic_wage = fields.Monetary(
        string="Basic Wage",
        compute="_compute_payroll_totals",
        currency_field="currency_id",
        store=True,
    )
    gross_pay = fields.Monetary(
        string="Gross Wage",
        compute="_compute_payroll_totals",
        currency_field="currency_id",
        store=True,
    )
    net_pay = fields.Monetary(
        string="Net Wage",
        compute="_compute_payroll_totals",
        currency_field="currency_id",
        store=True,
    )
    employer_cost = fields.Monetary(
        string="Employer Cost",
        compute="_compute_payroll_totals",
        currency_field="currency_id",
        store=True,
    )
    paid_time_off_days = fields.Float(
        string="Days of Paid Time Off",
        compute="_compute_time_off_days",
        store=True,
    )
    unpaid_time_off_days = fields.Float(
        string="Days of Unpaid Time Off",
        compute="_compute_time_off_days",
        store=True,
    )
    close_date = fields.Date(string="Close Date")

    @api.depends("employee_id")
    def _compute_department_id(self):
        # Keep a payroll-period snapshot: moving an employee later must not
        # rewrite the department used by historical salary analysis.
        for payslip in self:
            payslip.department_id = payslip.employee_id.department_id

    @api.depends("state", "paid")
    def _compute_dct_status(self):
        for payslip in self:
            payslip.dct_status = "paid" if payslip.paid else payslip.state

    @api.depends("line_ids.code", "line_ids.total")
    def _compute_payroll_totals(self):
        for payslip in self:
            payslip.basic_wage = sum(
                payslip.line_ids.filtered(
                    lambda line: (line.code or "").upper() == "BASIC"
                ).mapped("total")
            )
            payslip.gross_pay = sum(
                payslip.line_ids.filtered(
                    lambda line: (line.code or "").upper() == "GROSS"
                ).mapped("total")
            )
            payslip.net_pay = sum(
                payslip.line_ids.filtered(
                    lambda line: (line.code or "").upper() == "NET"
                ).mapped("total")
            )
            company_cost_lines = payslip.line_ids.filtered(
                lambda line: any(
                    marker in (line.code or "").upper()
                    for marker in ("EMPLOYER", "COMPANY", "ER_")
                )
            )
            payslip.employer_cost = payslip.gross_pay + sum(
                company_cost_lines.mapped("total")
            )

    @api.depends(
        "worked_days_line_ids.code",
        "worked_days_line_ids.number_of_days",
    )
    def _compute_time_off_days(self):
        unpaid_markers = ("UNPAID", "UNP", "LWOP", "LEAVE0")
        work_markers = ("WORK", "ATTEND")
        for payslip in self:
            paid_days = 0.0
            unpaid_days = 0.0
            for line in payslip.worked_days_line_ids:
                code = (line.code or "").upper()
                if any(marker in code for marker in work_markers):
                    continue
                days = abs(line.number_of_days)
                if any(marker in code for marker in unpaid_markers):
                    unpaid_days += days
                else:
                    paid_days += days
            payslip.paid_time_off_days = paid_days
            payslip.unpaid_time_off_days = unpaid_days

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            period_end = vals.get("date_to")
            if period_end:
                vals.setdefault("close_date", period_end)
                vals.setdefault("date", period_end)
        return super().create(vals_list)

    @api.onchange("date_from", "date_to")
    def onchange_dates(self):
        result = super().onchange_dates()
        for payslip in self:
            if payslip.date_to and payslip.state == "draft":
                payslip.close_date = payslip.date_to
                payslip.date = payslip.date_to
        return result

    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        values = super().get_inputs(contracts, date_from, date_to)
        input_types = self.env["hr.rule.input"]
        for value in values:
            input_type = input_types.search(
                [("code", "=", value.get("code"))], limit=1
            )
            value["dct_input_type_id"] = input_type.id
        return values

    @api.model
    def action_open_new_off_cycle(self, *args):
        today = fields.Date.context_today(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("New Off-Cycle Payslip"),
            "res_model": "hr.payslip",
            "view_mode": "form",
            "views": [(self.env.ref("payroll.hr_payslip_view_form").id, "form")],
            "target": "current",
            "context": {
                "default_date_from": today.replace(day=1),
                "default_date_to": fields.Date.end_of(today, "month"),
            },
        }

    @api.model
    def action_open_new_pay_run(self, *args):
        return {
            "type": "ir.actions.act_window",
            "name": _("New Pay Run"),
            "res_model": "hr.payslip.run",
            "view_mode": "form",
            "views": [(self.env.ref("payroll.hr_payslip_run_view_form").id, "form")],
            "target": "current",
        }

    def action_create_draft_entry(self):
        for payslip in self:
            if payslip.state == "draft":
                payslip.compute_sheet()
            if payslip.state != "verify":
                raise UserError(_("Only a waiting payslip can create a draft entry."))
        result = self.action_payslip_done()
        self._dct_ensure_account_moves()
        return result

    def _dct_find_fallback_accounts(self):
        """Return company-scoped accounts for an otherwise unconfigured payroll."""
        self.ensure_one()
        accounts = self.env["account.account"].with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id]
        )
        expense_types = ["expense", "expense_direct_cost", "expense_other"]
        liability_types = ["liability_current", "liability_payable"]

        expense_account = accounts.search(
            [
                ("account_type", "in", expense_types),
                "|",
                ("name", "ilike", "salary"),
                ("name", "ilike", "salaries"),
            ],
            limit=1,
        ) or accounts.search([("account_type", "in", expense_types)], limit=1)
        payable_account = accounts.search(
            [
                ("account_type", "in", liability_types),
                ("name", "ilike", "salary"),
            ],
            limit=1,
        ) or accounts.search([("account_type", "in", liability_types)], limit=1)
        deductions_account = accounts.search(
            [
                ("account_type", "in", liability_types),
                "|",
                ("name", "ilike", "payroll tax"),
                ("name", "ilike", "payroll taxes"),
            ],
            limit=1,
        ) or payable_account
        return expense_account, payable_account, deductions_account

    def _dct_create_fallback_account_move(self):
        """Create a balanced draft move when salary rules have no accounts.

        The Community accounting bridge intentionally creates no move when all
        salary-rule debit and credit accounts are empty.  Enterprise exposes a
        draft entry at this stage, so keep that workflow available by posting
        gross wages to salary expense, net wages to salary payable, and the
        difference to the closest payroll-liability account.
        """
        self.ensure_one()
        if self.move_id:
            return self.move_id
        if not self.journal_id:
            raise UserError(_("Select a Salary Journal before creating the entry."))

        currency = self.currency_id or self.company_id.currency_id
        gross_amount = currency.round(abs(self.gross_pay))
        net_amount = currency.round(abs(self.net_pay))
        expense_amount = max(gross_amount, net_amount)
        if currency.is_zero(expense_amount):
            raise UserError(
                _(
                    "The payslip has no Gross or Net amount. Compute the sheet and "
                    "check the salary rules before creating the journal entry."
                )
            )

        expense_account, payable_account, deductions_account = (
            self._dct_find_fallback_accounts()
        )
        if not expense_account or not payable_account:
            raise UserError(
                _(
                    "No salary expense and salary payable accounts were found for %s. "
                    "Configure the Accounting tab on the salary rules or install a "
                    "chart of accounts first."
                )
                % self.company_id.display_name
            )

        line_commands = []

        def add_line(label, account, debit=0.0, credit=0.0):
            if self.credit_note:
                debit, credit = credit, debit
            if not currency.is_zero(debit) or not currency.is_zero(credit):
                line_commands.append(
                    (
                        0,
                        0,
                        {
                            "name": label,
                            "account_id": account.id,
                            "debit": debit,
                            "credit": credit,
                        },
                    )
                )

        add_line(_("Gross Wages"), expense_account, debit=expense_amount)
        add_line(_("Net Salary Payable"), payable_account, credit=net_amount)
        deductions_amount = currency.round(expense_amount - net_amount)
        add_line(
            _("Payroll Deductions"),
            deductions_account,
            credit=deductions_amount,
        )

        accounting_date = self.date or self.date_to or fields.Date.context_today(self)
        move = self.env["account.move"].create(
            {
                "date": accounting_date,
                "journal_id": self.journal_id.id,
                "ref": self.number or self.name,
                "narration": _("Payslip of %s") % self.employee_id.display_name,
                "line_ids": line_commands,
            }
        )
        self.write({"move_id": move.id, "date": accounting_date})
        return move

    def _dct_ensure_account_moves(self, retry_standard=False):
        """Ensure each done payslip owns a visible draft accounting entry."""
        missing = self.filtered(lambda payslip: not payslip.move_id)
        if retry_standard and missing:
            missing.with_context(without_compute_sheet=True).action_payslip_done()

        for payslip in self.filtered(lambda slip: not slip.move_id):
            payslip._dct_create_fallback_account_move()

        for payslip in self:
            move = payslip.move_id
            if payslip.paid and move.state == "draft":
                move.action_post()
            elif not payslip.paid and move.state == "posted":
                if move.journal_id.restrict_mode_hash_table:
                    raise UserError(
                        _(
                            "The journal entry was posted automatically and its journal "
                            "uses hash locking, so it cannot be returned to draft."
                        )
                    )
                move.button_draft()
        return self.mapped("move_id")

    def action_mark_paid(self):
        invalid = self.filtered(lambda payslip: payslip.state != "done")
        if invalid:
            raise UserError(_("Create the draft entry before marking a payslip as paid."))
        missing_entry = self.filtered(lambda payslip: not payslip.move_id)
        if missing_entry:
            raise UserError(
                _("Create and post the journal entry before marking the payslip as paid.")
            )
        unposted = self.filtered(
            lambda payslip: payslip.move_id and payslip.move_id.state != "posted"
        )
        if unposted:
            raise UserError(_("Post the journal entry before marking the payslip as paid."))
        self.write({"paid": True})
        return True

    def action_open_journal_entry(self):
        self.ensure_one()
        if not self.move_id:
            if self.state != "done":
                raise UserError(
                    _("Create the draft entry before opening the journal entry.")
                )
            self._dct_ensure_account_moves(retry_standard=True)
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Entry"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_download_payment_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/dct_payroll/payment-report/payslip/{self.id}",
            "target": "download",
        }


class HrPayslipInput(models.Model):
    _inherit = "hr.payslip.input"

    dct_input_type_id = fields.Many2one("hr.rule.input", string="Type")

    @api.onchange("dct_input_type_id")
    def _onchange_dct_input_type_id(self):
        for line in self:
            if line.dct_input_type_id:
                line.code = line.dct_input_type_id.code
                line.name = line.dct_input_type_id.name
