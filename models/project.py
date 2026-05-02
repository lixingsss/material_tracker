from odoo import models, fields, api


class MaterialTrackerProject(models.Model):
    _name = 'material.tracker.project'
    _description = '项目模型'

    name = fields.Char(string='名称', required=True)
    description = fields.Text(string='描述')
    parent_id = fields.Many2one('material.tracker.project', string='大项目', ondelete='cascade', index=True)
    child_ids = fields.One2many('material.tracker.project', 'parent_id', string='子项目')
    item_ids = fields.One2many('material.tracker.item', 'project_id', string='料号')
    item_ids_main = fields.One2many('material.tracker.item', 'project_id', string='代表件', domain=[('is_series_representative', '=', True)])
    outsourced_item_ids = fields.One2many('material.tracker.outsourced.item', 'project_id', string='外购件')
    child_count = fields.Integer(string='子项目数', compute='_compute_child_count')
    project_url_html = fields.Html(string='子项目名称', compute='_compute_project_url_html')
    show_series_rep_only = fields.Boolean(string='只显示系列代表件', default=True)
    hide_common_prefix = fields.Boolean(string='隐藏相同前缀', default=True)
    common_sku_prefix = fields.Char(string='共同前缀', compute='_compute_common_sku_prefix')

    @api.depends('item_ids.sku_code')
    def _compute_common_sku_prefix(self):
        for project in self:
            skus = project.item_ids.filtered(lambda i: i.sku_code).mapped('sku_code')
            if not skus:
                project.common_sku_prefix = ''
                continue
            s1 = min(skus)
            s2 = max(skus)
            prefix = ''
            for i, c in enumerate(s1):
                if i < len(s2) and c == s2[i]:
                    prefix += c
                else:
                    break
            
            if '-' in prefix:
                last_hyphen = prefix.rfind('-')
                prefix = prefix[:last_hyphen+1]
            else:
                prefix = ''
                
            project.common_sku_prefix = prefix

    def _compute_project_url_html(self):
        for rec in self:
            if rec.id:
                url = f'/web#id={rec.id}&model=material.tracker.project&view_type=form'
                rec.project_url_html = f'<a href="{url}" target="_self" style="font-weight: bold; color: #017e84; text-decoration: none;">{rec.name}</a>'
            else:
                rec.project_url_html = rec.name

    def _compute_child_count(self):
        for project in self:
            project.child_count = len(project.child_ids)

    total_item_count = fields.Integer(string='总料号数', compute='_compute_progress_rate')
    arrived_item_count = fields.Integer(string='已完成数', compute='_compute_progress_rate')
    progress_rate = fields.Float(string='进度(%)', compute='_compute_progress_rate')

    def _compute_progress_rate(self):
        for project in self:
            if project.parent_id:
                # 子项目：基于自己的料号计算
                total = len(project.item_ids)
                arrived = len(project.item_ids.filtered(lambda i: i.is_done))
            else:
                # 大项目：汇总所有子项目的料号
                all_items = project.child_ids.mapped('item_ids')
                total = len(all_items)
                arrived = len(all_items.filtered(lambda i: i.is_done))
            project.total_item_count = total
            project.arrived_item_count = arrived
            project.progress_rate = (arrived / total * 100.0) if total > 0 else 0.0

    def action_view_children(self):
        self.ensure_one()
        return {
            'name': f'【{self.name}】子项目',
            'type': 'ir.actions.act_window',
            'res_model': 'material.tracker.project',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('parent_id', '=', self.id)],
            'context': {'default_parent_id': self.id},
        }

    def action_view_items(self):
        self.ensure_one()
        return {
            'name': f'【{self.name}】料号明细',
            'type': 'ir.actions.act_window',
            'res_model': 'material.tracker.item',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_open_project(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'material.tracker.project',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_go_back(self):
        """返回上一级（大项目表单）"""
        self.ensure_one()
        if self.parent_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'material.tracker.project',
                'res_id': self.parent_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return self.action_go_home()

    def action_go_home(self):
        """返回主页（项目列表）"""
        return {
            'type': 'ir.actions.act_window',
            'name': '项目列表',
            'res_model': 'material.tracker.project',
            'view_mode': 'kanban,list,form',
            'domain': [('parent_id', '=', False)],
            'target': 'current',
        }
