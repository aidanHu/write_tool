# 支持模型配置文件动态加载
import os
import time
import requests
import random
import string
import uuid
from PIL import Image
from qiniu import Auth, put_file, BucketManager
import logging

class ImageHandler:
    def __init__(self, access_key=None, secret_key=None, bucket_name=None, domain=None):
        """
        初始化图片处理器
        
        Args:
            access_key: 七牛云Access Key
            secret_key: 七牛云Secret Key  
            bucket_name: 七牛云存储空间名称
            domain: 七牛云域名
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.domain = domain
        
        # 设置日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # 初始化七牛云认证
        if access_key and secret_key:
            self.auth = Auth(access_key, secret_key)
        else:
            self.auth = None
            self.logger.warning("未配置七牛云认证信息")

    def download_image(self, url, save_path, referer=None, browser_manager=None):
        """
        下载图片到本地。
        优先使用浏览器下载，以绕过复杂的防盗链。
        
        Args:
            url: 图片URL
            save_path: 保存路径
            referer: (此参数保留，但浏览器下载模式下通常不需要)
            browser_manager: 浏览器管理器实例
            
        Returns:
            bool: 下载是否成功
        """
        if browser_manager:
            try:
                self.logger.info(f"使用浏览器模式下载图片: {url}")
                success = browser_manager.download_image_in_browser(url, save_path)
                if success:
                    self.logger.info(f"浏览器下载成功: {save_path}")
                    return True
                else:
                    self.logger.warning(f"浏览器下载失败，尝试使用备用方案: {url}")
            except Exception as e:
                self.logger.error(f"浏览器下载模式出现异常: {e}", exc_info=True)
                # 出现异常也尝试后备方案

        # 后备方案：使用requests库下载 (如果浏览器模式失败或未提供管理器)
        self.logger.info(f"使用Requests (后备方案) 下载图片: {url}")
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if referer:
                headers['Referer'] = referer
            
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                f.write(response.content)
            self.logger.info(f"Requests下载成功: {save_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Requests (后备方案) 下载失败 {url}: {str(e)}")
            return False

    def crop_and_resize_image(self, image_path, output_path, max_width=800, max_height=600, crop_bottom_pixels=0):
        """
        裁剪和调整图片大小
        
        Args:
            image_path: 输入图片路径
            output_path: 输出图片路径
            max_width: 最大宽度
            max_height: 最大高度
            crop_bottom_pixels: 从底部裁剪的像素值
        """
        try:
            with Image.open(image_path) as img:
                # 转换为RGB模式（如果是RGBA或其他模式）
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 1. 先从底部裁剪
                if crop_bottom_pixels > 0 and img.height > crop_bottom_pixels:
                    width, height = img.size
                    img = img.crop((0, 0, width, height - crop_bottom_pixels))
                    self.logger.info(f"已从图片底部裁剪 {crop_bottom_pixels} 像素")

                # 2. 再计算缩放比例
                width, height = img.size
                ratio = min(max_width / width, max_height / height)
                
                if ratio < 1:
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # 保存处理后的图片
                img.save(output_path, 'JPEG', quality=85, optimize=True)
                
            self.logger.info(f"图片处理成功: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"图片处理失败 {image_path}: {str(e)}")
            return False

    def generate_random_filename(self, extension="jpg"):
        """
        生成一个基于UUID的、保证唯一的随机文件名。
        
        Args:
            extension: 文件扩展名
            
        Returns:
            str: 唯一的随机文件名
        """
        return f"{uuid.uuid4().hex}.{extension}"

    def upload_to_qiniu(self, local_path, key=None):
        """
        上传文件到七牛云
        
        Args:
            local_path: 本地文件路径
            key: 七牛云存储的文件名，如果为None则自动生成
            
        Returns:
            str: 上传成功返回图片URL，失败返回None
        """
        if not self.auth:
            self.logger.error("七牛云认证未配置")
            return None
            
        if not self.bucket_name:
            self.logger.error("七牛云存储空间未配置")
            return None
            
        try:
            # 生成上传凭证
            token = self.auth.upload_token(self.bucket_name)
            
            # 如果没有指定key，则自动生成
            if not key:
                key = self.generate_random_filename()
            
            # 上传文件
            ret, info = put_file(token, key, local_path)
            
            if info.status_code == 200:
                # 构造图片URL
                if self.domain:
                    image_url = f"http://{self.domain}/{key}"
                else:
                    image_url = f"http://{self.bucket_name}.qiniudn.com/{key}"
                    
                self.logger.info(f"图片上传成功: {image_url}")
                return image_url
            else:
                self.logger.error(f"图片上传失败: {info}")
                return None
                
        except Exception as e:
            self.logger.error(f"图片上传异常: {str(e)}")
            return None

    def download_and_crop(self, url, crop_bottom_pixels=0, referer=None, browser_manager=None):
        """
        下载图片并裁剪，返回本地路径
        
        Args:
            url: 图片URL
            crop_bottom_pixels: 从底部裁剪的像素值
            referer: 下载时使用的Referer头
            browser_manager: 浏览器管理器实例
            
        Returns:
            str: 处理后的本地图片路径，失败返回None
        """
        try:
            # 生成临时文件路径
            temp_dir = "/tmp"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                
            original_filename = self.generate_random_filename()
            processed_filename = f"processed_{original_filename}"
            
            original_path = os.path.join(temp_dir, original_filename)
            processed_path = os.path.join(temp_dir, processed_filename)
            
            # 下载图片，传入referer和browser_manager
            if self.download_image(url, original_path, referer=referer, browser_manager=browser_manager):
                # 处理图片
                if self.crop_and_resize_image(original_path, processed_path, crop_bottom_pixels=crop_bottom_pixels):
                    # 删除原始文件
                    if os.path.exists(original_path):
                        os.remove(original_path)
                    return processed_path
                    
            return None
            
        except Exception as e:
            self.logger.error(f"图片下载和处理失败: {str(e)}")
            return None

    def process_and_upload_image(self, url, crop_bottom_pixels=0, referer=None, browser_manager=None):
        """
        完整的图片处理流程：下载 -> 处理 -> 上传 -> 清理
        
        Args:
            url: 原始图片URL
            crop_bottom_pixels: 从底部裁剪的像素值
            referer: 下载时使用的Referer头
            browser_manager: 浏览器管理器实例
            
        Returns:
            str: 七牛云图片URL，失败返回None
        """
        local_path = None
        try:
            # 下载并处理图片
            local_path = self.download_and_crop(url, crop_bottom_pixels=crop_bottom_pixels, referer=referer, browser_manager=browser_manager)
            if not local_path:
                return None
                
            # 上传到七牛云
            qiniu_url = self.upload_to_qiniu(local_path)
            
            return qiniu_url
            
        except Exception as e:
            self.logger.error(f"图片处理流程失败: {str(e)}")
            return None
        finally:
            # 清理临时文件
            if local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except:
                    pass

    def batch_process_images(self, image_urls, crop_bottom_pixels=0):
        """
        批量处理图片
        
        Args:
            image_urls: 图片URL列表
            crop_bottom_pixels: 从底部裁剪的像素值
            
        Returns:
            list: 处理后的七牛云图片URL列表
        """
        qiniu_urls = []
        for url in image_urls:
            # 注意：批量处理时无法提供特定的referer或浏览器实例，可能影响下载成功率
            qiniu_url = self.process_and_upload_image(url, crop_bottom_pixels)
            if qiniu_url:
                qiniu_urls.append(qiniu_url)
                
        return qiniu_urls

    def set_qiniu_config(self, access_key, secret_key, bucket_name, domain=None):
        """
        动态设置七牛云配置
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.domain = domain
        
        if access_key and secret_key:
            self.auth = Auth(access_key, secret_key)
            self.logger.info("七牛云配置更新成功")
        else:
            self.auth = None
            self.logger.warning("七牛云认证信息无效") 