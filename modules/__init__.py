# modules/__init__.py
"""
写作工具模块包
基于Chrome DevTools Protocol的自动化写作工具
"""

# flake8: noqa
# isort: off

# 修复 sys.path，以便能够正确导入 GUI 模块
import os
import sys

# 将项目根目录添加到 sys.path
# 这使得无论从哪里运行脚本，都可以使用绝对导入
# 例如：from modules import BrowserManager
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 从当前目录（modules）导入所有必要的类
from .browser_manager import BrowserManager
from .poe_automator import PoeAutomator
from .toutiao_scraper import ToutiaoScraper
from .workflow_manager import WorkflowThread
from .image_handler import ImageHandler
from .qiniu_config import QiniuConfig

__all__ = [
    'BrowserManager',
    'PoeAutomator', 
    'ToutiaoScraper',
    'WorkflowThread',
    'ImageHandler',
    'QiniuConfig'
] 