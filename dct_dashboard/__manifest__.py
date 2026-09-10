{
    "name": "DCT Dashboard",
    "summary": "Branded executive dashboard for Odoo Community",
    "version": "19.0.2.3.6",
    "category": "Productivity/Dashboard",
    "author": "Digital Creativity Technologies",
    "license": "AGPL-3",
    "depends": [
        "web",
        "web_responsive",
        "web_dark_mode",
        "web_dialog_size",
    ],
    "data": [
        "views/home_action.xml",
        "views/login_templates.xml",
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            ("prepend", "dct_dashboard/static/src/scss/variables.scss"),
        ],
        "web.assets_backend": [
            "dct_dashboard/static/src/scss/theme.scss",
            "dct_dashboard/static/src/theme/theme.js",
            "dct_dashboard/static/src/home/**/*",
            "dct_dashboard/static/src/dashboard/dashboard.js",
            "dct_dashboard/static/src/dashboard/dashboard.xml",
            "dct_dashboard/static/src/dashboard/dashboard.scss",
        ],
        "web.assets_frontend": [
            "dct_dashboard/static/src/scss/login.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}



