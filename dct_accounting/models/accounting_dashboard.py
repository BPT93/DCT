from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class DctAccountingDashboard(models.AbstractModel):
    _name = "dct.accounting.dashboard"
    _description = "DCT Accounting Dashboard"

    INCOME_TYPES = ["income", "income_other"]
    EXPENSE_TYPES = ["expense", "expense_depreciation", "expense_direct_cost"]

    @api.model
    def get_dashboard_data(self, period="month"):
        if not self.env.user.has_group("account.group_account_readonly"):
            raise AccessError(_("You need accounting access to open the DCT Accounting dashboard."))
        period = period if period in {"month", "quarter", "year"} else "month"
        today = fields.Date.context_today(self)
        date_from, date_to = self._period_bounds(period, today)
        previous_from, previous_to = self._previous_period(date_from, date_to)

        revenue = self._account_balance(self.INCOME_TYPES, date_from, date_to, invert=True)
        expenses = self._account_balance(self.EXPENSE_TYPES, date_from, date_to)
        previous_revenue = self._account_balance(self.INCOME_TYPES, previous_from, previous_to, invert=True)
        previous_expenses = self._account_balance(self.EXPENSE_TYPES, previous_from, previous_to)
        receivable = self._open_partner_balance("asset_receivable")
        payable = self._open_partner_balance("liability_payable", invert=True)
        cash = self._cash_balance(today)

        company = self.env.company
        return {
            "company": {
                "id": company.id,
                "name": company.name,
                "logo_url": f"/web/image/res.company/{company.id}/logo_web",
                "currency": self._currency_payload(company.currency_id),
            },
            "period": {
                "key": period,
                "label": self._period_label(period, date_from, date_to),
                "date_from": fields.Date.to_string(date_from),
                "date_to": fields.Date.to_string(date_to),
            },
            "metrics": [
                {
                    "id": "revenue",
                    "label": _("Revenue"),
                    "value": revenue,
                    "change": self._percentage_change(revenue, previous_revenue),
                    "icon": "fa-line-chart",
                    "accent": "blue",
                },
                {
                    "id": "expenses",
                    "label": _("Expenses"),
                    "value": expenses,
                    "change": self._percentage_change(expenses, previous_expenses),
                    "icon": "fa-money",
                    "accent": "coral",
                },
                {
                    "id": "receivable",
                    "label": _("Accounts Receivable"),
                    "value": receivable,
                    "change": None,
                    "icon": "fa-arrow-down",
                    "accent": "cyan",
                },
                {
                    "id": "payable",
                    "label": _("Accounts Payable"),
                    "value": payable,
                    "change": None,
                    "icon": "fa-arrow-up",
                    "accent": "violet",
                },
            ],
            "cash_balance": cash,
            "net_profit": round(revenue - expenses, 2),
            "profit_trend": self._profit_trend(today),
            "receivable_aging": self._aging("asset_receivable", today),
            "payable_aging": self._aging("liability_payable", today, invert=True),
            "overdue_invoices": self._overdue_invoices(today),
            "recent_entries": self._recent_entries(),
            "shortcuts": self._shortcuts(),
            "updated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    @staticmethod
    def _period_bounds(period, today):
        if period == "quarter":
            first_month = ((today.month - 1) // 3) * 3 + 1
            return today.replace(month=first_month, day=1), today
        if period == "year":
            return today.replace(month=1, day=1), today
        return today.replace(day=1), today

    @staticmethod
    def _previous_period(date_from, date_to):
        period_days = (date_to - date_from).days + 1
        previous_to = date_from - relativedelta(days=1)
        return previous_to - relativedelta(days=period_days - 1), previous_to

    @staticmethod
    def _percentage_change(current, previous):
        if previous:
            return round(((current - previous) / abs(previous)) * 100, 1)
        return 100.0 if current else 0.0

    @staticmethod
    def _currency_payload(currency):
        return {
            "code": currency.name,
            "symbol": currency.symbol,
            "position": currency.position,
            "digits": currency.decimal_places,
        }

    @staticmethod
    def _period_label(period, date_from, date_to):
        if period == "year":
            return str(date_to.year)
        if period == "quarter":
            return _("Q%(quarter)s %(year)s", quarter=((date_from.month - 1) // 3) + 1, year=date_from.year)
        return date_from.strftime("%B %Y")

    def _sum_move_lines(self, domain, field_name="balance"):
        rows = self.env["account.move.line"]._read_group(
            domain,
            groupby=[],
            aggregates=[f"{field_name}:sum"],
        )
        return rows[0][0] if rows else 0.0

    def _account_balance(self, account_types, date_from, date_to, invert=False):
        value = self._sum_move_lines([
            ("company_id", "=", self.env.company.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("account_id.account_type", "in", account_types),
        ])
        value = -value if invert else value
        return round(value, 2)

    def _open_partner_balance(self, account_type, invert=False):
        value = self._sum_move_lines([
            ("company_id", "=", self.env.company.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", account_type),
            ("reconciled", "=", False),
            ("amount_residual", "!=", 0),
        ], "amount_residual")
        value = -value if invert else value
        return round(max(0.0, value), 2)

    def _cash_balance(self, today):
        value = self._sum_move_lines([
            ("company_id", "=", self.env.company.id),
            ("parent_state", "=", "posted"),
            ("date", "<=", today),
            ("account_id.account_type", "=", "asset_cash"),
        ])
        return round(value, 2)

    def _profit_trend(self, today):
        first_month = today.replace(day=1) - relativedelta(months=5)
        rows = []
        for index in range(6):
            date_from = first_month + relativedelta(months=index)
            date_to = min(date_from + relativedelta(months=1, days=-1), today)
            revenue = self._account_balance(self.INCOME_TYPES, date_from, date_to, invert=True)
            expenses = self._account_balance(self.EXPENSE_TYPES, date_from, date_to)
            rows.append({
                "label": date_from.strftime("%b"),
                "revenue": revenue,
                "expenses": expenses,
                "profit": round(revenue - expenses, 2),
            })
        return rows

    def _aging(self, account_type, today, invert=False):
        base_domain = [
            ("company_id", "=", self.env.company.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", account_type),
            ("reconciled", "=", False),
            ("amount_residual", "!=", 0),
        ]
        buckets = [
            ("current", _("Not Due"), [("date_maturity", ">=", today)]),
            ("1_30", _("1–30 days"), [("date_maturity", "<", today), ("date_maturity", ">=", today - relativedelta(days=30))]),
            ("31_60", _("31–60 days"), [("date_maturity", "<", today - relativedelta(days=30)), ("date_maturity", ">=", today - relativedelta(days=60))]),
            ("61_90", _("61–90 days"), [("date_maturity", "<", today - relativedelta(days=60)), ("date_maturity", ">=", today - relativedelta(days=90))]),
            ("over_90", _("90+ days"), ["|", ("date_maturity", "=", False), ("date_maturity", "<", today - relativedelta(days=90))]),
        ]
        result = []
        for key, label, extra_domain in buckets:
            value = self._sum_move_lines(base_domain + extra_domain, "amount_residual")
            value = -value if invert else value
            result.append({"id": key, "label": label, "value": round(max(0.0, value), 2)})
        return result

    def _overdue_invoices(self, today):
        moves = self.env["account.move"].search([
            ("company_id", "=", self.env.company.id),
            ("state", "=", "posted"),
            ("move_type", "=", "out_invoice"),
            ("payment_state", "not in", ["paid", "reversed"]),
            ("invoice_date_due", "<", today),
        ], order="invoice_date_due asc, id asc", limit=6)
        return [{
            "id": move.id,
            "name": move.name,
            "partner": move.partner_id.display_name or _("No customer"),
            "due_date": fields.Date.to_string(move.invoice_date_due),
            "days_overdue": (today - move.invoice_date_due).days,
            "amount": abs(move.amount_residual_signed),
        } for move in moves]

    def _recent_entries(self):
        moves = self.env["account.move"].search([
            ("company_id", "=", self.env.company.id),
            ("state", "=", "posted"),
        ], order="date desc, id desc", limit=6)
        return [{
            "id": move.id,
            "name": move.name,
            "label": move.ref or move.partner_id.display_name or move.journal_id.display_name,
            "date": fields.Date.to_string(move.date),
            "amount": (
                abs(move.amount_total_signed)
                if move.move_type != "entry"
                else sum(move.line_ids.mapped("debit"))
            ),
            "move_type": move.move_type,
        } for move in moves]

    def _shortcuts(self):
        definitions = [
            (_("Customer Invoices"), "account.action_move_out_invoice", "fa-file-text-o"),
            (_("Vendor Bills"), "account.action_move_in_invoice", "fa-file-o"),
            (_("Customer Payments"), "account.action_account_payments", "fa-credit-card"),
            (_("Vendor Payments"), "account.action_account_payments_payable", "fa-money"),
            (_("Journal Entries"), "account.action_move_journal_line", "fa-book"),
            (_("Journal Items"), "account.action_account_moves_all", "fa-list"),
            (_("Accounting Dashboard"), "account.open_account_journal_dashboard_kanban", "fa-dashboard"),
            (_("Chart of Accounts"), "account.action_account_form", "fa-sitemap"),
            (_("Profit & Loss"), "dct_accounting.action_dct_profit_loss_interactive", "fa-line-chart"),
            (_("Balance Sheet"), "dct_accounting.action_dct_balance_sheet_interactive", "fa-balance-scale"),
            (_("Trial Balance"), "dct_accounting.action_dct_trial_balance_interactive", "fa-list-alt"),
        ]
        return [
            {"label": label, "xmlid": xmlid, "icon": icon}
            for label, xmlid, icon in definitions
            if self.env.ref(xmlid, raise_if_not_found=False)
        ]


