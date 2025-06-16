import os
import time
import json
import logging
from typing import Optional, Any
import copy

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

    def navigate_to_monica(self) -> bool:
        """导航到Monica页面并等待聊天输入框加载"""
        self.logger.info(f"导航到Monica页面: {self.model_url}")
        self.browser_manager.navigate(self.model_url)
        
        if not self.chat_input_selector:
            self.logger.error("无法获取聊天输入框选择器，初始化失败。")
            return False

        self.logger.info("等待聊天输入框出现...")
        if self.browser_manager.wait_for_element_by_xpath(
            self.chat_input_selector, timeout=self.timeouts.get('navigation', 30)
        ):
            self.logger.info("成功导航到Monica页面并找到聊天输入框。")
            return True
        else:
            self.logger.error("导航后未能找到聊天输入框，页面可能未正确加载。")
            return False

    def send_prompt(self, prompt: str) -> bool:
        """
        输入提示并发送。
        """
        if not self.chat_input_selector or not self.send_button_selector:
            self.logger.error("配置中缺少'chat_input_selector'或'send_button_selector'。")
            return False

        self.logger.info("正在输入提示...")
        
        # 首先尝试使用新的JavaScript输入方法
        input_success = self.browser_manager.input_text_by_xpath_js(
            self.chat_input_selector, prompt
        )
        
        # 如果JavaScript方法失败，回退到原来的方法
        if not input_success:
            self.logger.warning("JavaScript输入方法失败，回退到传统方法...")
            input_success = self.browser_manager.focus_and_type_text(
                self.chat_input_selector, prompt, clear_first=True
            )

        if not input_success:
            self.logger.error("输入提示文本失败。")
            return False

        self.logger.info("提示输入成功，准备通过模拟回车键发送。")

        press_enter_success = self.browser_manager.press_enter_on_xpath(self.chat_input_selector)

        if not press_enter_success:
            self.logger.error("模拟回车键失败。")
            return False

        self.logger.info("提示已成功发送。")
        return True

    def get_response(self) -> Optional[str]:
        """
        获取并返回生成的响应文本。
        """
        if not self.response_container_selector:
            self.logger.error("响应容器选择器未初始化。")
            return None
        
        self.logger.info("正在等待并获取最终响应...")
        
        try:
            self.browser_manager.wait_for_element_by_xpath(self.response_container_selector, timeout=self.timeouts.get('response', 60))
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
        
        response_text = self.browser_manager.execute_script(js_script)
        
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

    def wait_for_generation_to_complete(self) -> bool:
        """等待内容生成完成（通过检测停止按钮是否消失）。"""
        if not self.stop_generating_button_selector:
            self.logger.error("未找到停止按钮选择器，无法判断生成状态。")
            return False

        timeout = self.timeouts.get('generation', 120)
        self.logger.info(f"等待'停止生成'按钮出现 (最长 {timeout} 秒)...")
        
        appeared = self.browser_manager.wait_for_element_by_xpath(self.stop_generating_button_selector, timeout=20)
        if not appeared:
            self.logger.warning("'停止生成'按钮在20秒内未出现，可能生成已瞬间完成或未开始。将直接认为生成已结束。")
            return True

        self.logger.info("'停止生成'按钮已出现，现在等待它消失...")
        
        disappeared = self.browser_manager.wait_for_element_to_disappear_by_xpath(self.stop_generating_button_selector, timeout=timeout)
        if disappeared:
            self.logger.info("'停止生成'按钮已消失，内容生成完毕。")
            return True
        else:
            self.logger.error(f"'停止生成'按钮在 {timeout} 秒后仍未消失。")
            return False

    def save_response_to_file(self, response: str, output_path: str):
        """将响应保存到文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(response)
            self.logger.info(f"响应已成功保存到: {output_path}")
        except Exception as e:
            self.logger.error(f"保存响应到文件时出错: {e}")
            
    def generate_content(self, prompt: str, article_file: Optional[str] = None) -> Optional[str]:
        """
        执行完整的Monica文章生成工作流。
        这是被 WorkflowManager 调用的主入口方法。
        """
        self.logger.info("--- 开始Monica内容生成工作流 ---")
        
        if not self.navigate_to_monica():
            self.logger.error("导航失败，工作流终止。")
            return None

        # 文件上传步骤 (当前逻辑是跳过，因为没有直接的文件上传input)
        if article_file:
            self.logger.info(f"接收到文件 '{article_file}'，但当前实现中将跳过上传步骤。")
            # if not self.upload_file(article_file):
            #     return None
        
        # 记录即将发送的提示词（用于调试）
        self.logger.info(f"准备发送的提示词长度: {len(prompt)} 字符")
        self.logger.info(f"提示词前200字符: {prompt[:200]}...")
        
        # 发送主提示词
        if not self.send_prompt(prompt):
            self.logger.error("发送提示失败，工作流终止。")
            return None
            
        # 等待生成完成
        if not self.wait_for_generation_to_complete():
            self.logger.error("等待生成完成失败，工作流终止。")
            return None
            
        # 获取最终的响应
        self.logger.info("工作流完成，正在获取最终响应。")
        response = self.get_response()
        
        # 返回的是HTML或文本，WorkflowManager会处理后续的保存
        return response

    def continue_generation(self, continue_prompt: str) -> Optional[str]:
        """
        继续生成内容（用于字数不足时的二次创作）
        """
        self.logger.info("--- 开始Monica继续生成工作流 ---")
        
        # 发送继续提示词
        if not self.send_prompt(continue_prompt):
            self.logger.error("发送继续提示失败。")
            return None
            
        # 等待生成完成
        if not self.wait_for_generation_to_complete():
            self.logger.error("等待继续生成完成失败。")
            return None
            
        # 获取最终的响应
        response = self.get_response()
        self.logger.info("继续生成完成。")
        
        return response

    # --- 文件上传相关方法 (当前未使用) ---
    def upload_file(self, file_path: str) -> bool:
        if not os.path.exists(file_path):
            self.logger.error(f"文件不存在，无法上传: {file_path}")
            return False

        upload_button_selector = self._get_selector('upload_button')
        if not upload_button_selector:
            return False

        self.logger.info(f"尝试上传文件: {file_path}")
        
        # 此处需要一个能够在headless模式下工作的、不依赖原生文件选择对话框的上传方法
        # 这通常需要执行JS来创建一个隐藏的<input type="file">元素或使用网站提供的JS接口
        # 以下是一个示例性的JS注入，需要根据实际情况调整
        
        # 读取文件内容为base64
        try:
            with open(file_path, 'rb') as f:
                file_content_base64 = base64.b64encode(f.read()).decode('utf-8')
            file_name = os.path.basename(file_path)
        except Exception as e:
            self.logger.error(f"读取文件内容为Base64时出错: {e}")
            return False

        # JS注入来处理文件
        js_script = f"""
        async function(base64Content, fileName) {{
            try {{
                // Base64 to Blob
                const res = await fetch(`data:application/octet-stream;base64,${{base64Content}}`);
                const blob = await res.blob();
                
                // Create a File object
                const file = new File([blob], fileName, {{ type: blob.type }});

                // Create a DataTransfer object and add the file
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);

                // Find the target element to dispatch the drop event
                // This might be the document, body, or a specific drop zone
                const dropZone = document.body; // Or a more specific element

                // Create and dispatch the drop event
                const dropEvent = new DragEvent('drop', {{
                    dataTransfer: dataTransfer,
                    bubbles: true,
                    cancelable: true
                }});
                dropZone.dispatchEvent(dropEvent);
                
                return {{ success: true }};
            }} catch (e) {{
                return {{ success: false, error: e.toString() }};
            }}
        }}
        """
        
        try:
            result = self.browser_manager.execute_async_script(js_script, file_content_base64, file_name)
            if result and result.get('success'):
                self.logger.info("JS文件上传脚本执行成功。")
                return True
            else:
                error_msg = result.get('error', '未知JS错误') if result else "JS脚本未返回结果"
                self.logger.error(f"JS文件上传脚本执行失败: {error_msg}")
                return False
        except Exception as e:
            self.logger.error(f"执行JS文件上传脚本时发生Python异常: {e}")
            return False

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

    def cleanup(self):
        """执行清理操作"""
        self.logger.info("MonicaAutomator执行清理操作...")
        # 当前没有需要特别清理的资源
        pass 

    def close(self):
        self.logger.info("MonicaAutomator执行清理操作...")
        # 当前没有需要特别清理的资源
        pass 

    def run_automation(self, title: str, article: str, output_path: str) -> bool:
        """执行完整的Monica自动化流程"""
        try:
            self.logger.info("开始Monica自动化流程...")
            if not self.navigate_to_monica():
                return False

            prompt = f"{article}\n\n主题：{title}"
            
            self.logger.info("第二步：发送提示...")
            if not self.send_prompt(prompt):
                self.logger.error("发送提示失败。")
                return False
            self.logger.info("提示发送成功。")

            self.logger.info("第三步：等待内容生成完成...")
            if not self.wait_for_generation_to_complete():
                self.logger.error("等待生成完成时超时或失败。")
                return False
            self.logger.info("内容生成完成。")

            self.logger.info("第四步：获取并保存响应...")
            response = self.get_response()
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
            self.close()