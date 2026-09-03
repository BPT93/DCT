from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        home_action = self.env.ref("dct_dashboard.action_dct_home", raise_if_not_found=False)
        if home_action:
            internal_users = users.sudo().filtered(lambda user: not user.share and not user.action_id)
            internal_users.write({"action_id": home_action.id})
        return users



