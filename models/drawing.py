from odoo import models, fields, api, exceptions
import base64
import logging
import os
import tempfile
import gc
import re
import traceback

_logger = logging.getLogger(__name__)

try:
    import pymupdf
except ImportError:
    _logger.warning("PyMuPDF (pymupdf) 未安装。PDF 索引和切片功能将无法工作。")
    pymupdf = None

class MaterialTrackerDrawing(models.Model):
    _name = 'material_tracker.drawing'
    _description = '图纸集管理'

    name = fields.Char(string='图纸集名称/编号', required=True)
    pdf_file = fields.Binary(string='原始总 PDF 文件', required=True)
    
    index_status = fields.Selection([
        ('未建立', '未建立'),
        ('排队中', '排队中'),
        ('处理中', '处理中'),
        ('已建立', '已建立'),
        ('失败', '失败')
    ], string='索引状态', default='未建立', readonly=True)
    
    index_ids = fields.One2many('material_tracker.drawing.index', 'drawing_id', string='关联的页面文本索引')
    
    search_keyword = fields.Char(string='临时搜索词')
    cache_result_file = fields.Binary(string='缓存的单页预览文件', readonly=True)
    cache_page_num = fields.Integer(string='当前缓存页码', readonly=True)
    index_log = fields.Text(string='建立索引日志', readonly=True)

    def write(self, vals):
        """当更新文件时，重置状态"""
        res = super(MaterialTrackerDrawing, self).write(vals)
        if 'pdf_file' in vals or 'name' in vals:
            for rec in self:
                rec.write({
                    'index_status': '未建立',
                    'cache_result_file': False,
                    'cache_page_num': 0,
                    'index_log': '',
                })
                rec.index_ids.unlink()
        return res

    def action_queue_build_index(self):
        """前端按钮：将选中的文件加入队列，并自动唤醒后台任务"""
        if not pymupdf:
            raise exceptions.UserError("服务器未安装 PyMuPDF (pymupdf) 库")
            
        for rec in self:
            if not rec.pdf_file:
                raise exceptions.UserError(f"图纸 {rec.name} 缺少 PDF 文件")
            
            # 清理旧数据并修改状态为排队中
            rec.index_ids.unlink()
            rec.write({
                'index_status': '排队中',
                'index_log': '已加入后台处理队列，等待执行...',
                'cache_result_file': False,
                'cache_page_num': 0
            })
        
        # 自动唤醒后台计划任务
        try:
            cron_job = self.env.ref('material_tracker.ir_cron_auto_build_pdf_index', raise_if_not_found=False)
            if cron_job:
                cron_job.sudo().write({
                    'active': True,
                    'nextcall': fields.Datetime.now()
                })
        except Exception as e:
            _logger.error(f"唤醒计划任务失败: {e}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已加入后台队列',
                'message': f'已将 {len(self)} 个文件加入队列。后台正在安全处理中，请稍后刷新页面查看结果。',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def _cron_process_index_queue(self):
        """后台任务：每次处理一小批，处理完自动沉睡（含深度诊断）"""
        records = self.search([('index_status', '=', '排队中')], limit=5)
        if not records:
            cron_job = self.env.ref('material_tracker.ir_cron_auto_build_pdf_index', raise_if_not_found=False)
            if cron_job:
                cron_job.sudo().write({'active': False})
            return

        sku_pattern = re.compile(r'[A-Z]{2,6}\d*(?:-[A-Z0-9]+)+')

        for rec in records:
            rec.write({'index_status': '处理中', 'index_log': '正在解析 PDF...'})
            self.env.cr.commit() 

            fd, temp_path = tempfile.mkstemp(suffix='.pdf')
            doc = None
            log_lines = []
            
            try:
                # 1. 解码并诊断 Base64
                raw_b64 = rec.pdf_file
                # 剔除可能存在的前缀 (Odoo 有时会带 data:application/pdf;base64,)
                if isinstance(raw_b64, bytes):
                    raw_b64 = raw_b64.decode('utf-8')
                if raw_b64.startswith('data:'):
                    raw_b64 = raw_b64.split('base64,')[1]
                    
                pdf_bytes = base64.b64decode(raw_b64)
                
                # 记录文件大小，对比一下和您在命令行测试的文件大小是否一致
                file_size_kb = len(pdf_bytes) / 1024
                log_lines.append(f"🔍 [诊断1] PDF 文件大小: {file_size_kb:.2f} KB")

                with os.fdopen(fd, 'wb') as f:
                    f.write(pdf_bytes)
                
                # 2. 打开 PDF
                doc = pymupdf.open(temp_path)
                log_lines.append(f"🔍 [诊断2] PDF 加载成功，总页数: {len(doc)}")
                
                # 3. 深度诊断第一页
                if len(doc) > 0:
                    page0 = doc[0]
                    text0 = page0.get_text("text")
                    log_lines.append(f"🔍 [诊断3] 第1页提取到的纯文本长度: {len(text0)} 字符")
                    if len(text0) > 0:
                        # 打印前100个字符看看长什么样
                        clean_preview = text0[:100].replace('\n', ' ')
                        log_lines.append(f"🔍 [诊断4] 第1页文本预览: {clean_preview}")
                        
                        # 诊断正则是否能抓到
                        test_matches = sku_pattern.findall(text0)
                        log_lines.append(f"🔍 [诊断5] 第1页正则匹配结果: {test_matches}")
                    else:
                        log_lines.append("❌ [致命] 第1页提取不到任何文本！可能是扫描件或字体损坏。")

                master_sku = os.path.splitext(rec.name or "")[0]
                index_vals = []
                total_skus_found = 0

                # --- 正常提取逻辑 ---
                for page_index, page in enumerate(doc):
                    full_text = page.get_text("text") or ""
                    all_matches = sku_pattern.findall(full_text)
                    unique_skus_on_page = set(all_matches)
                    
                    if len(unique_skus_on_page) > 10:
                        continue
                        
                    is_assembly = False
                    if any(kw in full_text for kw in ["装配", "明细", "序号"]):
                        is_assembly = True
                    if len(unique_skus_on_page) > 2:
                        is_assembly = True

                    page_skus = set()
                    words = page.get_text("words")
                    page_width = page.rect.width
                    page_height = page.rect.height
                    
                    for w in words:
                        x0, y0, x1, y1, text_word = w[0], w[1], w[2], w[3], w[4]
                        matches = sku_pattern.findall(text_word)
                        
                        for clean_sku in matches:
                            x_center = (x0 + x1) / 2
                            y_center = (y0 + y1) / 2
                            
                            if is_assembly:
                                is_top_left = y_center < page_height * 0.25 and x_center < page_width * 0.6
                                is_absolute_bottom = y_center > page_height * 0.85 and x_center > page_width * 0.6
                                if is_top_left or is_absolute_bottom:
                                    page_skus.add(clean_sku)
                            else:
                                page_skus.add(clean_sku)
                    
                    final_skus = [sku for sku in page_skus if sku != master_sku]
                    
                    if not final_skus and page_skus:
                        final_skus = list(page_skus)

                    if final_skus:
                        final_set = set(final_skus)
                        skus_text = " ".join(sorted(list(final_set)))
                        index_vals.append({
                            'drawing_id': rec.id,
                            'page_number': page_index + 1,
                            'page_text': skus_text
                        })
                        total_skus_found += len(final_set)

                # 写入数据库
                if index_vals:
                    self.env['material_tracker.drawing.index'].search([('drawing_id', '=', rec.id)]).unlink()
                    self.env['material_tracker.drawing.index'].create(index_vals)
                    log_lines.append(f"✅ 成功！总共提取到 {total_skus_found} 个料号索引。")
                else:
                    log_lines.append("未发现任何匹配的料号。")
                
                rec.write({
                    'index_status': '已建立',
                    'index_log': "\n".join(log_lines)
                })

            except Exception as e:
                error_msg = f"解析失败: {traceback.format_exc()}"
                _logger.error(f"PDF 索引失败 [{rec.name}]: {error_msg}")
                rec.write({
                    'index_status': '失败',
                    'index_log': error_msg
                })
            
            finally:
                if doc:
                    doc.close()
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                gc.collect()
                self.env.cr.commit()

    def action_search_and_slice(self):
        """检索并动态切片：搜索关键字并高亮显示"""
        self.ensure_one()
        if self.index_status != '已建立':
            raise exceptions.UserError("请先建立索引")
        if not self.search_keyword:
            raise exceptions.UserError("请输入搜索词")
        
        if not pymupdf:
            raise exceptions.UserError("服务器未安装 PyMuPDF (pymupdf) 库")

        # 在索引中搜索
        hit = self.env['material_tracker.drawing.index'].search([
            ('drawing_id', '=', self.id),
            ('page_text', 'ilike', self.search_keyword)
        ], limit=1)

        if not hit:
            raise exceptions.UserError(f"未在图纸中找到关键字: {self.search_keyword}")

        page_num = hit.page_number

        try:
            raw_b64 = self.pdf_file
            if isinstance(raw_b64, bytes):
                raw_b64 = raw_b64.decode('utf-8')
            if raw_b64.startswith('data:'):
                raw_b64 = raw_b64.split('base64,')[1]
                
            pdf_bytes = base64.b64decode(raw_b64)
            src_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            
            # 提取单页
            dest_doc = pymupdf.open()
            dest_doc.insert_pdf(src_doc, from_page=page_num-1, to_page=page_num-1)
            
            # 高亮处理
            target_page = dest_doc[0]
            text_instances = target_page.search_for(self.search_keyword)
            for inst in text_instances:
                annot = target_page.add_highlight_annot(inst)
                annot.set_colors(stroke=(1, 1, 0)) # Yellow
                annot.update()
            
            # 转回 Base64
            sliced_pdf_bytes = dest_doc.tobytes()
            src_doc.close()
            dest_doc.close()
            del pdf_bytes
            gc.collect()

            self.write({
                'cache_result_file': base64.b64encode(sliced_pdf_bytes),
                'cache_page_num': page_num
            })
        except Exception as e:
            _logger.error("切片处理失败: %s", str(e))
            raise exceptions.UserError(f"切片处理失败: {str(e)}")

    def action_clear_cache(self):
        """清除缓存"""
        self.write({
            'cache_result_file': False,
            'cache_page_num': 0,
            'search_keyword': False
        })

    def action_clear_index(self):
        """清除索引"""
        self.index_ids.unlink()
        self.write({
            'index_status': '未建立',
            'index_log': ''
        })
        self.action_clear_cache()

class MaterialTrackerDrawingIndex(models.Model):
    _name = 'material_tracker.drawing.index'
    _description = '文本索引库'
    _order = 'page_number'

    drawing_id = fields.Many2one('material_tracker.drawing', string='归属总文件', ondelete='cascade', required=True)
    page_number = fields.Integer(string='页码')
    page_text = fields.Text(string='页提取的纯文本')