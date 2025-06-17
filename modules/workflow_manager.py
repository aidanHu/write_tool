from PyQt6.QtCore import QThread, pyqtSignal
import os
import traceback
import json
import re
import logging
import asyncio

from .toutiao_scraper import ToutiaoScraper
from .poe_automator import PoeAutomator
from .monica_automator import MonicaAutomator
from typing import Optional, List, Dict, Any
from .browser_manager import BrowserManager
import pandas as pd

class WorkflowThread(QThread):
    """
    在后台线程中执行完整的自动化工作流（头条抓取 + Poe创作）。
    通过信号与主GUI线程通信。
    """
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    log_signal = pyqtSignal(str) # 信号必须是类属性

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.browser_manager = BrowserManager(headless=self.config.get('headless', True))
        self.logger = self._setup_logging()

    def _setup_logging(self):
        """设置日志记录器"""
        logger = logging.getLogger('WorkflowThread')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def run(self):
        """同步的线程入口点，负责设置并运行asyncio事件循环"""
        self.log_signal.emit("工作流线程已启动...")
        try:
            # self.loop = asyncio.new_event_loop()
            # asyncio.set_event_loop(self.loop)
            asyncio.run(self.run_async())
        except Exception as e:
            self.log_signal.emit(f"线程启动或运行asyncio循环时出错: {e}")
            traceback.print_exc()
        finally:
            self.log_signal.emit("工作流线程已结束。")

    async def run_async(self):
        """包含所有核心异步逻辑"""
        try:
            self.log_signal.emit("正在启动浏览器...")
            if not await self.browser_manager.launch():
                self.log_signal.emit("启动浏览器失败！")
                return
            self.log_signal.emit("浏览器启动成功。")
            
            titles = self._load_titles_from_excel(self.config['title_path'])
            if not titles:
                self.log_signal.emit("Excel文件中没有找到标题，任务结束。")
                return

            self.log_signal.emit(f"成功加载 {len(titles)} 个任务标题。")

            for index, title in enumerate(titles):
                self.log_signal.emit(f"\n--- 开始处理任务 {index + 1}/{len(titles)}: {title} ---")
                
                # 清理旧的输出文件
                self._clear_file("article.txt")
                self._clear_file("picture.txt")

                should_scrape_articles = self.config.get('enable_article_collect', False)
                should_scrape_images = self.config.get('enable_image_collect', False)

                if should_scrape_articles or should_scrape_images:
                    self.log_signal.emit("正在启动今日头条抓取器...")
                    toutiao_scraper = ToutiaoScraper(self.config, self.browser_manager)
                    success = await toutiao_scraper.scrape_articles_and_images(
                        keyword=title,
                        scrape_articles=should_scrape_articles,
                        scrape_images=should_scrape_images
                    )
                    if not success:
                        self.log_signal.emit("今日头条抓取失败，跳过此任务。")
                        continue
                
                # 确定要上传的附件
                article_to_upload = None
                if self.config.get('enable_custom_attachment'):
                    custom_path = self.config.get('custom_attachment_path', '').strip()
                    if custom_path and os.path.exists(custom_path):
                        article_to_upload = custom_path
                        self.log_signal.emit(f"使用自定义附件: {custom_path}")
                    elif custom_path:
                        self.log_signal.emit(f"警告：自定义附件路径不存在: {custom_path}")
                    else:
                        self.log_signal.emit("警告：自定义附件路径为空")
                elif should_scrape_articles and os.path.exists("article.txt"):
                    article_to_upload = "article.txt"
                    self.log_signal.emit("使用抓取的文章作为附件: article.txt")
                
                if article_to_upload:
                    self.log_signal.emit(f"将上传附件: {article_to_upload}")
                else:
                    self.log_signal.emit("没有附件需要上传")

                # 开始文章生成流程
                platform = self.config.get('model', 'poe').lower()
                if platform == 'poe':
                    self.log_signal.emit("开始 POE 文章生成流程...")
                    workflow_success = await self._run_poe_workflow(title, article_to_upload)
                elif platform == 'monica':
                    self.log_signal.emit("开始 Monica 文章生成流程...")
                    workflow_success = await self._run_monica_workflow(title, article_to_upload)
                else:
                    self.log_signal.emit(f"未知的平台: {platform}")
                    workflow_success = False
                
                if workflow_success:
                     self.log_signal.emit(f"--- 任务 {index + 1}/{len(titles)} 完成 ---\n")
                     # 更新Excel状态
                     self._update_excel_status(index, "已完成文章创作")
                else:
                    self.log_signal.emit(f"--- 任务 {index + 1}/{len(titles)} 失败 ---\n")
                    # 更新Excel状态
                    self._update_excel_status(index, "创作失败")

                await asyncio.sleep(2) # 每个任务之间的短暂延迟

        except Exception as e:
            self.log_signal.emit(f"工作流执行期间发生严重错误: {e}")
            traceback.print_exc()
            self.error.emit(f"工作流执行失败: {e}")
        finally:
            await self.cleanup()
            self.log_signal.emit("所有任务已完成。")
            self.finished.emit("工作流已完成")

    async def _run_toutiao_workflow(self, scraper, keyword, scrape_articles, scrape_images):
        """为单个关键词运行头条抓取流程"""
        self.log_signal.emit(f"--- 开始为关键词 '{keyword}' 抓取头条内容 ---")
        try:
            return await scraper.scrape_articles_and_images(keyword, scrape_articles, scrape_images)
        except Exception as e:
            self.log_signal.emit(f"头条抓取工作流程执行失败: {str(e)}")
            return False

    async def _run_poe_workflow(self, title: str, article_path: Optional[str]) -> bool:
        self.log_signal.emit("正在启动 Poe 工作流程...")
        
        # 获取模型URL
        model_url = self.config.get('model_url')
        if not model_url:
            self.log_signal.emit("错误：未找到模型URL配置")
            return False
        
        poe_automator = PoeAutomator(self.config, self.browser_manager, model_url)
        try:
            generated_article = await poe_automator.compose_article(
                title,
                attachment_path=article_path,
                min_words=self.config.get('min_word_count', 800),
                prompt=self.config.get('prompt', ''),
                continue_prompt=self.config.get('continue_prompt', '')
            )
            if not generated_article:
                self.log_signal.emit("Poe 未能生成文章。")
                return False

            self._save_article(title, generated_article)
            return True
        except Exception as e:
            self.log_signal.emit(f"Poe 工作流程失败: {e}")
            return False

    async def _run_monica_workflow(self, title: str, article_path: Optional[str]) -> bool:
        self.log_signal.emit("正在启动 Monica 工作流程...")
        
        # 获取模型URL
        model_url = self.config.get('model_url')
        if not model_url:
            self.log_signal.emit("错误：未找到模型URL配置")
            return False
        
        monica_automator = MonicaAutomator(self.config, self.browser_manager, model_url)
        try:
            if not await monica_automator.navigate_to_monica():
                return False
            
            generated_article = await monica_automator.compose_article(
                title,
                attachment_path=article_path,
                min_words=self.config.get('min_word_count', 800),
                prompt=self.config.get('prompt', ''),
                continue_prompt=self.config.get('continue_prompt', '')
            )

            if not generated_article:
                self.log_signal.emit("Monica 未能生成文章。")
                return False

            self._save_article(title, generated_article)
            return True
        except Exception as e:
            self.log_signal.emit(f"Monica 工作流程失败: {e}")
            return False
            
    async def cleanup(self):
        self.log_signal.emit("正在清理资源并关闭浏览器...")
        if self.browser_manager:
            try:
                await self.browser_manager.cleanup()
            except Exception as e:
                self.log_signal.emit(f"浏览器关闭时出现警告（可忽略）: {e}")
                # EPIPE错误是常见的，不应该影响整体流程
        self.log_signal.emit("浏览器已关闭。")

    def _load_titles_from_excel(self, file_path: str) -> List[str]:
        if not file_path or not os.path.exists(file_path):
            self.log_signal.emit(f"Excel文件路径无效或文件不存在: {file_path}")
            return []
        try:
            # 读取完整的Excel文件
            df = pd.read_excel(file_path, header=None)
            
            # 获取第一列的标题
            titles = df[0].dropna().astype(str).tolist()
            
            # 检查是否有状态列，只处理未完成的任务
            if len(df.columns) >= 2:
                statuses = df[1].fillna('').astype(str).tolist()
                # 创建待处理任务列表，包含索引信息
                pending_tasks = []
                for i, title in enumerate(titles):
                    if i < len(statuses):
                        status = statuses[i]
                        if status != "已完成文章创作":
                            pending_tasks.append((i, title))
                    else:
                        # 没有状态的任务视为待处理
                        pending_tasks.append((i, title))
                
                # 保存任务索引映射
                self.task_indices = [task[0] for task in pending_tasks]
                titles = [task[1] for task in pending_tasks]
                
                self.log_signal.emit(f"从Excel文件加载 {len(titles)} 个待处理任务（跳过已完成任务）。")
            else:
                # 没有状态列，所有任务都是待处理的
                self.task_indices = list(range(len(titles)))
                self.log_signal.emit(f"从Excel文件成功加载 {len(titles)} 个标题。")
            
            # 保存Excel文件路径供后续更新状态使用
            self.excel_file_path = file_path
            return titles
        except Exception as e:
            self.log_signal.emit(f"读取Excel文件时发生错误: {e}")
            return []

    def _update_excel_status(self, task_index: int, status: str):
        """更新Excel文件中对应行的状态"""
        if not hasattr(self, 'excel_file_path') or not self.excel_file_path:
            return
        
        try:
            # 获取实际的Excel行索引
            if hasattr(self, 'task_indices') and task_index < len(self.task_indices):
                excel_row_index = self.task_indices[task_index]
            else:
                excel_row_index = task_index
            
            # 读取整个Excel文件
            df = pd.read_excel(self.excel_file_path, header=None)
            
            # 确保第二列存在，如果不存在则创建
            if len(df.columns) < 2:
                df[1] = ''
            
            # 更新对应行的状态（第二列）
            if excel_row_index < len(df):
                df.iloc[excel_row_index, 1] = status
                
                # 保存回Excel文件
                df.to_excel(self.excel_file_path, index=False, header=False)
                self.log_signal.emit(f"已更新Excel状态: 第{excel_row_index + 1}行 -> {status}")
            
        except Exception as e:
            self.log_signal.emit(f"更新Excel状态失败: {e}")

    def _save_article(self, title: str, content: str):
        save_path = self.config.get('save_path', '.')
        if not os.path.exists(save_path):
            os.makedirs(save_path)
            self.log_signal.emit(f"创建保存目录: {save_path}")

        # 文件名处理
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_')).rstrip()
        filename = os.path.join(save_path, f"{safe_title}.md")

        # 插入图片链接到二级标题后面
        if os.path.exists('picture.txt'):
            with open('picture.txt', 'r', encoding='utf-8') as f:
                pictures_content = f.read().strip()
            
            if pictures_content:
                # 将图片链接按行分割
                picture_lines = [line.strip() for line in pictures_content.split('\n') if line.strip()]
                
                if picture_lines:
                    content = self._insert_images_after_headings(content, picture_lines)
                    self.log_signal.emit(f"已将 {len(picture_lines)} 张图片分别插入到二级标题后面。")
                else:
                    self.log_signal.emit("图片文件为空，未插入图片。")
            else:
                self.log_signal.emit("图片文件内容为空，未插入图片。")

        # 保存文章
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log_signal.emit(f"文章已成功保存到: {filename}")
        except Exception as e:
            self.log_signal.emit(f"保存文章失败: {e}")
            traceback.print_exc()

    def _insert_images_after_headings(self, content: str, picture_lines: List[str]) -> str:
        """
        将图片链接分别插入到二级标题后面
        """
        import re
        
        lines = content.split('\n')
        result_lines = []
        picture_index = 0
        
        for i, line in enumerate(lines):
            result_lines.append(line)
            
            # 检查是否是二级标题（## 开头）
            if line.strip().startswith('## ') and picture_index < len(picture_lines):
                # 在二级标题后插入空行和图片
                result_lines.append('')  # 空行
                result_lines.append(picture_lines[picture_index])  # 图片链接
                result_lines.append('')  # 空行
                picture_index += 1
        
        # 如果还有剩余图片，插入到文章末尾
        if picture_index < len(picture_lines):
            result_lines.append('')  # 空行
            result_lines.append('## 相关图片')  # 添加一个图片标题
            result_lines.append('')  # 空行
            for i in range(picture_index, len(picture_lines)):
                result_lines.append(picture_lines[i])
                result_lines.append('')  # 每张图片后空行
        
        return '\n'.join(result_lines)

    def _clear_file(self, filename: str):
        if os.path.exists(filename):
            try:
                os.remove(filename)
                self.log_signal.emit(f"已清理旧文件: {filename}")
            except OSError as e:
                self.log_signal.emit(f"清理文件 {filename} 失败: {e}") 