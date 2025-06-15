import os
import time
import json
import logging
import re
from typing import Optional, Dict, Any
from .browser_manager import BrowserManager


class PoeAutomator:
    """基于Chrome DevTools Protocol的POE自动化器"""
    
    def __init__(self, gui_config, browser_manager):
        self.browser_manager = browser_manager
        self.setup_logging()
        
        # 加载模块自身的配置文件，并与GUI传入的配置合并
        local_config = self.load_config('poe_config.json')
        local_config.update(gui_config)
        self.config = local_config
        
        self.logger.info("POE自动化器初始化完成")
    
    def setup_logging(self):
        """设置日志配置"""
        self.logger = logging.getLogger('modules.poe_automator')
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def load_config(self, config_file):
        """加载配置文件"""
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.logger.info(f"已加载配置文件: {config_file}")
                return config
            else:
                # 创建默认配置
                default_config = {
                    "selectors": {
                        "chat_input": "textarea[placeholder*='Talk']",
                        "send_button": "button[data-testid='send-button']",
                        "file_upload": "input[type='file']",
                        "attach_button": "button[aria-label*='attach']",
                        "message_container": "[class*='Message']",
                        "bot_message": "[class*='bot'] [class*='markdown']",
                        "login_button": "button[data-testid='loginButton']",
                        "model_selector": "[data-testid='model-selector']"
                    },
                    "timeouts": {
                        "page_load": 30,
                        "element_wait": 15,
                        "message_wait": 60,
                        "upload_wait": 30
                    },
                    "retry": {
                        "max_attempts": 3,
                        "delay": 2
                    },
                    "content_generation": {
                        "min_words": 800,
                        "check_interval": 5,
                        "max_wait_time": 300
                    }
                }
                
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                
                self.logger.info(f"已创建默认配置文件: {config_file}")
                return default_config
                
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {str(e)}")
            return {}
    
    def navigate_to_poe(self, model_url=None):
        """导航到POE页面"""
        try:
            url = model_url or "https://poe.com/"
            self.browser_manager.navigate_to(url)
            
            # 等待页面加载
            time.sleep(3)
            
            self.logger.info("成功导航到POE页面")
            
            # 清理多余标签页
            all_tabs = self.browser_manager.get_all_tabs()
            if len(all_tabs) > 1:
                self.logger.info(f"发现 {len(all_tabs)} 个标签页，开始清理...")
                current_tab_id = self.browser_manager.current_tab_id
                for i in range(len(all_tabs) - 1, -1, -1):
                    tab_id = all_tabs[i].get('id')
                    if tab_id != current_tab_id:
                        self.browser_manager.close_tab_by_id(tab_id)
                self.logger.info("多余标签页清理完毕。")

            return True
            
        except Exception as e:
            self.logger.error(f"导航到POE失败: {str(e)}")
            return False
    
    def wait_for_chat_ready(self):
        """等待聊天界面准备就绪"""
        try:
            print("🔍 [DEBUG] 等待POE聊天界面准备就绪...")
            
            chat_input_selector = self.config.get('selectors', {}).get('chat_input', 'textarea[placeholder*="Talk"]')
            timeout = self.config.get('timeouts', {}).get('element_wait', 15)
            
            print(f"🔍 [DEBUG] 聊天输入框选择器: {chat_input_selector}")
            print(f"🔍 [DEBUG] 等待超时时间: {timeout}秒")
            
            # 先检查页面上的textarea元素
            try:
                textarea_count = self.browser_manager.execute_script("document.querySelectorAll('textarea').length")
                print(f"🔍 [DEBUG] 页面上textarea元素数量: {textarea_count}")
                
                if textarea_count > 0:
                    textarea_info = self.browser_manager.execute_script("""
                        Array.from(document.querySelectorAll('textarea')).slice(0, 3).map(el => ({
                            placeholder: el.placeholder,
                            className: el.className,
                            id: el.id,
                            visible: el.offsetParent !== null
                        }))
                    """)
                    print(f"🔍 [DEBUG] 前3个textarea信息: {textarea_info}")
            except Exception as e:
                print(f"❌ [DEBUG] 获取textarea信息失败: {e}")
            
            print(f"🔍 [DEBUG] 开始等待聊天输入框...")
            if self.browser_manager.wait_for_element(chat_input_selector, timeout):
                print("✅ [DEBUG] 聊天界面已准备就绪")
                self.logger.info("聊天界面已准备就绪")
                return True
            else:
                print("❌ [DEBUG] 聊天界面未准备就绪")
                self.logger.error("聊天界面未准备就绪")
                return False
                
        except Exception as e:
            print(f"❌ [DEBUG] 等待聊天界面异常: {e}")
            self.logger.error(f"等待聊天界面失败: {str(e)}")
            return False
    
    def upload_file(self, file_path):
        """上传文件 - 根据需求文档优化"""
        try:
            if not os.path.exists(file_path):
                self.logger.error(f"素材文件不存在: {file_path}")
                return False
            
            # 1. 定位上传按钮
            upload_button_xpath = "//button[@data-button-file-input='true']"
            upload_button = self.browser_manager.find_element(upload_button_xpath, timeout=10)
            
            if not upload_button:
                self.logger.error("未找到文件上传按钮。")
                return False

            # 2. 使用 set_input_files 上传文件
            # 这是更可靠的上传方式，它模拟了文件选择对话框
            success = self.browser_manager.set_input_files(
                "//input[@type='file']", # 通常隐藏的文件输入元素
                file_path
            )

            if success:
                self.logger.info(f"文件已提交上传: {file_path}")
                # 等待文件上传完成的视觉提示（例如，文件名出现在输入框附近）
                time.sleep(self.config.get('timeouts', {}).get('upload_wait', 30))
                return True
            else:
                self.logger.error("文件上传失败。")
                return False
                
        except Exception as e:
            self.logger.error(f"上传文件时出现异常: {str(e)}")
            return False
    
    def send_message(self, message):
        """发送消息"""
        try:
            chat_input_selector = self.config.get('selectors', {}).get('chat_input', 'textarea[placeholder*="Talk"]')
            send_button_selector = self.config.get('selectors', {}).get('send_button', 'button[data-testid="send-button"]')
            
            # 清空输入框并输入消息
            clear_script = f"""
            var input = document.querySelector('{chat_input_selector}');
            if (input) {{
                input.focus();
                input.value = '';
                input.dispatchEvent(new Event('input', {{bubbles: true}}));
                true;
            }} else {{
                false;
            }}
            """
            
            if not self.browser_manager.execute_script(clear_script):
                self.logger.error("无法清空输入框")
                return False
            
            # 输入消息
            if not self.browser_manager.type_text(chat_input_selector, message):
                self.logger.error("无法输入消息")
                return False
            
            time.sleep(1)
            
            # 点击发送按钮或按回车
            if self.browser_manager.is_element_visible(send_button_selector):
                if not self.browser_manager.click_element(send_button_selector):
                    self.logger.warning("点击发送按钮失败，尝试按回车键发送。")
                    self.browser_manager.press_key(chat_input_selector, 'Enter')
            else:
                self.logger.info("未找到发送按钮，直接按回车键发送。")
                self.browser_manager.press_key(chat_input_selector, 'Enter')

            self.logger.info("消息已发送")
            return True
                
        except Exception as e:
            self.logger.error(f"发送消息失败: {str(e)}")
            return False
    
    def wait_for_response(self, timeout=None):
        """
        等待AI响应完成。
        通过循环检测"停止"按钮的可见性来判断AI是否仍在生成。
        """
        timeout = timeout or self.config.get('timeouts', {}).get('message_wait', 60)
        check_interval = self.config.get('content_generation', {}).get('check_interval', 5)
        stop_button_xpath = "//button[.//span[text()='停止']]"
        
        start_time = time.time()
        
        self.logger.info("等待AI响应...")
        
        # 初始等待，让AI有时间开始生成
        time.sleep(check_interval)
        
        while time.time() - start_time < timeout:
            is_generating = self.browser_manager.is_element_visible(stop_button_xpath)
            if is_generating:
                self.logger.info("AI仍在生成内容，继续等待...")
                time.sleep(check_interval)
            else:
                self.logger.info("AI响应完成（'停止'按钮不可见）。")
                # 为确保内容完全渲染，再稍作等待
                time.sleep(2)
                return True
        
        self.logger.warning(f"等待AI响应超时（{timeout}秒）。")
        return False
    
    def get_latest_response(self):
        """获取最新的AI回复"""
        try:
            # 使用需求文档中指定的XPath
            response_xpath = "(//*[starts-with(@id, 'message-')]/div[2]/div[2]/div/div[1]/div/div)[last()]"
            
            # 获取HTML内容
            html_content = self.browser_manager.get_element_html(response_xpath)

            if html_content:
                self.logger.info("成功获取最新的AI回复内容。")
                return html_content
            else:
                self.logger.warning("未能获取AI回复内容，可能元素未找到。")
                return None
        except Exception as e:
            self.logger.error(f"获取最新回复失败: {str(e)}")
            return None
    
    def check_content_length(self, content, min_words):
        """检查内容字数"""
        # 简单的字数计算，基于空格和换行
        word_count = len(content.split())
        self.logger.info(f"当前内容字数: {word_count}，最小要求: {min_words}")
        return word_count >= min_words
    
    def generate_content(self, title):
        """
        生成内容的完整流程。
        - 导航到指定模型URL
        - 上传文件（如果存在）
        - 发送提示词
        - 等待响应
        - 检查内容长度并补充
        - 返回最终的HTML内容
        """
        try:
            prompt = self.config.get('prompt', '')
            model_url = self.config.get('model_url', 'https://poe.com')
            min_words = self.config.get('min_word_count', 800)
            supplemental_prompt = self.config.get('continue_prompt', '继续')
            
            # 组合主提示词
            main_prompt = f"{prompt}\n\n标题：{title}"
            
            # 检查是否存在素材文件
            article_file = "article.txt" if os.path.exists("article.txt") else None

            # 1. 导航到指定的模型页面
            if not self.navigate_to_poe(model_url):
                return None
            
            # 2. 等待聊天界面加载完成
            if not self.wait_for_chat_ready():
                self.logger.error("聊天界面未就绪，无法继续。")
                return None
            
            # 3. 如果有素材文件，则上传
            if article_file:
                if not self.upload_file(article_file):
                    self.logger.warning("素材文件上传失败，将仅使用提示词继续。")
            
            # 4. 发送主提示词
            if not self.send_message(main_prompt):
                self.logger.error("发送主提示词失败。")
                return None
            
            # 5. 等待AI响应
            self.wait_for_response()
            
            # 6. 获取响应并检查长度
            response_content = self.get_latest_response()
            if not response_content:
                self.logger.error("未能获取AI响应内容。")
                return None

            # 7. 循环补充内容直到满足最低字数要求
            while not self.check_content_length(response_content, min_words):
                self.logger.info(f"当前字数不足{min_words}，发送补充提示词...")
                if not self.send_message(supplemental_prompt):
                    self.logger.error("发送补充提示词失败，中止内容生成。")
                    break
                
                self.wait_for_response()
                new_content = self.get_latest_response()
                if new_content == response_content: # 如果内容没有变化
                    self.logger.warning("补充内容后响应没有变化，可能已达上限。")
                    break
                response_content = new_content
            
            self.logger.info("内容生成完成。")
            return response_content
            
        except Exception as e:
            self.logger.error(f"内容生成过程中发生严重错误: {e}", exc_info=True)
            return None
    
    def _clean_html_to_markdown(self, html_content):
        """
        一个简单的、零依赖的HTML到Markdown转换器。
        - 移除脚本和样式
        - 转换标题、段落、列表等
        - 剥离其余HTML标签
        """
        if not html_content:
            return ""

        # 1. 移除脚本和样式块
        content = re.sub(r'<(script|style).*?>.*?</\1>', '', html_content, flags=re.DOTALL)

        # 2. 基本的块级元素转换 (在剥离标签前)
        content = re.sub(r'</p>', r'</p>\n', content)
        content = re.sub(r'<br\s*/?>', r'\n', content)
        content = re.sub(r'<h1>(.*?)</h1>', r'# \1\n', content)
        content = re.sub(r'<h2>(.*?)</h2>', r'## \1\n', content)
        content = re.sub(r'<h3>(.*?)</h3>', r'### \1\n', content)
        content = re.sub(r'<li>(.*?)</li>', r'- \1\n', content)

        # 3. 剥离所有剩下的HTML标签
        text_content = re.sub(r'<[^>]+>', '', content)

        # 4. 清理多余的空行
        text_content = re.sub(r'\n\s*\n', '\n\n', text_content).strip()

        return text_content

    def save_content(self, html_content, output_file):
        """将HTML内容转换为Markdown并保存"""
        if not html_content:
            self.logger.error("没有内容可保存。")
            return False
            
        try:
            # 使用内部方法转换
            markdown_content = self._clean_html_to_markdown(html_content)

            # 创建目录（如果不存在）
            output_dir = os.path.dirname(output_file)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            self.logger.info(f"内容已成功保存为Markdown文件: {output_file}")
            return True
        except Exception as e:
            self.logger.error(f"保存内容为Markdown时出错: {str(e)}")
            return False
    
    def cleanup(self):
        """清理资源，关闭浏览器"""
        self.browser_manager.close()
        self.logger.info("浏览器已关闭，清理完成。") 