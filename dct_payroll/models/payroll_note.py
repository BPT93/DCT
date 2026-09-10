from odoo import fields, models


class DctPayrollNote(models.Model):
    _name = "dct.payroll.note"
    _description = "Payroll To-Do Note"
    _order = "sequence, id"

    name = fields.Char(required=True, default="To-Do")
    memo = fields.Text()
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    active = fields.Boolean(default=True)
