import os
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from playwright.async_api import Page
from .browser_manager import BrowserManager
from .image_handler import ImageHandler
from .qiniu_config import QiniuConfig
import traceback


class ToutiaoScraper:
    """基于Playwright的今日头条抓取器"""
    
    def __init__(self, gui_config: Dict[str, Any], browser_manager: BrowserManager):
        self.browser_manager = browser_manager
        self.setup_logging()
        
        # 加载基础配置文件
        local_config = self.load_config('toutiao_config.json')
        
        # 显式地、安全地合并GUI配置，避免覆盖复杂字典
        simple_keys_to_update = ['article_count', 'image_count']
        for key in simple_keys_to_update:
            if key in gui_config:
                local_config[key] = gui_config[key]
        
        self.config = local_config
        self.logger.info("今日头条抓取器初始化完成")
    
    def setup_logging(self):
        """设置日志配置"""
        self.logger = logging.getLogger('modules.toutiao_scraper')
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False
    
    async def scrape_articles_and_images(self, keyword: str, scrape_articles: bool = True, scrape_images: bool = True) -> bool:
        """
        公开的主方法，用于根据需要抓取文章和/或图片链接。
        """
        try:
            if not await self.navigate_to_toutiao():
                self.logger.error("无法打开今日头条首页，抓取任务中止。")
                return False

            if scrape_articles:
                self._clear_file("article.txt")
            if scrape_images:
                self._clear_file("picture.txt")

            articles_data = await self.search_articles(keyword, self.config.get('article_count', 5))
            
            if not articles_data:
                self.logger.warning(f"未能根据关键词 '{keyword}' 抓取到任何文章数据。")
                return False

            if scrape_articles:
                self._save_articles_content(articles_data)

            if scrape_images:
                await self._save_images_links(articles_data)
            
            self.logger.info("头条抓取工作流程成功完成。")
            return True

        except Exception as e:
            self.logger.error(f"头条抓取工作流程执行失败: {str(e)}", exc_info=True)
            return False

    def _save_articles_content(self, articles_data: List[Dict[str, Any]]):
        """从抓取的数据中提取并保存文章内容。"""
        article_texts = [article['content'] for article in articles_data if article.get('content')]
        if article_texts:
            with open("article.txt", "w", encoding='utf-8') as f:
                f.write("\n\n---\n\n".join(article_texts))
            self.logger.info(f"已将 {len(article_texts)} 篇文章内容保存到 article.txt")
        else:
            self.logger.info("抓取到的文章内容为空。")

    async def _save_images_links(self, articles_data: List[Dict[str, Any]]):
        """
        从抓取的数据中提取、处理图片并保存七牛云链接。
        """
        all_images_with_referer = [img for article in articles_data for img in article.get('images_with_referer', [])]
        max_images = self.config.get('image_count', 3)
        images_to_process = all_images_with_referer[:max_images]

        if not images_to_process:
            self.logger.info("未抓取到任何图片链接。")
            return

        qiniu_loader = QiniuConfig()
        is_valid, message = qiniu_loader.validate()
        if not is_valid:
            self.logger.warning(message)
            return

        qiniu_config = qiniu_loader.get_config()
        # 只传递ImageHandler需要的参数
        image_handler_config = {
            'access_key': qiniu_config.get('access_key'),
            'secret_key': qiniu_config.get('secret_key'),
            'bucket_name': qiniu_config.get('bucket_name'),
            'domain': qiniu_config.get('domain')
        }
        image_handler = ImageHandler(**image_handler_config)
        
        qiniu_links = []
        crop_pixels = self.config.get('scraping', {}).get('crop_bottom_pixels', 80)
        self.logger.info(f"图片处理：将从每张图片底部裁剪 {crop_pixels} 像素。")
        
        for i, image_data in enumerate(images_to_process):
            try:
                url, referer = image_data['url'], image_data['referer']
                self.logger.info(f"--- [图片 {i+1}/{len(images_to_process)}] 开始处理: {url} ---")
                qiniu_link = image_handler.process_and_upload_image(url, crop_bottom_pixels=crop_pixels, referer=referer)
                if qiniu_link:
                    qiniu_links.append(qiniu_link)
                    self.logger.info(f"图片成功上传到七牛云: {qiniu_link}")
                else:
                    self.logger.warning(f"图片处理或上传失败，跳过: {url}")
            except Exception as e:
                self.logger.error(f"处理单张图片时发生未知错误: {url}, 错误: {e}", exc_info=True)

        if qiniu_links:
            markdown_links = [f"![Image]({link})" for link in qiniu_links]
            with open("picture.txt", "w", encoding='utf-8') as f:
                f.write("\n".join(markdown_links))
            self.logger.info(f"已将 {len(qiniu_links)} 个七牛云图片链接（Markdown格式）保存到 picture.txt")
        else:
            self.logger.warning("所有图片处理/上传均失败，picture.txt 为空。")

    def load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            
            self.logger.info(f"配置文件 {config_file} 不存在，将创建并使用默认配置。")
            default_config = {
                "selectors": {
                    "homepage": {"search_input": "input[type='search']", "search_button": "button[type='submit']"},
                    "search_results": {
                        "news_tab": "div[role='tablist'] a:has-text('资讯')", 
                        "article_links": ["div.cs-view a[href*='/article/']", "//div[contains(@class, 'result')]//a[contains(@href, 'toutiao.com')]"],
                        "next_page_button": "button:has-text('下一页')"
                    },
                    "article_page": {"content_containers": ["article", "div.article-content"], "title_selectors": ["h1.article-title", "h1"], "image_selectors": ["article img", "div.pgc-img img"]}
                },
                "timeouts": {"page_load": 30, "element_wait": 15, "search_delay": 5, "article_delay": 2},
                "scraping": {"max_articles": 10, "max_pages": 5, "max_images": 5, "delay_between_requests": 2, "content_min_length": 100, "crop_bottom_pixels": 80}
            }
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
            return default_config
                
        except Exception as e:
            self.logger.error(f"加载或创建配置文件失败: {str(e)}")
            return {}
    
    async def navigate_to_toutiao(self) -> bool:
        """导航到今日头条"""
        try:
            await self.browser_manager.navigate("https://www.toutiao.com/")
            # 检查是否有验证码
            has_verification = await self._check_for_captcha()
            if has_verification:
                self.logger.info("已处理人工验证，继续执行...")
            self.logger.info("成功导航到今日头条")
            return True
        except Exception as e:
            self.logger.error(f"导航到今日头条失败: {e}", exc_info=True)
            return False
    
    async def search_articles(self, keyword: str, max_articles: int = 5) -> List[Dict[str, Any]]:
        """
        使用Playwright进行搜索和抓取，并处理翻页，直到满足数量要求。
        """
        self.logger.info(f"开始搜索关键词: '{keyword}', 目标文章数: {max_articles}")
        page = self.browser_manager.page
        if not page:
            self.logger.error("主页面未初始化。")
            return []

        # 1. 执行初始搜索，进入搜索结果页
        selectors = self.config.get('selectors', {})
        search_results_page = None
        try:
            self.logger.info("准备在原始页面执行搜索...")
            async with page.context.expect_page() as new_page_info:
                # 使用修复后的元素定位方法
                search_input_selector = selectors['homepage']['search_input']
                search_button_selector = selectors['homepage']['search_button']
                
                # 支持XPath选择器
                if search_input_selector.startswith('//') or search_input_selector.startswith('/'):
                    search_input = page.locator(f"xpath={search_input_selector}")
                else:
                    search_input = page.locator(search_input_selector)
                
                if search_button_selector.startswith('//') or search_button_selector.startswith('/'):
                    search_button = page.locator(f"xpath={search_button_selector}")
                else:
                    search_button = page.locator(search_button_selector)
                
                await search_input.fill(keyword)
                await search_button.click()
            
            search_results_page = await new_page_info.value
            await search_results_page.wait_for_load_state()
            self.logger.info("已捕获搜索结果新标签页。")
            
            # 在搜索结果页面也检查验证码
            current_page = self.browser_manager.page
            self.browser_manager.page = search_results_page  # 临时切换页面进行检查
            has_verification = await self._check_for_captcha()
            self.browser_manager.page = current_page  # 恢复原页面
            
            if has_verification:
                self.logger.info("搜索结果页面验证已处理，继续执行...")

            # 点击资讯标签
            news_tab_selector = selectors['search_results']['news_tab']
            if news_tab_selector.startswith('//') or news_tab_selector.startswith('/'):
                news_tab = search_results_page.locator(f"xpath={news_tab_selector}")
            else:
                news_tab = search_results_page.locator(news_tab_selector)
            
            await news_tab.click()
            self.logger.info("已点击'资讯'标签，等待文章列表加载...")
            await asyncio.sleep(2)

            # 2. 循环抓取和翻页
            all_articles_data = []
            page_count = 0
            max_pages_to_scrape = self.config.get('scraping', {}).get('max_pages', 5)

            while len(all_articles_data) < max_articles and page_count < max_pages_to_scrape:
                page_count += 1
                self.logger.info(f"--- 开始抓取第 {page_count} 页 ---")
                
                # 传递剩余需要抓取的数量，但_scrape_current_page会尝试抓取当前页面所有链接
                remaining_needed = max_articles - len(all_articles_data)
                new_data = await self._scrape_current_page(search_results_page, remaining_needed)
                if new_data:
                    all_articles_data.extend(new_data)
                    self.logger.info(f"第 {page_count} 页成功抓取 {len(new_data)} 篇文章，总计: {len(all_articles_data)}/{max_articles}")
                else:
                    self.logger.warning(f"第 {page_count} 页没有抓取到任何有效文章")
                
                if len(all_articles_data) >= max_articles:
                    self.logger.info(f"已成功抓取 {len(all_articles_data)} 篇文章，达到目标数量。")
                    break
                
                # 尝试翻页
                next_button_selectors = selectors.get('search_results', {}).get('next_page_buttons')
                if not next_button_selectors:
                    self.logger.warning("配置中未找到'下一页'按钮选择器，停止翻页。")
                    break

                # 尝试每个可能的下一页按钮选择器
                next_button_found = False
                for next_button_selector in next_button_selectors:
                    try:
                        if next_button_selector.startswith('//') or next_button_selector.startswith('/'):
                            next_button = search_results_page.locator(f"xpath={next_button_selector}")
                        else:
                            next_button = search_results_page.locator(next_button_selector)
                        
                        if await next_button.is_visible():
                            self.logger.info(f"点击'下一页'按钮... (使用选择器: {next_button_selector})")
                            await next_button.click()
                            await search_results_page.wait_for_load_state('domcontentloaded')
                            await asyncio.sleep(3) # 等待页面内容刷新
                            next_button_found = True
                            break
                    except Exception as e:
                        self.logger.debug(f"尝试下一页按钮选择器失败: {next_button_selector}, 错误: {e}")
                        continue
                
                if not next_button_found:
                    self.logger.info("未找到可用的'下一页'按钮，抓取结束。")
                    break
            
            return all_articles_data

        except Exception as e:
            self.logger.error(f"搜索文章时发生错误: {e}", exc_info=True)
            return []
        finally:
            if search_results_page and not search_results_page.is_closed():
                await search_results_page.close()
                self.logger.info("搜索结果标签页已关闭。")

    async def _scrape_current_page(self, page: Page, max_count: int) -> List[Dict[str, Any]]:
        """从当前页面提取文章数据，会依次尝试配置文件中提供的多个选择器。"""
        possible_selectors = self.config.get('selectors', {}).get('search_results', {}).get('article_links')
        
        if not isinstance(possible_selectors, list):
            self.logger.error("配置错误：'article_links' 应该是一个选择器列表（list）。")
            return []

        # 找到第一个有效的选择器
        valid_selector = None
        count = 0
        for selector in possible_selectors:
            self.logger.info(f"正在尝试使用选择器: {selector}")
            try:
                # 支持XPath选择器
                if selector.startswith('//') or selector.startswith('/'):
                    await page.wait_for_selector(f"xpath={selector}", state='attached', timeout=5000)
                    count = await page.locator(f"xpath={selector}").count()
                else:
                    await page.wait_for_selector(selector, state='attached', timeout=5000)
                    count = await page.locator(selector).count()
                
                if count > 0:
                    self.logger.info(f"选择器 '{selector}' 成功找到 {count} 个链接。")
                    valid_selector = selector
                    break
            except Exception:
                self.logger.warning(f"选择器 '{selector}' 失败或超时，尝试下一个。")
        
        if not valid_selector:
            self.logger.error("所有备选选择器都未能找到文章链接。")
            return []

        try:
            # 修复逻辑：先尝试抓取当前页面的所有链接，而不是只抓取max_count个
            all_articles_data = []
            self.logger.info(f"当前页面共找到 {count} 个链接，将逐个尝试抓取（跳过内容太短的文章）。")

            for i in range(count):  # 遍历所有链接，而不是限制数量
                # 如果已经抓取到足够的文章，停止抓取
                if len(all_articles_data) >= max_count:
                    self.logger.info(f"已抓取到 {len(all_articles_data)} 篇有效文章，达到当前页面目标数量。")
                    break
                    
                self.logger.info(f"--- 准备处理第 {i + 1}/{count} 个链接 ---")
                
                # 在每次交互前重新定位元素，确保获取到的是最新的状态
                if valid_selector.startswith('//') or valid_selector.startswith('/'):
                    current_link_locator = page.locator(f"xpath={valid_selector}").nth(i)
                else:
                    current_link_locator = page.locator(valid_selector).nth(i)
                
                # 等待元素可见
                try:
                    await current_link_locator.wait_for(state='visible', timeout=10000)
                except Exception as e:
                    self.logger.warning(f"第 {i+1} 个链接元素不可见，跳过: {e}")
                    continue
                
                href = await current_link_locator.get_attribute('href')
                if not href:
                    self.logger.warning(f"第 {i+1} 个链接没有href属性，跳过。")
                    continue
                
                # 处理相对链接
                if href.startswith('/'):
                    href = f"https://www.toutiao.com{href}"
                elif not href.startswith('http'):
                    href = f"https://www.toutiao.com/{href}"
                
                self.logger.info(f"第 {i+1} 个链接地址: {href}")

                # 点击链接，并等待新页面
                try:
                    async with page.context.expect_page(timeout=30000) as article_page_info:
                        # 滚动到元素并点击
                        await current_link_locator.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await current_link_locator.click()
                    
                    article_page = await article_page_info.value
                    await article_page.wait_for_load_state()
                    self.logger.info("已捕获文章详情新标签页。")
                except Exception as e:
                    self.logger.error(f"点击第 {i+1} 个链接失败: {e}")
                    continue

                try:
                    # 在新标签页中提取内容
                    article_data = await self.extract_article_content(article_page, article_page.url)
                    if article_data:
                        all_articles_data.append(article_data)
                finally:
                    # 确保文章页被关闭
                    if not article_page.is_closed():
                        await article_page.close()
                        self.logger.info("文章详情标签页已关闭，返回搜索结果页。")
                
                await asyncio.sleep(self.config.get('scraping', {}).get('delay_between_requests', 2))

            return all_articles_data
        
        except Exception as e:
            self.logger.error(f"从结果页面提取文章链接时出错: {e}", exc_info=True)
            return []
    
    async def extract_article_content(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """在新标签页中打开文章并提取内容"""
        try:
            # 直接使用已经打开的页面，不需要再次导航
            await page.wait_for_load_state('domcontentloaded', timeout=20000)
            await asyncio.sleep(self.config.get('timeouts', {}).get('article_delay', 2))

            title = await self._extract_text_by_selectors(page, self.config['selectors']['article_page']['title_selectors'])
            content = await self._extract_text_by_selectors(page, self.config['selectors']['article_page']['content_containers'])
            images = await self._extract_article_images_with_referer(page, self.config['selectors']['article_page']['image_selectors'])
            
            self.logger.info(f"在页面 {url} 提取到 - 标题: '{title[:20] if title else 'N/A'}...', 内容长度: {len(content)}, 图片数量: {len(images)}")

            if content and len(content) > self.config.get('scraping', {}).get('content_min_length', 100):
                return {
                    'url': url,
                    'title': title or '无标题',
                    'content': content,
                    'images_with_referer': images
                }
            else:
                self.logger.warning(f"文章内容太短或为空，跳过: {url}")
                return None
        except Exception as e:
            self.logger.error(f"提取文章内容失败: {url}, 错误: {e}", exc_info=True)
            return None

    async def _extract_text_by_selectors(self, page: Page, selectors: List[str]) -> str:
        """根据选择器列表提取第一个匹配的文本内容。"""
        for selector in selectors:
            try:
                # 支持XPath选择器  
                if selector.startswith('//') or selector.startswith('/'):
                    locator = page.locator(f"xpath={selector}").first
                else:
                    locator = page.locator(selector).first
                    
                if await locator.is_visible(timeout=2000):
                    text = await locator.inner_text()
                    if text and text.strip():
                        # 清理文本内容，移除图片相关的备注
                        cleaned_text = self._clean_article_text(text.strip())
                        return cleaned_text
            except Exception as e:
                self.logger.debug(f"选择器 {selector} 提取文本失败: {e}")
                continue
        return ""
    
    def _clean_article_text(self, text: str) -> str:
        """清理文章文本，移除图片备注等无关内容"""
        import re
        
        # 移除常见的图片备注文字 - 使用句子边界来精确匹配
        patterns_to_remove = [
            r'图片来源于网络[，。、]*[^。！？\n]*[。！？]?',
            r'图片来源：[^。！？\n]*[。！？]?',
            r'图源：[^。！？\n]*[。！？]?',
            r'配图来源[^。！？\n]*[。！？]?',
            r'（图片来源[^）]*）',
            r'\(图片来源[^)]*\)',
            r'【图片来源[^】]*】',
            r'图片版权归[^。！？\n]*[。！？]?',
            r'图片仅供参考[^。！？\n]*[。！？]?',
            r'图片与内容无关[^。！？\n]*[。！？]?',
            r'图片为配图[^。！？\n]*[。！？]?',
            r'网络配图[。！？]?',
            r'图片来自网络[^。！？\n]*[。！？]?',
            r'图片素材来源[^。！？\n]*[。！？]?',
            r'图片来源网络[^。！？\n]*[。！？]?',
            r'图片来源：网络[^。！？\n]*[。！？]?',
            r'图片来源于网络，如有侵权请联系删除[^。！？\n]*[。！？]?',
            r'图片来源网络，如有侵权请联系删除[^。！？\n]*[。！？]?',
            r'图片来源于网络，侵删[^。！？\n]*[。！？]?',
            r'图片来源网络，侵删[^。！？\n]*[。！？]?'
        ]
        
        cleaned_text = text
        for pattern in patterns_to_remove:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
        
        # 清理空的括号和方括号
        cleaned_text = re.sub(r'（\s*）', '', cleaned_text)
        cleaned_text = re.sub(r'【\s*】', '', cleaned_text)
        cleaned_text = re.sub(r'\(\s*\)', '', cleaned_text)
        cleaned_text = re.sub(r'\[\s*\]', '', cleaned_text)
        
        # 修复因删除内容导致的语法问题
        cleaned_text = re.sub(r'(\w+)（\s*(\w+)', r'\1\2', cleaned_text)
        
        # 清理标点符号
        cleaned_text = re.sub(r'[，。、]*\s*[，。、]+', '，', cleaned_text)
        cleaned_text = re.sub(r'，\s*。', '。', cleaned_text)
        cleaned_text = re.sub(r'，\s*，', '，', cleaned_text)
        cleaned_text = re.sub(r'。\s*。', '。', cleaned_text)
        
        # 清理空格和换行
        cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
        cleaned_text = re.sub(r'[ \t]+', ' ', cleaned_text)
        
        # 移除开头和结尾的多余标点
        cleaned_text = re.sub(r'^[，。、\s]+', '', cleaned_text)
        cleaned_text = re.sub(r'[，。、\s]+$', '', cleaned_text)
        
        # 确保句子以正确的标点结尾
        if cleaned_text and not cleaned_text.endswith(('。', '！', '？')):
            cleaned_text += '。'
        
        return cleaned_text.strip()
    
    async def _extract_article_images_with_referer(self, page: Page, selectors: List[str]) -> List[Dict[str, str]]:
        """根据选择器列表提取所有匹配的图片链接。"""
        images = []
        referer_url = page.url
        for selector in selectors:
            try:
                # 支持XPath选择器
                if selector.startswith('//') or selector.startswith('/'):
                    locator = page.locator(f"xpath={selector}")
                else:
                    locator = page.locator(selector)
                
                # 检查选择器本身是否存在于页面上
                if await locator.count() > 0:
                    for img_locator in await locator.all():
                        try:
                            if src := await img_locator.get_attribute('src'):
                                if src.startswith('http'):
                                    images.append({'url': src, 'referer': referer_url})
                                elif src.startswith('//'):
                                    images.append({'url': f'https:{src}', 'referer': referer_url})
                        except Exception as e:
                            self.logger.debug(f"提取图片链接失败: {e}")
                            continue
                    # 如果这个选择器找到了图片，就没必要再试其他的了
                    if images:
                        return images
            except Exception as e:
                self.logger.debug(f"选择器 {selector} 查找图片失败: {e}")
                continue
        return images
    
    async def cleanup(self):
        """执行清理操作"""
        self.logger.info("ToutiaoScraper正在执行清理操作...")
        if self.browser_manager:
            await self.browser_manager.cleanup()

    async def _check_for_captcha(self):
        """检查页面是否出现验证码或人工验证"""
        try:
            page = self.browser_manager.page
            if not page:
                return
            
            # 从配置文件获取验证选择器
            verification_selectors = self.config.get('verification', {}).get('selectors', [])
            
            self.logger.info("正在检查是否出现人工验证...")
            
            for selector in verification_selectors:
                try:
                    if selector.startswith('//') or selector.startswith('/'):
                        locator = page.locator(f"xpath={selector}")
                    else:
                        locator = page.locator(selector)
                    
                    if await locator.is_visible(timeout=2000):
                        self.logger.warning(f"🚨 检测到人工验证元素: {selector}")
                        await self._handle_manual_verification(selector)
                        return True
                        
                except Exception as e:
                    self.logger.debug(f"检查验证元素 {selector} 时出错: {e}")
                    continue
            
            self.logger.info("✅ 未检测到人工验证，继续执行...")
            return False
            
        except Exception as e:
            self.logger.error(f"检查验证码时出现异常: {e}")
            return False

    async def _handle_manual_verification(self, detected_selector: str):
        """处理人工验证"""
        self.logger.warning("=" * 60)
        self.logger.warning("🚨 检测到今日头条人工验证！")
        self.logger.warning(f"检测到的验证元素: {detected_selector}")
        self.logger.warning("=" * 60)
        self.logger.warning("📋 请按以下步骤操作：")
        self.logger.warning("1. 在浏览器中完成人工验证（滑块、点击图片等）")
        self.logger.warning("2. 等待验证通过，页面正常显示")
        self.logger.warning("3. 完成后在控制台按回车键继续...")
        self.logger.warning("=" * 60)
        
        # 暂停执行，等待用户手动处理
        try:
            input("⌨️  请完成验证后按回车键继续...")
            self.logger.info("✅ 用户确认已完成验证，继续执行...")
            
            # 等待验证完成后页面加载
            await asyncio.sleep(3)
            
            # 再次检查验证是否真的完成了
            page = self.browser_manager.page
            if detected_selector.startswith('//') or detected_selector.startswith('/'):
                locator = page.locator(f"xpath={detected_selector}")
            else:
                locator = page.locator(detected_selector)
            
            if await locator.is_visible(timeout=5000):
                self.logger.warning("⚠️  验证元素仍然存在，可能需要重新验证")
                # 递归调用，再次处理
                await self._handle_manual_verification(detected_selector)
            else:
                self.logger.info("✅ 验证已完成，验证元素已消失")
                
        except KeyboardInterrupt:
            self.logger.error("❌ 用户中断操作")
            raise
        except Exception as e:
            self.logger.error(f"处理人工验证时出错: {e}")
            raise
    
    def _clear_file(self, filename: str):
        """如果文件存在，则清空它"""
        if os.path.exists(filename):
            try:
                os.remove(filename)
                self.logger.info(f"已清理旧文件: {filename}")
            except OSError as e:
                self.logger.error(f"清理文件 {filename} 失败: {e}")