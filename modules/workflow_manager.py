from PyQt6.QtCore import QThread, pyqtSignal
import os
import traceback
import json
import random
import re
import logging
from markdownify import markdownify as md
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
        """
        根据GUI的配置，运行完整的工作流。
        """
        try:
            # 1. 初始化
            title_reader = TitleReader(self.config['title_file_path'])
            titles_to_process = title_reader.get_all_pending_titles()
            total_tasks = len(titles_to_process)
            completed_count = 0
            
            if not titles_to_process:
                print("所有标题都已处理完毕，无需执行新任务。")
                return

            # 2. 在循环外，根据GUI设置，一次性确定本次运行的工作流程
            should_scrape_articles = self.config.get('enable_article_collect', False)
            should_scrape_images = self.config.get('enable_image_collect', False)
            should_run_poe = not (self.config.get('toutiao_scrape_only', False) and not self.config.get('poe_generate_only', False))
            
            print("\n" + "="*50)
            print(" 工作流程已确定 ".center(50, "="))
            print(f"抓取文章: {'是' if should_scrape_articles else '否'}")
            print(f"抓取图片 (并上传七牛云): {'是' if should_scrape_images else '否'}")
            print(f"执行Poe创作: {'是' if should_run_poe else '否'}")
            print("="*50 + "\n")

            poe_automator = None
            if should_run_poe:
                poe_automator = self._init_poe_automator()
                if not poe_automator:
                    print("Poe模块初始化失败，无法继续执行Poe创作流程。")
                    return # 如果需要Poe但初始化失败，则终止

            # --- 3. 主循环开始 ---
            for i, (index, title) in enumerate(titles_to_process):
                print(f"\n======== [ {i+1}/{total_tasks} ] 开始新任务: {title} ========")
                
                # a. 按需执行头条抓取
                if should_scrape_articles or should_scrape_images:
                    if not self._run_toutiao_workflow(title, should_scrape_articles, should_scrape_images):
                        print(f"--- 任务 '{title}' 的头条抓取失败，跳过此任务 ---")
                        title_reader.mark_failed(index) # 标记为失败
                        continue
                
                # b. 按需执行Poe创作流程
                if should_run_poe:
                    article_to_upload = 'article.txt' if should_scrape_articles and os.path.exists('article.txt') else None
                    if self._run_poe_workflow(poe_automator, title, article_to_upload):
                        completed_count += 1
                        title_reader.mark_finished(index)
                    else:
                        print(f"--- 任务 '{title}' 的Poe创作流程失败 ---")
                        title_reader.mark_failed(index) # 标记为失败
                else:
                    # 如果只抓取，不创作，也算作完成
                    completed_count += 1
                    title_reader.mark_finished(index)

        except Exception as e:
            print(f"工作流发生严重错误: {e}")
            traceback.print_exc()
        finally:
            if 'poe_automator' in locals() and poe_automator:
                poe_automator.cleanup()
            print(f"\n======== 工作流结束: {completed_count}/{total_tasks} 个任务成功完成 ========")

    def _init_poe_automator(self):
        """初始化PoeAutomator实例"""
        try:
            model_config_path = self.config.get('model_config_path', 'model_config.json')
            with open(model_config_path, 'r', encoding='utf-8') as f:
                model_urls = json.load(f)
            platform = self.config.get('model')
            model_detail = self.config.get('model_detail')
            model_url = model_urls.get(platform, {}).get(model_detail)
            if not model_url:
                raise ValueError(f"未在 {model_config_path} 中找到模型URL。")
            return PoeAutomator(self.config, self.browser_manager, model_url=model_url)
        except Exception as e:
            self.error.emit(f"PoeAutomator初始化失败: {e}")
            return None

    def _run_toutiao_workflow(self, keyword, scrape_articles, scrape_images):
        """为单个关键词运行头条抓取流程"""
        print(f"--- 开始为关键词 '{keyword}' 抓取头条内容 ---")
        try:
            scraper = ToutiaoScraper(self.config, self.browser_manager)
            return scraper.scrape_articles_and_images(keyword, scrape_articles, scrape_images)
        except Exception as e:
            print(f"头条抓取工作流程执行失败: {str(e)}")
            return False

    def _run_poe_workflow(self, poe_automator, title, article_path):
        """为单个标题运行Poe自动化工作流程"""
        main_prompt_template = self.config.get('prompt', "以'{title}'为标题写一篇文章。")
        continue_prompt = self.config.get('continue_prompt', '请继续写，内容要更丰富。')
        min_word_count = self.config.get('min_word_count', 800)
        
        main_prompt = main_prompt_template.format(title=title)
        
        # 1. 首次生成
        html_content = poe_automator.generate_content(prompt=main_prompt, article_file=article_path)
        if not html_content:
            return False

        # 2. 检查字数并二次创作
        markdown_content = md(html_content, heading_style='ATX')
        
        # 使用更准确的字数统计方法
        cleaned_text = re.sub(r'[\s\W_]+', '', markdown_content)
        word_count = len(cleaned_text)
        print(f"首次生成完成，字数: {word_count} (要求: {min_word_count})")

        if word_count < min_word_count:
            print("字数不足，开始二次创作...")
            html_content = poe_automator.continue_generation(continue_prompt)
            if html_content:
                markdown_content = md(html_content, heading_style='ATX')
                print("二次创作完成。")
            else:
                print("二次创作失败，将使用当前内容。")

        # 3. 在插入图片前，清理Poe生成的内容
        self.logger.info("清理Poe生成内容，移除H1标题和底部时间戳...")
        lines = markdown_content.split('\n')

        # 移除H1标题 (通常是第一行)
        if lines and lines[0].strip().startswith('# '):
            self.logger.info(f"移除H1标题: {lines[0]}")
            lines.pop(0)
        
        # 移除前导空行
        while lines and not lines[0].strip():
            lines.pop(0)

        # 清理尾部空行
        while lines and not lines[-1].strip():
            lines.pop(-1)

        # 检查并移除时间戳
        if lines:
            time_pattern = re.compile(r'^\\d{1,2}:\\d{2}$')
            if time_pattern.match(lines[-1].strip()):
                self.logger.info(f"发现并移除底部时间戳: '{lines[-1].strip()}'")
                lines.pop(-1)
        
        markdown_content = '\n'.join(lines)

        # 4. 按需插入图片
        if self.config.get('enable_image_collect', False):
            markdown_content = self._insert_pictures(markdown_content)
        
        # 5. 保存
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_").rstrip()
        output_filename = os.path.join(self.config['save_path'], f"{safe_title}.md")
        
        return poe_automator.save_content(markdown_content, output_filename)

    def _insert_pictures(self, markdown_content):
        """
        将图片链接智能地插入到Markdown文本中。
        优先插入到二级标题后，其次插入到段落之间。
        """
        print("--- 开始智能插入图片 ---")
        try:
            with open('picture.txt', 'r', encoding='utf-8') as f:
                # 直接读取已是Markdown格式的图片链接
                pictures = [line.strip() for line in f if line.strip()]
            
            if not pictures:
                print("picture.txt 中没有图片链接，跳过插入。")
                return markdown_content

            lines = markdown_content.split('\n')
            
            # 查找所有二级标题的行号
            h2_indices = [i for i, line in enumerate(lines) if line.strip().startswith('## ')]
            
            # 查找所有段落分隔处的行号（连续两个或更多换行符，表现为空行）
            # 我们只在内容非空的行后面的空行插入
            paragraph_break_indices = [i for i, line in enumerate(lines) if not line.strip() and i > 0 and lines[i-1].strip()]

            # 优先使用二级标题后的位置
            # 使用集合以避免重复
            insertion_points = set(h2_indices)
            
            # 如果二级标题位置不够，用段落分隔处补充
            if len(insertion_points) < len(pictures):
                # 排除掉紧跟在标题或已选位置后面的段落分隔符，避免重复插入
                available_para_breaks = [p for p in paragraph_break_indices if p-1 not in insertion_points]
                needed = len(pictures) - len(insertion_points)
                # 如果有可用的段落分隔符，随机挑选一些
                if available_para_breaks:
                    insertion_points.update(random.sample(available_para_breaks, min(needed, len(available_para_breaks))))

            if not insertion_points:
                print("未能在文章中找到合适的图片插入点（二级标题或段落），图片将不会被插入。")
                return markdown_content

            # 转换回列表并按倒序排序，以便安全地插入
            sorted_points = sorted(list(insertion_points), reverse=True)
            
            num_to_insert = min(len(pictures), len(sorted_points))
            pics_to_insert = pictures[:num_to_insert]

            for i in range(num_to_insert):
                pic_markdown = pics_to_insert[i]
                insert_index = sorted_points[i]
                # 插入到标题或段落的下一行，并确保前后都有空行，以符合Markdown语法
                lines.insert(insert_index + 1, f"\n{pic_markdown}\n")

            final_content = '\n'.join(lines)
            print(f"成功将 {num_to_insert} 张图片智能插入到文章中。")
            return final_content

        except FileNotFoundError:
            print("picture.txt 未找到，跳过图片插入。")
            return markdown_content
        except Exception as e:
            print(f"插入图片时出错: {e}")
            traceback.print_exc()
            return markdown_content 