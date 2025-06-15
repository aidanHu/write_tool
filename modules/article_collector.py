from .toutiao_scraper import ToutiaoScraper
from .image_handler import ImageHandler

# 支持模型配置文件动态加载
class ArticleCollector:
    def __init__(self, article_count=5, image_count=3):
        self.article_count = article_count
        self.image_count = image_count
        self.scraper = ToutiaoScraper(article_count, image_count)
        self.image_handler = ImageHandler()
        # 可根据详细模型适配采集逻辑

    def collect_articles(self, title):
        """
        采集今日头条文章
        
        Args:
            title: 搜索关键词
            
        Returns:
            list: 文章内容列表
        """
        try:
            # 使用ToutiaoScraper进行采集
            success = self.scraper.collect_content(title)
            if success:
                return [article['content'] for article in self.scraper.collected_articles]
            else:
                return []
        except Exception as e:
            print(f"采集文章失败: {str(e)}")
            return []

    def collect_images(self, title):
        """
        采集今日头条图片
        
        Args:
            title: 搜索关键词
            
        Returns:
            list: 图片URL列表
        """
        try:
            # 使用ToutiaoScraper进行采集
            success = self.scraper.collect_content(title)
            if success:
                return self.scraper.collected_images
            else:
                return []
        except Exception as e:
            print(f"采集图片失败: {str(e)}")
            return []
            
    def run_full_collection(self, keyword, article_file="article.txt", image_file="picture.txt"):
        """
        运行完整的采集流程
        
        Args:
            keyword: 搜索关键词
            article_file: 文章保存文件路径
            image_file: 图片链接保存文件路径
            
        Returns:
            bool: 采集是否成功
        """
        try:
            return self.scraper.run(keyword, article_file, image_file, self.image_handler)
        except Exception as e:
            print(f"完整采集流程失败: {str(e)}")
            return False 