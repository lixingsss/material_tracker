# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions
import logging
import base64
import re
from collections import defaultdict

_logger = logging.getLogger(__name__)

class MaterialTrackerItem(models.Model):
    _name = 'material.tracker.item'
    _description = '料号模型'

    project_id = fields.Many2one('material.tracker.project', string='归属项目', required=True, ondelete='cascade')
    sku_code = fields.Char(string='料号', required=True)
    qty = fields.Integer(string='数量', default=1)
    is_done = fields.Boolean(string='状态', default=False)
    due_date = fields.Date(string='完成日期')
    process_requirement = fields.Char(string='工艺要求')
    material = fields.Char(string='材料')
    remark = fields.Char(string='备注')
    order_person = fields.Char(string='下单人员')
    image = fields.Image(string='图片', max_width=1024, max_height=1024)
    state_modified_by = fields.Many2one('res.users', string='修改人', readonly=True)
    state_modified_date = fields.Datetime(string='修改时间', readonly=True)
    
    # 保持旧字段以避免破坏旧视图或历史数据
    pdf_attachment_id = fields.Many2one('ir.attachment', string='图纸 PDF', ondelete='set null')
    pdf_page_num = fields.Integer(string='图纸页码', default=1)
    
    sku_code_link = fields.Html(string='料号', compute='_compute_sku_code_link', sanitize=False)

    @api.depends('sku_code')
    def _compute_sku_code_link(self):
        for rec in self:
            rec.sku_code_link = f'<span>{rec.sku_code}</span>'

    def action_view_pdf(self):
        """对接图纸管理系统：自动检索、切片并以全屏沉浸模式展示图纸"""
        self.ensure_one()
        
        if not self.sku_code:
            raise exceptions.UserError('该料号缺少料号代码(SKU)，无法检索图纸。')

        # 1. 在图纸索引库中全局搜索该料号
        hit_index = self.env['material_tracker.drawing.index'].search([
            ('page_text', 'ilike', self.sku_code)
        ], limit=1)

        if not hit_index:
            raise exceptions.UserError(f'未在任何图纸中检索到料号: {self.sku_code}。\n请前往“图纸管理”确认图纸已上传并成功建立索引。')

        # 2. 获取对应的图纸主记录
        drawing = hit_index.drawing_id

        # 3. 将料号作为搜索词写入图纸记录，并触发切片功能（高亮显示搜索词）
        drawing.write({'search_keyword': self.sku_code})
        drawing.action_search_and_slice()

        # 4. 获取专门定义的沉浸式预览视图 ID (该视图在 XML 中不包含 <sheet> 标签)
        try:
            view_id = self.env.ref('material_tracker.view_material_tracker_drawing_immersive').id
        except Exception:
            view_id = False

        # 5. 弹窗打开图纸，应用全屏标志位
        return {
            'name': f'图纸预览 - {self.sku_code}',
            'type': 'ir.actions.act_window',
            'res_model': 'material_tracker.drawing',
            'res_id': drawing.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'new', # 弹窗模式
            'context': {
                'dialog_size': 'extra-large', 
            },
            'flags': {
                'mode': 'readonly',
                'action_buttons': False, # 彻底隐藏顶部的“保存/编辑/丢弃”按钮
                'headless': True,        # 告知系统尽可能隐藏弹窗标题栏
            },
        }

    # --- 以下为系列代表件相关逻辑 ---

    is_series_representative = fields.Boolean(
        string='系列代表件',
        compute='_compute_is_series_representative',
        store=True,
    )
    display_sku_code = fields.Char(string='显示料号', compute='_compute_display_sku_code')

    @api.depends('project_id.item_ids.sku_code')
    def _compute_is_series_representative(self):
        processed = self.env['material.tracker.item']
        projects = self.mapped('project_id')

        for project in projects:
            items = project.item_ids
            series_groups = defaultdict(list)

            for item in items:
                if not item.sku_code:
                    series_groups[f'__none__{item.id}'].append((0, item))
                    continue

                sku = item.sku_code.strip()
                h_match = re.search(r'([-_]H)$', sku, re.IGNORECASE)
                if not h_match:
                    series_groups[f'__noh__{item.id}'].append((0, item))
                    continue

                sku_no_h = sku[:h_match.start()]
                h_suffix = h_match.group(0)
                num_match = re.search(r'([-_])(\d+)$', sku_no_h)
                if num_match:
                    series_key = sku_no_h[:num_match.end(1)] + h_suffix
                    num = int(num_match.group(2))
                else:
                    series_key = f'{sku}__standalone'
                    num = 0
                series_groups[series_key].append((num, item))

            representative_ids = set()
            for group_items in series_groups.values():
                group_items.sort(key=lambda x: x[0])
                representative_ids.add(group_items[0][1].id)

            for item in items:
                item.is_series_representative = item.id in representative_ids
            processed |= items

        for item in self - processed:
            item.is_series_representative = True

    @api.depends('sku_code', 'project_id.hide_common_prefix', 'project_id.common_sku_prefix')
    def _compute_display_sku_code(self):
        for item in self:
            if (item.project_id and item.project_id.hide_common_prefix
                    and item.project_id.common_sku_prefix):
                prefix = item.project_id.common_sku_prefix
                if item.sku_code and item.sku_code.startswith(prefix):
                    item.display_sku_code = item.sku_code[len(prefix):]
                else:
                    item.display_sku_code = item.sku_code
            else:
                item.display_sku_code = item.sku_code

    def write(self, vals):
        if 'is_done' in vals:
            vals['state_modified_by'] = self.env.uid
            vals['state_modified_date'] = fields.Datetime.now()
        return super(MaterialTrackerItem, self).write(vals)