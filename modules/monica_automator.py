import os
import time
import json
import logging
from typing import Optional, Any
import copy
import asyncio
from playwright.async_api import async_playwright, Playwright

from .browser_manager import BrowserManager

def deep_merge(source: dict, destination: dict) -> dict:
    """
    深度合并两个字典。
    """
    for key, value in source.items():
        if isinstance(value, dict):
            # 获取节点，如果不存在则创建
            node = destination.setdefault(key, {})
            deep_merge(value, node)
        else:
            destination[key] = value
    return destination

class MonicaAutomator:
    """基于Chrome DevTools Protocol的Monica自动化器"""

    def __init__(self, gui_config: dict, browser_manager: BrowserManager, model_url: str):
        self.browser_manager = browser_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # --- 正确的配置加载逻辑 ---
        # 1. 首先加载基础配置文件，这里面包含了 selectors
        config = self._load_config('monica_config.json')
        
        # 2. 然后，用从GUI传来的配置去更新基础配置。
        #    这样可以覆盖 model_url 等顶层键，但不会破坏深层的 selectors 字典。
        config.update(gui_config)
        self.config = config
        
        # 3. 在这里设置最终的 model_url
        self.model_url = self.config.get('model_url', model_url) # 优先使用合并后的配置，否则用传入的

        # 4. 从合并后的最终配置中安全地提取 selectors
        self.selectors = self.config.get('selectors', {})
        if not self.selectors:
            self.logger.error("最终配置中缺少 'selectors' 部分或加载失败。")

        # 提取常用配置项
        self.timeouts = self.config.get('timeouts', {})
        
        # 预加载选择器，这些方法现在会从 self.selectors 中正确读取
        self.chat_input_selector = self._get_selector('chat_input')
        self.send_button_selector = self._get_selector('send_button')
        self.upload_button_selector = self._get_selector('upload_button')
        self.stop_generating_button_selector = self._get_selector('stop_button')
        self.response_container_selector = self._get_selector('last_response')

        self.logger.info(f"Monica自动化器初始化完成，目标URL: {self.model_url}")
        self.logger.info(f"聊天输入框选择器: {self.chat_input_selector}")
        self.logger.info(f"发送按钮选择器: {self.send_button_selector}")
        self.logger.info(f"停止按钮选择器: {self.stop_generating_button_selector}")
        self.logger.info(f"响应容器选择器: {self.response_container_selector}")

    def _setup_logging(self):
        """设置日志记录器"""
        logger = logging.getLogger('MonicaAutomator')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _load_config(self, config_path: str) -> dict:
        """从JSON文件加载配置"""
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            self.logger.warning(f"配置文件 {config_path} 不存在，将使用默认或GUI传入的配置。")
        except Exception as e:
            self.logger.error(f"加载配置文件 {config_path} 时发生未知错误: {e}")
        return {}
    
    def _get_selector(self, key: str) -> Optional[str]:
        """从 self.selectors 安全地获取XPath"""
        try:
            # 修复：正确访问嵌套的配置结构
            chat_selectors = self.selectors.get('chat', {})
            return chat_selectors.get(key)
        except Exception as e:
            self.logger.error(f"获取选择器 '{key}' 时出错: {e}")
            return None

    async def navigate_to_monica(self) -> bool:
        """导航到Monica页面并等待聊天输入框加载"""
        self.logger.info(f"导航到Monica页面: {self.model_url}")
        await self.browser_manager.navigate(self.model_url)
        
        if not self.chat_input_selector:
            self.logger.error("无法获取聊天输入框选择器，初始化失败。")
            return False

        self.logger.info("等待聊天输入框出现...")
        element = await self.browser_manager.find_element(
            self.chat_input_selector, timeout=self.timeouts.get('navigation', 30)
        )
        if element:
            self.logger.info("成功导航到Monica页面并找到聊天输入框。")
            return True
        else:
            self.logger.error("导航后未能找到聊天输入框，页面可能未正确加载。")
            return False

    async def send_prompt(self, prompt: str) -> bool:
        """
        输入提示并发送。
        """
        if not self.chat_input_selector:
            self.logger.error("配置中缺少'chat_input_selector'。")
            return False

        self.logger.info("正在输入提示...")
        
        # 使用精简后的BrowserManager方法
        input_success = await self.browser_manager.focus_and_type_text(
            self.chat_input_selector, prompt, clear_first=True
        )

        if not input_success:
            self.logger.error("输入提示文本失败。")
            return False

        self.logger.info("提示输入成功，准备通过模拟回车键发送。")
        
        # 直接在找到的元素上按回车
        input_element = await self.browser_manager.find_element(self.chat_input_selector)
        if not input_element:
            self.logger.error("无法重新定位输入框以按回车。")
            return False

        await input_element.press('Enter')
        self.logger.info("提示已成功发送。")
        return True

    async def get_response(self) -> Optional[str]:
        """
        获取并返回生成的响应文本。
        """
        if not self.response_container_selector:
            self.logger.error("响应容器选择器未初始化。")
            return None
        
        self.logger.info("正在等待并获取最终响应...")
        
        try:
            # 直接等待元素出现
            response_element = await self.browser_manager.find_element(
                self.response_container_selector, 
                timeout=self.timeouts.get('response', 60)
            )
            if not response_element:
                self.logger.error("等待响应容器超时。")
                return None
        except Exception as e:
            self.logger.error(f"等待响应容器时出错: {e}")
            return None

        # 转义选择器中的引号，避免JavaScript语法错误
        escaped_selector = self.response_container_selector.replace('"', '\\"').replace("'", "\\'")
        
        js_script = f"""
        (function() {{
            try {{
                var xpath = "{escaped_selector}";
                var allResponses = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                if (allResponses.snapshotLength > 0) {{
                    var lastResponse = allResponses.snapshotItem(allResponses.snapshotLength - 1);
                    // 优先获取innerHTML以保留格式，如果失败则获取纯文本
                    return lastResponse.innerHTML || lastResponse.innerText || lastResponse.textContent || '';
                }}
                return null;
            }} catch (error) {{
                console.error('获取响应时出错:', error);
                return null;
            }}
        }})()
        """
        
        response_text = await self.browser_manager.execute_script(js_script)
        
        if response_text:
            self.logger.info(f"成功提取响应内容，长度: {len(response_text)} 字符")
            # 如果获取到的是HTML内容，记录一下
            if '<' in response_text and '>' in response_text:
                self.logger.info("获取到HTML格式的响应内容")
            else:
                self.logger.info("获取到纯文本格式的响应内容")
            return response_text
        else:
            self.logger.error("未能提取响应文本。")
            return None

    async def wait_for_generation_to_complete(self) -> bool:
        """等待内容生成完成（通过检测停止按钮是否消失）。"""
        if not self.stop_generating_button_selector:
            self.logger.error("未找到停止按钮选择器，无法判断生成状态。")
            return False

        timeout = self.timeouts.get('generation', 120) * 1000  # 转换为毫秒
        self.logger.info(f"等待'停止生成'按钮出现 (最长 {timeout / 1000} 秒)...")
        
        stop_button = await self.browser_manager.find_element(self.stop_generating_button_selector, timeout=20)
        
        if not stop_button:
            self.logger.warning("'停止生成'按钮在20秒内未出现，可能生成已瞬间完成或未开始。将直接认为生成已结束。")
            return True

        self.logger.info("'停止生成'按钮已出现，现在等待它消失...")
        
        try:
            await stop_button.wait_for(state='hidden', timeout=timeout)
            self.logger.info("'停止生成'按钮已消失，内容生成完毕。")
            return True
        except Exception:
            self.logger.error(f"'停止生成'按钮在 {timeout / 1000} 秒后仍未消失。")
            return False

    def save_response_to_file(self, response: str, output_path: str):
        """将响应保存到文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(response)
            self.logger.info(f"响应已成功保存到: {output_path}")
        except Exception as e:
            self.logger.error(f"保存响应到文件时出错: {e}")
            
    async def generate_content(self, prompt: str, article_file: Optional[str] = None) -> Optional[str]:
        """
        执行完整的Monica文章生成工作流。
        这是被 WorkflowManager 调用的主入口方法。
        """
        self.logger.info("--- 开始Monica内容生成工作流 ---")
        
        if not await self.navigate_to_monica():
            self.logger.error("导航失败，工作流终止。")
            return None

        # 文件上传步骤
        if article_file:
            self.logger.info(f"接收到文件 '{article_file}'，正在尝试上传...")
            if await self.upload_file(article_file):
                self.logger.info("✅ 文件上传成功，等待文件处理完成...")
                # 等待文件上传和处理完成
                await asyncio.sleep(3)
                
                # 再次检查文件是否真的上传成功
                file_name = os.path.basename(article_file)
                check_script = f"""
                    (function() {{
                        try {{
                            var pageText = document.body.textContent || '';
                            return pageText.includes('{file_name}');
                        }} catch (error) {{
                            console.log('❌ 检查文件状态出错: ' + error.message);
                            return false;
                        }}
                    }})()
                """
                
                file_confirmed = await self.browser_manager.execute_script(check_script)
                if file_confirmed:
                    self.logger.info("✅ 文件上传确认成功，可以继续发送提示词")
                else:
                    self.logger.warning("⚠️ 文件上传状态不确定，但继续执行")
            else:
                self.logger.warning("⚠️ 文件上传失败，但继续执行工作流...")
                # 不返回None，允许工作流继续
        
        # 记录即将发送的提示词（用于调试）
        self.logger.info(f"准备发送的提示词长度: {len(prompt)} 字符")
        self.logger.info(f"提示词前200字符: {prompt[:200]}...")
        
        # 发送主提示词
        if not await self.send_prompt(prompt):
            self.logger.error("发送提示失败，工作流终止。")
            return None
            
        # 等待生成完成
        if not await self.wait_for_generation_to_complete():
            self.logger.error("等待生成完成失败，工作流终止。")
            return None
            
        # 获取最终的响应
        self.logger.info("工作流完成，正在获取最终响应。")
        response = await self.get_response()
        
        # 返回的是HTML或文本，WorkflowManager会处理后续的保存
        return response

    async def continue_generation(self, continue_prompt: str) -> Optional[str]:
        """
        继续生成内容（用于字数不足时的二次创作）
        """
        self.logger.info("--- 开始Monica继续生成工作流 ---")
        
        # 发送继续提示词
        if not await self.send_prompt(continue_prompt):
            self.logger.error("发送继续提示失败。")
            return None
            
        # 等待生成完成
        if not await self.wait_for_generation_to_complete():
            self.logger.error("等待继续生成完成失败。")
            return None
            
        # 获取最终的响应
        response = await self.get_response()
        self.logger.info("继续生成完成。")
        
        return response

    # --- 文件上传相关方法 ---
    async def upload_file(self, file_path: str) -> bool:
        """使用新的BrowserManager方法上传文件。"""
        absolute_path = os.path.abspath(file_path)
        if not os.path.exists(absolute_path):
            self.logger.error(f"文件不存在，无法上传: {absolute_path}")
            return False

        if not self.upload_button_selector:
            self.logger.error("配置中缺少 'upload_button' 选择器。")
            return False

        self.logger.info(f"📁 开始上传文件: {file_path}")
        self.logger.info(f"使用上传按钮选择器: {self.upload_button_selector}")

        # 直接调用新的、职责明确的方法
        return await self.browser_manager.upload_file_with_dialog(
            self.upload_button_selector, absolute_path
        )

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
            # 1. 导航到Monica
            if not await self.navigate_to_monica():
                self.logger.error("导航到Monica失败")
                return None
            
            # 2. 上传附件（如果有）
            if attachment_path:
                if os.path.exists(attachment_path):
                    self.logger.info(f"开始上传附件: {attachment_path}")
                    if not await self.upload_file(attachment_path):
                        self.logger.warning("附件上传失败，继续进行文章创作")
                    else:
                        self.logger.info("附件上传成功")
                        # 等待文件处理完成
                        await asyncio.sleep(3)
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
            content = await self.get_response()
            if not content:
                self.logger.error("获取生成内容失败")
                return None
            
            # 6. 将HTML转换为Markdown（如果需要）
            if '<' in content and '>' in content:
                # 看起来是HTML，转换为Markdown
                from markdownify import markdownify as md
                content = md(content, heading_style="ATX")
                # 清理多余的空行
                import re
                content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
                content = content.strip()
            
            # 7. 检查字数，如果不够则继续生成
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
                additional_content = await self.get_response()
                if additional_content:
                    # 将HTML转换为Markdown（如果需要）
                    if '<' in additional_content and '>' in additional_content:
                        additional_content = md(additional_content, heading_style="ATX")
                        additional_content = re.sub(r'\n\s*\n\s*\n', '\n\n', additional_content)
                        additional_content = additional_content.strip()
                    
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
        self.logger.info("MonicaAutomator执行清理操作...")
        if self.browser_manager:
            await self.browser_manager.cleanup()

    async def run_automation(self, title: str, article: str, output_path: str) -> bool:
        """执行完整的Monica自动化流程"""
        try:
            self.logger.info("开始Monica自动化流程...")
            if not await self.navigate_to_monica():
                return False

            prompt = f"{article}\n\n主题：{title}"
            
            self.logger.info("第二步：发送提示...")
            if not await self.send_prompt(prompt):
                self.logger.error("发送提示失败。")
                return False
            self.logger.info("提示发送成功。")

            self.logger.info("第三步：等待内容生成完成...")
            if not await self.wait_for_generation_to_complete():
                self.logger.error("等待生成完成时超时或失败。")
                return False
            self.logger.info("内容生成完成。")

            self.logger.info("第四步：获取并保存响应...")
            response = await self.get_response()
            if response:
                self.save_response_to_file(response, output_path)
                self.logger.info(f"成功获取响应并保存到 {output_path}")
                return True
            else:
                self.logger.error("获取响应失败。")
                return False

        except Exception as e:
            self.logger.error(f"Monica自动化流程发生未预料的错误: {e}", exc_info=True)
            return False
        finally:
            await self.cleanup()