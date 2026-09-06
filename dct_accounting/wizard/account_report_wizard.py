from dateutil.relativedelta import relativedelta

from odoo import _, api, Command, fields, models
from odoo.exceptions import ValidationError


REPORT_TYPES = [
    ("balance_sheet", "Balance Sheet"),
    ("profit_loss", "Profit & Loss"),
    ("executive_summary", "Executive Summary"),
    ("cash_flow", "Cash Flow Statement"),
    ("general_ledger", "General Ledger"),
    ("trial_balance", "Trial Balance"),
    ("journal_ledger", "Journal Audit"),
    ("partner_ledger", "Partner Ledger"),
    ("aged_receivable", "Aged Receivable"),
    ("aged_payable", "Aged Payable"),
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
    def _section(
        name,
        *,
        balance=0.0,
        level=0,
        line_key=False,
        parent_key=False,
        foldable=True,
        show_amount=False,
        style_class="section",
    ):
        return {
            "line_type": "section",
            "name": name,
            "balance": balance,
            "ending_balance": balance,
            "is_total": True,
            "hierarchy_level": level,
            "line_key": line_key,
            "parent_key": parent_key,
            "foldable": foldable,
            "show_amount": show_amount,
            "style_class": style_class,
        }

    @staticmethod
    def _total(
        name,
        balance,
        *,
        level=0,
        parent_key=False,
        style_class="subtotal",
        **values,
    ):
        return {
            "line_type": "total",
            "name": name,
            "balance": balance,
            "ending_balance": balance,
            "is_total": True,
            "hierarchy_level": level,
            "parent_key": parent_key,
            "show_amount": True,
            "style_class": style_class,
            **values,
        }

    @staticmethod
    def _with_hierarchy(rows, level, parent_key):
        for row in rows:
            row.update({
                "hierarchy_level": level,
                "parent_key": parent_key,
                "show_amount": True,
                "style_class": "normal",
            })
        return rows

    @staticmethod
    def _rows_total(rows, key="balance"):
        return sum(row.get(key, 0.0) for row in rows)

    def _account_type_balance(self, domain, account_types, sign=1.0):
        totals = self._read_account_totals(domain, account_types)
        return sign * sum(values["balance"] for values in totals.values())

    def _profit_loss_lines(self):
        domain = self._base_domain(self.date_from, self.date_to)
        income_rows = self._with_hierarchy(
            self._account_rows(domain, ("income",), sign=-1.0),
            1,
            "income",
        )
        cost_rows = self._with_hierarchy(
            self._account_rows(domain, ("expense_direct_cost",)),
            1,
            "cost_sales",
        )
        expense_rows = self._with_hierarchy(self._account_rows(
            domain,
            ("expense", "expense_depreciation"),
        ), 1, "expense")
        other_income_rows = self._with_hierarchy(
            self._account_rows(domain, ("income_other",), sign=-1.0),
            1,
            "other_income",
        )
        other_expense_rows = self._with_hierarchy(
            self._account_rows(domain, ("expense_other",)),
            1,
            "other_expense",
        )
        income = self._rows_total(income_rows)
        cost = self._rows_total(cost_rows)
        expenses = self._rows_total(expense_rows)
        other_income = self._rows_total(other_income_rows)
        other_expense = self._rows_total(other_expense_rows)
        gross_profit = income - cost
        net_operating_income = gross_profit - expenses
        net_other_income = other_income - other_expense
        net_income = net_operating_income + net_other_income
        return [
            self._section(
                _("Income"),
                balance=income,
                line_key="income",
                show_amount=True,
            ),
            *income_rows,
            self._section(
                _("Cost of Sales"),
                balance=cost,
                line_key="cost_sales",
                show_amount=True,
            ),
            *cost_rows,
            self._total(
                _("Gross Profit"),
                gross_profit,
                style_class="grand",
            ),
            self._section(
                _("Expense"),
                balance=expenses,
                line_key="expense",
                show_amount=True,
            ),
            *expense_rows,
            self._total(
                _("Net Operating Income"),
                net_operating_income,
                style_class="grand",
            ),
            self._section(
                _("Other Income"),
                balance=other_income,
                line_key="other_income",
                show_amount=True,
            ),
            *other_income_rows,
            self._section(
                _("Other Expense"),
                balance=other_expense,
                line_key="other_expense",
                show_amount=True,
            ),
            *other_expense_rows,
            self._total(
                _("Net Other Income"),
                net_other_income,
                style_class="grand",
            ),
            self._total(_("Net Income"), net_income, style_class="grand"),
        ]

    def _balance_sheet_lines(self):
        domain = self._base_domain(date_to=self.date_to)
        def account_rows(account_types, sign, level, parent_key):
            return self._with_hierarchy(
                self._account_rows(domain, account_types, sign=sign),
                level,
                parent_key,
            )

        cash_rows = account_rows(("asset_cash",), 1.0, 3, "assets_cash")
        receivable_rows = account_rows(("asset_receivable",), 1.0, 3, "assets_receivable")
        current_other_rows = account_rows(("asset_current",), 1.0, 3, "assets_other_current")
        prepayment_rows = account_rows(("asset_prepayments",), 1.0, 3, "assets_prepayments")
        fixed_asset_rows = account_rows(("asset_fixed",), 1.0, 2, "assets_fixed")
        non_current_rows = account_rows(("asset_non_current",), 1.0, 2, "assets_non_current")

        payable_rows = account_rows(("liability_payable",), -1.0, 3, "liabilities_payable")
        credit_card_rows = account_rows(("liability_credit_card",), -1.0, 3, "liabilities_card")
        current_other_liability_rows = account_rows(
            ("liability_current",), -1.0, 3, "liabilities_other_current"
        )
        non_current_liability_rows = account_rows(
            ("liability_non_current",), -1.0, 2, "liabilities_non_current"
        )
        equity_rows = account_rows(
            ("equity", "equity_unaffected"), -1.0, 2, "equity"
        )

        cash = self._rows_total(cash_rows)
        receivables = self._rows_total(receivable_rows)
        other_current_assets = self._rows_total(current_other_rows)
        prepayments = self._rows_total(prepayment_rows)
        fixed_assets = self._rows_total(fixed_asset_rows)
        other_non_current_assets = self._rows_total(non_current_rows)
        current_assets = cash + receivables + other_current_assets + prepayments
        non_current_assets = fixed_assets + other_non_current_assets
        total_assets = current_assets + non_current_assets
        payables = self._rows_total(payable_rows)
        credit_cards = self._rows_total(credit_card_rows)
        other_current_liabilities = self._rows_total(current_other_liability_rows)
        current_liabilities = payables + credit_cards + other_current_liabilities
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
            self._section(
                _("Assets"), line_key="assets", style_class="primary"
            ),
            self._section(
                _("Current Assets"), level=1, line_key="assets_current", parent_key="assets"
            ),
            self._section(
                _("Bank and Cash"), level=2, line_key="assets_cash", parent_key="assets_current"
            ),
            *cash_rows,
            self._total(_("Total Bank and Cash"), cash, level=2, parent_key="assets_cash"),
            self._section(
                _("Accounts Receivable"),
                level=2,
                line_key="assets_receivable",
                parent_key="assets_current",
            ),
            *receivable_rows,
            self._total(
                _("Total Accounts Receivable"),
                receivables,
                level=2,
                parent_key="assets_receivable",
            ),
            self._section(
                _("Other Current Assets"),
                level=2,
                line_key="assets_other_current",
                parent_key="assets_current",
            ),
            *current_other_rows,
            self._total(
                _("Total Other Current Assets"),
                other_current_assets,
                level=2,
                parent_key="assets_other_current",
            ),
            self._section(
                _("Prepayments"),
                level=2,
                line_key="assets_prepayments",
                parent_key="assets_current",
            ),
            *prepayment_rows,
            self._total(
                _("Total Prepayments"),
                prepayments,
                level=2,
                parent_key="assets_prepayments",
            ),
            self._total(
                _("Total Current Assets"), current_assets, level=1, parent_key="assets_current"
            ),
            self._section(
                _("Fixed Assets"), level=1, line_key="assets_fixed", parent_key="assets"
            ),
            *fixed_asset_rows,
            self._total(
                _("Total Fixed Assets"), fixed_assets, level=1, parent_key="assets_fixed"
            ),
            self._section(
                _("Other Assets"),
                level=1,
                line_key="assets_non_current",
                parent_key="assets",
            ),
            *non_current_rows,
            self._total(
                _("Total Other Assets"),
                other_non_current_assets,
                level=1,
                parent_key="assets_non_current",
            ),
            self._total(_("Total Assets"), total_assets, style_class="grand"),
            self._section(
                _("Liabilities & Equity"),
                line_key="liabilities_equity",
                style_class="primary",
            ),
            self._section(
                _("Current Liabilities"),
                level=1,
                line_key="liabilities_current",
                parent_key="liabilities_equity",
            ),
            self._section(
                _("Accounts Payable"),
                level=2,
                line_key="liabilities_payable",
                parent_key="liabilities_current",
            ),
            *payable_rows,
            self._total(
                _("Total Accounts Payable"),
                payables,
                level=2,
                parent_key="liabilities_payable",
            ),
            self._section(
                _("Credit Cards"),
                level=2,
                line_key="liabilities_card",
                parent_key="liabilities_current",
            ),
            *credit_card_rows,
            self._total(
                _("Total Credit Cards"),
                credit_cards,
                level=2,
                parent_key="liabilities_card",
            ),
            self._section(
                _("Other Current Liabilities"),
                level=2,
                line_key="liabilities_other_current",
                parent_key="liabilities_current",
            ),
            *current_other_liability_rows,
            self._total(
                _("Total Other Current Liabilities"),
                other_current_liabilities,
                level=2,
                parent_key="liabilities_other_current",
            ),
            self._total(
                _("Total Current Liabilities"),
                current_liabilities,
                level=1,
                parent_key="liabilities_current",
            ),
            self._section(
                _("Long-term Liabilities"),
                level=1,
                line_key="liabilities_non_current",
                parent_key="liabilities_equity",
            ),
            *non_current_liability_rows,
            self._total(
                _("Total Long-term Liabilities"),
                non_current_liabilities,
                level=1,
                parent_key="liabilities_non_current",
            ),
            self._total(_("Total Liabilities"), total_liabilities),
            self._section(
                _("Equity"),
                level=1,
                line_key="equity",
                parent_key="liabilities_equity",
            ),
            *equity_rows,
            self._total(
                _("Current Year Unallocated Earnings"),
                current_earnings,
                level=2,
                parent_key="equity",
            ),
            self._total(_("Total Equity"), total_equity, level=1, parent_key="equity"),
            self._total(
                _("Total Liabilities & Equity"),
                total_liabilities_equity,
                style_class="grand",
            ),
        ]

    def _executive_summary_lines(self):
        period_domain = self._base_domain(self.date_from, self.date_to)
        position_domain = self._base_domain(date_to=self.date_to)

        revenue = self._account_type_balance(
            period_domain,
            ("income", "income_other"),
            sign=-1.0,
        )
        direct_cost = self._account_type_balance(
            period_domain,
            ("expense_direct_cost",),
        )
        operating_expenses = self._account_type_balance(
            period_domain,
            ("expense", "expense_other", "expense_depreciation"),
        )
        gross_profit = revenue - direct_cost
        net_profit = gross_profit - operating_expenses

        cash = self._account_type_balance(position_domain, ("asset_cash",))
        receivables = self._account_type_balance(position_domain, ("asset_receivable",))
        payables = self._account_type_balance(
            position_domain,
            ("liability_payable",),
            sign=-1.0,
        )
        current_assets = self._account_type_balance(
            position_domain,
            ("asset_receivable", "asset_cash", "asset_current", "asset_prepayments"),
        )
        current_liabilities = self._account_type_balance(
            position_domain,
            ("liability_payable", "liability_credit_card", "liability_current"),
            sign=-1.0,
        )

        return [
            self._section(_("Performance")),
            self._total(_("Revenue"), revenue),
            self._total(_("Gross Profit"), gross_profit),
            self._total(_("Operating Expenses"), operating_expenses),
            self._total(_("Net Income"), net_profit),
            self._section(_("Financial Position")),
            self._total(_("Cash and Bank"), cash),
            self._total(_("Receivables"), receivables),
            self._total(_("Payables"), payables),
            self._total(_("Working Capital"), current_assets - current_liabilities),
        ]

    def _cash_flow_lines(self):
        opening_domain = self._base_domain(
            date_to=self.date_from - relativedelta(days=1),
        )
        period_domain = self._base_domain(self.date_from, self.date_to)
        cash_types = ("asset_cash",)
        opening = self._read_account_totals(opening_domain, cash_types)
        period = self._read_account_totals(period_domain, cash_types)
        account_ids = set(opening) | set(period)

        rows = []
        accounts = self.env["account.account"].browse(account_ids).with_company(self.company_id)
        for account in sorted(accounts, key=lambda item: (item.code or "", item.name or "")):
            opening_balance = opening.get(account.id, {}).get("balance", 0.0)
            cash_in = period.get(account.id, {}).get("debit", 0.0)
            cash_out = period.get(account.id, {}).get("credit", 0.0)
            movement = period.get(account.id, {}).get("balance", 0.0)
            ending_balance = opening_balance + movement
            if not self.show_zero and all(
                self.currency_id.is_zero(value)
                for value in (opening_balance, cash_in, cash_out, ending_balance)
            ):
                continue
            rows.append({
                "line_type": "account",
                "code": account.code,
                "name": account.name,
                "account_id": account.id,
                "opening_balance": opening_balance,
                "period_debit": cash_in,
                "period_credit": cash_out,
                "debit": cash_in,
                "credit": cash_out,
                "balance": movement,
                "ending_balance": ending_balance,
                "can_drilldown": True,
            })

        return [
            self._section(_("Cash and Bank Accounts")),
            *rows,
            self._total(
                _("Net Cash and Cash Equivalents"),
                self._rows_total(rows),
                opening_balance=self._rows_total(rows, "opening_balance"),
                period_debit=self._rows_total(rows, "period_debit"),
                period_credit=self._rows_total(rows, "period_credit"),
                ending_balance=self._rows_total(rows, "ending_balance"),
            ),
        ]

    def _aged_partner_lines(self, account_type, sign=1.0):
        base_domain = self._base_domain(date_to=self.date_to) + [
            ("account_id.account_type", "=", account_type),
            ("amount_residual", "!=", 0.0),
        ]
        date_30 = self.date_to - relativedelta(days=30)
        date_60 = self.date_to - relativedelta(days=60)
        date_90 = self.date_to - relativedelta(days=90)
        buckets = [
            (
                "bucket_current",
                ["|", ("date_maturity", "=", False), ("date_maturity", ">=", self.date_to)],
            ),
            (
                "bucket_1_30",
                [("date_maturity", "<", self.date_to), ("date_maturity", ">=", date_30)],
            ),
            (
                "bucket_31_60",
                [("date_maturity", "<", date_30), ("date_maturity", ">=", date_60)],
            ),
            (
                "bucket_61_90",
                [("date_maturity", "<", date_60), ("date_maturity", ">=", date_90)],
            ),
            ("bucket_older", [("date_maturity", "<", date_90)]),
        ]
        partner_values = {}
        for field_name, bucket_domain in buckets:
            grouped = self.env["account.move.line"]._read_group(
                base_domain + bucket_domain,
                ["partner_id"],
                ["amount_residual:sum"],
            )
            for partner, residual in grouped:
                key = partner.id if partner else 0
                values = partner_values.setdefault(key, {
                    "partner": partner,
                    "bucket_current": 0.0,
                    "bucket_1_30": 0.0,
                    "bucket_31_60": 0.0,
                    "bucket_61_90": 0.0,
                    "bucket_older": 0.0,
                })
                values[field_name] = sign * (residual or 0.0)

        rows = []
        for values in sorted(
            partner_values.values(),
            key=lambda item: item["partner"].display_name if item["partner"] else "",
        ):
            total = sum(values[field_name] for field_name, _domain in buckets)
            if not self.show_zero and self.currency_id.is_zero(total):
                continue
            partner = values["partner"]
            rows.append({
                "line_type": "account",
                "name": partner.display_name if partner else _("Unassigned"),
                "partner_id": partner.id if partner else False,
                "balance": total,
                "ending_balance": total,
                "bucket_current": values["bucket_current"],
                "bucket_1_30": values["bucket_1_30"],
                "bucket_31_60": values["bucket_31_60"],
                "bucket_61_90": values["bucket_61_90"],
                "bucket_older": values["bucket_older"],
                "can_drilldown": True,
            })

        return [
            *rows,
            self._total(
                _("TOTAL"),
                self._rows_total(rows),
                bucket_current=self._rows_total(rows, "bucket_current"),
                bucket_1_30=self._rows_total(rows, "bucket_1_30"),
                bucket_31_60=self._rows_total(rows, "bucket_31_60"),
                bucket_61_90=self._rows_total(rows, "bucket_61_90"),
                bucket_older=self._rows_total(rows, "bucket_older"),
            ),
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
            "executive_summary": self._executive_summary_lines,
            "cash_flow": self._cash_flow_lines,
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
            "aged_receivable": lambda: self._aged_partner_lines("asset_receivable"),
            "aged_payable": lambda: self._aged_partner_lines(
                "liability_payable",
                sign=-1.0,
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
        if self.report_type in ("profit_loss", "balance_sheet", "executive_summary"):
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
        if report_type in ("aged_receivable", "aged_payable"):
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

        lines = []
        for line in wizard.line_ids.sorted("sequence"):
            lines.append({
                "id": line.id,
                "sequence": line.sequence,
                "line_type": line.line_type,
                "line_key": line.line_key or f"line-{line.id}",
                "parent_key": line.parent_key or "",
                "level": line.hierarchy_level,
                "foldable": line.foldable,
                "show_amount": line.show_amount,
                "style_class": line.style_class or "normal",
                "code": line.code or "",
                "name": line.name,
                "opening_balance": line.opening_balance,
                "debit": line.period_debit,
                "credit": line.period_credit,
                "balance": line.balance,
                "ending_balance": line.ending_balance,
                "comparison_balance": line.comparison_balance,
                "variance": line.variance,
                "bucket_current": line.bucket_current,
                "bucket_1_30": line.bucket_1_30,
                "bucket_31_60": line.bucket_31_60,
                "bucket_61_90": line.bucket_61_90,
                "bucket_older": line.bucket_older,
                "can_drilldown": line.can_drilldown,
                "is_total": line.is_total,
            })

        unposted_domain = [
            ("company_id", "=", wizard.company_id.id),
            ("account_id", "!=", False),
            ("parent_state", "=", "draft"),
            ("date", "<=", wizard.date_to),
        ]
        if wizard.report_type not in ("balance_sheet", "aged_receivable", "aged_payable"):
            unposted_domain.append(("date", ">=", wizard.date_from))

        return {
            "wizard_id": wizard.id,
            "report_type": wizard.report_type,
            "report_name": wizard.report_name,
            "company_name": wizard.company_id.display_name,
            "company_country_code": wizard.company_id.country_id.code or "",
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
            "has_unposted_entries": bool(
                self.env["account.move.line"].search_count(unposted_domain, limit=1)
            ),
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
    hierarchy_level = fields.Integer(default=0, readonly=True)
    line_key = fields.Char(readonly=True)
    parent_key = fields.Char(readonly=True)
    foldable = fields.Boolean(readonly=True)
    show_amount = fields.Boolean(default=True, readonly=True)
    style_class = fields.Selection(
        [
            ("normal", "Normal"),
            ("section", "Section"),
            ("primary", "Primary Section"),
            ("subtotal", "Subtotal"),
            ("grand", "Grand Total"),
        ],
        default="normal",
        readonly=True,
    )
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
    bucket_current = fields.Monetary(currency_field="currency_id", readonly=True)
    bucket_1_30 = fields.Monetary(currency_field="currency_id", readonly=True)
    bucket_31_60 = fields.Monetary(currency_field="currency_id", readonly=True)
    bucket_61_90 = fields.Monetary(currency_field="currency_id", readonly=True)
    bucket_older = fields.Monetary(currency_field="currency_id", readonly=True)
    is_total = fields.Boolean(readonly=True)
    can_drilldown = fields.Boolean(readonly=True)

    def action_open_journal_items(self):
        self.ensure_one()
        wizard = self.wizard_id
        if wizard.report_type in ("balance_sheet", "aged_receivable", "aged_payable"):
            domain = wizard._base_domain(date_to=wizard.date_to)
        else:
            domain = wizard._base_domain(wizard.date_from, wizard.date_to)
        if wizard.report_type == "aged_receivable":
            domain.extend([
                ("account_id.account_type", "=", "asset_receivable"),
                ("amount_residual", "!=", 0.0),
            ])
        elif wizard.report_type == "aged_payable":
            domain.extend([
                ("account_id.account_type", "=", "liability_payable"),
                ("amount_residual", "!=", 0.0),
            ])
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


