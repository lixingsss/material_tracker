import base64
import io
import re
from odoo import models, fields, api, exceptions
from difflib import SequenceMatcher

class ImportPdfWizard(models.TransientModel):
    _name = 'material.tracker.import.pdf.wizard'
    _description = '导入图纸 PDF 向导'

    project_id = fields.Many2one('material.tracker.project', string='归属项目', required=False)
    attachment_ids = fields.Many2many('ir.attachment', string='手动上传新 PDF', help='如果文件较多或较大，建议先通过项目附件功能上传，然后留空此处直接点击匹配')
    
    match_threshold = fields.Float(string='匹配阈值', default=0.6, help='文件名与料号的相似度阈值 (0-1)')

    # 用于图纸预览的临时字段
    pdf_file = fields.Binary(string='图纸预览')
    pdf_page = fields.Integer(string='页码', default=1)

    def action_import(self):
        self.ensure_one()
        # 1. 确定数据源附件
        source_attachments = self.attachment_ids
        if not source_attachments:
            domain = [('name', 'ilike', '%.pdf')]
            if self.project_id:
                domain += [('res_model', '=', 'material.tracker.project'), ('res_id', '=', self.project_id.id)]
            else:
                # 全局模式：查找所有未关联料号的项目附件
                domain += [('res_model', '=', 'material.tracker.project')]
            
            source_attachments = self.env['ir.attachment'].search(domain)

        if not source_attachments:
            raise exceptions.UserError('没有找到可匹配的 PDF 文件')

        # 2. 确定待匹配料号范围
        item_domain = []
        if self.project_id:
            item_domain = [('project_id', '=', self.project_id.id)]
        
        items = self.env['material.tracker.item'].search(item_domain)
        if not items:
            raise exceptions.UserError('当前项目下没有料号，请先导入 Excel 数据')

        # 归一化清理函数
        def ultra_normalize(text):
            if not text: return ""
            return re.sub(r'[^A-Z0-9]', '', text.upper())

        item_clean_map = {item: ultra_normalize(item.sku_code) for item in items if item.sku_code}
        
        try:
            import fitz  # PyMuPDF
        except ImportError:
            try:
                import pymupdf as fitz
            except ImportError:
                raise exceptions.UserError('服务器未安装 PyMuPDF (fitz) 库，请联系管理员安装：pip install pymupdf')

        success_count = 0
        mismatch_files = []

        for attachment in source_attachments:
            if not attachment.name.lower().endswith('.pdf'):
                continue

            try:
                pdf_data = base64.b64decode(attachment.datas)
                doc = fitz.open(stream=pdf_data, filetype="pdf")
                
                for page_index, page in enumerate(doc):
                    page_text_raw = page.get_text()
                    if not page_text_raw.strip():
                        page_text_raw = " ".join([b[4] for b in page.get_text("blocks")])
                    
                    clean_page_text = ultra_normalize(page_text_raw)
                    
                    # 严格匹配：全词包含校验
                    for item, clean_sku in item_clean_map.items():
                        if clean_sku and clean_sku in clean_page_text:
                            index_obj = self.env['material.tracker.drawing.index']
                            # 检查是否已存在（避免在同一个 PDF 的同一页重复创建）
                            existing = index_obj.search([
                                ('sku_code', '=', item.sku_code),
                                ('attachment_id', '=', attachment.id),
                                ('page_num', '=', page_index + 1)
                            ], limit=1)
                            
                            if not existing:
                                index = index_obj.create({
                                    'sku_code': item.sku_code,
                                    'attachment_id': attachment.id,
                                    'page_num': page_index + 1,
                                    'project_id': self.project_id.id if self.project_id else False,
                                })
                                # 关联到 Item 记录
                                if not item.pdf_attachment_id:
                                    item.write({
                                        'pdf_attachment_id': attachment.id,
                                        'pdf_page_num': page_index + 1,
                                        'drawing_index_id': index.id,
                                    })
                                success_count += 1
                doc.close()
            except Exception:
                pass

        if mismatch_files:
            msg = f'成功匹配 {success_count} 个文件。\n以下文件未能自动匹配到料号：\n' + '\n'.join(mismatch_files[:10])
            if len(mismatch_files) > 10:
                msg += f'\n...等共 {len(mismatch_files)} 个文件'
            
            # 返回一个确认框或简单的提示
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '匹配结果',
                    'message': msg,
                    'sticky': True,
                    'type': 'warning',
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
