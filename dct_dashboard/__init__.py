from . import models


def post_init_hook(env):
    """Use the DCT launcher for internal users without a chosen home action."""
    home_action = env.ref("dct_dashboard.action_dct_home")
    internal_users = env["res.users"].with_context(active_test=False).search([
        ("share", "=", False),
        ("action_id", "=", False),
    ])
    internal_users.write({"action_id": home_action.id})



