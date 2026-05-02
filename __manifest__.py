{
    'name': '独立项目来料跟踪',
    'version': '1.0',
    'category': 'Operations/Project',
    'summary': 'Material Tracker',
    'description': """
        独立项目来料跟踪模块
    """,
    'author': 'Antigravity',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'wizard/import_item_wizard_views.xml',
        'wizard/import_outsourced_wizard_views.xml',
        'wizard/import_pdf_wizard_views.xml',
        'views/material_project_views.xml',
        'views/material_item_views.xml',
        'views/outsourced_item_views.xml',
        'views/state_views.xml',
        'views/material_drawing_views.xml', # 确保在该文件之前加载 CSS（可选）
        'views/menus.xml',
    ],
  'assets': {
        'web.assets_backend': [
            'material_tracker/static/src/css/pdf_preview.css',
        ],
    },
        
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}