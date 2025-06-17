import asyncio
import os
import logging
from typing import Optional, List, Any
from playwright.async_api import async_playwright, Browser, Page, Playwright, Locator

class BrowserManager:
    """基于Playwright的精简版浏览器管理器"""

    def __init__(self, headless=False):
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.profile_dir = os.path.join(os.getcwd(), "playwright_chrome_profile")
        
        # 设置日志
        self.logger = logging.getLogger('BrowserManager')
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False

    async def launch(self):
        """启动浏览器并创建一个新页面"""
        try:
            # 清理可能残留的锁文件，避免SingletonLock错误
            singleton_lock = os.path.join(self.profile_dir, "SingletonLock")
            if os.path.exists(singleton_lock):
                try:
                    os.remove(singleton_lock)
                    self.logger.info("已清理残留的SingletonLock文件")
                except OSError as e:
                    self.logger.warning(f"清理SingletonLock文件失败: {e}")
            
            self.playwright = await async_playwright().start()
            
            # 优化的浏览器参数，专门为保持POE登录状态设计
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--disable-translate",
                "--disable-features=TranslateUI",
                "--enable-features=NetworkService,NetworkServiceLogging",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                # 确保cookie和存储保持
                "--enable-features=VaapiVideoDecoder",
                "--disable-features=VizDisplayCompositor",
                "--disable-dev-shm-usage",
                "--no-sandbox"  # 在某些环境下有助于稳定性
            ]
            
            context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=self.headless,
                args=browser_args,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                # 明确启用持久化存储
                accept_downloads=True,
                bypass_csp=False,  # 不绕过内容安全策略，保持网站原有行为
                ignore_https_errors=False,  # 不忽略HTTPS错误，保持安全性
                # 确保cookie和本地存储被保存
                record_har_path=None,  # 不记录HAR，避免影响性能
                record_video_dir=None,  # 不录制视频，避免影响性能
            )
            
            self.browser = context
            if context.pages:
                self.page = context.pages[0]
            else:
                self.page = await context.new_page()
            
            self.logger.info("Playwright浏览器启动成功。")
            return True
        except Exception as e:
            self.logger.error(f"启动Playwright浏览器失败: {e}", exc_info=True)
            return False

    def is_connected(self) -> bool:
        """检查浏览器是否仍然连接"""
        return self.browser is not None and not self.browser.is_closed()

    async def navigate(self, url: str, timeout: int = 60000) -> bool:
        """导航到指定URL"""
        if not self.page:
            self.logger.error("页面未初始化，无法导航。")
            return False
        try:
            self.logger.info(f"导航到: {url}")
            await self.page.goto(url, timeout=timeout, wait_until='domcontentloaded')
            self.logger.info(f"成功导航到: {url}")
            return True
        except Exception as e:
            self.logger.error(f"导航到 {url} 失败: {e}")
            return False

    async def find_element(self, selector: str, timeout: int = 10) -> Optional[Locator]:
        """查找单个元素，支持CSS和XPath选择器，返回第一个匹配的Locator"""
        if not self.page: return None
        try:
            # 判断是否为XPath选择器
            if selector.startswith('//') or selector.startswith('/'):
                locator = self.page.locator(f"xpath={selector}").first
            else:
                locator = self.page.locator(selector).first
            await locator.wait_for(state='attached', timeout=timeout * 1000)
            return locator
        except Exception:
            self.logger.debug(f"未找到元素: {selector}")
            return None

    async def find_elements(self, selector: str, timeout: int = 10) -> List[Locator]:
        """查找所有匹配的元素，支持CSS和XPath选择器，返回Locator列表"""
        if not self.page: return []
        try:
            # 判断是否为XPath选择器
            if selector.startswith('//') or selector.startswith('/'):
                locator = self.page.locator(f"xpath={selector}")
            else:
                locator = self.page.locator(selector)
            
            # 等待第一个元素出现，然后返回所有匹配的元素
            await locator.first.wait_for(state='attached', timeout=timeout * 1000)
            return await locator.all()
        except Exception:
            self.logger.debug(f"查找多个元素超时或失败: {selector}")
            return []

    async def execute_script(self, script: str, arg: Any = None) -> Any:
        """在页面上执行JavaScript"""
        if not self.page: return None
        try:
            return await self.page.evaluate(script, arg)
        except Exception as e:
            self.logger.error(f"执行脚本失败: {e}")
            return None

    async def focus_and_type_text(self, selector: str, text: str, clear_first: bool = True, timeout: int = 10) -> bool:
        """聚焦到元素并输入文本"""
        element = await self.find_element(selector, timeout)
        if not element:
            self.logger.error(f"无法找到元素以输入文本: {selector}")
            return False
        try:
            await element.focus()
            if clear_first:
                await element.fill(text)
            else:
                await element.press_sequentially(text) # 使用更自然的输入方式
            return True
        except Exception as e:
            self.logger.error(f"输入文本到 '{selector}' 失败: {e}")
            return False

    async def upload_file_with_dialog(self, trigger_selector: str, file_path: str, timeout: int = 10) -> bool:
        """
        通过点击按钮触发文件选择对话框来上传文件。
        适用于Monica这样的场景。
        """
        if not self.page: return False
        try:
            async with self.page.expect_file_chooser(timeout=timeout * 1000) as fc_info:
                await self.page.locator(trigger_selector).click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
            self.logger.info(f"文件 '{file_path}' 已通过对话框上传。")
            return True
        except Exception as e:
            self.logger.error(f"通过文件对话框上传失败 (选择器: '{trigger_selector}'): {e}")
            return False
            
    async def set_input_files_for_hidden_element(self, selector: str, file_path: str, timeout: int = 10) -> bool:
        """
        直接为隐藏的<input type="file">元素设置文件路径。
        适用于Poe这样的场景。
        """
        if not self.page: return False
        try:
            element = await self.find_element(selector, timeout)
            if not element:
                self.logger.error(f"找不到隐藏的文件输入元素: {selector}")
                return False
            await element.set_input_files(file_path)
            self.logger.info(f"文件 '{file_path}' 已直接设置到元素。")
            return True
        except Exception as e:
            self.logger.error(f"为隐藏元素设置输入文件失败 (选择器: '{selector}'): {e}")
            return False

    async def cleanup(self):
        """关闭浏览器和Playwright实例"""
        try:
            if self.browser:
                self.logger.info("正在关闭浏览器...")
                await self.browser.close()
                self.browser = None
                # 给浏览器进程一些时间完全关闭
                await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.warning(f"关闭浏览器时出现警告（可忽略）: {e}")
            self.browser = None
        
        try:
            if self.playwright:
                self.logger.info("正在停止Playwright...")
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            self.logger.warning(f"停止Playwright时出现警告（可忽略）: {e}")
            self.playwright = None
        
        self.logger.info("Playwright浏览器已关闭。")

    def get_current_url(self) -> Optional[str]:
        """获取当前页面的URL"""
        if self.page:
            return self.page.url
        return None




# 移除全局实例，由GUI主窗口负责创建和管理 