import pandas as pd

# 支持模型配置文件动态加载
class TitleReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.df = pd.read_excel(file_path)
        # 可根据详细模型适配标题读取逻辑

    def get_next_title(self):
        for idx, row in self.df.iterrows():
            if pd.isna(row[1]):  # 第二列未备注
                return idx, row[0]
        return None, None

    def mark_finished(self, idx):
        self.df.iloc[idx, 1] = '文章已创作'
        self.df.to_excel(self.file_path, index=False) 