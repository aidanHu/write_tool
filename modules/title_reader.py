import pandas as pd

# 支持模型配置文件动态加载
class TitleReader:
    def __init__(self, file_path):
        self.file_path = file_path
        
        # 先尝试读取文件，检查是否有列名
        try:
            # 先读取前几行来判断格式
            df_peek = pd.read_excel(file_path, nrows=2)
            
            # 如果第一行看起来像列名（包含"标题"、"状态"等），则使用header=0
            if len(df_peek.columns) >= 1 and ('标题' in str(df_peek.columns[0]) or 
                                              df_peek.iloc[0, 0] in ['标题', 'title', 'Title']):
                self.df = pd.read_excel(file_path, header=0)
                # 确保列名正确
                if len(self.df.columns) == 1:
                    self.df.columns = ['标题']
                    self.df['状态'] = None
                elif len(self.df.columns) >= 2:
                    self.df.columns = ['标题', '状态'] + [f'列{i}' for i in range(2, len(self.df.columns))]
            else:
                # 没有列名，直接读取
                self.df = pd.read_excel(file_path, header=None)
                if len(self.df.columns) == 1:
                    self.df[1] = None
        except Exception as e:
            # 出错时使用默认方式读取
            self.df = pd.read_excel(file_path)
            if len(self.df.columns) == 1:
                self.df['状态'] = None
        
        # 可根据详细模型适配标题读取逻辑

    def get_next_title(self):
        for idx, row in self.df.iterrows():
            # 检查状态列是否为空或未标记为已完成
            if len(row) < 2 or pd.isna(row.iloc[1]) or row.iloc[1] != '文章已创作':
                return idx, row.iloc[0]
        return None, None
    
    def get_all_pending_titles(self):
        """获取所有待处理的标题"""
        pending_titles = []
        for idx, row in self.df.iterrows():
            # 检查状态列是否为空或未标记为已完成
            if len(row) < 2 or pd.isna(row.iloc[1]) or row.iloc[1] != '文章已创作':
                pending_titles.append((idx, row.iloc[0]))
        return pending_titles

    def mark_finished(self, idx):
        self.df.iloc[idx, 1] = '文章已创作'
        # 根据是否有列名来决定保存方式
        if isinstance(self.df.columns[0], str) and self.df.columns[0] in ['标题', 'title', 'Title']:
            # 有列名，保存时包含列名
            self.df.to_excel(self.file_path, index=False, header=True)
        else:
            # 没有列名，保存时不包含列名
            self.df.to_excel(self.file_path, index=False, header=False) 