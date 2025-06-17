import os
import time
import json
import logging
import re
from typing import Optional
import asyncio

from .browser_manager import BrowserManager


class PoeAutomator:
    """基于Playwright的POE自动化器"""

    def __init__(self, gui_config: dict, browser_manager: BrowserManager, model_url: str):
        self.browser_manager = browser_manager
        self.logger = self._setup_logging()
        self.model_url = model_url

        # 加载并合并配置
        base_config = self._load_config('poe_config.json')
        base_config.update(gui_config)
        self.config = base_config

        # 提取常用配置项
        self.selectors = self.config.get('selectors', {}).get('chat', {})
        self.timeouts = self.config.get('timeouts', {})
        self.urls = self.config.get('urls', {})
        
        self.logger.info(f"POE自动化器初始化完成，目标URL: {self.model_url}")

    def _setup_logging(self):
        """设置日志记录器"""
        logger = logging.getLogger('PoeAutomator')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _load_config(self, config_file: str) -> dict:
        """从JSON文件加载配置"""
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            self.logger.warning(f"配置文件 {config_file} 不存在，将使用默认或GUI传入的配置。")
        except Exception as e:
            self.logger.error(f"加载配置文件 {config_file} 失败: {e}")
        return {}
    
    def _get_selector(self, name: str) -> Optional[str]:
        """从配置中安全地获取选择器"""
        selector = self.selectors.get(name)
        if not selector:
            self.logger.error(f"在配置中未找到选择器: '{name}'")
        return selector

    async def navigate_to_poe(self) -> bool:
        """导航到在初始化时指定的模型URL"""
        try:
            self.logger.info(f"导航到: {self.model_url}")
            if not await self.browser_manager.navigate(self.model_url):
                raise ConnectionError("浏览器导航失败")
            
            await asyncio.sleep(2) # 等待页面初步加载
            
            chat_input_selector = self._get_selector('chat_input')
            if not chat_input_selector: return False

            element = await self.browser_manager.find_element(
                chat_input_selector, timeout=self.timeouts.get('page_load', 30)
            )
            if not element:
                self.logger.error("导航后未能找到聊天输入框，页面可能未正确加载。")
                return False

            self.logger.info("成功导航到POE页面并找到聊天输入框。")
            return True
        except Exception as e:
            self.logger.error(f"导航到POE失败: {e}", exc_info=True)
            return False

    async def upload_file(self, file_path: str) -> bool:
        """
        使用BrowserManager为隐藏的input元素设置文件路径。
        """
        self.logger.info(f"开始直接上传文件: {file_path}")
        if not os.path.exists(file_path):
            self.logger.error(f"素材文件不存在: {file_path}")
            return False

        file_input_selector = self._get_selector('file_input')
        if not file_input_selector:
            return False

        self.logger.info(f"正在直接为选择器 '{file_input_selector}' 设置文件...")
        success = await self.browser_manager.set_input_files_for_hidden_element(
            file_input_selector, file_path
        )

        if success:
            self.logger.info(f"文件上传操作已提交: {file_path}")
            await asyncio.sleep(3) # 等待文件处理
        else:
            self.logger.error(f"为隐藏元素设置文件 '{file_path}' 失败。")

        return success

    async def send_prompt(self, prompt: str) -> bool:
        """在文本框中输入提示并点击发送。"""
        self.logger.info("开始发送提示...")
        try:
            chat_input_selector = self._get_selector('chat_input')
            send_button_selector = self._get_selector('send_button')
            if not chat_input_selector or not send_button_selector:
                return False

            self.logger.info("正在输入提示文本...")
            if not await self.browser_manager.focus_and_type_text(chat_input_selector, prompt):
                 self.logger.error(f"输入提示失败: {chat_input_selector}")
                 return False

            self.logger.info(f"正在点击发送按钮: {send_button_selector}")
            send_button = await self.browser_manager.find_element(send_button_selector)
            if not send_button or not await send_button.is_enabled():
                self.logger.error("发送按钮未找到或不可用。")
                return False
            
            await send_button.click()

            self.logger.info("提示已成功发送。")
            return True
        except Exception as e:
            self.logger.error(f"发送提示时出现异常: {e}", exc_info=True)
            return False

    async def wait_for_generation_to_complete(self) -> bool:
        """等待内容生成完成。"""
        self.logger.info("等待内容生成完成...")
        try:
            stop_button_selector = self._get_selector('stop_button')
            if not stop_button_selector:
                return False
            
            timeout = self.timeouts.get('ai_response_wait', 300) * 1000 # 转换为毫秒

            self.logger.info("等待'停止'按钮出现...")
            stop_button = await self.browser_manager.find_element(stop_button_selector, timeout=15)
            
            if not stop_button:
                self.logger.warning("在15秒内未检测到'停止'按钮，可能已秒速生成或未开始。继续。")
                return True

            self.logger.info("'停止'按钮已出现，内容正在生成中。")
            self.logger.info("等待'停止'按钮消失...")
            
            await stop_button.wait_for(state='hidden', timeout=timeout)
            
            self.logger.info("'停止'按钮已消失，内容生成完成。")
            await asyncio.sleep(2) # 等待UI更新
            return True

        except Exception as e:
            self.logger.error(f"等待生成完成时出现异常: {e}", exc_info=True)
            return False

    async def get_latest_response(self) -> Optional[str]:
        """
        获取最后一条机器人消息的HTML，并转换为Markdown格式。
        """
        self.logger.info("正在获取最新生成的内容...")
        try:
            response_selector = self._get_selector('last_response')
            if not response_selector:
                return None
            
            # 使用Playwright的locator来获取所有匹配的元素
            response_elements = await self.browser_manager.find_elements(response_selector)
            if not response_elements:
                self.logger.warning(f"未能找到任何回复元素。选择器: {response_selector}")
                return None

            # 获取最后一个元素
            last_response_element = response_elements[-1]
            
            # 在最后一个元素上执行脚本，移除时间戳
            js_script = """
            (element) => {
                if (!element) { return null; }
                
                var clonedElement = element.cloneNode(true);
                var lastChild = clonedElement.lastElementChild;
                if (lastChild) {
                    var timestampRegex = /^\\s*\\d{1,2}:\\d{2}(:\\d{2})?\\s*$/;
                    if (timestampRegex.test(lastChild.innerText)) {
                        lastChild.remove();
                    }
                }
                return clonedElement.innerHTML;
            }
            """
            
            html_content = await last_response_element.evaluate(js_script)

            if html_content and html_content.strip():
                # 将HTML转换为Markdown
                from markdownify import markdownify as md
                markdown_content = md(html_content, heading_style="ATX")
                
                # 清理多余的空行
                import re
                markdown_content = re.sub(r'\n\s*\n\s*\n', '\n\n', markdown_content)
                markdown_content = markdown_content.strip()
                
                self.logger.info(f"成功获取并转换内容为Markdown，长度为 {len(markdown_content)} 字符。")
                return markdown_content

            self.logger.warning(f"未能获取到最新回复的HTML内容，或内容为空。")
            return None
        except Exception as e:
            self.logger.error(f"获取最新回复时出现异常: {e}", exc_info=True)
            return None

    async def generate_content(self, prompt: str, article_file: Optional[str] = None) -> Optional[str]:
        """
        执行完整的Poe文章生成工作流。
        """
        self.logger.info(f"--- 开始Poe内容生成工作流 ---")
        
        # 1. 导航
        if not await self.navigate_to_poe():
            return None

        # 2. 如果有文件，上传文件
        if article_file:
            if not await self.upload_file(article_file):
                self.logger.error("文件上传失败，工作流终止。")
                return None
        
        # 3. 发送提示词
        if not await self.send_prompt(prompt):
            return None

        # 4. 等待生成完成
        if not await self.wait_for_generation_to_complete():
            return None

        # 5. 获取最终响应
        return await self.get_latest_response()

    async def continue_generation(self, prompt: str) -> Optional[str]:
        """
        继续生成内容
        """
        self.logger.info(f"--- 开始Poe继续生成工作流 ---")
        
        # 1. 发送提示词
        if not await self.send_prompt(prompt):
            return None

        # 2. 等待生成完成
        if not await self.wait_for_generation_to_complete():
            return None

        # 3. 获取最终响应
        return await self.get_latest_response()

    def save_content(self, markdown_content: str, output_file: str) -> bool:
        """保存内容到文件"""
        self.logger.info(f"正在保存内容到: {output_file}")
        try:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            self.logger.info("内容保存成功。")
            return True
        except Exception as e:
            self.logger.error(f"保存文件失败: {e}", exc_info=True)
            return False

    async def compose_article(self, title: str, attachment_path: Optional[str] = None, 
                            min_words: int = 800, prompt: str = '', continue_prompt: str = '') -> Optional[str]:
        """
        完整的文章创作流程，包括上传附件、发送提示、等待生成、检查字数、继续生成等
        """
        self.logger.info(f"开始为标题 '{title}' 创作文章...")
        
        try:
            # 1. 导航到POE
            if not await self.navigate_to_poe():
                self.logger.error("导航到POE失败")
                return None
            
            # 2. 上传附件（如果有）
            if attachment_path:
                if os.path.exists(attachment_path):
                    self.logger.info(f"开始上传附件: {attachment_path}")
                    if not await self.upload_file(attachment_path):
                        self.logger.warning("附件上传失败，继续进行文章创作")
                    else:
                        self.logger.info("附件上传成功")
                else:
                    self.logger.warning(f"附件文件不存在: {attachment_path}")
            
            # 3. 构建提示词：直接使用用户提示词 + 标题
            if prompt:
                full_prompt = f"{prompt} 标题：{title}"
            else:
                full_prompt = f"请写一篇文章，标题：{title}"
            
            # 4. 发送提示词并生成内容
            if not await self.send_prompt(full_prompt):
                self.logger.error("发送提示词失败")
                return None
            
            if not await self.wait_for_generation_to_complete():
                self.logger.error("等待生成完成失败")
                return None
            
            # 5. 获取生成的内容
            content = await self.get_latest_response()
            if not content:
                self.logger.error("获取生成内容失败")
                return None
            
            # 6. 检查字数，如果不够则继续生成
            word_count = len(content.replace(' ', '').replace('\n', ''))
            self.logger.info(f"初次生成内容字数: {word_count}")
            
            if word_count < min_words and continue_prompt:
                self.logger.info(f"字数不足{min_words}字，开始继续生成...")
                
                # 发送继续生成的提示
                continue_full_prompt = continue_prompt or f"请继续完善上述内容，确保文章达到{min_words}字以上。"
                
                if not await self.send_prompt(continue_full_prompt):
                    self.logger.warning("发送继续生成提示失败，返回当前内容")
                    return content
                
                if not await self.wait_for_generation_to_complete():
                    self.logger.warning("等待继续生成完成失败，返回当前内容")
                    return content
                
                # 获取继续生成的内容
                additional_content = await self.get_latest_response()
                if additional_content:
                    # 合并内容
                    content = content + "\n\n" + additional_content
                    final_word_count = len(content.replace(' ', '').replace('\n', ''))
                    self.logger.info(f"继续生成后总字数: {final_word_count}")
            
            final_word_count = len(content.replace(' ', '').replace('\n', ''))
            self.logger.info(f"文章创作完成，最终字数: {final_word_count}")
            return content
            
        except Exception as e:
            self.logger.error(f"文章创作过程中出现错误: {e}", exc_info=True)
            return None

    async def cleanup(self):
        """执行清理操作"""
        self.logger.info("PoeAutomator正在执行清理操作...")
        if self.browser_manager:
            try:
                await self.browser_manager.cleanup()
            except Exception as e:
                self.logger.warning(f"浏览器清理时出现警告（可忽略）: {e}")
                # EPIPE等错误是正常的清理过程，不应该抛出异常 