import os
import time
import json
import logging
from typing import Optional

from .browser_manager import BrowserManager


class PoeAutomator:
    """基于Chrome DevTools Protocol的POE自动化器"""

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

    def navigate_to_poe(self) -> bool:
        """导航到在初始化时指定的模型URL"""
        try:
            self.logger.info(f"导航到: {self.model_url}")
            if not self.browser_manager.navigate_to(self.model_url):
                raise ConnectionError("浏览器导航失败")
            
            self.browser_manager.close_other_tabs()
            time.sleep(3)
            
            chat_input_selector = self._get_selector('chat_input')
            if not chat_input_selector or not self.browser_manager.wait_for_element(
                chat_input_selector, self.timeouts.get('page_load', 30)
            ):
                self.logger.error("导航后未能找到聊天输入框，页面可能未正确加载。")
                return False

            self.logger.info("成功导航到POE页面并找到聊天输入框。")
            return True
        except Exception as e:
            self.logger.error(f"导航到POE失败: {e}")
            return False

    def upload_file(self, file_path: str) -> bool:
        """
        直接为隐藏的input元素设置文件路径，绕过点击按钮。
        """
        self.logger.info(f"开始直接上传文件: {file_path}")
        if not os.path.exists(file_path):
            self.logger.error(f"素材文件不存在: {file_path}")
            return False

        try:
            file_input_selector = self._get_selector('file_input')
            if not file_input_selector:
                return False

            # 直接调用set_input_files，不再点击上传按钮
            self.logger.info(f"正在直接为选择器 '{file_input_selector}' 设置文件...")
            if not self.browser_manager.set_input_files(file_input_selector, file_path):
                self.logger.error(f"使用set_input_files方法上传文件 '{file_path}' 失败。")
                return False

            self.logger.info(f"文件上传操作已提交: {file_path}")
            # 使用一个合理的短等待时间，而不是从配置中读取可能很长的值
            time.sleep(3)
            return True
        except Exception as e:
            self.logger.error(f"上传文件时出现异常: {e}", exc_info=True)
            return False

    def send_prompt(self, prompt: str) -> bool:
        """在文本框中输入提示并点击发送。"""
        self.logger.info("开始发送提示...")
        try:
            chat_input_selector = self._get_selector('chat_input')
            send_button_selector = self._get_selector('send_button')
            if not chat_input_selector or not send_button_selector:
                return False

            self.logger.info("正在输入提示文本...")
            element = self.browser_manager.find_element(chat_input_selector)
            if not element:
                 self.logger.error(f"找不到聊天输入框: {chat_input_selector}")
                 return False
            
            # 使用 type_text 进行输入，这里假设 browser_manager 有一个可以处理 xpath 的输入方法
            # 如果没有，我们需要依赖JS注入
            # 为了修复之前的语法错误，我们暂时使用一个更简单但可能较慢的方法
            # self.browser_manager.type_text(element, prompt) 
            # 鉴于 browser_manager 的 type_text 可能不兼容 xpath, 我们还是用JS，但保证语法正确

            escaped_prompt = json.dumps(prompt)
            # f-string的表达式部分不能包含反斜杠，所以我们先把替换操作拿出来
            escaped_selector = chat_input_selector.replace('"', '\\"')
            js_code = f"""
            var ta = document.evaluate("{escaped_selector}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (ta) {{
                ta.value = {escaped_prompt};
                ta.dispatchEvent(new Event('input', {{'bubbles': true}}));
                ta.focus();
            }}
            """
            self.browser_manager.execute_script(js_code)
            
            # 删除不必要的等待，实现即时发送
            # time.sleep(1)

            self.logger.info(f"正在点击发送按钮: {send_button_selector}")
            if not self.browser_manager.click_element_by_xpath(send_button_selector):
                self.logger.error("点击发送按钮失败。")
                return False

            self.logger.info("提示已成功发送。")
            return True
        except Exception as e:
            self.logger.error(f"发送提示时出现异常: {e}", exc_info=True)
            return False

    def wait_for_generation_to_complete(self) -> bool:
        """等待内容生成完成。"""
        self.logger.info("等待内容生成完成...")
        try:
            stop_button_selector = self._get_selector('stop_button')
            if not stop_button_selector:
                return False
            
            timeout = self.timeouts.get('ai_response_wait', 300)
            check_interval = self.timeouts.get('typing_check_interval', 3)

            self.logger.info("等待'停止'按钮出现...")
            start_time = time.time()
            stop_button_found = False
            while time.time() - start_time < timeout:
                if self.browser_manager.is_element_present(stop_button_selector):
                    self.logger.info("'停止'按钮已出现，内容正在生成中。")
                    stop_button_found = True
                    break
                time.sleep(check_interval)
            
            if not stop_button_found:
                self.logger.warning("在超时时间内未检测到'停止'按钮，可能已秒速生成或未开始生成。继续后续步骤。")
                return True

            self.logger.info("等待'停止'按钮消失...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not self.browser_manager.is_element_present(stop_button_selector):
                    self.logger.info("'停止'按钮已消失，内容生成完成。")
                    time.sleep(2)
                    return True
                time.sleep(check_interval)

            self.logger.error("超时！'停止'按钮长时间未消失，生成可能已卡住。")
            return False
        except Exception as e:
            self.logger.error(f"等待生成完成时出现异常: {e}", exc_info=True)
            return False

    def get_latest_response(self) -> Optional[str]:
        """
        获取最后一条由机器人生成的消息的HTML内容。
        """
        self.logger.info("正在获取最新生成的内容 (HTML)...")
        try:
            response_selector = self._get_selector('last_response')
            if not response_selector:
                return None

            # 修正f-string错误：将替换操作移到f-string外部
            escaped_selector = response_selector.replace('"', '\\"')
            js_script = f"""
            (function() {{
                var element = document.evaluate("{escaped_selector}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                return element ? element.innerHTML : null;
            }})()
            """
            
            for _ in range(3):
                html_content = self.browser_manager.execute_script(js_script)
                if html_content and html_content.strip():
                    self.logger.info(f"成功获取到HTML内容，长度为 {len(html_content)}。")
                    return html_content
                time.sleep(1)

            self.logger.error(f"未能获取到最新回复的HTML内容，选择器: {response_selector}")
            return None
        except Exception as e:
            self.logger.error(f"获取最新回复时出现异常: {e}", exc_info=True)
            return None

    def generate_content(self, prompt: str, article_file: Optional[str] = None) -> Optional[str]:
        """
        执行完整的Poe文章生成工作流。
        现在接收prompt作为参数，并且article_file是可选的。
        """
        self.logger.info(f"--- 开始Poe内容生成工作流 ---")
        self.logger.info(f"提示: {prompt}")

        if not self.navigate_to_poe():
            return None

        # 如果提供了文章路径，则执行上传
        if article_file and os.path.exists(article_file):
            self.logger.info(f"素材文件: {article_file}")
            if not self.upload_file(article_file):
                # 上传失败是一个严重问题，应该中止
                self.logger.error("文章上传失败，中止本次任务。")
                return None
        else:
            self.logger.info("未提供文章附件或文件不存在，将直接根据提示进行创作。")
            
        if not self.send_prompt(prompt):
            return None

        if not self.wait_for_generation_to_complete():
            return None

        content = self.get_latest_response()
        
        if content:
            self.logger.info("--- Poe内容生成工作流成功结束 ---")
        else:
            self.logger.error("--- Poe内容生成工作流结束，但未能获取到内容 ---")
            
        return content

    def continue_generation(self, prompt: str) -> Optional[str]:
        """
        用于在已有对话中继续生成内容（二次创作）。
        """
        self.logger.info("--- 开始二次创作 ---")
        self.logger.info(f"二次创作提示: {prompt}")

        if not self.send_prompt(prompt):
            return None

        if not self.wait_for_generation_to_complete():
            return None
        
        content = self.get_latest_response()
        if content:
            self.logger.info("--- 二次创作成功结束 ---")
        else:
            self.logger.error("--- 二次创作结束，但未能获取到内容 ---")
        
        return content

    def save_content(self, markdown_content: str, output_file: str) -> bool:
        """将最终的Markdown内容保存到指定文件。"""
        if not markdown_content:
            self.logger.error("没有内容可保存。")
            return False
        try:
            output_dir = os.path.dirname(output_file)
            os.makedirs(output_dir, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            self.logger.info(f"内容已成功保存到: {output_file}")
            return True
        except Exception as e:
            self.logger.error(f"保存Markdown内容时出错: {e}", exc_info=True)
            return False

    def cleanup(self):
        """清理资源（如果需要）"""
        self.logger.info("PoeAutomator清理完成。") 