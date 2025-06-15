import os
import time
import json
import logging
import subprocess
import requests
import websocket
import threading
import psutil
import random
from typing import Optional, Dict, Any, List, Union
import select


class BrowserManager:
    """基于Chrome DevTools Protocol的浏览器管理器"""
    
    def __init__(self, port=9222, headless=False):
        self.ws = None
        self.debug_port = port
        self.chrome_process = None
        # 明确使用项目根目录下的 "write_tool_chrome_profile" 文件夹
        self.profile_dir = os.path.join(os.getcwd(), "write_tool_chrome_profile")
        self._user_data_dir = self.profile_dir
        self.current_tab_id = None
        self.message_id = 0
        self.headless = headless
        
        # 确保配置目录存在
        os.makedirs(self.profile_dir, exist_ok=True)
        
        # 设置日志
        self.logger = logging.getLogger('BrowserManager')
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            # 防止日志向上传播到根日志器
            self.logger.propagate = False
    
    def is_connected(self):
        """检查WebSocket是否仍然连接"""
        return self.ws is not None and self.ws.connected
    
    def _get_next_message_id(self):
        self.message_id += 1
        return self.message_id
    
    def _kill_existing_chrome(self):
        """杀死占用调试端口的Chrome进程"""
        try:
            # 查找占用端口的进程
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                        cmdline = proc.info['cmdline']
                        if cmdline and any(f'--remote-debugging-port={self.debug_port}' in str(arg) for arg in cmdline):
                            self.logger.info(f"杀死占用端口{self.debug_port}的Chrome进程: PID {proc.info['pid']}")
                            proc.kill()
                            time.sleep(2)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.error(f"清理Chrome进程时出错: {e}")
    
    def start_chrome(self):
        """启动Chrome浏览器"""
        try:
            # 先杀死可能存在的Chrome进程
            self._kill_existing_chrome()
            
            chrome_args = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            
            self.logger.info(f"启动Chrome，配置目录: {self.profile_dir}")
            self.chrome_process = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # 等待Chrome启动并立即连接
            time.sleep(3)
            if not self.connect():
                self.logger.error("启动Chrome后未能连接到调试端口。")
                return False

            return True
            
        except Exception as e:
            self.logger.error(f"启动Chrome失败: {e}")
            return False
    
    def connect(self):
        """连接到Chrome"""
        try:
            # if not self.chrome_process:
            #     if not self.start_chrome():
            #         return False
            
            # 获取可用的标签页
            response = requests.get(f"http://localhost:{self.debug_port}/json")
            tabs = response.json()
            
            if not tabs:
                self.logger.error("没有找到可用的标签页")
                return False
            
            # 使用第一个标签页
            tab = tabs[0]
            self.current_tab_id = tab['id']
            ws_url = tab['webSocketDebuggerUrl']
            
            self.logger.info(f"连接到标签页: {ws_url}")
            self.ws = websocket.create_connection(ws_url)
            
            # 启用必要的域
            self._send_command("Runtime.enable")
            self._send_command("Page.enable")
            self._send_command("DOM.enable")
            
            return True
            
        except Exception as e:
            self.logger.error(f"连接Chrome失败: {e}")
            return False
    
    def _ensure_connection(self):
        """确保WebSocket连接存在，如果不存在则尝试重连"""
        if self.ws is None:
            self.logger.warning("WebSocket连接不存在，正在尝试重新连接...")
            if not self.connect():
                self.logger.error("重新连接失败。")
                return False
        return True

    def _send_command(self, method, params=None):
        """发送CDP命令"""
        if not self._ensure_connection():
            return None
        
        message_id = self._get_next_message_id()
        command = {
            "id": message_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            self.ws.send(json.dumps(command))
            
            # 接收响应，增加超时控制
            timeout = 15  # 15秒超时
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                # 检查是否有数据可读
                ready = select.select([self.ws.sock], [], [], 1.0)
                if ready[0]:
                    try:
                        response = self.ws.recv()
                        response_data = json.loads(response)
                        
                        # 检查是否是我们要的响应
                        if response_data.get('id') == message_id:
                            return response_data
                        
                        # 如果不是，可能是事件消息，继续接收
                        self.logger.debug(f"收到事件消息: {response_data.get('method', 'unknown')}")
                        
                    except Exception as e:
                        self.logger.debug(f"接收消息时出错: {e}")
                        break
                else:
                    # 没有数据可读，继续等待
                    continue
            
            self.logger.warning(f"未收到命令 {method} 的响应（超时）")
            return None
            
        except Exception as e:
            self.logger.error(f"发送命令失败: {method}, 错误: {e}")
            return None
    
    def navigate_to(self, url):
        """导航到指定URL"""
        try:
            self.logger.info(f"导航到: {url}")
            result = self._send_command("Page.navigate", {"url": url})
            if result and 'result' in result:
                # 等待页面加载完成
                max_wait = 15
                start_time = time.time()
                
                while time.time() - start_time < max_wait:
                    try:
                        # 检查页面加载状态
                        ready_state = self.execute_script("document.readyState")
                        if ready_state in ['interactive', 'complete']:
                            # 额外等待确保页面完全渲染
                            time.sleep(2)
                            current_url = self.get_current_url()
                            self.logger.info(f"页面加载完成: {current_url}")
                            return True
                        time.sleep(1)
                    except Exception as e:
                        self.logger.debug(f"检查页面状态时出错: {e}")
                        time.sleep(1)
                
                # 即使超时也返回True，让后续操作继续
                self.logger.warning("页面加载可能未完成，但继续执行")
                return True
            return False
        except Exception as e:
            self.logger.error(f"导航失败: {e}")
            return False
    
    def _is_xpath(self, selector):
        """判断选择器是否为XPath"""
        return selector.startswith('//') or selector.startswith('/') or selector.startswith('(')
    
    def find_element(self, selector, timeout=10):
        """查找元素，自动判断XPath或CSS选择器"""
        try:
            if self._is_xpath(selector):
                return self._find_element_by_xpath(selector, timeout)
            else:
                return self._find_element_by_css(selector, timeout)
        except Exception as e:
            self.logger.error(f"查找元素失败: {selector}, 错误: {e}")
            return None
    
    def _find_element_by_xpath(self, xpath, timeout=10):
        """通过XPath查找元素"""
        try:
            # 使用JavaScript执行XPath查询
            js_code = f"""
            (function() {{
                var result = document.evaluate(
                    {json.dumps(xpath)}, 
                    document, 
                    null, 
                    XPathResult.FIRST_ORDERED_NODE_TYPE, 
                    null
                );
                var element = result.singleNodeValue;
                if (element) {{
                    // 为元素添加唯一ID以便后续操作
                    if (!element.id) {{
                        element.id = 'xpath_element_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
                    }}
                    return {{
                        id: element.id,
                        tagName: element.tagName,
                        className: element.className,
                        textContent: element.textContent ? element.textContent.substring(0, 100) : '',
                        found: true
                    }};
                }}
                return {{found: false}};
            }})()
            """
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                result = self.execute_script(js_code)
                if result and result.get('found'):
                    self.logger.info(f"找到XPath元素: {xpath} -> {result}")
                    return result
                time.sleep(0.5)
            
            self.logger.warning(f"XPath元素未找到: {xpath}")
            return None
            
        except Exception as e:
            self.logger.error(f"XPath查找失败: {xpath}, 错误: {e}")
            return None
    
    def _find_element_by_css(self, css_selector, timeout=10):
        """通过CSS选择器查找元素"""
        try:
            js_code = f"""
            (function() {{
                var element = document.querySelector({json.dumps(css_selector)});
                if (element) {{
                    if (!element.id) {{
                        element.id = 'css_element_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
                    }}
                    return {{
                        id: element.id,
                        tagName: element.tagName,
                        className: element.className,
                        textContent: element.textContent ? element.textContent.substring(0, 100) : '',
                        found: true
                    }};
                }}
                return {{found: false}};
            }})()
            """
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                result = self.execute_script(js_code)
                if result and result.get('found'):
                    self.logger.info(f"找到CSS元素: {css_selector} -> {result}")
                    return result
                time.sleep(0.5)
            
            self.logger.warning(f"CSS元素未找到: {css_selector}")
            return None
            
        except Exception as e:
            self.logger.error(f"CSS查找失败: {css_selector}, 错误: {e}")
            return None
    
    def find_elements(self, selector, timeout=10):
        """查找多个元素"""
        try:
            if self._is_xpath(selector):
                return self._find_elements_by_xpath(selector, timeout)
            else:
                return self._find_elements_by_css(selector, timeout)
        except Exception as e:
            self.logger.error(f"查找多个元素失败: {selector}, 错误: {e}")
            return []
    
    def _find_elements_by_xpath(self, xpath, timeout=10):
        """通过XPath查找多个元素"""
        try:
            js_code = f"""
            (function() {{
                var result = document.evaluate(
                    {json.dumps(xpath)}, 
                    document, 
                    null, 
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, 
                    null
                );
                var elements = [];
                for (var i = 0; i < result.snapshotLength; i++) {{
                    var element = result.snapshotItem(i);
                    if (!element.id) {{
                        element.id = 'xpath_element_' + Date.now() + '_' + i + '_' + Math.random().toString(36).substr(2, 9);
                    }}
                    elements.push({{
                        id: element.id,
                        tagName: element.tagName,
                        className: element.className,
                        textContent: element.textContent ? element.textContent.substring(0, 100) : ''
                    }});
                }}
                return elements;
            }})()
            """
            
            result = self.execute_script(js_code)
            if result and isinstance(result, list):
                self.logger.info(f"找到{len(result)}个XPath元素: {xpath}")
                return result
            return []
            
        except Exception as e:
            self.logger.error(f"XPath多元素查找失败: {xpath}, 错误: {e}")
            return []
    
    def _find_elements_by_css(self, css_selector, timeout=10):
        """通过CSS选择器查找多个元素"""
        try:
            js_code = f"""
            (function() {{
                var elements = document.querySelectorAll({json.dumps(css_selector)});
                var result = [];
                for (var i = 0; i < elements.length; i++) {{
                    var element = elements[i];
                    if (!element.id) {{
                        element.id = 'css_element_' + Date.now() + '_' + i + '_' + Math.random().toString(36).substr(2, 9);
                    }}
                    result.push({{
                        id: element.id,
                        tagName: element.tagName,
                        className: element.className,
                        textContent: element.textContent ? element.textContent.substring(0, 100) : ''
                    }});
                }}
                return result;
            }})()
            """
            
            result = self.execute_script(js_code)
            if result and isinstance(result, list):
                self.logger.info(f"找到{len(result)}个CSS元素: {css_selector}")
                return result
            return []
            
        except Exception as e:
            self.logger.error(f"CSS多元素查找失败: {css_selector}, 错误: {e}")
            return []
    
    def click_element(self, element_info):
        """点击元素"""
        try:
            if isinstance(element_info, str):
                # 如果传入的是选择器字符串，先查找元素
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            js_code = f"""
            (function() {{
                var element = document.getElementById({json.dumps(element_id)});
                if (element) {{
                    element.click();
                    return true;
                }}
                return false;
            }})()
            """
            
            result = self.execute_script(js_code)
            if result:
                self.logger.info(f"成功点击元素: {element_id}")
                time.sleep(random.uniform(0.5, 1.5))  # 随机延迟
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"点击元素失败: {e}")
            return False
    
    def type_text(self, element_info, text, clear_first=True):
        """在元素中输入文本"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            # 先点击元素获得焦点
            if not self.click_element(element_info):
                self.logger.error("无法点击元素获得焦点")
                return False
            
            time.sleep(0.5)
            
            # 如果需要清空，先全选然后删除
            if clear_first:
                # Ctrl+A 全选
                self._send_command("Input.dispatchKeyEvent", {
                    "type": "keyDown",
                    "key": "a",
                    "modifiers": 2  # Ctrl键
                })
                self._send_command("Input.dispatchKeyEvent", {
                    "type": "keyUp", 
                    "key": "a",
                    "modifiers": 2
                })
                
                time.sleep(0.1)
                
                # Delete键删除选中内容
                self._send_command("Input.dispatchKeyEvent", {
                    "type": "keyDown",
                    "key": "Delete"
                })
                self._send_command("Input.dispatchKeyEvent", {
                    "type": "keyUp",
                    "key": "Delete"
                })
                
                time.sleep(0.2)
            
            # 逐个字符输入
            for char in text:
                self._send_command("Input.dispatchKeyEvent", {
                    "type": "char",
                    "text": char
                })
                time.sleep(0.05)  # 每个字符间隔50ms
            
            self.logger.info(f"成功输入文本到元素: {element_id}")
            time.sleep(0.5)
            return True
            
        except Exception as e:
            self.logger.error(f"输入文本失败: {e}")
            return False
    
    def get_element_text(self, element_info):
        """获取元素文本"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return ""
            
            element_id = element_info.get('id')
            if not element_id:
                return ""
            
            js_code = f"""
            (function() {{
                var element = document.getElementById({json.dumps(element_id)});
                if (element) {{
                    return element.textContent || element.innerText || '';
                }}
                return '';
            }})()
            """
            
            result = self.execute_script(js_code)
            return result or ""
            
        except Exception as e:
            self.logger.error(f"获取元素文本失败: {e}")
            return ""
    
    def execute_script(self, script):
        """执行JavaScript代码"""
        try:
            if not self.ws:
                self.logger.error("WebSocket连接不存在，无法执行JavaScript")
                return None
            
            result = self._send_command("Runtime.evaluate", {
                "expression": script,
                "returnByValue": True,
                "awaitPromise": False,  # 改为False，避免等待Promise
                "timeout": 10000  # 10秒超时
            })
            
            if not result:
                self.logger.warning("JavaScript执行未返回结果")
                return None
            
            if 'result' in result:
                result_data = result['result']
                
                # 检查是否有异常
                if 'exceptionDetails' in result_data:
                    exception = result_data['exceptionDetails']
                    self.logger.error(f"JavaScript执行异常: {exception.get('text', 'Unknown error')}")
                    return None
                
                # 获取结果值
                if 'result' in result_data:
                    result_obj = result_data['result']
                    
                    # 直接返回value字段
                    if 'value' in result_obj:
                        return result_obj['value']
                    
                    # 处理其他类型
                    result_type = result_obj.get('type', 'unknown')
                    if result_type == 'undefined':
                        return None
                    elif result_type == 'object' and result_obj.get('subtype') == 'null':
                        return None
                    elif result_type == 'string':
                        return result_obj.get('description', '')
                    elif result_type == 'number':
                        return result_obj.get('description', 0)
                    elif result_type == 'boolean':
                        return result_obj.get('description', 'false') == 'true'
                    else:
                        # 对于其他复杂类型，尝试获取描述
                        return result_obj.get('description', f"[{result_type}]")
            
            self.logger.warning("JavaScript执行结果格式异常")
            return None
            
        except Exception as e:
            self.logger.error(f"执行JavaScript失败: {e}")
            return None
    
    def wait_for_element(self, selector, timeout=10):
        """等待元素出现"""
        return self.find_element(selector, timeout)
    
    def is_element_present(self, selector):
        """检查元素是否存在"""
        element = self.find_element(selector, timeout=1)
        return element is not None
    
    def get_current_url(self):
        """获取当前页面URL"""
        try:
            # 使用CDP的Target.getTargetInfo获取当前页面信息
            result = self._send_command("Target.getTargetInfo", {
                "targetId": self.current_tab_id
            })
            
            if result and 'result' in result and 'targetInfo' in result['result']:
                url = result['result']['targetInfo'].get('url', '')
                return url
            
            # 备用方案：通过标签页列表获取当前URL
            tabs = self.get_all_tabs()
            for tab in tabs:
                if tab.get('id') == self.current_tab_id:
                    return tab.get('url', '')
            
            return ""
        except Exception as e:
            self.logger.error(f"获取当前URL失败: {e}")
            return ""
    
    def navigate_back(self):
        """后退到上一页"""
        try:
            response = self._send_command("Page.goBack")
            if response and not response.get('error'):
                self.logger.info("成功后退到上一页")
                return True
            else:
                self.logger.error(f"后退失败: {response}")
                return False
        except Exception as e:
            self.logger.error(f"后退时发生错误: {e}")
            return False

    def navigate_forward(self):
        """前进到下一页"""
        try:
            response = self._send_command("Page.goForward")
            if response and not response.get('error'):
                self.logger.info("成功前进到下一页")
                return True
            else:
                self.logger.error(f"前进失败: {response}")
                return False
        except Exception as e:
            self.logger.error(f"前进时发生错误: {e}")
            return False
    
    def close(self):
        """关闭浏览器连接"""
        try:
            if self.ws:
                self.ws.close()
                self.ws = None
            
            if self.chrome_process:
                self.chrome_process.terminate()
                self.chrome_process = None
                
            self.logger.info("浏览器连接已关闭")
            
        except Exception as e:
            self.logger.error(f"关闭浏览器连接失败: {e}")
    
    def get_all_tabs(self):
        """获取所有可用的页面标签页"""
        try:
            response = requests.get(f"http://localhost:{self.debug_port}/json")
            tabs = response.json()
            # 过滤掉非页面类型的目标
            page_tabs = [t for t in tabs if t.get('type') == 'page']
            self.logger.info(f"找到 {len(page_tabs)} 个页面标签页 (总共 {len(tabs)} 个目标)")
            return page_tabs
        except Exception as e:
            self.logger.error(f"获取标签页列表失败: {e}")
            return []
    
    def switch_to_tab(self, tab_index):
        """切换到指定索引的标签页"""
        try:
            tabs = self.get_all_tabs()
            if not tabs or tab_index >= len(tabs):
                self.logger.error(f"标签页索引 {tab_index} 超出范围")
                return False
            
            target_tab = tabs[tab_index]
            self.current_tab_id = target_tab['id']
            
            # 重新连接到新标签页
            ws_url = target_tab['webSocketDebuggerUrl']
            
            # 关闭旧连接
            if self.ws:
                self.ws.close()
            
            # 建立新连接
            self.ws = websocket.create_connection(ws_url)
            
            # 启用必要的域
            self._send_command("Runtime.enable")
            self._send_command("Page.enable")
            self._send_command("DOM.enable")
            
            self.logger.info(f"成功切换到标签页 {tab_index}: {target_tab.get('title', 'Unknown')}")
            return True
            
        except Exception as e:
            self.logger.error(f"切换标签页失败: {e}")
            return False

    def get_current_tab_index(self):
        """获取当前标签页的索引"""
        try:
            tabs = self.get_all_tabs()
            if not tabs:
                return -1
            
            for i, tab in enumerate(tabs):
                if tab['id'] == self.current_tab_id:
                    return i
            
            return -1
            
        except Exception as e:
            self.logger.error(f"获取当前标签页索引失败: {e}")
            return -1

    def close_current_tab(self):
        """关闭当前标签页"""
        try:
            if not self.current_tab_id:
                self.logger.warning("没有当前标签页可关闭")
                return False
            
            # 通过CDP API关闭标签页
            response = requests.delete(f"http://localhost:{self.debug_port}/json/close/{self.current_tab_id}")
            
            if response.status_code == 200:
                self.logger.info("成功关闭当前标签页")
                
                # 关闭WebSocket连接
                if self.ws:
                    self.ws.close()
                    self.ws = None
                
                self.current_tab_id = None
                return True
            else:
                self.logger.error(f"关闭标签页失败: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"关闭标签页失败: {e}")
            return False

    def close_tab_by_id(self, tab_id):
        """通过ID关闭指定标签页"""
        try:
            self._send_command("Target.closeTarget", {"targetId": tab_id})
            self.logger.info(f"已发送关闭标签页 {tab_id} 的请求。")
            return True
        except Exception as e:
            self.logger.error(f"通过ID关闭标签页 {tab_id} 失败: {e}")
            return False

    def open_new_tab(self, url='about:blank'):
        """使用CDP打开新标签页并切换"""
        try:
            self.logger.info(f"请求打开新标签页: {url}")
            
            # 创建新目标（即新标签页）
            create_target_result = self._send_command("Target.createTarget", {"url": "about:blank"})
            if not create_target_result or 'result' not in create_target_result:
                self.logger.error("创建新标签页失败")
                return False

            new_tab_id = create_target_result['result']['targetId']
            self.logger.info(f"新标签页创建成功, ID: {new_tab_id}")
            time.sleep(1) # 等待新标签页准备好

            # 获取所有标签页，找到新标签页的索引
            all_tabs = self.get_all_tabs()
            new_tab_index = -1
            for i, tab in enumerate(all_tabs):
                if tab.get('id') == new_tab_id:
                    new_tab_index = i
                    break
            
            if new_tab_index == -1:
                self.logger.error("无法找到新创建的标签页")
                return False

            # 切换到新标签页
            if not self.switch_to_tab(new_tab_index):
                self.logger.error("切换到新标签页失败")
                return False
            
            # 在新标签页中导航到指定URL
            return self.navigate_to(url)

        except Exception as e:
            self.logger.error(f"打开新标签页时出错: {e}")
            return False
    
    def find_tab_by_url(self, url_pattern):
        """根据URL模式查找标签页"""
        try:
            tabs = self.get_all_tabs()
            for i, tab in enumerate(tabs):
                if url_pattern in tab.get('url', ''):
                    return i
            return -1
        except Exception as e:
            self.logger.error(f"查找标签页失败: {e}")
            return -1

    def start_browser(self):
        """启动浏览器（公共方法，用于GUI调用）"""
        return self.start_chrome()

    def get_browser(self):
        """获取浏览器实例（用于WorkflowManager）"""
        try:
            # 确保浏览器已启动并连接
            if not self.chrome_process or not self.ws:
                if not self.start_browser():
                    return None, None
            
            # 返回浏览器实例和当前标签
            return self, self.current_tab_id
            
        except Exception as e:
            self.logger.error(f"获取浏览器实例失败: {e}")
            return None, None

    def cleanup(self):
        """清理资源"""
        try:
            self.close()
        except Exception as e:
            self.logger.error(f"清理资源失败: {e}")

    def click_element_with_mouse(self, element_info):
        """使用鼠标事件点击元素（更真实的点击方式）"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            # 简化的滚动脚本
            scroll_script = f"document.getElementById('{element_id}').scrollIntoView(true);"
            
            try:
                self.execute_script(scroll_script)
                time.sleep(1)  # 等待滚动完成
                self.logger.info("已滚动到元素位置")
            except Exception as e:
                self.logger.warning(f"滚动失败: {e}")
            
            # 简化的位置获取脚本
            bounds_script = f"""
            var el = document.getElementById('{element_id}');
            var rect = el.getBoundingClientRect();
            return [rect.left + rect.width/2, rect.top + rect.height/2, rect.width, rect.height];
            """
            
            try:
                bounds_result = self.execute_script(bounds_script)
                if not bounds_result or len(bounds_result) < 2:
                    self.logger.error("无法获取元素位置")
                    return False
                
                click_x = int(bounds_result[0])
                click_y = int(bounds_result[1])
                
                self.logger.info(f"准备在位置 ({click_x}, {click_y}) 点击元素")
                
                # 先移动鼠标到元素位置
                move_result = self._send_command("Input.dispatchMouseEvent", {
                    "type": "mouseMoved",
                    "x": click_x,
                    "y": click_y
                })
                
                time.sleep(0.2)
                
                # 鼠标按下
                press_result = self._send_command("Input.dispatchMouseEvent", {
                    "type": "mousePressed",
                    "x": click_x,
                    "y": click_y,
                    "button": "left",
                    "clickCount": 1
                })
                
                time.sleep(0.1)
                
                # 鼠标释放
                release_result = self._send_command("Input.dispatchMouseEvent", {
                    "type": "mouseReleased",
                    "x": click_x,
                    "y": click_y,
                    "button": "left",
                    "clickCount": 1
                })
                
                self.logger.info(f"鼠标事件执行结果 - 移动: {move_result is not None}, 按下: {press_result is not None}, 释放: {release_result is not None}")
                self.logger.info(f"成功使用鼠标点击元素: {element_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"获取元素位置或执行鼠标事件失败: {e}")
                return False
            
        except Exception as e:
            self.logger.error(f"鼠标点击元素失败: {e}")
            return False

    def click_element_with_dom_api(self, element_info):
        """使用CDP DOM API点击元素（不依赖JavaScript）"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            # 使用DOM.getBoxModel获取元素的位置信息
            # 首先需要获取DOM节点ID
            get_node_script = f"document.getElementById('{element_id}')"
            
            # 使用Runtime.evaluate获取节点
            eval_result = self._send_command("Runtime.evaluate", {
                "expression": get_node_script,
                "returnByValue": False
            })
            
            if not eval_result or 'result' not in eval_result:
                self.logger.error("无法获取DOM节点")
                return False
            
            object_id = eval_result['result'].get('objectId')
            if not object_id:
                self.logger.error("无法获取对象ID")
                return False
            
            # 使用DOM.requestNode获取节点ID
            node_result = self._send_command("DOM.requestNode", {
                "objectId": object_id
            })
            
            if not node_result or 'result' not in node_result:
                self.logger.error("无法获取节点ID")
                return False
            
            node_id = node_result['result']['nodeId']
            
            # 获取元素的盒模型
            box_result = self._send_command("DOM.getBoxModel", {
                "nodeId": node_id
            })
            
            if not box_result or 'result' not in box_result:
                self.logger.error("无法获取元素盒模型")
                return False
            
            content_quad = box_result['result']['model']['content']
            
            # 计算中心点
            # content_quad是一个包含8个数字的数组，表示4个角的坐标 [x1,y1,x2,y2,x3,y3,x4,y4]
            center_x = (content_quad[0] + content_quad[4]) / 2
            center_y = (content_quad[1] + content_quad[5]) / 2
            
            self.logger.info(f"使用DOM API获取元素中心位置: ({center_x}, {center_y})")
            
            # 使用鼠标事件点击
            # 移动鼠标
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": center_x,
                "y": center_y
            })
            
            time.sleep(0.1)
            
            # 鼠标按下
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            time.sleep(0.05)
            
            # 鼠标释放
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            self.logger.info(f"成功使用DOM API点击元素: {element_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"DOM API点击元素失败: {e}")
            return False

    def click_element_simple(self, element_info):
        """简单点击方法，使用JavaScript获取元素位置"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            # 使用简单的JavaScript获取元素位置
            try:
                # 直接使用JavaScript获取元素的位置和大小
                get_position_script = f"""
                (function() {{
                    var element = document.getElementById('{element_id}');
                    if (!element) return null;
                    var rect = element.getBoundingClientRect();
                    return {{
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height,
                        centerX: rect.left + rect.width / 2,
                        centerY: rect.top + rect.height / 2
                    }};
                }})()
                """
                
                eval_result = self._send_command("Runtime.evaluate", {
                    "expression": get_position_script,
                    "returnByValue": True
                })
                
                if eval_result and 'result' in eval_result and 'value' in eval_result['result'] and eval_result['result']['value']:
                    position = eval_result['result']['value']
                    center_x = position['centerX']
                    center_y = position['centerY']
                    
                    self.logger.info(f"JavaScript获取到元素位置: left={position['left']}, top={position['top']}, 中心点({center_x}, {center_y})")
                else:
                    raise Exception("JavaScript执行失败或返回空值")
                    
            except Exception as e:
                self.logger.warning(f"JavaScript获取元素位置失败: {e}，使用默认坐标")
                center_x = 500
                center_y = 300
            
            # 移动鼠标到元素位置
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": center_x,
                "y": center_y
            })
            
            time.sleep(0.1)
            
            # 点击
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            time.sleep(0.05)
            
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            self.logger.info(f"完成点击元素: {element_id} 在位置 ({center_x}, {center_y})")
            return True
            
        except Exception as e:
            self.logger.error(f"点击元素失败: {e}")
            return False

    def get_element_attribute(self, element_info, attribute_name):
        """获取元素属性值"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return None
            
            element_id = element_info.get('id')
            if not element_id:
                return None
            
            # 使用CDP的DOM.getAttributes获取元素属性
            # 首先需要获取DOM节点ID
            get_node_script = f"document.getElementById('{element_id}')"
            
            # 使用Runtime.evaluate获取节点
            eval_result = self._send_command("Runtime.evaluate", {
                "expression": get_node_script,
                "returnByValue": False
            })
            
            if not eval_result or 'result' not in eval_result:
                return None
            
            object_id = eval_result['result'].get('objectId')
            if not object_id:
                return None
            
            # 使用DOM.requestNode获取节点ID
            node_result = self._send_command("DOM.requestNode", {
                "objectId": object_id
            })
            
            if not node_result or 'result' not in node_result:
                return None
            
            node_id = node_result['result']['nodeId']
            
            # 获取元素的所有属性
            attrs_result = self._send_command("DOM.getAttributes", {
                "nodeId": node_id
            })
            
            if attrs_result and 'result' in attrs_result and 'attributes' in attrs_result['result']:
                attributes = attrs_result['result']['attributes']
                # attributes是一个数组，格式为[name1, value1, name2, value2, ...]
                for i in range(0, len(attributes), 2):
                    if i + 1 < len(attributes) and attributes[i] == attribute_name:
                        return attributes[i + 1]
            
            return None
            
        except Exception as e:
            self.logger.error(f"获取元素属性失败: {e}")
            return None

    def click_element_direct(self, element_info):
        """直接点击方法，不使用任何JavaScript，使用固定策略"""
        try:
            if isinstance(element_info, str):
                element_info = self.find_element(element_info)
                if not element_info:
                    return False
            
            element_id = element_info.get('id')
            if not element_id:
                return False
            
            # 获取视口大小来计算合理的点击位置
            try:
                viewport_result = self._send_command("Page.getLayoutMetrics")
                if viewport_result and 'result' in viewport_result:
                    viewport = viewport_result['result']['layoutViewport']
                    viewport_width = viewport['clientWidth']
                    viewport_height = viewport['clientHeight']
                else:
                    viewport_width = 1200
                    viewport_height = 800
            except:
                viewport_width = 1200
                viewport_height = 800
            
            # 使用固定的点击策略：根据元素在页面中的位置计算点击坐标
            # 假设搜索结果在页面中央区域垂直排列
            element_text = element_info.get('textContent', '')
            
            # 根据元素文本内容的哈希值来确定Y坐标，确保不同元素有不同的点击位置
            text_hash = hashlib.md5(element_text.encode()).hexdigest()
            hash_int = int(text_hash[:8], 16)
            
            # 计算点击位置：X坐标在页面中央，Y坐标根据元素内容变化
            center_x = viewport_width / 2
            base_y = viewport_height * 0.3  # 从页面30%的位置开始
            offset_y = (hash_int % 300) + 50  # 在50-350像素范围内变化
            center_y = base_y + offset_y
            
            self.logger.info(f"使用直接点击方法，元素: {element_text[:30]}, 位置: ({center_x}, {center_y})")
            
            # 移动鼠标到计算的位置
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": center_x,
                "y": center_y
            })
            
            time.sleep(0.1)
            
            # 鼠标按下
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            time.sleep(0.05)
            
            # 鼠标释放
            self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": center_x,
                "y": center_y,
                "button": "left",
                "clickCount": 1
            })
            
            self.logger.info(f"完成直接点击元素: {element_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"直接点击元素失败: {e}")
            return False

    def click_element_by_xpath(self, xpath):
        """直接使用XPath定位并点击元素，类似影刀的做法"""
        try:
            # 使用JavaScript直接通过XPath定位并点击元素
            click_script = f"""
            (function() {{
                // 使用XPath定位元素
                var result = document.evaluate(
                    '{xpath}',
                    document,
                    null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                    null
                );
                
                var element = result.singleNodeValue;
                if (!element) {{
                    return {{success: false, error: 'Element not found'}};
                }}
                
                // 确保元素可见
                element.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                
                // 创建并触发点击事件
                var clickEvent = new MouseEvent('click', {{
                    view: window,
                    bubbles: true,
                    cancelable: true,
                    button: 0
                }});
                
                element.dispatchEvent(clickEvent);
                
                return {{
                    success: true, 
                    tagName: element.tagName,
                    textContent: element.textContent ? element.textContent.substring(0, 50) : '',
                    href: element.href || ''
                }};
            }})()
            """
            
            eval_result = self._send_command("Runtime.evaluate", {
                "expression": click_script,
                "returnByValue": True
            })
            
            if eval_result and 'result' in eval_result and 'value' in eval_result['result']:
                result = eval_result['result']['value']
                if result and result.get('success'):
                    self.logger.info(f"XPath点击成功: {xpath}")
                    self.logger.info(f"元素信息: 标签={result.get('tagName')}, 文本={result.get('textContent')}, 链接={result.get('href')}")
                    return True
                else:
                    self.logger.error(f"XPath点击失败: {result.get('error', '未知错误')}")
                    return False
            else:
                self.logger.error(f"XPath点击脚本执行失败")
                return False
                
        except Exception as e:
            self.logger.error(f"XPath点击异常: {e}")
            return False

    def set_input_files(self, selector, file_path):
        """为文件输入元素设置文件路径（用于上传）"""
        try:
            # 1. 获取元素的 nodeId
            element_info = self.find_element(selector)
            if not element_info or 'result' not in element_info or 'rootId' not in element_info['result']:
                self.logger.error(f"无法找到或获取文件输入元素: {selector}")
                return False
            
            node_id = element_info['result']['nodeId']

            # 2. 使用 DOM.setFileInputs 命令
            result = self._send_command("DOM.setFileInputs", {
                "nodeId": node_id,
                "files": [file_path]
            })

            if result and 'error' not in result:
                self.logger.info(f"文件路径已成功设置: {file_path}")
                return True
            else:
                error_message = result.get('error', {}).get('message', '未知错误') if result else '无响应'
                self.logger.error(f"设置文件输入失败: {error_message}")
                return False
        except Exception as e:
            self.logger.error(f"设置文件输入时出现异常: {e}")
            return False

    def is_browser_running(self):
        """检查浏览器是否已连接"""
        return self.ws is not None

    def _connect_to_browser(self):
        """连接到浏览器的WebSocket"""
        for _ in range(10): # 尝试连接10次
            if self.connect():
                return True
            time.sleep(1) # 每次连接失败后等待1秒
        return False




# 移除全局实例，由GUI主窗口负责创建和管理 