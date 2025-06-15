from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox
from config import load_config, save_config
from .elements import get_elements
from modules.browser_manager import BrowserManager
from modules.workflow_manager import WorkflowThread
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
        self.workflow_thread = None
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
        # 浏览器和启动按钮
        hl_buttons = QHBoxLayout()
        hl_buttons.addWidget(e['open_browser_btn'])
        hl_buttons.addWidget(e['start_btn'])
        layout.addLayout(hl_buttons)
        # 无头模式选项
        layout.addWidget(e['headless_checkbox'])
        self.setLayout(layout)
        # 事件绑定
        e['title_path_btn'].clicked.connect(self.choose_title_file)
        e['save_path_btn'].clicked.connect(self.choose_save_folder)
        e['open_browser_btn'].clicked.connect(self.open_browser)
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
        e['headless_checkbox'].setChecked(c.get('headless', False))

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

    def open_browser(self):
        """
        独立的辅助工具：使用与主任务相同的配置打开浏览器，用于手动登录或调试。
        这个浏览器实例不会被主流程使用，它的生命周期由用户手动管理。
        """
        try:
            # 使用一个临时的管理器实例
            utility_browser_manager = BrowserManager(port=9222) 
            utility_browser_manager.start_browser()
            QMessageBox.information(self, "浏览器已启动", "辅助浏览器已启动。您可在此手动登录，登录状态将被保存。\n完成后可直接关闭此浏览器。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动辅助浏览器时出错: {e}")

    def save_and_start(self):
        """
        一键启动：创建浏览器，执行完整任务，然后由工作流自己关闭浏览器。
        完全独立，不依赖任何外部状态，没有任何前置检查或弹窗。
        """
        if self.workflow_thread and self.workflow_thread.isRunning():
            QMessageBox.information(self, "提示", "当前任务正在运行，请稍后再试。")
            return

        # 保存最新配置
        e = self.elements
        config = {
            'model': e['model_combo'].currentText(),
            'model_detail': e['model_detail_combo'].currentText(),
            'model_url': self.model_map.get(e['model_combo'].currentText(), {}).get(e['model_detail_combo'].currentText(), ''),
            'model_config_path': self.config.get('model_config_path', 'model_config.json'),
            'title_file_path': e['title_path_edit'].text(),
            'save_path': e['save_path_edit'].text(),
            'prompt': e['prompt_edit'].toPlainText(),
            'min_word_count': e['min_word_count_spin'].value(),
            'continue_prompt': e['continue_prompt_edit'].toPlainText(),
            'enable_article_collect': e['enable_article_collect'].isChecked(),
            'article_count': e['article_count_spin'].value(),
            'enable_image_collect': e['enable_image_collect'].isChecked(),
            'image_count': e['image_count_spin'].value(),
            'headless': e['headless_checkbox'].isChecked(),
        }
        save_config(config)
        
        try:
            # 为本次工作流创建专用的浏览器实例
            is_headless = config.get('headless', False)
            workflow_browser_manager = BrowserManager(port=9222, headless=is_headless)
            workflow_browser_manager.start_browser()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"为工作流启动浏览器时出错: {e}")
            return

        # 直接启动工作流线程，将浏览器实例所有权交给它
        self.workflow_thread = WorkflowThread(config, workflow_browser_manager)
        self.workflow_thread.finished.connect(self.on_workflow_finished)
        self.workflow_thread.error.connect(self.on_workflow_error)
        self.workflow_thread.start()
        
        self.elements['start_btn'].setText("运行中...")
        self.elements['start_btn'].setEnabled(False)

    def on_workflow_finished(self, message):
        QMessageBox.information(self, "任务完成", message)
        self.elements['start_btn'].setText("开始运行")
        self.elements['start_btn'].setEnabled(True)

    def on_workflow_error(self, error_message):
        QMessageBox.critical(self, "任务出错", error_message)
        self.elements['start_btn'].setText("开始运行")
        self.elements['start_btn'].setEnabled(True)

    def closeEvent(self, event):
        """重写关闭事件，处理正在运行的线程。"""
        if self.workflow_thread and self.workflow_thread.isRunning():
            reply = QMessageBox.question(self, '确认退出',
                                       '任务正在运行中，确定要退出吗？',
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                # 允许退出，正在运行的线程中的finally块会尽力关闭浏览器
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def run_gui():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    run_gui() 