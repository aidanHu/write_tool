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
import hashlib


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
            
            if self.headless:
                self.logger.info("以无头模式启动Chrome...")
                chrome_args.append("--headless")
                chrome_args.append("--disable-gpu") # 在某些系统上，无头模式需要禁用GPU

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
        """尝试使用多种方法直接点击元素，直到成功为止"""
        if self.click_element_simple(element_info):
            return True
        if self.click_element_with_dom_api(element_info):
            return True
        if self.click_element_with_mouse(element_info):
            return True
        return False

    def click_element_by_xpath(self, xpath):
        """
        通过XPath查找并点击元素，采用多策略方法提高成功率。
        策略1: 标准 .click()
        策略2: 派发一个 MouseEvent
        """
        self.logger.info(f"尝试以多策略点击XPath元素: {xpath}")
        try:
            js_code = f"""
            (function() {{
                var element = document.evaluate(
                    {json.dumps(xpath)},
                    document,
                    null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                    null
                ).singleNodeValue;

                if (!element) {{
                    console.error('多策略点击失败：未找到元素。XPath: ' + {json.dumps(xpath)});
                    return {{'success': false, 'error': 'Element not found'}};
                }}

                // 策略 1: 标准 .click()
                try {{
                    if (typeof element.click === 'function') {{
                        element.click();
                        console.log('策略1 (.click()) 成功。');
                        return {{'success': true, 'strategy': 'standard_click'}};
                    }}
                }} catch (e) {{
                    console.warn('策略1 (.click()) 失败: ' + e.message);
                }}

                // 策略 2: 派发 MouseEvent
                try {{
                    console.log('尝试策略2 (MouseEvent)...');
                    var event = new MouseEvent('click', {{
                        'view': window,
                        'bubbles': true,
                        'cancelable': true
                    }});
                    element.dispatchEvent(event);
                    console.log('策略2 (MouseEvent) 派发成功。');
                    return {{'success': true, 'strategy': 'mouse_event'}};
                }} catch (e) {{
                    console.error('策略2 (MouseEvent) 失败: ' + e.message);
                    return {{'success': false, 'error': 'MouseEvent dispatch failed: ' + e.message}};
                }}
            }})()
            """
            result = self.execute_script(js_code)

            if result and result.get('success'):
                self.logger.info(f"成功点击XPath元素: {xpath} (使用策略: {result.get('strategy', 'unknown')})")
                return True
            else:
                error_msg = result.get('error', '未知错误') if result else '未知错误'
                self.logger.error(f"多策略点击失败: {xpath}. 错误: {error_msg}")
                return False
        except Exception as e:
            self.logger.error(f"执行多策略点击时出现异常: {xpath}, {e}", exc_info=True)
            return False

    def set_input_files(self, selector, file_path):
        """
        为一个<input type="file">元素设置上传文件路径。
        增加了等待和重试机制，并能自动判断选择器类型。
        """
        self.logger.info(f"准备为选择器 '{selector}' 设置文件: {file_path}")
        try:
            timeout = 5
            start_time = time.time()
            node_id = None
            is_xpath = self._is_xpath(selector)

            while time.time() - start_time < timeout:
                doc = self._send_command('DOM.getDocument', {'depth': -1})
                if not doc or 'root' not in doc.get('result', {}):
                    time.sleep(0.5)
                    continue
                root_node_id = doc['result']['root']['nodeId']

                # 根据选择器类型使用不同的查询方法
                if is_xpath:
                    search_result = self._send_command('DOM.performSearch', {'query': selector})
                    if search_result and search_result.get('result', {}).get('resultCount', 0) > 0:
                        search_id = search_result['result']['searchId']
                        nodes_result = self._send_command('DOM.getSearchResults', {'searchId': search_id, 'fromIndex': 0, 'toIndex': 1})
                        if nodes_result and nodes_result.get('result', {}).get('nodeIds'):
                            node_id = nodes_result['result']['nodeIds'][0]
                else:
                    query_result = self._send_command('DOM.querySelector', {'nodeId': root_node_id, 'selector': selector})
                    if query_result and query_result.get('result', {}).get('nodeId'):
                        node_id = query_result['result']['nodeId']
                
                if node_id:
                    self.logger.info(f"成功找到文件输入元素节点, NodeId: {node_id}")
                    break
                
                self.logger.info(f"暂未找到文件输入元素 '{selector}', 正在重试...")
                time.sleep(0.5)

            if not node_id:
                self.logger.error(f"超时! 未能找到文件输入元素: {selector}")
                return False

            abs_file_path = os.path.abspath(file_path)
            self.logger.info(f"正在为NodeId {node_id} 设置绝对路径: {abs_file_path}")

            set_files_result = self._send_command('DOM.setFileInputFiles', {
                'nodeId': node_id,
                'files': [abs_file_path]
            })

            if set_files_result and 'error' not in set_files_result:
                self.logger.info(f"文件 '{abs_file_path}' 已成功设置。")
                return True
            else:
                error = set_files_result.get('error', {'message': '未知错误'}) if set_files_result else {'message': '未知错误'}
                self.logger.error(f"设置文件输入失败: {error.get('message')}")
                return False

        except Exception as e:
            self.logger.error(f"设置文件输入时发生异常: {e}", exc_info=True)
            return False

    def scroll_to_bottom(self, steps=10, delay=0.5):
        """
        平滑滚动到页面底部以加载所有内容。
        """
        self.logger.info("开始滚动到页面底部...")
        try:
            js_script = f"""
            (async () => {{
                const totalHeight = document.body.scrollHeight;
                const steps = {steps};
                const delay = {delay * 1000}; // a-wait-ms in JS needs milliseconds
                for (let i = 0; i <= steps; i++) {{
                    window.scrollTo(0, (totalHeight / steps) * i);
                    await new Promise(resolve => setTimeout(resolve, delay));
                }}
                return true;
            }})()
            """
            self.execute_script(js_script)
            self.logger.info("滚动完成。")
        except Exception as e:
            self.logger.error(f"滚动页面时出错: {e}")

    def is_browser_running(self):
        """检查Chrome进程是否仍在运行"""
        return self.chrome_process and self.chrome_process.poll() is None

    def _connect_to_browser(self):
        """连接到浏览器的WebSocket"""
        for _ in range(10): # 尝试连接10次
            if self.connect():
                return True
            time.sleep(1) # 每次连接失败后等待1秒
        return False

    def close_other_tabs(self):
        """关闭除当前活动标签页外的所有其他标签页"""
        self.logger.info("正在关闭其他标签页...")
        try:
            all_tabs = self.get_all_tabs()
            current_tab_id = self.current_tab_id
            
            if not all_tabs or len(all_tabs) <= 1:
                self.logger.info("没有其他标签页需要关闭。")
                return

            for tab in all_tabs:
                if tab.get('id') != current_tab_id:
                    self.logger.info(f"正在关闭标签页: {tab.get('title', tab.get('id'))}")
                    self.close_tab_by_id(tab.get('id'))
            
            self.logger.info("已关闭所有其他标签页。")
        except Exception as e:
            self.logger.error(f"关闭其他标签页时出错: {e}")

    def switch_to_tab_by_id(self, tab_id: str) -> bool:
        """通过标签页ID切换到指定标签页"""
        self.logger.info(f"尝试切换到标签页ID: {tab_id}")
        try:
            all_tabs = self.get_all_tabs()
            target_tab = next((tab for tab in all_tabs if tab.get('id') == tab_id), None)

            if not target_tab:
                self.logger.error(f"未能找到ID为 '{tab_id}' 的标签页。")
                return False

            # 如果已经是当前标签页，则无需切换
            if self.current_tab_id == tab_id and self.is_connected():
                self.logger.info(f"已经是当前标签页: {tab_id}")
                return True

            # 关闭旧的WebSocket连接
            if self.ws and self.ws.connected:
                self.ws.close()

            # 连接到新标签页的WebSocket
            ws_url = target_tab.get('webSocketDebuggerUrl')
            self.ws = websocket.create_connection(ws_url)
            self.current_tab_id = tab_id

            # 为新标签页启用必要的域
            self._send_command("Page.enable")
            self._send_command("DOM.enable")
            self._send_command("Runtime.enable")

            self.logger.info(f"成功切换到标签页: {target_tab.get('title', tab_id)}")
            return True
        except Exception as e:
            self.logger.error(f"切换到标签页 {tab_id} 失败: {e}")
            return False




# 移除全局实例，由GUI主窗口负责创建和管理 