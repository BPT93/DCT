{
    "name": "DCT Payroll",
    "summary": "Complete payroll workspace for Odoo Community",
    "version": "19.0.3.1.0",
    "category": "Human Resources/Payroll",
    "author": "Digital Creativity Technologies",
    "license": "AGPL-3",
    "depends": [
        "payroll_account",
        "hr_work_entry",
        "web_responsive",
        "web_dark_mode",
        "web_dialog_size",
    ],
    "data": [
        "security/payroll_security.xml",
        "security/ir.model.access.csv",
        "data/payroll_note_data.xml",
        "views/payroll_configuration_views.xml",
        "views/payroll_payslip_views.xml",
        "views/payroll_report_views.xml",
        "views/payroll_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dct_payroll/static/src/theme/theme.js",
            "dct_payroll/static/src/payroll_dashboard/payroll_dashboard.js",
            "dct_payroll/static/src/payroll_dashboard/payroll_dashboard.xml",
            "dct_payroll/static/src/payroll_dashboard/payroll_dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}
