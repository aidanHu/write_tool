from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox
from config import load_config, save_config
from .elements import get_elements
from modules.browser_manager import BrowserManager
from modules.workflow_manager import WorkflowThread
import sys
import json
import os
import asyncio
import threading

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
        # 自定义附件
        layout.addWidget(e['enable_custom_attachment'])
        hl_attachment = QHBoxLayout()
        hl_attachment.addWidget(e['custom_attachment_path_label'])
        hl_attachment.addWidget(e['custom_attachment_path_edit'])
        hl_attachment.addWidget(e['custom_attachment_path_btn'])
        layout.addLayout(hl_attachment)
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
        # 日志输出
        layout.addWidget(e['log_output_label'])
        layout.addWidget(e['log_output'])
        self.setLayout(layout)
        # 事件绑定
        e['title_path_btn'].clicked.connect(self.choose_title_file)
        e['save_path_btn'].clicked.connect(self.choose_save_folder)
        e['custom_attachment_path_btn'].clicked.connect(self.choose_custom_attachment_file)
        e['open_browser_btn'].clicked.connect(self.launch_utility_browser)
        e['start_btn'].clicked.connect(self.start_workflow)
        e['model_combo'].currentTextChanged.connect(self.update_model_detail)

    def load_config_to_ui(self):
        e = self.elements
        c = self.config
        e['model_combo'].setCurrentText(c.get('model', self.platforms[0] if self.platforms else ''))
        self.update_model_detail()
        e['model_detail_combo'].setCurrentText(c.get('model_detail', ''))
        e['title_path_edit'].setText(c.get('title_path', ''))
        e['save_path_edit'].setText(c.get('save_path', ''))
        e['enable_article_collect'].setChecked(c.get('enable_article_collect', False))
        e['article_count_spin'].setValue(c.get('article_count', 5))
        e['enable_image_collect'].setChecked(c.get('enable_image_collect', False))
        e['image_count_spin'].setValue(c.get('image_count', 3))
        e['enable_custom_attachment'].setChecked(c.get('enable_custom_attachment', False))
        e['custom_attachment_path_edit'].setText(c.get('custom_attachment_path', ''))
        e['prompt_edit'].setPlainText(c.get('prompt', ''))
        e['min_word_count_spin'].setValue(c.get('min_word_count', 800))
        e['continue_prompt_edit'].setPlainText(c.get('continue_prompt', ''))
        e['headless_checkbox'].setChecked(c.get('headless', False))

    def update_log(self, message):
        """线程安全地更新日志文本框。"""
        self.elements['log_output'].append(message)

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

    def choose_custom_attachment_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择附件文件', '', 'All Files (*.*)')
        if path:
            self.elements['custom_attachment_path_edit'].setText(path)

    def launch_utility_browser(self):
        """启动一个浏览器用于手动登录等操作"""
        if hasattr(self, 'util_browser_thread') and self.util_browser_thread.is_alive():
            QMessageBox.information(self, "提示", "辅助浏览器已在运行中。")
            return

        def start_util_browser():
            try:
                utility_browser_manager = BrowserManager()
                asyncio.run(utility_browser_manager.launch())
                self.update_log("辅助浏览器已启动。请在此浏览器中手动登录，完成后可直接关闭此浏览器。")
                # 浏览器将在asyncio.run结束后自动关闭，但由于没有其他任务，它会一直等待。
                # 这是一个简化的后台任务，用户手动关闭浏览器窗口即可结束进程。
            except Exception as e:
                self.update_log(f"启动辅助浏览器时出错: {e}")

        # 在新线程中运行，防止阻塞GUI
        self.util_browser_thread = threading.Thread(target=start_util_browser, daemon=True)
        self.util_browser_thread.start()

    def start_workflow(self):
        """
        一键启动：创建浏览器，执行完整任务，然后由工作流自己关闭浏览器。
        完全独立，不依赖任何外部状态，没有任何前置检查或弹窗。
        """
        # 检查是否有任务正在运行
        if self.workflow_thread and self.workflow_thread.isRunning():
            QMessageBox.information(self, "提示", "当前任务正在运行，请稍后再试。")
            return

        # 检查是否有待处理的任务
        title_path = self.elements['title_path_edit'].text().strip()
        if not title_path or not os.path.exists(title_path):
            QMessageBox.warning(self, "提示", "请先选择有效的标题文件（Excel）。")
            return

        # 简单检查Excel文件是否有内容
        try:
            import pandas as pd
            df = pd.read_excel(title_path, header=None, usecols=[0])
            titles = df[0].dropna().astype(str).tolist()
            if not titles:
                QMessageBox.warning(self, "提示", "Excel文件中没有找到任何标题。")
                return
            
            # 检查是否有未完成的任务
            if len(df.columns) >= 2:
                # 检查第二列的状态
                statuses = df[1].fillna('').astype(str).tolist()
                pending_count = sum(1 for i, status in enumerate(statuses) if i < len(titles) and status != "已完成文章创作")
            else:
                # 没有状态列，所有任务都是待处理的
                pending_count = len(titles)
            
            if pending_count == 0:
                QMessageBox.information(self, "提示", "所有任务都已完成，没有待处理的任务。")
                return
            else:
                self.update_log(f"检测到 {pending_count} 个待处理任务，开始执行...")
                
        except Exception as e:
            QMessageBox.warning(self, "错误", f"检查Excel文件时出错: {e}")
            return

        # 保存最新配置
        e = self.elements
        config = {
            'model': e['model_combo'].currentText(),
            'model_detail': e['model_detail_combo'].currentText(),
            'model_url': self.model_map.get(e['model_combo'].currentText(), {}).get(e['model_detail_combo'].currentText(), ''),
            'model_config_path': self.config.get('model_config_path', 'model_config.json'),
            'title_path': e['title_path_edit'].text(),
            'save_path': e['save_path_edit'].text(),
            'prompt': e['prompt_edit'].toPlainText(),
            'min_word_count': e['min_word_count_spin'].value(),
            'continue_prompt': e['continue_prompt_edit'].toPlainText(),
            'enable_article_collect': e['enable_article_collect'].isChecked(),
            'article_count': e['article_count_spin'].value(),
            'enable_image_collect': e['enable_image_collect'].isChecked(),
            'image_count': e['image_count_spin'].value(),
            'enable_custom_attachment': e['enable_custom_attachment'].isChecked(),
            'custom_attachment_path': e['custom_attachment_path_edit'].text(),
            'headless': e['headless_checkbox'].isChecked(),
        }
        save_config(config)
        
        try:
            # 工作流线程现在自己管理BrowserManager，我们只需要传递配置
            self.workflow_thread = WorkflowThread(config)
            self.workflow_thread.log_signal.connect(self.update_log)
            # 连接自定义的finished和error信号
            self.workflow_thread.finished.connect(self.on_workflow_finished)
            self.workflow_thread.error.connect(self.on_workflow_error)
            self.workflow_thread.start()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建工作流时出错: {e}")

        self.elements['start_btn'].setText("运行中...")
        self.elements['start_btn'].setEnabled(False)

    def on_workflow_finished(self, message=""):
        QMessageBox.information(self, "任务完成", "工作流已执行完毕。")
        self.elements['start_btn'].setText("开始运行")
        self.elements['start_btn'].setEnabled(True)

    def on_workflow_error(self, error_message):
        QMessageBox.critical(self, "任务出错", f"工作流执行失败：{error_message}")
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