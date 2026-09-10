import csv
import io

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import osutil


class DctPayrollPaymentReport(http.Controller):

    @staticmethod
    def _employee_bank_account(employee):
        account = getattr(employee, "bank_account_id", False)
        return getattr(account, "acc_number", "") if account else ""

    @staticmethod
    def _render_csv(payslips):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            [
                "Reference",
                "Employee",
                "Bank Account",
                "Period Start",
                "Period End",
                "Payment Date",
                "Net Wage",
                "Currency",
            ]
        )
        for payslip in payslips:
            writer.writerow(
                [
                    payslip.number or payslip.name or "",
                    payslip.employee_id.display_name,
                    DctPayrollPaymentReport._employee_bank_account(
                        payslip.employee_id
                    ),
                    payslip.date_from,
                    payslip.date_to,
                    payslip.close_date or payslip.date or payslip.date_to,
                    payslip.net_pay,
                    payslip.currency_id.name,
                ]
            )
        return stream.getvalue().encode("utf-8-sig")

    @http.route(
        "/dct_payroll/payment-report/payslip/<int:payslip_id>",
        type="http",
        auth="user",
    )
    def payslip_payment_report(self, payslip_id, **kwargs):
        payslip = request.env["hr.payslip"].browse(payslip_id).exists()
        if not payslip:
            raise NotFound()
        payslip.check_access("read")
        filename = osutil.clean_filename(
            f"Payment Report - {payslip.number or payslip.name or payslip.id}.csv"
        )
        return request.make_response(
            self._render_csv(payslip),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    @http.route(
        "/dct_payroll/payment-report/pay-run/<int:pay_run_id>",
        type="http",
        auth="user",
    )
    def pay_run_payment_report(self, pay_run_id, **kwargs):
        pay_run = request.env["hr.payslip.run"].browse(pay_run_id).exists()
        if not pay_run:
            raise NotFound()
        pay_run.check_access("read")
        pay_run.slip_ids.check_access("read")
        filename = osutil.clean_filename(f"Payment Report - {pay_run.name}.csv")
        return request.make_response(
            self._render_csv(pay_run.slip_ids),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
