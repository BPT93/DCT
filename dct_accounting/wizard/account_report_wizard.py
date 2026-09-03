from dateutil.relativedelta import relativedelta

from odoo import _, api, Command, fields, models
from odoo.exceptions import ValidationError


REPORT_TYPES = [
    ("profit_loss", "Profit & Loss"),
    ("balance_sheet", "Balance Sheet"),
    ("trial_balance", "Trial Balance"),
    ("general_ledger", "General Ledger"),
    ("partner_ledger", "Partner Ledger"),
    ("journal_ledger", "Journal Ledger"),
]

COMPARISON_TYPES = [
    ("none", "No Comparison"),
    ("previous_period", "Previous Period"),
    ("previous_year", "Previous Year"),
]


class DctAccountReportWizard(models.TransientModel):
    _name = "dct.account.report.wizard"
    _description = "DCT Financial Report"

    @api.model
    def _default_date_from(self):
        return fields.Date.context_today(self).replace(day=1)

    report_type = fields.Selection(
        REPORT_TYPES,
        required=True,
        default="profit_loss",
        string="Report",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        readonly=True,
    )
    date_from = fields.Date(required=True, default=_default_date_from)
    date_to = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    target_move = fields.Selection(
        [("posted", "Posted Entries"), ("all", "All Entries")],
        required=True,
        default="posted",
    )
    journal_ids = fields.Many2many(
        "account.journal",
        string="Journals",
        domain="[('company_id', '=', company_id)]",
    )
    account_ids = fields.Many2many(
        "account.account",
        string="Accounts",
        domain="[('company_ids', 'in', [company_id])]",
    )
    partner_ids = fields.Many2many("res.partner", string="Partners")
    show_zero = fields.Boolean(string="Show Zero-balance Lines")
    comparison = fields.Selection(
        COMPARISON_TYPES,
        required=True,
        default="none",
        string="Comparison",
    )
    comparison_date_from = fields.Date(readonly=True)
    comparison_date_to = fields.Date(readonly=True)
    comparison_label = fields.Char(readonly=True)
    line_ids = fields.One2many(
        "dct.account.report.line",
        "wizard_id",
        string="Report Lines",
        readonly=True,
    )
    generated_at = fields.Datetime(readonly=True)
    line_count = fields.Integer(compute="_compute_line_count")
    report_name = fields.Char(compute="_compute_report_name")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)

    @api.depends("report_type")
    def _compute_report_name(self):
        labels = dict(self._fields["report_type"]._description_selection(self.env))
        for wizard in self:
            wizard.report_name = labels.get(wizard.report_type, _("Financial Report"))

    @api.onchange("company_id")
    def _onchange_company_id(self):
        self.journal_ids = False
        self.account_ids = False
        self.line_ids = False

    def _check_dates(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("The start date must be before the end date."))

    def _base_domain(self, date_from=None, date_to=None):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("account_id", "!=", False),
        ]
        if self.target_move == "posted":
            domain.append(("parent_state", "=", "posted"))
        else:
            domain.append(("parent_state", "!=", "cancel"))
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        if self.journal_ids:
            domain.append(("journal_id", "in", self.journal_ids.ids))
        if self.account_ids:
            domain.append(("account_id", "in", self.account_ids.ids))
        if self.partner_ids:
            domain.append(("partner_id", "in", self.partner_ids.ids))
        return domain

    def _read_account_totals(self, domain, account_types=None):
        self.ensure_one()
        if account_types:
            domain = domain + [("account_id.account_type", "in", tuple(account_types))]
        grouped = self.env["account.move.line"]._read_group(
            domain,
            ["account_id"],
            ["debit:sum", "credit:sum", "balance:sum"],
        )
        totals = {
            account.id: {
                "account": account,
                "debit": debit or 0.0,
                "credit": credit or 0.0,
                "balance": balance or 0.0,
            }
            for account, debit, credit, balance in grouped
            if account
        }
        if self.show_zero and account_types:
            account_domain = [
                ("company_ids", "in", [self.company_id.id]),
                ("account_type", "in", tuple(account_types)),
            ]
            if self.account_ids:
                account_domain.append(("id", "in", self.account_ids.ids))
            for account in self.env["account.account"].search(account_domain):
                totals.setdefault(account.id, {
                    "account": account,
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": 0.0,
                })
        return totals

    def _account_rows(self, domain, account_types, sign=1.0):
        totals = self._read_account_totals(domain, account_types)
        rows = []
        for values in sorted(
            totals.values(),
            key=lambda item: (item["account"].code or "", item["account"].name or ""),
        ):
            account = values["account"].with_company(self.company_id)
            balance = sign * values["balance"]
            if not self.show_zero and self.currency_id.is_zero(balance):
                continue
            rows.append({
                "line_type": "account",
                "code": account.code,
                "name": account.name,
                "account_id": account.id,
                "debit": values["debit"],
                "credit": values["credit"],
                "balance": balance,
                "period_debit": values["debit"],
                "period_credit": values["credit"],
                "ending_balance": balance,
                "can_drilldown": True,
            })
        return rows

    @staticmethod
    def _section(name):
        return {
            "line_type": "section",
            "name": name,
            "is_total": True,
        }

    @staticmethod
    def _total(name, balance, **values):
        return {
            "line_type": "total",
            "name": name,
            "balance": balance,
            "ending_balance": balance,
            "is_total": True,
            **values,
        }

    @staticmethod
    def _rows_total(rows, key="balance"):
        return sum(row.get(key, 0.0) for row in rows)

    def _profit_loss_lines(self):
        domain = self._base_domain(self.date_from, self.date_to)
        revenue_rows = self._account_rows(domain, ("income", "income_other"), sign=-1.0)
        cost_rows = self._account_rows(domain, ("expense_direct_cost",))
        expense_rows = self._account_rows(
            domain,
            ("expense", "expense_other", "expense_depreciation"),
        )
        revenue = self._rows_total(revenue_rows)
        cost = self._rows_total(cost_rows)
        expenses = self._rows_total(expense_rows)
        gross_profit = revenue - cost
        net_profit = gross_profit - expenses
        return [
            self._section(_("Revenue")),
            *revenue_rows,
            self._total(_("Total Revenue"), revenue),
            self._section(_("Cost of Revenue")),
            *cost_rows,
            self._total(_("Total Cost of Revenue"), cost),
            self._total(_("Gross Profit"), gross_profit),
            self._section(_("Operating Expenses")),
            *expense_rows,
            self._total(_("Total Operating Expenses"), expenses),
            self._total(_("Net Profit / Loss"), net_profit),
        ]

    def _balance_sheet_lines(self):
        domain = self._base_domain(date_to=self.date_to)
        current_asset_rows = self._account_rows(
            domain,
            ("asset_receivable", "asset_cash", "asset_current", "asset_prepayments"),
        )
        non_current_asset_rows = self._account_rows(
            domain,
            ("asset_non_current", "asset_fixed"),
        )
        current_liability_rows = self._account_rows(
            domain,
            ("liability_payable", "liability_credit_card", "liability_current"),
            sign=-1.0,
        )
        non_current_liability_rows = self._account_rows(
            domain,
            ("liability_non_current",),
            sign=-1.0,
        )
        equity_rows = self._account_rows(
            domain,
            ("equity", "equity_unaffected"),
            sign=-1.0,
        )

        current_assets = self._rows_total(current_asset_rows)
        non_current_assets = self._rows_total(non_current_asset_rows)
        total_assets = current_assets + non_current_assets
        current_liabilities = self._rows_total(current_liability_rows)
        non_current_liabilities = self._rows_total(non_current_liability_rows)
        total_liabilities = current_liabilities + non_current_liabilities
        equity = self._rows_total(equity_rows)

        fiscal_start = self.company_id.compute_fiscalyear_dates(self.date_to)["date_from"]
        earnings_domain = self._base_domain(fiscal_start, self.date_to) + [
            ("account_id.internal_group", "in", ("income", "expense")),
        ]
        earnings_group = self.env["account.move.line"]._read_group(
            earnings_domain,
            [],
            ["balance:sum"],
        )
        current_earnings = -((earnings_group[0][0] if earnings_group else 0.0) or 0.0)
        total_equity = equity + current_earnings
        total_liabilities_equity = total_liabilities + total_equity

        return [
            self._section(_("Current Assets")),
            *current_asset_rows,
            self._total(_("Total Current Assets"), current_assets),
            self._section(_("Non-current Assets")),
            *non_current_asset_rows,
            self._total(_("Total Non-current Assets"), non_current_assets),
            self._total(_("TOTAL ASSETS"), total_assets),
            self._section(_("Current Liabilities")),
            *current_liability_rows,
            self._total(_("Total Current Liabilities"), current_liabilities),
            self._section(_("Non-current Liabilities")),
            *non_current_liability_rows,
            self._total(_("Total Non-current Liabilities"), non_current_liabilities),
            self._total(_("TOTAL LIABILITIES"), total_liabilities),
            self._section(_("Equity")),
            *equity_rows,
            self._total(_("Current Period Earnings"), current_earnings),
            self._total(_("TOTAL EQUITY"), total_equity),
            self._total(_("TOTAL LIABILITIES & EQUITY"), total_liabilities_equity),
        ]

    def _ledger_account_lines(self):
        opening_domain = self._base_domain(date_to=self.date_from - relativedelta(days=1))
        period_domain = self._base_domain(self.date_from, self.date_to)
        opening = self._read_account_totals(opening_domain)
        period = self._read_account_totals(period_domain)
        account_ids = set(opening) | set(period)
        if self.show_zero:
            account_domain = [("company_ids", "in", [self.company_id.id])]
            if self.account_ids:
                account_domain.append(("id", "in", self.account_ids.ids))
            account_ids.update(self.env["account.account"].search(account_domain).ids)

        rows = []
        accounts = self.env["account.account"].browse(account_ids).with_company(self.company_id)
        for account in sorted(accounts, key=lambda item: (item.code or "", item.name or "")):
            opening_balance = opening.get(account.id, {}).get("balance", 0.0)
            debit = period.get(account.id, {}).get("debit", 0.0)
            credit = period.get(account.id, {}).get("credit", 0.0)
            period_balance = period.get(account.id, {}).get("balance", 0.0)
            ending = opening_balance + period_balance
            if not self.show_zero and all(
                self.currency_id.is_zero(value)
                for value in (opening_balance, debit, credit, ending)
            ):
                continue
            rows.append({
                "line_type": "account",
                "code": account.code,
                "name": account.name,
                "account_id": account.id,
                "opening_balance": opening_balance,
                "period_debit": debit,
                "period_credit": credit,
                "debit": debit,
                "credit": credit,
                "balance": period_balance,
                "ending_balance": ending,
                "can_drilldown": True,
            })
        return [
            *rows,
            self._total(
                _("TOTAL"),
                self._rows_total(rows),
                opening_balance=self._rows_total(rows, "opening_balance"),
                period_debit=self._rows_total(rows, "period_debit"),
                period_credit=self._rows_total(rows, "period_credit"),
                ending_balance=self._rows_total(rows, "ending_balance"),
            ),
        ]

    def _grouped_ledger_lines(self, groupby, relation_field, account_types=None):
        opening_domain = self._base_domain(date_to=self.date_from - relativedelta(days=1))
        period_domain = self._base_domain(self.date_from, self.date_to)
        if account_types:
            account_filter = [("account_id.account_type", "in", tuple(account_types))]
            opening_domain += account_filter
            period_domain += account_filter

        def read(domain):
            return {
                (record.id if record else 0): {
                    "record": record,
                    "debit": debit or 0.0,
                    "credit": credit or 0.0,
                    "balance": balance or 0.0,
                }
                for record, debit, credit, balance in self.env["account.move.line"]._read_group(
                    domain,
                    [groupby],
                    ["debit:sum", "credit:sum", "balance:sum"],
                )
            }

        opening = read(opening_domain)
        period = read(period_domain)
        keys = set(opening) | set(period)
        if self.show_zero and groupby == "partner_id" and self.partner_ids:
            for partner in self.partner_ids:
                opening.setdefault(partner.id, {
                    "record": partner,
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": 0.0,
                })
                keys.add(partner.id)
        if self.show_zero and groupby == "journal_id":
            journals = self.journal_ids or self.env["account.journal"].search([
                ("company_id", "=", self.company_id.id),
                ("active", "=", True),
            ])
            for journal in journals:
                opening.setdefault(journal.id, {
                    "record": journal,
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": 0.0,
                })
                keys.add(journal.id)
        rows = []
        for key in sorted(
            keys,
            key=lambda item: (
                (period.get(item) or opening.get(item))["record"].display_name
                if (period.get(item) or opening.get(item))["record"]
                else "",
            ),
        ):
            record = (period.get(key) or opening.get(key))["record"]
            opening_balance = opening.get(key, {}).get("balance", 0.0)
            debit = period.get(key, {}).get("debit", 0.0)
            credit = period.get(key, {}).get("credit", 0.0)
            period_balance = period.get(key, {}).get("balance", 0.0)
            ending = opening_balance + period_balance
            if not self.show_zero and all(
                self.currency_id.is_zero(value)
                for value in (opening_balance, debit, credit, ending)
            ):
                continue
            rows.append({
                "line_type": "account",
                "name": record.display_name if record else _("Unassigned"),
                relation_field: record.id if record else False,
                "opening_balance": opening_balance,
                "period_debit": debit,
                "period_credit": credit,
                "debit": debit,
                "credit": credit,
                "balance": period_balance,
                "ending_balance": ending,
                "can_drilldown": True,
            })
        return [
            *rows,
            self._total(
                _("TOTAL"),
                self._rows_total(rows),
                opening_balance=self._rows_total(rows, "opening_balance"),
                period_debit=self._rows_total(rows, "period_debit"),
                period_credit=self._rows_total(rows, "period_credit"),
                ending_balance=self._rows_total(rows, "ending_balance"),
            ),
        ]

    def _report_line_values(self):
        self.ensure_one()
        self._check_dates()
        generators = {
            "profit_loss": self._profit_loss_lines,
            "balance_sheet": self._balance_sheet_lines,
            "trial_balance": self._ledger_account_lines,
            "general_ledger": self._ledger_account_lines,
            "partner_ledger": lambda: self._grouped_ledger_lines(
                "partner_id",
                "partner_id",
                ("asset_receivable", "liability_payable"),
            ),
            "journal_ledger": lambda: self._grouped_ledger_lines(
                "journal_id",
                "journal_id",
            ),
        }
        return generators[self.report_type]()

    def _comparison_period(self):
        self.ensure_one()
        if self.comparison == "previous_year":
            return (
                self.date_from - relativedelta(years=1),
                self.date_to - relativedelta(years=1),
                _("Previous Year"),
            )
        if self.comparison == "previous_period":
            period_days = (self.date_to - self.date_from).days + 1
            comparison_to = self.date_from - relativedelta(days=1)
            return (
                comparison_to - relativedelta(days=period_days - 1),
                comparison_to,
                _("Previous Period"),
            )
        return False, False, False

    @staticmethod
    def _comparison_key(values):
        return (
            values.get("line_type"),
            values.get("account_id") or 0,
            values.get("partner_id") or 0,
            values.get("journal_id") or 0,
            values.get("code") or "",
            values.get("name") or "",
        )

    def _comparison_metric(self, values):
        if self.report_type in ("profit_loss", "balance_sheet"):
            return values.get("balance", 0.0)
        return values.get("ending_balance", 0.0)

    def _comparison_line_values(self, date_from, date_to):
        self.ensure_one()
        comparison_wizard = self.create({
            "report_type": self.report_type,
            "company_id": self.company_id.id,
            "date_from": date_from,
            "date_to": date_to,
            "target_move": self.target_move,
            "journal_ids": [Command.set(self.journal_ids.ids)],
            "account_ids": [Command.set(self.account_ids.ids)],
            "partner_ids": [Command.set(self.partner_ids.ids)],
            "show_zero": self.show_zero,
            "comparison": "none",
        })
        try:
            return comparison_wizard._report_line_values()
        finally:
            comparison_wizard.unlink()

    def _generate_lines(self):
        self.ensure_one()
        values = self._report_line_values()
        comparison_from, comparison_to, comparison_label = self._comparison_period()
        comparison_by_key = {}
        if comparison_from and comparison_to:
            comparison_by_key = {
                self._comparison_key(line_values): line_values
                for line_values in self._comparison_line_values(
                    comparison_from,
                    comparison_to,
                )
            }

        commands = [Command.clear()]
        for sequence, line_values in enumerate(values, start=1):
            comparison_values = comparison_by_key.get(self._comparison_key(line_values), {})
            current_amount = self._comparison_metric(line_values)
            comparison_amount = self._comparison_metric(comparison_values)
            commands.append(Command.create({
                "sequence": sequence,
                **line_values,
                "comparison_balance": comparison_amount,
                "variance": current_amount - comparison_amount,
            }))
        self.write({
            "line_ids": commands,
            "generated_at": fields.Datetime.now(),
            "comparison_date_from": comparison_from,
            "comparison_date_to": comparison_to,
            "comparison_label": comparison_label,
        })

    @api.model
    def get_report_data(self, options=None):
        """Return an interactive, permission-aware report payload for the OWL client."""
        options = options or {}
        report_types = {key for key, _label in REPORT_TYPES}
        comparison_types = {key for key, _label in COMPARISON_TYPES}
        report_type = options.get("report_type", "profit_loss")
        if report_type not in report_types:
            report_type = "profit_loss"
        comparison = options.get("comparison", "none")
        if comparison not in comparison_types:
            comparison = "none"
        target_move = options.get("target_move", "posted")
        if target_move not in ("posted", "all"):
            target_move = "posted"

        date_from = fields.Date.to_date(options.get("date_from")) or self._default_date_from()
        date_to = fields.Date.to_date(options.get("date_to")) or fields.Date.context_today(self)
        available_journals = self.env["account.journal"].search([
            ("company_id", "=", self.env.company.id),
            ("active", "=", True),
        ], order="sequence, code, name")
        requested_journal_ids = {
            int(journal_id)
            for journal_id in options.get("journal_ids", [])
            if str(journal_id).isdigit()
        }
        selected_journals = available_journals.filtered(
            lambda journal: journal.id in requested_journal_ids
        )
        values = {
            "report_type": report_type,
            "company_id": self.env.company.id,
            "date_from": date_from,
            "date_to": date_to,
            "target_move": target_move,
            "journal_ids": [Command.set(selected_journals.ids)],
            "show_zero": bool(options.get("show_zero")),
            "comparison": comparison,
        }

        wizard = self.browse(int(options.get("wizard_id") or 0)).exists()
        if wizard:
            wizard.check_access("write")
            wizard.write(values)
        else:
            wizard = self.create(values)
        wizard._generate_lines()

        current_section = False
        lines = []
        for line in wizard.line_ids.sorted("sequence"):
            if line.line_type == "section":
                current_section = f"section-{line.id}"
            lines.append({
                "id": line.id,
                "sequence": line.sequence,
                "line_type": line.line_type,
                "section_key": current_section,
                "code": line.code or "",
                "name": line.name,
                "opening_balance": line.opening_balance,
                "debit": line.period_debit,
                "credit": line.period_credit,
                "balance": line.balance,
                "ending_balance": line.ending_balance,
                "comparison_balance": line.comparison_balance,
                "variance": line.variance,
                "can_drilldown": line.can_drilldown,
                "is_total": line.is_total,
            })

        return {
            "wizard_id": wizard.id,
            "report_type": wizard.report_type,
            "report_name": wizard.report_name,
            "company_name": wizard.company_id.display_name,
            "date_from": fields.Date.to_string(wizard.date_from),
            "date_to": fields.Date.to_string(wizard.date_to),
            "target_move": wizard.target_move,
            "show_zero": wizard.show_zero,
            "comparison": wizard.comparison,
            "comparison_label": wizard.comparison_label or "",
            "comparison_date_from": fields.Date.to_string(wizard.comparison_date_from)
                if wizard.comparison_date_from else "",
            "comparison_date_to": fields.Date.to_string(wizard.comparison_date_to)
                if wizard.comparison_date_to else "",
            "generated_at": fields.Datetime.to_string(wizard.generated_at),
            "currency": {
                "name": wizard.currency_id.name,
                "symbol": wizard.currency_id.symbol,
                "position": wizard.currency_id.position,
                "decimal_places": wizard.currency_id.decimal_places,
            },
            "journals": [
                {
                    "id": journal.id,
                    "name": journal.display_name,
                    "code": journal.code,
                    "selected": journal in selected_journals,
                }
                for journal in available_journals
            ],
            "lines": lines,
        }

    def action_generate_report(self):
        self._generate_lines()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_print_pdf(self):
        self.ensure_one()
        if not self.line_ids:
            self._generate_lines()
        return self.env.ref("dct_accounting.action_report_dct_financial_statement").report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        if not self.line_ids:
            self._generate_lines()
        return {
            "type": "ir.actions.act_url",
            "url": f"/dct_accounting/report/{self.id}/xlsx",
            "target": "self",
        }


class DctAccountReportLine(models.TransientModel):
    _name = "dct.account.report.line"
    _description = "DCT Financial Report Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "dct.account.report.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [("section", "Section"), ("account", "Account"), ("total", "Total")],
        required=True,
        default="account",
    )
    code = fields.Char()
    name = fields.Char(required=True)
    account_id = fields.Many2one("account.account", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    journal_id = fields.Many2one("account.journal", readonly=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id", readonly=True)
    opening_balance = fields.Monetary(currency_field="currency_id", readonly=True)
    period_debit = fields.Monetary(currency_field="currency_id", readonly=True)
    period_credit = fields.Monetary(currency_field="currency_id", readonly=True)
    debit = fields.Monetary(currency_field="currency_id", readonly=True)
    credit = fields.Monetary(currency_field="currency_id", readonly=True)
    balance = fields.Monetary(currency_field="currency_id", readonly=True)
    ending_balance = fields.Monetary(currency_field="currency_id", readonly=True)
    comparison_balance = fields.Monetary(currency_field="currency_id", readonly=True)
    variance = fields.Monetary(currency_field="currency_id", readonly=True)
    is_total = fields.Boolean(readonly=True)
    can_drilldown = fields.Boolean(readonly=True)

    def action_open_journal_items(self):
        self.ensure_one()
        wizard = self.wizard_id
        if wizard.report_type == "balance_sheet":
            domain = wizard._base_domain(date_to=wizard.date_to)
        else:
            domain = wizard._base_domain(wizard.date_from, wizard.date_to)
        if self.account_id:
            domain.append(("account_id", "=", self.account_id.id))
        if self.partner_id:
            domain.append(("partner_id", "=", self.partner_id.id))
        if self.journal_id:
            domain.append(("journal_id", "=", self.journal_id.id))
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Items — %s", self.name),
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": domain,
            "context": {"create": False},
            "target": "current",
        }


