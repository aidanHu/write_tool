from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QFileDialog, QSpinBox, QTextEdit

# 支持详细模型选择和宽输入框
# 所有界面元素集中定义，便于维护
# 支持模型配置文件动态加载

def get_elements(platforms=None, model_map=None):
    elements = {
        'model_label': QLabel('模型平台选择'),
        'model_combo': QComboBox(),
        'model_detail_label': QLabel('详细模型选择'),
        'model_detail_combo': QComboBox(),
        'title_path_label': QLabel('标题文件路径'),
        'title_path_edit': QLineEdit(),
        'title_path_btn': QPushButton('选择文件'),
        'save_path_label': QLabel('文件保存路径'),
        'save_path_edit': QLineEdit(),
        'save_path_btn': QPushButton('选择文件夹'),
        'enable_article_collect': QCheckBox('开启文章采集'),
        'article_count_label': QLabel('采集文章数量'),
        'article_count_spin': QSpinBox(),
        'enable_image_collect': QCheckBox('开启图片采集'),
        'image_count_label': QLabel('采集图片数量'),
        'image_count_spin': QSpinBox(),
        'enable_custom_attachment': QCheckBox('上传自定义附件 (将覆盖文章采集)'),
        'custom_attachment_path_label': QLabel('自定义附件路径'),
        'custom_attachment_path_edit': QLineEdit(),
        'custom_attachment_path_btn': QPushButton('选择附件'),
        'prompt_label': QLabel('创作提示词'),
        'prompt_edit': QTextEdit(),
        'min_word_count_label': QLabel('文章最少字数'),
        'min_word_count_spin': QSpinBox(),
        'continue_prompt_label': QLabel('继续创作提示词'),
        'continue_prompt_edit': QTextEdit(),
        'open_browser_btn': QPushButton('打开浏览器'),
        'start_btn': QPushButton('开始运行'),
        'headless_checkbox': QCheckBox('无头模式 (后台静默运行)'),
        'log_output_label': QLabel('运行日志'),
        'log_output': QTextEdit(),
    }
    # 选项初始化
    if platforms:
        elements['model_combo'].addItems(platforms)
    if model_map and platforms:
        first_platform = platforms[0]
        elements['model_detail_combo'].addItems(list(model_map.get(first_platform, {}).keys()))
    elements['article_count_spin'].setRange(1, 20)
    elements['image_count_spin'].setRange(1, 20)
    elements['min_word_count_spin'].setRange(100, 10000)
    # 设置输入框宽度
    elements['prompt_edit'].setMinimumWidth(400)
    elements['continue_prompt_edit'].setMinimumWidth(400)
    elements['prompt_edit'].setMinimumHeight(60)
    elements['continue_prompt_edit'].setMinimumHeight(60)
    elements['headless_checkbox'].setToolTip('勾选后，浏览器将在后台静默运行，不会显示界面，完全避免抢占操作焦点。推荐在正式使用时启用此选项。')
    elements['log_output'].setReadOnly(True)
    elements['log_output'].setMinimumHeight(150)
    return elements 