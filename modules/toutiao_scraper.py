import os
import time
import json
import logging
import random
from typing import List, Dict, Any
from .browser_manager import BrowserManager
from .image_handler import ImageHandler
from .qiniu_config import QiniuConfig
import traceback


class ToutiaoScraper:
    """基于Chrome DevTools Protocol的今日头条抓取器"""
    
    def __init__(self, gui_config, browser_manager):
        self.browser_manager = browser_manager
        self.setup_logging()
        
        # 加载模块自身的配置文件，并与GUI传入的配置合并
        local_config = self.load_config('toutiao_config.json')
        local_config.update(gui_config)
        self.config = local_config
        
        self.logger.info("今日头条抓取器初始化完成")
    
    def setup_logging(self):
        """设置日志配置"""
        self.logger = logging.getLogger('modules.toutiao_scraper')
        
        # 避免重复添加处理器
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            # 防止日志向上传播到根日志器
            self.logger.propagate = False
    
    def scrape_articles_and_images(self, keyword, scrape_articles=True, scrape_images=True):
        """
        公开的主方法，用于根据需要抓取文章和/或图片链接。
        """
        try:
            if not self.navigate_to_toutiao():
                self.logger.error("无法打开今日头条首页，抓取任务中止。")
                return False

            # 根据指令清理旧文件
            if scrape_articles:
                self._clear_file("article.txt")
            if scrape_images:
                self._clear_file("picture.txt")

            # 抓取文章数据（总是需要抓取，因为图片链接在文章内）
            articles_data = self.search_articles(keyword, self.config.get('article_count', 5))
            if not articles_data:
                self.logger.warning(f"未能根据关键词 '{keyword}' 抓取到任何文章数据。")
                return False 

            # 根据指令分别保存文章和图片
            if scrape_articles:
                self._save_articles_content(articles_data)

            if scrape_images:
                self._save_images_links(articles_data)
            
            self.logger.info("头条抓取工作流程成功完成。")
            return True

        except Exception as e:
            self.logger.error(f"头条抓取工作流程执行失败: {str(e)}")
            traceback.print_exc()
            return False

    def _save_articles_content(self, articles_data):
        """从抓取的数据中提取并保存文章内容。"""
        article_texts = [article['content'] for article in articles_data if article.get('content')]
        if article_texts:
            with open("article.txt", "w", encoding='utf-8') as f:
                f.write("\n\n---\n\n".join(article_texts))
            self.logger.info(f"已将 {len(article_texts)} 篇文章内容保存到 article.txt")
        else:
            self.logger.info("抓取到的文章内容为空。")

    def _save_images_links(self, articles_data):
        """
        从抓取的数据中提取、处理图片并保存七牛云链接。
        """
        all_images = []
        for article in articles_data:
            all_images.extend(article.get('images', []))
        
        max_images = self.config.get('image_count', 3)
        images_to_process = all_images[:max_images]

        if not images_to_process:
            self.logger.info("未抓取到任何图片链接。")
            return

        # 独立加载七牛云配置
        qiniu_loader = QiniuConfig()
        is_valid, message = qiniu_loader.validate()

        if not is_valid:
            self.logger.warning(message)  # 打印来自validate()的详细错误信息
            return

        # 初始化图片处理器
        qiniu_config = qiniu_loader.get_config()
        image_handler = ImageHandler(
            access_key=qiniu_config.get('access_key'),
            secret_key=qiniu_config.get('secret_key'),
            bucket_name=qiniu_config.get('bucket_name'),
            domain=qiniu_config.get('domain')
        )
        
        qiniu_links = []
        # 从主配置中读取裁剪像素值
        crop_pixels = self.config.get('crop_bottom_pixels', 0)
        
        for i, url in enumerate(images_to_process):
            try:
                self.logger.info(f"--- [图片 {i+1}/{len(images_to_process)}] 开始处理: {url} ---")
                
                # 使用ImageHandler的集成方法处理图片
                qiniu_link = image_handler.process_and_upload_image(url, crop_bottom_pixels=crop_pixels)
                
                if qiniu_link:
                    qiniu_links.append(qiniu_link)
                    self.logger.info(f"图片成功上传到七牛云: {qiniu_link}")
                else:
                    self.logger.warning(f"图片处理或上传失败，跳过: {url}")

            except Exception as e:
                self.logger.error(f"处理单张图片时发生未知错误: {url}, 错误: {e}")
                traceback.print_exc()

        if qiniu_links:
            with open("picture.txt", "w", encoding='utf-8') as f:
                for link in qiniu_links:
                    f.write(f"![Image]({link})\n")
            self.logger.info(f"已将 {len(qiniu_links)} 个七牛云图片链接（Markdown格式）保存到 picture.txt")
        else:
            self.logger.warning("所有图片处理/上传均失败，picture.txt 为空。")

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
                        "homepage": {
                            "search_input": "//*[@id=\"root\"]/div/div[4]/div/div[1]/input",
                            "search_button": "//*[@id=\"root\"]/div/div[4]/div/div[1]/button"
                        },
                        "search_results": {
                            "news_tab": "//*[starts-with(@id, 's-dom-')]/div/div/div[3]/div[1]/a[2]",
                            "article_links": [
                                "/html/body/div[2]/div[2]/div/div/div/div/div/div[1]/div/a",
                                "//div[contains(@class, \"result\")]//a[contains(@href, \"toutiao.com\")]",
                                "//a[contains(@href, \"/article/\")]",
                                "//div[@class=\"result-content\"]//a"
                            ],
                            "next_page_buttons": [
                                "//a[contains(@class, 'cs-button') and .//span[text()='2']]"
                            ]
                        },
                        "article_page": {
                            "content_containers": [
                                "//*[@id=\"root\"]/div[2]/div[2]/div[1]/div/div/div/div/div[2]/article",
                                "//article",
                                "//div[contains(@class, \"article-content\")]",
                                "//div[contains(@class, \"content\")]"
                            ],
                            "title_selectors": [
                                "h1",
                                "h2", 
                                ".title",
                                "[class*=\"title\"]"
                            ],
                            "image_selectors": [
                                "//*[@id=\"root\"]/div[2]/div[2]/div[1]/div/div/div/div/div[2]/article/div/img",
                                "//article//img",
                                "//div[contains(@class, \"content\")]//img",
                                "//img[contains(@src, \"http\")]"
                            ]
                        }
                    },
                    "timeouts": {
                        "page_load": 30,
                        "element_wait": 15,
                        "implicit_wait": 10,
                        "search_delay": 5,
                        "article_delay": 2
                    },
                    "scraping": {
                        "max_articles": 10,
                        "max_pages": 3,
                        "max_images": 5,
                        "delay_between_requests": 2,
                        "content_min_length": 100
                    },
                    "random_delays": {
                        "min_delay": 1,
                        "max_delay": 5
                    }
                }
                
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                
                self.logger.info(f"已创建默认配置文件: {config_file}")
                return default_config
                
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {str(e)}")
            return {}
    
    def navigate_to_toutiao(self):
        """导航到今日头条"""
        try:
            self.browser_manager.navigate_to("https://www.toutiao.com/")
            self.browser_manager.close_other_tabs()  # 清理其他标签页
            time.sleep(3)
            self._check_for_captcha() # 检查首页加载后是否有验证码
            self.logger.info("成功导航到今日头条")
            return True
        except Exception as e:
            self.logger.error(f"导航到今日头条失败: {str(e)}")
            return False
    
    def search_articles(self, keyword, max_articles=5):
        """搜索文章并抓取内容"""
        try:
            self.logger.info(f"搜索关键词: {keyword}")

            # --- 搜索操作 ---
            search_input_selector = self.config['selectors']['homepage']['search_input']
            search_button_selector = self.config['selectors']['homepage']['search_button']
            
            # 找到并激活输入框
            search_input = self.browser_manager.find_element(search_input_selector, timeout=10)
            if not search_input:
                self.logger.error("未找到搜索框")
                return []
            self.logger.info("找到搜索框，先点击激活")
            self.browser_manager.click_element(search_input)
            time.sleep(2)

            # 输入关键词
            self.logger.info(f"输入搜索关键词: {keyword}")
            self.browser_manager.type_text(search_input, keyword, clear_first=False)
            time.sleep(1.5)

            # 点击搜索按钮
            search_button = self.browser_manager.find_element(search_button_selector)
            if not search_button:
                self.logger.error("未找到搜索按钮")
                return []
            
            # --- 标签页切换逻辑 ---
            self.logger.info("准备点击搜索按钮并处理新标签页...")
            tabs_before = self.browser_manager.get_all_tabs()
            tab_ids_before = {tab['id'] for tab in tabs_before} if tabs_before else set()

            self.logger.info("点击搜索按钮")
            self.browser_manager.click_element(search_button)
            time.sleep(3) # 等待新标签页出现

            tabs_after = self.browser_manager.get_all_tabs()
            tab_ids_after = {tab['id'] for tab in tabs_after} if tabs_after else set()

            new_tab_ids = tab_ids_after - tab_ids_before
            if new_tab_ids:
                new_tab_id = new_tab_ids.pop()
                self.logger.info(f"检测到新的搜索结果标签页，ID: {new_tab_id}。正在切换...")
                self.browser_manager.switch_to_tab_by_id(new_tab_id)
                time.sleep(2) # 等待新标签页内容加载
            else:
                self.logger.warning("未检测到新标签页，将继续在当前标签页操作。")

            # --- 后续操作 ---
            # 切换到"资讯"分类（如果需要）
            news_tab_selector = self.config['selectors']['search_results']['news_tab']
            if self.browser_manager.click_element_by_xpath(news_tab_selector):
                self.logger.info("已切换到'资讯'分类。")
                time.sleep(2)
            else:
                self.logger.warning("未能切换到'资讯'分类，可能页面结构已改变或当前已是资讯页。")
            
            # 后续的抓取逻辑...
            articles_data = self._extract_articles_from_current_page(max_articles)
            
            if not articles_data:
                 self.logger.warning("在当前页面未能抓取到任何文章。")

            return articles_data
            
        except Exception as e:
            self.logger.error(f"搜索文章时出错: {e}", exc_info=True)
            return []
    
    def _extract_articles_from_current_page(self, max_count):
        """从当前搜索结果页面抓取文章"""
        try:
            articles = []
            
            # 等待页面完全加载
            time.sleep(2)
            
            # 获取当前所有标签页，确定搜索结果页的位置
            all_tabs = self.browser_manager.get_all_tabs()
            self.logger.info(f"当前共有 {len(all_tabs)} 个标签页")
            
            # 找到搜索结果页（通常包含搜索关键词的页面）
            search_tab_index = None
            for i, tab in enumerate(all_tabs):
                tab_url = tab.get('url', '')
                tab_title = tab.get('title', '')
                if 'so.toutiao.com/search' in tab_url or '头条搜索' in tab_title:
                    search_tab_index = i
                    self.logger.info(f"找到搜索结果页，标签索引: {i}, URL: {tab_url}")
                    break
            
            if search_tab_index is None:
                # 如果没找到，使用最后一个标签页
                search_tab_index = len(all_tabs) - 1
                self.logger.info(f"未找到明确的搜索结果页，使用最后一个标签页，索引: {search_tab_index}")
            
            # 确保在搜索结果页
            if not self.browser_manager.switch_to_tab(search_tab_index):
                self.logger.error("无法切换到搜索结果页")
                return []
            
            time.sleep(1)  # 等待切换完成
            
            # 验证搜索结果是否存在
            self._check_for_captcha() # 验证前检查
            best_selector, result_count = self._verify_search_results_exist()
            
            if not best_selector or result_count == 0:
                self.logger.error("未找到任何搜索结果")
                return []
            
            self.logger.info(f"使用最佳选择器: {best_selector}, 找到 {result_count} 个搜索结果")
            
            # 获取文章链接列表（仅一次）
            result_links = self._get_current_page_article_links()
            if not result_links:
                self.logger.warning("当前页面未找到可处理的文章链接。")
                return []
            
            # 抓取指定数量的文章
            processed_count = 0
            
            while processed_count < max_count and processed_count < len(result_links):
                self.logger.info(f"开始处理第 {processed_count + 1} 个搜索结果")
                
                # 确保在搜索结果页面
                current_tabs = self.browser_manager.get_all_tabs()
                search_result_tab_index = -1
                
                for tab_idx, tab in enumerate(current_tabs):
                    tab_url = tab.get('url', '')
                    tab_title = tab.get('title', '')
                    if 'so.toutiao.com/search' in tab_url or '头条搜索' in tab_title:
                        search_result_tab_index = tab_idx
                        break
                
                if search_result_tab_index == -1:
                    self.logger.error("无法找到搜索结果页面，抓取中断")
                    break
                
                # 切换到搜索结果页面
                if not self.browser_manager.switch_to_tab(search_result_tab_index):
                    self.logger.error("无法切换到搜索结果页面，抓取中断")
                    break
                
                # time.sleep(1) # 优化：移除等待

                current_link_index = processed_count
                
                # 导航并抓取
                navigate_success = self._extract_and_navigate_to_article(current_link_index + 1)
                
                if not navigate_success:
                    self.logger.warning(f"导航到第 {current_link_index + 1} 个结果失败，跳过")
                    processed_count += 1
                    continue
                
                # 切换后，我们应该在新标签页里。等待页面加载
                self.logger.info("等待文章页面加载...")
                time.sleep(2) # 优化：从5秒缩短至2秒

                # 检查文章页是否被验证码挡住
                self._check_for_captcha()

                # 提取文章内容和图片
                article_content = self._extract_article_from_current_page()
                
                if article_content:
                    # 在这里同步提取图片
                    article_content['images'] = self._extract_article_images()
                    articles.append(article_content)
                    self.logger.info(f"成功提取文章: {article_content['title'][:20]}...")
                else:
                    self.logger.warning(f"提取文章内容失败")
                
                # 关闭当前(文章)标签页
                self.logger.info("关闭文章标签页...")
                self.browser_manager.close_current_tab()
                time.sleep(1)
                
                # 切换回搜索结果页
                self.logger.info("正在切换回搜索结果页面...")
                search_tab_index = self.browser_manager.find_tab_by_url("so.toutiao.com/search")
                if search_tab_index != -1:
                    if self.browser_manager.switch_to_tab(search_tab_index):
                        self.logger.info("成功切换回搜索结果页面")
                    else:
                        self.logger.error("切换回搜索结果页面失败，抓取中断")
                        break
                else:
                    self.logger.error("无法找到搜索结果页面，抓取中断")
                    break

                processed_count += 1
                # time.sleep(random.uniform(1, 3)) # 优化：移除随机延时
            
            return articles
            
        except Exception as e:
            self.logger.error(f"从当前页面抓取文章失败: {e}")
            return []
    
    def _get_current_page_article_links(self):
        """获取当前页面的文章链接列表"""
        try:
            # 先验证搜索结果是否存在，获取最佳选择器
            best_selector, result_count = self._verify_search_results_exist()
            
            if not best_selector or result_count == 0:
                self.logger.warning("未找到任何搜索结果")
                return []
            
            # 使用最佳选择器获取所有搜索结果
            result_elements = self.browser_manager.find_elements(best_selector, timeout=5)
            
            if result_elements:
                # 提取链接信息用于验证和记录
                links = []
                for i, element in enumerate(result_elements):
                    try:
                        # 尝试从元素中获取链接信息（如果有的话）
                        link_element = self.browser_manager.find_element(f"({best_selector})[{i+1}]//a[@href]", timeout=2)
                        if link_element:
                            href = self.browser_manager.get_element_attribute(link_element, 'href')
                            if href and 'toutiao.com' in href:
                                links.append(href)
                            else:
                                links.append(f"searchresult_{i+1}")
                        else:
                            # 如果没有找到链接，仍然添加一个占位符，表示这是一个可点击的结果
                            links.append(f"searchresult_{i+1}")
                    except:
                        # 如果获取链接失败，添加占位符
                        links.append(f"searchresult_{i+1}")
                        continue
                
                self.logger.info(f"当前页面找到 {len(links)} 个搜索结果（使用选择器: {best_selector}）")
                return links
            
            return []
            
        except Exception as e:
            self.logger.error(f"获取当前页面文章链接失败: {e}")
            return []
    
    def _get_search_result_count(self):
        """获取搜索结果的数量"""
        try:
            # 使用正确的XPath选择器
            result_selector = "//div[contains(@class, 'cs-header') and contains(@class, 'cs-view-block')]"
            elements = self.browser_manager.find_elements(result_selector, timeout=5)
            
            if elements:
                count = len(elements)
                self.logger.info(f"使用正确选择器找到 {count} 个搜索结果")
                return count
            
            # 如果没找到，尝试备用选择器
            backup_selector = "//div[@data-test-card-id='undefined-default']"
            elements = self.browser_manager.find_elements(backup_selector, timeout=3)
            if elements:
                count = len(elements)
                self.logger.info(f"使用备用选择器找到 {count} 个结果")
                return count
            
            # 最后的备用选择器
            backup_selector2 = "//div[contains(@class, 'cs-result-item')]"
            elements = self.browser_manager.find_elements(backup_selector2, timeout=3)
            if elements:
                count = len(elements)
                self.logger.info(f"使用最后备用选择器找到 {count} 个结果")
                return count
            
            self.logger.warning("未找到任何搜索结果")
            return 0
                
        except Exception as e:
            self.logger.error(f"获取搜索结果数量失败: {e}")
            return 0
    
    def _extract_article_from_current_page(self):
        """从当前文章页面抓取内容"""
        try:
            # 等待页面加载
            time.sleep(2)
            
            # 获取当前页面URL用于记录
            current_url = self.browser_manager.get_current_url()
            self.logger.info(f"正在抓取文章页面: {current_url}")
            
            # 获取文章标题
            title = self._extract_article_title()
            
            # 获取文章内容
            content = self._extract_article_content()
            
            if not content or len(content.strip()) < 50:
                self.logger.warning("文章内容过短或为空，跳过")
                # 检查是否因为验证码
                self._check_for_captcha()
                return None
            
            article_data = {
                'title': title or '无标题',
                'content': content,
                'images': [], # 图片将异步提取
                'url': current_url,
                'extracted_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return article_data
            
        except Exception as e:
            self.logger.error(f"抓取文章内容失败: {e}")
            return None
    
    def _extract_article_title(self):
        """提取文章标题"""
        try:
            # 尝试多个标题选择器（XPath）
            title_selectors = [
                "//h1",
                "//h2",
                "//*[contains(@class, 'title')]",
                "//*[@class='article-title']"
            ]
            
            for selector in title_selectors:
                element = self.browser_manager.find_element(selector, timeout=3)
                if element:
                    title = self.browser_manager.get_element_text(element)
                    if title and title.strip():
                        return title.strip()
            
            return "无标题"
            
        except Exception as e:
            self.logger.error(f"提取标题失败: {e}")
            return "无标题"
    
    def _extract_article_content(self):
        """
        在当前文章页面中提取正文内容。
        该版本采用健壮策略：尝试多种选择器。
        """
        self.logger.info("开始提取文章正文内容...")
        
        # 1. 从配置文件获取内容选择器列表
        selectors = self.config.get('selectors', {}).get('article_page', {}).get('content_containers', [])
        if not selectors:
            self.logger.error("配置文件中未定义 'content_containers'。")
            return None

        # 2. 遍历所有选择器寻找内容
        for selector in selectors:
            try:
                # 使用JS脚本提取文本内容，更稳定
                escaped_selector = selector.replace('"', '\\"')
                js_script = f"""
                (function() {{
                    var element = document.evaluate("{escaped_selector}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    return element ? element.innerText : null;
                }})()
                """
                content = self.browser_manager.execute_script(js_script)

                if content and isinstance(content, str) and len(content.strip()) > 100:
                    self.logger.info(f"使用选择器 '{selector}' 成功提取到长度为 {len(content)} 的内容。")
                    return content.strip()
            except Exception as e:
                self.logger.warning(f"使用选择器 '{selector}' 提取内容时出错: {e}")
                continue
        
        self.logger.error("未能使用任何选择器提取到有效的文章内容。")
        return None
    
    def _extract_article_images(self):
        """
        在当前文章页面中提取所有图片链接。
        该版本恢复了稳健的策略：滚动页面、尝试多种选择器、检查多种属性。
        """
        self.logger.info("开始提取文章图片...")
        image_urls = set()

        # 1. 滚动页面以触发懒加载
        self.logger.info("滚动页面以加载所有图片...")
        self.browser_manager.scroll_to_bottom(steps=15, delay=0.3)
        time.sleep(3)  # 等待图片资源加载

        # 2. 从配置文件获取图片选择器列表
        selectors = self.config.get('selectors', {}).get('article_page', {}).get('image_selectors', [])
        if not selectors:
            self.logger.error("配置文件中未定义 'image_selectors'。")
            return []

        self.logger.info(f"将要尝试的选择器: {selectors}")

        # 3. 遍历所有选择器寻找图片元素
        for selector in selectors:
            try:
                # 使用JS脚本一次性提取所有符合条件的图片URL，效率更高
                escaped_selector = selector.replace('"', '\\"')
                js_script = f"""
                (function() {{
                    const urls = new Set();
                    const query = document.evaluate("{escaped_selector}", document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                    
                    for (let i = 0; i < query.snapshotLength; i++) {{
                        let img = query.snapshotItem(i);
                        // 尝试从多个属性获取URL，这是处理懒加载的关键
                        for (const attr of ['src', 'data-src', 'data-original', 'data-original-src']) {{
                            let url = img.getAttribute(attr);
                            if (url && url.startsWith('http')) {{
                                // 清洗URL，去掉查询参数
                                const cleanedUrl = url.split('?')[0];
                                if (cleanedUrl.endsWith('.jpg') || cleanedUrl.endsWith('.jpeg') || cleanedUrl.endsWith('.png') || cleanedUrl.endsWith('.gif')) {{
                                    urls.add(cleanedUrl);
                                    break; // 找到有效URL后，不再检查此元素的其他属性
                                }}
                            }}
                        }}
                    }}
                    return Array.from(urls);
                }})()
                """
                urls_from_script = self.browser_manager.execute_script(js_script)
                
                if urls_from_script:
                    self.logger.info(f"使用选择器 '{selector}' 找到了 {len(urls_from_script)} 张图片。")
                    image_urls.update(urls_from_script)

            except Exception as e:
                self.logger.warning(f"使用选择器 '{selector}' 时出错: {e}")
                continue
        
        if not image_urls:
            self.logger.warning("未能通过任何选择器提取到有效的图片URL。")
        
        final_urls = list(image_urls)
        self.logger.info(f"提取结束，共找到 {len(final_urls)} 张不重复的图片。")
        return final_urls
    
    def _go_to_next_page(self):
        """翻到下一页"""
        try:
            # 首先获取当前页码
            current_page = self._get_current_page_number()
            next_page = current_page + 1
            
            self.logger.info(f"当前页码: {current_page}, 尝试翻到第 {next_page} 页")
            
            # 构建下一页的选择器
            next_page_selector = f"//a[contains(@class, 'cs-button') and .//span[text()='{next_page}']]"
            
            # 尝试找到下一页按钮
            next_button = self.browser_manager.find_element(next_page_selector, timeout=5)
            if next_button:
                self.logger.info(f"找到第 {next_page} 页按钮，点击翻页")
                if self.browser_manager.click_element(next_button):
                    time.sleep(3)
                    # 验证是否成功翻页
                    new_page = self._get_current_page_number()
                    if new_page > current_page:
                        self.logger.info(f"成功翻页到第 {new_page} 页")
                        return True
                    else:
                        self.logger.warning("点击翻页按钮后页码未变化")
                        return False
                else:
                    self.logger.warning("点击翻页按钮失败")
            else:
                self.logger.info(f"未找到第 {next_page} 页按钮，可能已到最后一页")
            
            # 备用方案：尝试通用的下一页按钮
            fallback_selectors = [
                "//a[contains(text(), '下一页')]",
                "//button[contains(text(), '下一页')]",
                "//a[contains(@class, 'next')]",
                "//button[contains(@class, 'next')]"
            ]
            
            for selector in fallback_selectors:
                next_button = self.browser_manager.find_element(selector, timeout=3)
                if next_button:
                    self.logger.info("找到通用下一页按钮，尝试点击")
                    if self.browser_manager.click_element(next_button):
                        time.sleep(3)
                        new_page = self._get_current_page_number()
                        if new_page > current_page:
                            self.logger.info(f"使用通用按钮成功翻页到第 {new_page} 页")
                            return True
            
            self.logger.info("无法翻页，可能已到最后一页")
            return False
            
        except Exception as e:
            self.logger.error(f"翻页失败: {e}")
            return False

    def _get_current_page_number(self):
        """获取当前页码"""
        try:
            # 尝试从URL中获取页码
            current_url = self.browser_manager.get_current_url()
            if 'page=' in current_url:
                import re
                match = re.search(r'page=(\d+)', current_url)
                if match:
                    return int(match.group(1))
            
            # 如果URL中没有页码信息，默认返回1
            return 1
            
        except Exception as e:
            self.logger.error(f"获取页码失败: {e}")
            return 1
    
    def get_article_links(self):
        """获取文章链接列表"""
        try:
            article_links_selector = self.config.get('selectors', {}).get('article_links', 'a[href*="/article/"]')
            
            script = f"""
            var links = document.querySelectorAll('{article_links_selector}');
            var urls = [];
            
            links.forEach(function(link) {{
                var href = link.href;
                if (href && href.includes('/article/') && !urls.includes(href)) {{
                    urls.push(href);
                }}
            }});
            
            return urls;
            """
            
            urls = self.browser_manager.execute_script(script)
            
            if urls:
                self.logger.info(f"找到 {len(urls)} 个文章链接")
                return urls[:self.config.get('scraping', {}).get('max_articles', 10)]
            else:
                self.logger.warning("未找到文章链接")
                return []
                
        except Exception as e:
            self.logger.error(f"获取文章链接失败: {str(e)}")
            return []
    
    def extract_article_content(self, url):
        """提取文章内容"""
        try:
            self.logger.info(f"提取文章内容: {url}")
            
            # 导航到文章页面
            self.browser_manager.navigate_to(url)
            time.sleep(3)
            
            # 提取标题
            title_selector = self.config.get('selectors', {}).get('article_title', 'h1, .article-title, [class*="title"]')
            title_script = f"""
            var titleElement = document.querySelector('{title_selector}');
            return titleElement ? titleElement.textContent.trim() : '';
            """
            title = self.browser_manager.execute_script(title_script)
            
            # 提取内容
            content_selector = self.config.get('selectors', {}).get('article_content', '.article-content, [class*="content"], .article-body')
            content_script = f"""
            var contentElements = document.querySelectorAll('{content_selector}');
            var content = '';
            
            contentElements.forEach(function(element) {{
                content += element.textContent + '\\n';
            }});
            
            return content.trim();
            """
            content = self.browser_manager.execute_script(content_script)
            
            # 检查内容长度
            min_length = self.config.get('scraping', {}).get('content_min_length', 100)
            if len(content) < min_length:
                self.logger.warning(f"文章内容过短，跳过: {len(content)} 字符")
                return None
            
            article_data = {
                'url': url,
                'title': title or '无标题',
                'content': content,
                'extracted_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.logger.info(f"文章提取成功: {title[:50]}...")
            return article_data
            
        except Exception as e:
            self.logger.error(f"提取文章内容失败: {str(e)}")
            return None
    
    def collect_content(self, keyword):
        """收集内容的主要方法"""
        try:
            self.logger.info(f"开始收集内容: {keyword}")
            self.collected_articles = []
            self.collected_images = []
            
            # 检查当前是否在今日头条页面，如果不是则导航
            current_url = self.browser_manager.get_current_url()
            if 'toutiao.com' not in current_url:
                self.logger.info("当前不在今日头条页面，开始导航")
                if not self.navigate_to_toutiao():
                    return False
            else:
                self.logger.info(f"当前已在今日头条页面: {current_url}")
            
            # 搜索并抓取文章
            max_articles = self.config.get('scraping', {}).get('max_articles', 5)
            articles = self.search_articles(keyword, max_articles)
            
            if not articles:
                self.logger.warning("未找到相关文章")
                return False
            
            # 保存抓取的文章
            self.collected_articles = articles
            
            # 收集所有图片
            all_images = []
            for article in articles:
                if article.get('images'):
                    all_images.extend(article['images'])
            
            # 去重并根据配置限制总数
            unique_images = list(set(all_images))
            max_images_total = self.config.get('scraping', {}).get('max_images', 5)
            self.collected_images = unique_images[:max_images_total]
            
            self.logger.info(f"内容收集完成，成功抓取 {len(self.collected_articles)} 篇文章，找到 {len(unique_images)} 张不重复图片，按配置保存 {len(self.collected_images)} 张。")
            return True
            
        except Exception as e:
            self.logger.error(f"收集内容失败: {str(e)}")
            return False
    
    def save_articles(self, output_file):
        """保存文章到文件,只保留正文内容并分段"""
        try:
            if not self.collected_articles:
                self.logger.warning("没有文章可保存")
                return False
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # 保存文章
            with open(output_file, 'w', encoding='utf-8') as f:
                for i, article in enumerate(self.collected_articles, 1):
                    # 只写入正文内容
                    f.write(article.get('content', '').strip())
                    # 用分隔符区分不同的文章
                    if i < len(self.collected_articles):
                        f.write("\n\n---\n\n")
            
            self.logger.info(f"文章内容已保存到: {output_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"保存文章失败: {str(e)}")
            return False
    
    def cleanup(self):
        """清理资源"""
        try:
            self.collected_articles = []
            self.collected_images = []
            # CDP浏览器管理器会统一清理
            self.logger.info("今日头条抓取器(CDP版本)清理完成")
        except Exception as e:
            self.logger.warning(f"清理资源时出现异常: {str(e)}")
    
    def _verify_search_results_exist(self):
        """验证搜索结果是否存在"""
        try:
            # 等待页面稳定
            time.sleep(2)
            
            # 检查多个可能的选择器
            selectors = [
                "//div[contains(@class, 'cs-header') and contains(@class, 'cs-view-block')]",
                "//div[@data-test-card-id='undefined-default']",
                "//div[contains(@class, 'cs-result-item')]",
                "//div[contains(@class, 'result')]"
            ]
            
            for i, selector in enumerate(selectors):
                elements = self.browser_manager.find_elements(selector, timeout=3)
                if elements:
                    self.logger.info(f"选择器 {i+1} 找到 {len(elements)} 个搜索结果: {selector}")
                    
                    # 打印前几个元素的信息用于调试
                    for j, element in enumerate(elements[:3]):
                        try:
                            # 尝试获取元素的文本内容
                            text = self.browser_manager.get_element_text(element)
                            if text:
                                self.logger.info(f"  结果 {j+1}: {text[:100]}...")
                            else:
                                self.logger.info(f"  结果 {j+1}: 无文本内容")
                        except:
                            self.logger.info(f"  结果 {j+1}: 无法获取文本")
                    
                    return selector, len(elements)
                else:
                    self.logger.warning(f"选择器 {i+1} 未找到元素: {selector}")
            
            self.logger.error("所有选择器都未找到搜索结果")
            return None, 0
            
        except Exception as e:
            self.logger.error(f"验证搜索结果存在时出错: {e}")
            return None, 0
    
    def _extract_and_navigate_to_article(self, index):
        """提取搜索结果链接并导航到文章页面"""
        try:
            # 动态获取当前页面的最佳选择器
            best_selector, result_count = self._verify_search_results_exist()
            
            if not best_selector or result_count == 0:
                self.logger.error(f"无法获取搜索结果选择器")
                return False
            
            if index > result_count:
                self.logger.error(f"要处理的索引 {index} 超出了搜索结果数量 {result_count}")
                return False
            
            # 提取链接URL
            link_xpath = f"({best_selector})[{index}]//a[@href]"
            link_element = self.browser_manager.find_element(link_xpath, timeout=10)
            
            if not link_element:
                self.logger.error(f"无法找到第 {index} 个搜索结果的链接")
                return False
            
            # 使用JavaScript直接获取链接的href属性
            get_href_script = f"""
            (function() {{
                var elements = document.evaluate("{link_xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                var element = elements.singleNodeValue;
                if (element && element.href) {{
                    return element.href;
                }}
                return null;
            }})()
            """
            
            eval_result = self.browser_manager.execute_script(get_href_script)
            if not eval_result:
                self.logger.error(f"无法获取第 {index} 个搜索结果的链接地址")
                return False
            
            href = eval_result
            self.logger.info(f"第 {index} 个搜索结果链接: {href}")
            
            # 解析跳转链接，提取真实的文章URL
            if href.startswith('/search/jump?url='):
                # 提取URL参数中的真实链接
                import urllib.parse
                parsed = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qs(parsed.query)
                if 'url' in query_params:
                    real_url = urllib.parse.unquote(query_params['url'][0])
                    self.logger.info(f"提取到真实文章URL: {real_url}")
                    
                    # 在新标签页中打开文章
                    success = self.browser_manager.open_new_tab(real_url)
                    if success:
                        self.logger.info(f"成功在新标签页中打开第 {index} 个搜索结果")
                        return True
                    else:
                        self.logger.error(f"无法在新标签页中打开第 {index} 个搜索结果")
                        return False
            else:
                # 如果不是跳转链接，直接使用原链接
                if href.startswith('/'):
                    # 相对链接，补充域名
                    href = 'https://so.toutiao.com' + href
                
                success = self.browser_manager.open_new_tab(href)
                if success:
                    self.logger.info(f"成功在新标签页中打开第 {index} 个搜索结果（直接链接）")
                    return True
                else:
                    self.logger.error(f"无法在新标签页中打开第 {index} 个搜索结果（直接链接）")
                    return False
            
        except Exception as e:
            self.logger.error(f"提取并导航到第 {index} 个搜索结果时出错: {e}")
            return False 

    def _check_for_captcha(self):
        """检查并处理机器人验证"""
        try:
            captcha_iframe_xpath = "//*[@id='pc_captcha']/iframe"
            iframe_element = self.browser_manager.find_element(captcha_iframe_xpath, timeout=3)
            if iframe_element:
                self.logger.critical("检测到机器人验证码！程序已暂停。")
                self.logger.critical("请在打开的浏览器窗口中手动完成验证，然后回到这里按Enter键继续...")
                input("手动处理验证码后，请按Enter键继续...")
                self.logger.info("接收到用户输入，程序将继续执行。")
                # 验证后给予页面一点时间恢复
                time.sleep(5)
                return True
        except Exception as e:
            # 查找元素超时也意味着没有验证码
            return False
        return False

    def _clear_file(self, filename):
        """清空指定文件内容"""
        if os.path.exists(filename):
            try:
                open(filename, 'w').close()
                self.logger.info(f"已清空文件: {filename}")
            except Exception as e:
                self.logger.error(f"清空文件 {filename} 时出错: {e}")