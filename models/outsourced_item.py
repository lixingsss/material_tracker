from odoo import models, fields


class MaterialTrackerOutsourcedItem(models.Model):
    _name = 'material.tracker.outsourced.item'
    _description = '外购件模型'

    project_id = fields.Many2one('material.tracker.project', string='归属项目', required=True, ondelete='cascade')
    name = fields.Char(string='名称', required=True)
    qty = fields.Integer(string='数量', default=1)
