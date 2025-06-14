from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox
from config import load_config, save_config
from .elements import get_elements
import sys
import json
import os

# 支持详细模型选择和宽输入框
# 支持模型配置文件动态加载
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.model_map = self.load_model_config(self.config.get('model_config_path', 'model_config.json'))
        self.platforms = list(self.model_map.keys())
        self.elements = get_elements(self.platforms, self.model_map)
        self.setWindowTitle('写作助手')
        self.init_ui()
        self.load_config_to_ui()

    def load_model_config(self, path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def init_ui(self):
        layout = QVBoxLayout()
        e = self.elements
        # 模型平台选择
        layout.addWidget(e['model_label'])
        layout.addWidget(e['model_combo'])
        # 详细模型选择
        hl_model = QHBoxLayout()
        hl_model.addWidget(e['model_detail_label'])
        hl_model.addWidget(e['model_detail_combo'])
        layout.addLayout(hl_model)
        # 标题文件路径
        hl1 = QHBoxLayout()
        hl1.addWidget(e['title_path_label'])
        hl1.addWidget(e['title_path_edit'])
        hl1.addWidget(e['title_path_btn'])
        layout.addLayout(hl1)
        # 保存路径
        hl2 = QHBoxLayout()
        hl2.addWidget(e['save_path_label'])
        hl2.addWidget(e['save_path_edit'])
        hl2.addWidget(e['save_path_btn'])
        layout.addLayout(hl2)
        # 文章采集
        layout.addWidget(e['enable_article_collect'])
        hl3 = QHBoxLayout()
        hl3.addWidget(e['article_count_label'])
        hl3.addWidget(e['article_count_spin'])
        layout.addLayout(hl3)
        # 图片采集
        layout.addWidget(e['enable_image_collect'])
        hl4 = QHBoxLayout()
        hl4.addWidget(e['image_count_label'])
        hl4.addWidget(e['image_count_spin'])
        layout.addLayout(hl4)
        # 提示词
        layout.addWidget(e['prompt_label'])
        layout.addWidget(e['prompt_edit'])
        # 最少字数
        layout.addWidget(e['min_word_count_label'])
        layout.addWidget(e['min_word_count_spin'])
        # 继续创作提示词
        layout.addWidget(e['continue_prompt_label'])
        layout.addWidget(e['continue_prompt_edit'])
        # 启动按钮
        layout.addWidget(e['start_btn'])
        self.setLayout(layout)
        # 事件绑定
        e['title_path_btn'].clicked.connect(self.choose_title_file)
        e['save_path_btn'].clicked.connect(self.choose_save_folder)
        e['start_btn'].clicked.connect(self.save_and_start)
        e['model_combo'].currentTextChanged.connect(self.update_model_detail)

    def load_config_to_ui(self):
        e = self.elements
        c = self.config
        e['model_combo'].setCurrentText(c.get('model', self.platforms[0] if self.platforms else ''))
        self.update_model_detail()
        e['model_detail_combo'].setCurrentText(c.get('model_detail', ''))
        e['title_path_edit'].setText(c.get('title_file_path', ''))
        e['save_path_edit'].setText(c.get('save_path', ''))
        e['enable_article_collect'].setChecked(c.get('enable_article_collect', False))
        e['article_count_spin'].setValue(c.get('article_count', 5))
        e['enable_image_collect'].setChecked(c.get('enable_image_collect', False))
        e['image_count_spin'].setValue(c.get('image_count', 3))
        e['prompt_edit'].setPlainText(c.get('prompt', ''))
        e['min_word_count_spin'].setValue(c.get('min_word_count', 800))
        e['continue_prompt_edit'].setPlainText(c.get('continue_prompt', ''))

    def update_model_detail(self):
        e = self.elements
        platform = e['model_combo'].currentText()
        e['model_detail_combo'].clear()
        if platform in self.model_map:
            e['model_detail_combo'].addItems(list(self.model_map[platform].keys()))

    def choose_title_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择标题文件', '', 'Excel Files (*.xlsx *.xls)')
        if path:
            self.elements['title_path_edit'].setText(path)

    def choose_save_folder(self):
        path = QFileDialog.getExistingDirectory(self, '选择保存文件夹')
        if path:
            self.elements['save_path_edit'].setText(path)

    def save_and_start(self):
        e = self.elements
        platform = e['model_combo'].currentText()
        model = e['model_detail_combo'].currentText()
        model_url = self.model_map.get(platform, {}).get(model, '')
        config = {
            'model': platform,
            'model_detail': model,
            'model_url': model_url,
            'model_config_path': self.config.get('model_config_path', 'model_config.json'),
            'title_file_path': e['title_path_edit'].text(),
            'save_path': e['save_path_edit'].text(),
            'enable_article_collect': e['enable_article_collect'].isChecked(),
            'article_count': e['article_count_spin'].value(),
            'enable_image_collect': e['enable_image_collect'].isChecked(),
            'image_count': e['image_count_spin'].value(),
            'prompt': e['prompt_edit'].toPlainText(),
            'min_word_count': e['min_word_count_spin'].value(),
            'continue_prompt': e['continue_prompt_edit'].toPlainText()
        }
        save_config(config)
        QMessageBox.information(self, '提示', '配置已保存，程序即将开始运行！')
        # TODO: 启动主流程


def run_gui():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec()) 