import json
import os

class QiniuConfig:
    """七牛云配置管理类"""
    
    def __init__(self, config_file="qiniu_config.json"):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """加载七牛云配置"""
        default_config = {
            "access_key": "",
            "secret_key": "",
            "bucket_name": "",
            "domain": "",
            "enabled": False
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置，确保所有字段都存在
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                print(f"加载七牛云配置失败: {e}")
                return default_config
        else:
            return default_config
    
    def save_config(self):
        """保存七牛云配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存七牛云配置失败: {e}")
            return False
    
    def set_config(self, access_key, secret_key, bucket_name, domain="", enabled=True):
        """设置七牛云配置"""
        self.config.update({
            "access_key": access_key,
            "secret_key": secret_key,
            "bucket_name": bucket_name,
            "domain": domain,
            "enabled": enabled
        })
        return self.save_config()
    
    def get_config(self):
        """获取七牛云配置"""
        return self.config.copy()
    
    def is_enabled(self):
        """检查七牛云是否已启用"""
        return (self.config.get("enabled", False) and 
                bool(self.config.get("access_key")) and 
                bool(self.config.get("secret_key")) and 
                bool(self.config.get("bucket_name")))
    
    def get_access_key(self):
        """获取Access Key"""
        return self.config.get("access_key", "")
    
    def get_secret_key(self):
        """获取Secret Key"""
        return self.config.get("secret_key", "")
    
    def get_bucket_name(self):
        """获取存储空间名称"""
        return self.config.get("bucket_name", "")
    
    def get_domain(self):
        """获取自定义域名"""
        return self.config.get("domain", "")
    
    def disable(self):
        """禁用七牛云"""
        self.config["enabled"] = False
        return self.save_config()
    
    def enable(self):
        """启用七牛云"""
        if (self.config.get("access_key") and 
            self.config.get("secret_key") and 
            self.config.get("bucket_name")):
            self.config["enabled"] = True
            return self.save_config()
        else:
            print("七牛云配置不完整，无法启用")
            return False 