/** @odoo-module **/
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("dct_security_dashboard_smoke", {
    steps: () => [
        {
            content: "The connected overview has loaded its current operational cards",
            trigger: ".o_dct_security .dct_cards .dct_card",
            run() {
                if (document.querySelector(".o_dct_security [role='alert']")) {
                    throw new Error("Operations dashboard reported an error");
                }
                if (!document.querySelector(".o_dct_security .dct_filters input[type='date']")) {
                    throw new Error("Reporting date filters are missing");
                }
            },
        },
        {
            content: "Open the guard KPI source records",
            trigger: ".o_dct_security .dct_cards .dct_card:first-child",
            run: "click",
        },
        {
            content: "The KPI opens a native Odoo list view",
            trigger: ".o_list_view",
        },
    ],
});
