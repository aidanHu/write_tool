# 支持模型配置文件动态加载
class FileManager:
    def __init__(self, save_path):
        self.save_path = save_path
        # 可根据详细模型适配保存逻辑

    def save_md(self, title, content, image_links):
        # TODO: 保存为md文件，并插入图片链接
        md_path = f"{self.save_path}/{title}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n")
            f.write(content + '\n\n')
            for link in image_links:
                f.write(f"![]({link})\n")
        return md_path 