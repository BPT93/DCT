import io

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import osutil


class DctAccountReportExport(http.Controller):

    @http.route(
        "/dct_accounting/report/<int:wizard_id>/xlsx",
        type="http",
        auth="user",
    )
    def export_xlsx(self, wizard_id, **kwargs):
        import xlsxwriter  # noqa: PLC0415

        wizard = request.env["dct.account.report.wizard"].browse(wizard_id).exists()
        if not wizard:
            raise NotFound()
        wizard.check_access("read")
        if not wizard.line_ids:
            wizard._generate_lines()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        report_label = dict(wizard._fields["report_type"]._description_selection(request.env))[
            wizard.report_type
        ]
        worksheet = workbook.add_worksheet(report_label[:31])
        title_format = workbook.add_format({
            "bold": True,
            "font_size": 18,
            "font_color": "#FFFFFF",
            "bg_color": "#0A132B",
            "align": "left",
            "valign": "vcenter",
        })
        meta_format = workbook.add_format({"font_color": "#5F6072", "italic": True})
        header_format = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#1577FF",
            "border": 0,
        })
        section_format = workbook.add_format({
            "bold": True,
            "font_color": "#0A132B",
            "bg_color": "#EAF2FF",
        })
        total_format = workbook.add_format({
            "bold": True,
            "top": 1,
            "top_color": "#8AAFE0",
            "num_format": "#,##0.00;[Red]-#,##0.00",
        })
        money_format = workbook.add_format({"num_format": "#,##0.00;[Red]-#,##0.00"})

        is_statement = wizard.report_type in (
            "profit_loss",
            "balance_sheet",
            "executive_summary",
        )
        is_aged = wizard.report_type in ("aged_receivable", "aged_payable")
        headers = ([] if is_aged else ["Code"]) + [
            "Partner" if is_aged else "Account / Partner / Journal"
        ]
        if is_aged:
            headers.extend(["Not Due", "1–30", "31–60", "61–90", "90+", "Total"])
        elif is_statement:
            headers.append("Balance")
        else:
            headers.extend(["Opening", "Debit", "Credit", "Ending"])
        if wizard.comparison != "none":
            headers.extend([wizard.comparison_label, "Variance"])

        last_column = len(headers) - 1
        worksheet.merge_range(0, 0, 1, last_column, f"DCT | {report_label}", title_format)
        worksheet.write("A3", wizard.company_id.display_name, meta_format)
        worksheet.write(
            "A4",
            f"{wizard.date_from.isoformat()} — {wizard.date_to.isoformat()} | "
            f"{dict(wizard._fields['target_move']._description_selection(request.env))[wizard.target_move]}",
            meta_format,
        )
        for column, label in enumerate(headers):
            worksheet.write(5, column, label, header_format)

        for row_index, line in enumerate(wizard.line_ids, start=6):
            if line.line_type == "section":
                worksheet.merge_range(
                    row_index,
                    0,
                    row_index,
                    last_column,
                    line.name,
                    section_format,
                )
                continue
            name_format = total_format if line.is_total else None
            number_format = total_format if line.is_total else money_format
            name_column = 0 if is_aged else 1
            if not is_aged:
                worksheet.write(row_index, 0, line.code or "", name_format)
            worksheet.write(row_index, name_column, line.name, name_format)
            values = [
                line.bucket_current,
                line.bucket_1_30,
                line.bucket_31_60,
                line.bucket_61_90,
                line.bucket_older,
                line.ending_balance,
            ] if is_aged else [line.balance] if is_statement else [
                line.opening_balance,
                line.period_debit,
                line.period_credit,
                line.ending_balance,
            ]
            if wizard.comparison != "none":
                values.extend([line.comparison_balance, line.variance])
            for column, value in enumerate(values, start=name_column + 1):
                worksheet.write_number(row_index, column, value, number_format)

        worksheet.freeze_panes(6, 1 if is_aged else 2)
        if is_aged:
            worksheet.set_column("A:A", 42)
            worksheet.set_column(1, last_column, 18)
        else:
            worksheet.set_column("A:A", 16)
            worksheet.set_column("B:B", 42)
            worksheet.set_column(2, last_column, 18)
        worksheet.autofilter(
            5,
            0,
            max(5, 5 + len(wizard.line_ids)),
            last_column,
        )
        workbook.close()

        filename = osutil.clean_filename(f"DCT {report_label} {wizard.date_to}.xlsx")
        return request.make_response(
            output.getvalue(),
            headers=[
                (
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )


