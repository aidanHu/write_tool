from PyQt6.QtCore import QThread, pyqtSignal
import os
import traceback
from .title_reader import TitleReader
from .toutiao_scraper import ToutiaoScraper
from .poe_automator import PoeAutomator

class WorkflowThread(QThread):
    """
    在后台线程中执行完整的自动化工作流（头条抓取 + Poe创作）。
    通过信号与主GUI线程通信。
    """
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, config, browser_manager, parent=None):
        super().__init__(parent)
        self.config = config
        self.browser_manager = browser_manager # 使用传入的实例

    def run(self):
        try:
            # 1. 如果勾选，执行前置任务：头条内容采集
            if self.config.get('enable_article_collect') or self.config.get('enable_image_collect'):
                print("\n======== 开始执行前置任务：头条内容抓取 ========")
                toutiao_success = self._run_toutiao_workflow()
                if not toutiao_success:
                    # self.error.emit("头条内容抓取失败，主任务中止。") # 改为更柔和的提示
                    print("头条内容抓取未获取到内容或失败，但将继续尝试Poe创作。")
                else:
                    print("======== 头条内容抓取完成 ========")
            else:
                print("\n未开启内容抓取，直接进入Poe创作流程。")

            # 2. 执行主任务：Poe内容创作
            print("\n======== 开始执行主任务：Poe内容创作 ========")
            poe_summary = self._run_poe_workflow()
            
            # 3. 任务结束，发送成功信号
            self.finished.emit(poe_summary)

        except Exception as e:
            # 捕获任何未预料的异常，发送错误信号
            detailed_error = f'执行工作流时发生未知错误：\n{str(e)}\n\n{traceback.format_exc()}'
            print(detailed_error)
            self.error.emit(detailed_error)
        finally:
            # 确保无论成功还是失败，都关闭此工作流使用的浏览器
            if self.browser_manager:
                print("工作流执行完毕，正在关闭浏览器...")
                self.browser_manager.close_browser()

    def _run_toutiao_workflow(self):
        """运行头条抓取流程，成功返回True，失败返回False。"""
        try:
            # 初始化标题读取器以获取关键词
            title_reader = TitleReader(self.config['title_file_path'])
            pending_titles = title_reader.get_all_pending_titles()
            if not pending_titles:
                print("没有待处理的标题，头条抓取任务跳过。")
                return True

            keyword = pending_titles[0][1] # 使用第一个标题作为搜索关键词
            print(f"将使用第一个标题作为头条搜索关键词: '{keyword}'")

            # 初始化抓取器，并传入共享的浏览器实例
            scraper = ToutiaoScraper(self.config, self.browser_manager)
            return scraper.scrape_articles_and_images(keyword)

        except Exception as e:
            print(f"头条抓取工作流程执行失败: {str(e)}")
            traceback.print_exc()
            return False

    def _run_poe_workflow(self):
        """运行Poe自动化工作流程，返回一个包含结果摘要的字符串。"""
        # 1. 验证Poe特定配置
        if not self.config.get('title_file_path') or not self.config.get('save_path') or not self.config.get('prompt'):
            raise ValueError("Poe任务缺少必要配置：需要标题文件、保存路径和提示词。")

        # 2. 读取所有待处理标题
        title_reader = TitleReader(self.config['title_file_path'])
        titles_to_process = title_reader.get_all_pending_titles()
        if not titles_to_process:
            return "所有标题都已处理完毕，无需执行Poe任务。"

        print(f"======== POE任务开始，共需处理 {len(titles_to_process)} 个标题。 ========")

        # 3. 初始化PoeAutomator，传入共享的浏览器实例
        poe_automator = PoeAutomator(self.config, self.browser_manager)

        # 4. 循环处理每个标题
        completed_count = 0
        total_count = len(titles_to_process)
        for i, (index, title) in enumerate(titles_to_process):
            print(f"\n--- [ {i+1}/{total_count} ] 开始处理标题: {title} ---")
            
            # 生成内容
            html_content = poe_automator.generate_content(title=title)

            if html_content:
                # 定义保存文件名
                safe_title = "".join(x for x in title if x.isalnum() or x in " -_").rstrip()
                output_filename = os.path.join(self.config['save_path'], f"{safe_title}.md")
                
                # 保存内容
                if poe_automator.save_content(html_content, output_filename):
                    completed_count += 1
                    title_reader.mark_finished(index) # 标记为完成
                    print(f"--- [ {i+1}/{total_count} ] 标题 '{title}' 处理完成并保存。 ---")
                else:
                    print(f"--- [ {i+1}/{total_count} ] 标题 '{title}' 保存失败。 ---")
            else:
                print(f"--- [ {i+1}/{total_count} ] 标题 '{title}' 的内容生成失败。 ---")

        # 5. 任务结束
        summary = f"Poe任务全部完成。\n成功生成 {completed_count}/{total_count} 篇文章。"
        print(f"\n======== {summary} ========")
        return summary 