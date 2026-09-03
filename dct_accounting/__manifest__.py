{
    "name": "DCT Accounting",
    "summary": "Branded accounting workspace for Odoo Community",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "author": "Digital Creativity Technologies",
    "license": "LGPL-3",
    "depends": ["account", "web"],
    "data": [
        "security/account_security.xml",
        "security/ir.model.access.csv",
        "views/account_report_views.xml",
        "report/financial_report_templates.xml",
        "views/accounting_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dct_accounting/static/src/accounting_dashboard/accounting_dashboard.js",
            "dct_accounting/static/src/accounting_dashboard/accounting_dashboard.xml",
            "dct_accounting/static/src/accounting_dashboard/accounting_dashboard.scss",
            "dct_accounting/static/src/report/**/*",
        ],
    },
    "application": True,
    "installable": True,
}



