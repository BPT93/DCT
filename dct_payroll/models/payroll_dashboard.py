from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class DctPayrollDashboard(models.AbstractModel):
    _name = "dct.payroll.dashboard"
    _description = "DCT Payroll Dashboard"

    @api.model
    def get_dashboard_data(self, period="month"):
        if not self.env.user.has_group("payroll.group_payroll_user"):
            raise AccessError(
                _("You need payroll access to open the payroll dashboard.")
            )

        period = period if period in {"month", "quarter", "year"} else "month"
        today = fields.Date.context_today(self)
        date_from, date_to = self._period_bounds(period, today)
        previous_from, previous_to = self._previous_period(date_from, date_to)

        payslips = self._payslips(date_from, date_to)
        previous_payslips = self._payslips(previous_from, previous_to)
        done_payslips = payslips.filtered(lambda slip: slip.state == "done")
        previous_done = previous_payslips.filtered(
            lambda slip: slip.state == "done"
        )

        gross_pay = round(sum(done_payslips.mapped("gross_pay")), 2)
        net_pay = round(sum(done_payslips.mapped("net_pay")), 2)
        previous_gross = round(sum(previous_done.mapped("gross_pay")), 2)
        previous_net = round(sum(previous_done.mapped("net_pay")), 2)
        employee_count = len(done_payslips.employee_id)
        previous_employee_count = len(previous_done.employee_id)

        state_counts = {"draft": 0, "verify": 0, "done": 0, "cancel": 0}
        for payslip in payslips:
            state_counts[payslip.state] = state_counts.get(payslip.state, 0) + 1

        company = self.env.company
        return {
            "company": {
                "id": company.id,
                "name": company.name,
                "logo_url": "/payroll/static/description/icon.png",
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
                    "id": "gross_pay",
                    "label": _("Gross Payroll"),
                    "value": gross_pay,
                    "change": self._percentage_change(gross_pay, previous_gross),
                    "kind": "currency",
                    "icon": "fa-money",
                    "accent": "blue",
                },
                {
                    "id": "net_pay",
                    "label": _("Net Payroll"),
                    "value": net_pay,
                    "change": self._percentage_change(net_pay, previous_net),
                    "kind": "currency",
                    "icon": "fa-credit-card",
                    "accent": "cyan",
                },
                {
                    "id": "employees",
                    "label": _("Employees Paid"),
                    "value": employee_count,
                    "change": self._percentage_change(
                        employee_count, previous_employee_count
                    ),
                    "kind": "number",
                    "icon": "fa-users",
                    "accent": "violet",
                },
                {
                    "id": "payslips",
                    "label": _("Payslips"),
                    "value": len(payslips),
                    "change": self._percentage_change(
                        len(payslips), len(previous_payslips)
                    ),
                    "kind": "number",
                    "icon": "fa-file-text-o",
                    "accent": "coral",
                },
            ],
            "states": [
                {
                    "id": "draft",
                    "label": _("Draft"),
                    "value": state_counts["draft"],
                },
                {
                    "id": "verify",
                    "label": _("Waiting"),
                    "value": state_counts["verify"],
                },
                {
                    "id": "done",
                    "label": _("Done"),
                    "value": state_counts["done"],
                },
                {
                    "id": "cancel",
                    "label": _("Rejected"),
                    "value": state_counts["cancel"],
                },
            ],
            "accounted_count": len(done_payslips.filtered("move_id")),
            "cost_trend": self._cost_trend(today),
            "department_costs": self._department_costs(done_payslips),
            "recent_payslips": self._recent_payslips(payslips),
            "warnings": self._warnings(today),
            "batches": self._batches(today),
            "statistics": self._statistics(today),
            "notes": self._notes(),
            "is_manager": self.env.user.has_group(
                "payroll.group_payroll_manager"
            ),
            "readiness": self._readiness(),
            "shortcuts": self._shortcuts(),
            "updated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def _payslips(self, date_from, date_to):
        return self.env["hr.payslip"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("date_from", "<=", date_to),
                ("date_to", ">=", date_from),
            ],
            order="date_to desc, id desc",
        )

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
            return _(
                "Q%(quarter)s %(year)s",
                quarter=((date_from.month - 1) // 3) + 1,
                year=date_from.year,
            )
        return date_from.strftime("%B %Y")

    def _cost_trend(self, today):
        first_month = today.replace(day=1) - relativedelta(months=5)
        rows = []
        for index in range(6):
            date_from = first_month + relativedelta(months=index)
            date_to = min(date_from + relativedelta(months=1, days=-1), today)
            payslips = self._payslips(date_from, date_to).filtered(
                lambda slip: slip.state == "done"
            )
            rows.append(
                {
                    "label": date_from.strftime("%b"),
                    "gross": round(sum(payslips.mapped("gross_pay")), 2),
                    "net": round(sum(payslips.mapped("net_pay")), 2),
                }
            )
        return rows

    @staticmethod
    def _department_costs(payslips):
        totals = {}
        for payslip in payslips:
            department = payslip.department_id
            key = department.id or 0
            row = totals.setdefault(
                key,
                {
                    "id": key,
                    "label": department.display_name or _("No Department"),
                    "value": 0.0,
                    "employees": set(),
                },
            )
            row["value"] += payslip.net_pay
            row["employees"].add(payslip.employee_id.id)

        rows = sorted(totals.values(), key=lambda row: row["value"], reverse=True)
        for row in rows:
            row["value"] = round(row["value"], 2)
            row["employees"] = len(row["employees"])
        return rows[:6]

    @staticmethod
    def _recent_payslips(payslips):
        return [
            {
                "id": payslip.id,
                "number": payslip.number or payslip.name or _("Draft Payslip"),
                "employee": payslip.employee_id.display_name,
                "department": payslip.department_id.display_name
                or _("No Department"),
                "date_to": fields.Date.to_string(payslip.date_to),
                "state": payslip.state,
                "net": payslip.net_pay,
                "accounted": bool(payslip.move_id),
            }
            for payslip in payslips[:8]
        ]

    def _warnings(self, today):
        employees = self.env["hr.employee"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("active", "=", True),
                ("employee_type", "=", "employee"),
            ]
        )
        employees_sudo = employees.sudo()
        without_contract = employees_sudo.filtered(
            lambda employee: not employee.is_in_contract
        )
        missing_structure = employees_sudo.filtered(
            lambda employee: employee.is_in_contract
            and employee.current_version_id
            and not employee.current_version_id.struct_id
        )
        missing_bank = employees_sudo.filtered(
            lambda employee: employee.is_in_contract
            and not employee.primary_bank_account_id
        )

        payslip_domain = [("company_id", "=", self.env.company.id)]
        waiting = self.env["hr.payslip"].search(
            payslip_domain + [("state", "=", "verify")]
        )
        to_pay = self.env["hr.payslip"].search(
            payslip_domain
            + [("state", "=", "done"), ("paid", "=", False)]
        )
        negative = self.env["hr.payslip"].search(
            payslip_domain
            + [("state", "!=", "cancel"), ("net_pay", "<", 0)]
        )

        month_start = today.replace(day=1)
        conflicts = self.env["hr.work.entry"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "=", "conflict"),
                ("date", ">=", month_start),
                ("date", "<", month_start + relativedelta(months=1)),
            ]
        )

        definitions = [
            (
                _("Employees Without Running Contracts"),
                "hr.employee",
                without_contract,
                "fa-user-times",
                "warning",
            ),
            (
                _("Employees Without a Salary Structure"),
                "hr.employee",
                missing_structure,
                "fa-sitemap",
                "warning",
            ),
            (
                _("Employees Without a Bank Account"),
                "hr.employee",
                missing_bank,
                "fa-university",
                "warning",
            ),
            (
                _("Work Entry Conflicts"),
                "hr.work.entry",
                conflicts,
                "fa-exclamation-triangle",
                "danger",
            ),
            (
                _("Payslips Waiting for Validation"),
                "hr.payslip",
                waiting,
                "fa-clock-o",
                "info",
            ),
            (
                _("Validated Payslips To Pay"),
                "hr.payslip",
                to_pay,
                "fa-credit-card",
                "info",
            ),
            (
                _("Payslips With Negative Net Amounts"),
                "hr.payslip",
                negative,
                "fa-minus-circle",
                "danger",
            ),
        ]
        return [
            {
                "id": f"{model_name}-{index}",
                "label": label,
                "count": len(records),
                "icon": icon,
                "tone": tone,
                "action": self._record_action(label, model_name, records.ids),
            }
            for index, (label, model_name, records, icon, tone) in enumerate(
                definitions
            )
            if records
        ]

    def _batches(self, today):
        batches = self.env["hr.payslip.run"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("date_start", ">=", today - relativedelta(years=1)),
            ],
            order="date_start desc, id desc",
            limit=8,
        )
        state_labels = dict(
            self.env["hr.payslip.run"]
            ._fields["state"]
            ._description_selection(self.env)
        )
        return [
            {
                "id": batch.id,
                "name": batch.name,
                "date": batch.date_start.strftime("%m/%Y"),
                "state": batch.state,
                "state_label": state_labels.get(batch.state, batch.state),
                "payslip_count": len(batch.slip_ids),
            }
            for batch in batches
        ]

    def _statistics(self, today):
        monthly_periods = []
        for offset in range(-2, 1):
            date_from = today.replace(day=1) + relativedelta(months=offset)
            monthly_periods.append(
                (
                    date_from,
                    date_from + relativedelta(months=1, days=-1),
                    date_from.strftime("%b %Y"),
                )
            )

        yearly_periods = []
        for offset in range(-2, 1):
            year = today.year + offset
            yearly_periods.append(
                (
                    today.replace(year=year, month=1, day=1),
                    today.replace(year=year, month=12, day=31),
                    str(year),
                )
            )

        return {
            "employer_cost": {
                "title": _("Employer Cost"),
                "help": _(
                    "Gross and net amounts from completed employee payslips."
                ),
                "monthly": self._payroll_cost_periods(monthly_periods),
                "yearly": self._payroll_cost_periods(yearly_periods),
            },
            "employee_trends": {
                "title": _("Employee Trends"),
                "help": _(
                    "Employees whose contract overlaps each displayed period."
                ),
                "monthly": self._employee_periods(monthly_periods),
                "yearly": self._employee_periods(yearly_periods),
            },
        }

    def _payroll_cost_periods(self, periods):
        rows = []
        for date_from, date_to, label in periods:
            payslips = self._payslips(date_from, date_to).filtered(
                lambda slip: slip.state == "done"
            )
            rows.append(
                {
                    "label": label,
                    "gross": round(sum(payslips.mapped("gross_pay")), 2),
                    "net": round(sum(payslips.mapped("net_pay")), 2),
                }
            )
        return rows

    def _employee_periods(self, periods):
        rows = []
        for date_from, date_to, label in periods:
            count = self.env["hr.employee"].search_count(
                [
                    ("company_id", "=", self.env.company.id),
                    ("active", "=", True),
                    ("date_start", "<=", date_to),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", date_from),
                ]
            )
            rows.append({"label": label, "value": count})
        return rows

    def _notes(self):
        return self.env["dct.payroll.note"].search_read(
            [("company_id", "=", self.env.company.id)],
            ["name", "memo", "sequence"],
            order="sequence, id",
        )

    @staticmethod
    def _record_action(title, model_name, record_ids):
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": model_name,
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", record_ids)],
            "target": "current",
        }

    def _readiness(self):
        if not self.env.user.has_group("payroll.group_payroll_manager"):
            return []
        company_domain = [("company_id", "in", [False, self.env.company.id])]
        structure_count = self.env["hr.payroll.structure"].search_count(
            company_domain
        )
        rule_count = self.env["hr.salary.rule"].search_count(company_domain)
        reporting_rule_count = self.env["hr.salary.rule"].search_count(
            company_domain + [("code", "in", ["GROSS", "NET"])]
        )
        mapping_count = self.env["hr.salary.rule"].search_count(
            company_domain
            + ["|", ("account_debit", "!=", False), ("account_credit", "!=", False)]
        )
        journal_count = self.env["account.journal"].search_count(
            [("company_id", "=", self.env.company.id), ("type", "=", "general")]
        )
        return [
            {
                "id": "structures",
                "label": _("Salary structures"),
                "ready": bool(structure_count),
                "detail": _("%(count)s configured", count=structure_count),
                "xmlid": "payroll.hr_payroll_structure_action",
            },
            {
                "id": "rules",
                "label": _("Salary rules"),
                "ready": bool(rule_count),
                "detail": _("%(count)s configured", count=rule_count),
                "xmlid": "payroll.action_salary_rule_form",
            },
            {
                "id": "reporting_rules",
                "label": _("Gross/net reporting rules"),
                "ready": reporting_rule_count == 2,
                "detail": _(
                    "%(count)s of 2 codes configured", count=reporting_rule_count
                ),
                "xmlid": "payroll.action_salary_rule_form",
            },
            {
                "id": "accounts",
                "label": _("Accounting mappings"),
                "ready": bool(mapping_count),
                "detail": _("%(count)s rules mapped", count=mapping_count),
                "xmlid": "payroll.action_salary_rule_form",
            },
            {
                "id": "journals",
                "label": _("Salary journal"),
                "ready": bool(journal_count),
                "detail": _(
                    "%(count)s general journals available", count=journal_count
                ),
                "xmlid": "payroll.payroll_configuration_action",
            },
        ]

    def _shortcuts(self):
        definitions = [
            (
                _("Employee Payslips"),
                "payroll.hr_payslip_action",
                "fa-file-text-o",
                None,
            ),
            (
                _("Payslip Batches"),
                "payroll.hr_payslip_run_action",
                "fa-files-o",
                "payroll.group_payroll_manager",
            ),
            (_("Employees"), "hr.open_view_employee_list_my", "fa-users", None),
            (
                _("Salary Analysis"),
                "dct_payroll.action_dct_payroll_analysis",
                "fa-bar-chart",
                None,
            ),
            (
                _("Salary Structures"),
                "payroll.hr_payroll_structure_action",
                "fa-sitemap",
                "payroll.group_payroll_manager",
            ),
            (
                _("Salary Rules"),
                "payroll.action_salary_rule_form",
                "fa-sliders",
                "payroll.group_payroll_manager",
            ),
            (
                _("Contribution Registers"),
                "payroll.hr_contribution_register_action",
                "fa-building-o",
                "payroll.group_payroll_manager",
            ),
        ]
        return [
            {"label": label, "xmlid": xmlid, "icon": icon}
            for label, xmlid, icon, group in definitions
            if (not group or self.env.user.has_group(group))
            and self.env.ref(xmlid, raise_if_not_found=False)
        ]
