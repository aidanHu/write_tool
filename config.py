import json
import os

CONFIG_FILE = 'config.json'

# 配置支持详细模型和模型配置文件动态加载
DEFAULT_CONFIG = {
    'model': 'poe',
    'model_detail': 'gpt-4.1',
    'model_url': '',  # 自动获取
    'model_config_path': 'model_config.json',
    'title_file_path': '',
    'save_path': '',
    'enable_article_collect': False,
    'article_count': 5,
    'enable_image_collect': False,
    'image_count': 3,
    'prompt': '',
    'min_word_count': 800,
    'continue_prompt': ''
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2) 