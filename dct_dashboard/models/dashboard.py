from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


class DctDashboard(models.AbstractModel):
    _name = "dct.dashboard"
    _description = "DCT Executive Dashboard"

    @api.model
    def get_dashboard_data(self, period="month"):
        """Return an access-aware snapshot for the branded dashboard.

        The module deliberately has no hard dependency on the business apps.
        Every section is enabled only when its model is installed and the
        current user can read it. ORM record rules remain active throughout.
        """
        period = period if period in {"month", "quarter", "year"} else "month"
        today = fields.Date.context_today(self)
        date_from, date_to = self._period_bounds(period, today)
        previous_from, previous_to = self._previous_period(date_from, date_to)

        availability = {
            "accounting": self._can_read("account.move"),
            "sales": self._can_read("sale.order"),
            "purchase": self._can_read("purchase.order"),
            "inventory": self._can_read("stock.picking"),
        }

        revenue = previous_revenue = receivable = 0.0
        revenue_trend = self._empty_month_trend(today)
        recent_documents = []
        if availability["accounting"]:
            revenue = self._invoice_total(date_from, date_to)
            previous_revenue = self._invoice_total(previous_from, previous_to)
            receivable = self._open_receivable()
            revenue_trend = self._revenue_trend(today)
            recent_documents = self._recent_invoices()

        sales_count = previous_sales_count = 0
        sales_pipeline = []
        if availability["sales"]:
            sales_count = self._sale_count(date_from, date_to)
            previous_sales_count = self._sale_count(previous_from, previous_to)
            sales_pipeline = self._sales_pipeline(date_from, date_to)

        pending_purchases = 0
        if availability["purchase"]:
            pending_purchases = self.env["purchase.order"].search_count([
                ("company_id", "=", self.env.company.id),
                ("state", "in", ["draft", "sent", "to approve"]),
            ])

        logistics = {"receipts": 0, "deliveries": 0}
        if availability["inventory"]:
            logistics = self._logistics_snapshot()

        shortcuts = self._available_shortcuts(availability)
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
                    "kind": "currency",
                    "change": self._percentage_change(revenue, previous_revenue),
                    "icon": "fa-line-chart",
                    "accent": "blue",
                    "available": availability["accounting"],
                },
                {
                    "id": "receivable",
                    "label": _("Open Receivables"),
                    "value": receivable,
                    "kind": "currency",
                    "change": None,
                    "icon": "fa-credit-card",
                    "accent": "navy",
                    "available": availability["accounting"],
                },
                {
                    "id": "sales",
                    "label": _("Confirmed Sales"),
                    "value": sales_count,
                    "kind": "number",
                    "change": self._percentage_change(sales_count, previous_sales_count),
                    "icon": "fa-shopping-bag",
                    "accent": "cyan",
                    "available": availability["sales"],
                },
                {
                    "id": "purchases",
                    "label": _("Purchases to Process"),
                    "value": pending_purchases,
                    "kind": "number",
                    "change": None,
                    "icon": "fa-shopping-cart",
                    "accent": "violet",
                    "available": availability["purchase"],
                },
            ],
            "revenue_trend": revenue_trend,
            "sales_pipeline": sales_pipeline,
            "logistics": logistics,
            "recent_documents": recent_documents,
            "shortcuts": shortcuts,
            "availability": availability,
            "updated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def _can_read(self, model_name):
        try:
            model = self.env[model_name]
        except KeyError:
            return False
        return model.has_access("read")

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

    def _invoice_domain(self, date_from, date_to):
        return [
            ("company_id", "=", self.env.company.id),
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<=", date_to),
        ]

    def _invoice_total(self, date_from, date_to):
        moves = self.env["account.move"].search(self._invoice_domain(date_from, date_to))
        return round(sum(
            abs(move.amount_total_signed) * (1 if move.move_type == "out_invoice" else -1)
            for move in moves
        ), 2)

    def _open_receivable(self):
        moves = self.env["account.move"].search([
            ("company_id", "=", self.env.company.id),
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("payment_state", "not in", ["paid", "reversed"]),
        ])
        return round(max(0.0, sum(
            abs(move.amount_residual_signed) * (1 if move.move_type == "out_invoice" else -1)
            for move in moves
        )), 2)

    def _sale_count(self, date_from, date_to):
        date_start = fields.Datetime.to_string(datetime.combine(date_from, time.min))
        date_end = fields.Datetime.to_string(datetime.combine(date_to, time.max))
        return self.env["sale.order"].search_count([
            ("company_id", "=", self.env.company.id),
            ("state", "=", "sale"),
            ("date_order", ">=", date_start),
            ("date_order", "<=", date_end),
        ])

    def _sales_pipeline(self, date_from, date_to):
        date_start = fields.Datetime.to_string(datetime.combine(date_from, time.min))
        date_end = fields.Datetime.to_string(datetime.combine(date_to, time.max))
        base_domain = [
            ("company_id", "=", self.env.company.id),
            ("date_order", ">=", date_start),
            ("date_order", "<=", date_end),
        ]
        SaleOrder = self.env["sale.order"]
        rows = [
            ("quotation", _("Quotations"), ["draft", "sent"], "#1577FF"),
            ("confirmed", _("Confirmed"), ["sale"], "#0A132B"),
            ("cancelled", _("Cancelled"), ["cancel"], "#94A3B8"),
        ]
        return [
            {
                "id": key,
                "label": label,
                "count": SaleOrder.search_count(base_domain + [("state", "in", states)]),
                "color": color,
            }
            for key, label, states, color in rows
        ]

    def _logistics_snapshot(self):
        Picking = self.env["stock.picking"]
        base_domain = [
            ("company_id", "=", self.env.company.id),
            ("state", "not in", ["done", "cancel"]),
        ]
        return {
            "receipts": Picking.search_count(base_domain + [("picking_type_code", "=", "incoming")]),
            "deliveries": Picking.search_count(base_domain + [("picking_type_code", "=", "outgoing")]),
        }

    def _revenue_trend(self, today):
        first_month = today.replace(day=1) - relativedelta(months=5)
        rows = []
        for month_index in range(6):
            start = first_month + relativedelta(months=month_index)
            end = min(start + relativedelta(months=1, days=-1), today)
            value = self._invoice_total(start, end) if start <= today else 0.0
            rows.append({"label": start.strftime("%b"), "value": value})
        return rows

    @staticmethod
    def _empty_month_trend(today):
        first_month = today.replace(day=1) - relativedelta(months=5)
        return [
            {"label": (first_month + relativedelta(months=index)).strftime("%b"), "value": 0.0}
            for index in range(6)
        ]

    def _recent_invoices(self):
        moves = self.env["account.move"].search([
            ("company_id", "=", self.env.company.id),
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("state", "!=", "cancel"),
        ], order="invoice_date desc, id desc", limit=6)
        return [{
            "id": move.id,
            "name": move.name if move.name != "/" else _("Draft invoice"),
            "partner": move.partner_id.display_name or _("No customer"),
            "date": fields.Date.to_string(move.invoice_date) if move.invoice_date else "",
            "amount": abs(move.amount_total_signed),
            "state": move.payment_state or move.state,
        } for move in moves]

    def _available_shortcuts(self, availability):
        definitions = [
            ("accounting", _("Customer Invoices"), "account.action_move_out_invoice", "fa-file-text-o"),
            ("sales", _("Sales Orders"), "sale.action_orders", "fa-shopping-bag"),
            ("purchase", _("Purchase Orders"), "purchase.purchase_form_action", "fa-shopping-cart"),
            ("inventory", _("Inventory Transfers"), "stock.action_picking_tree_all", "fa-truck"),
        ]
        shortcuts = []
        for app, label, xmlid, icon in definitions:
            if availability[app] and self.env.ref(xmlid, raise_if_not_found=False):
                shortcuts.append({"label": label, "xmlid": xmlid, "icon": icon})
        return shortcuts



