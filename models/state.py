from odoo import models, fields

class MaterialTrackerState(models.Model):
    _name = 'material.tracker.state'
    _description = '料号状态'
    _order = 'sequence, id'

    name = fields.Char(string='状态名称', required=True)
    sequence = fields.Integer(string='序号', default=10)
