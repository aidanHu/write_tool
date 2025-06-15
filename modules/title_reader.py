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
            print(f"Excel文件保存失败: {str(e)}")
            return False
        
        # 可根据详细模型适配标题读取逻辑

    def get_next_title(self):
        for idx, row in self.df.iterrows():
            # 检查状态列是否为空或未标记为已完成
            if len(row) < 2 or pd.isna(row.iloc[1]) or row.iloc[1] != '文章已创作':
                return idx, row.iloc[0]
        return None, None
    
    def get_all_pending_titles(self):
        """
        获取所有待处理的标题。
        待处理定义为：状态不是"文章已创作"。这包括空白状态和"失败"状态。
        """
        pending_titles = []
        # 假设状态在第二列 (索引为1)
        for index, row in self.df.iterrows():
            status = ''
            if len(row) > 1 and pd.notna(row.iloc[1]):
                status = str(row.iloc[1]).strip()
            
            if status != '文章已创作':
                pending_titles.append((index, row.iloc[0]))
        return pending_titles

    def mark_finished(self, row_index):
        """将指定行标记为文章已创作"""
        self._update_status(row_index, "文章已创作")

    def mark_failed(self, row_index):
        """将指定行标记为失败"""
        self._update_status(row_index, "失败")

    def _update_status(self, row_index, status):
        """内部方法：更新指定行的状态并保存文件"""
        try:
            # 更新DataFrame中的状态 (假设状态列索引为1)
            self.df.iloc[row_index, 1] = status
            
            # 决定是否在保存时包含列名
            # 检查第一列的列名是否是'标题'或'title'
            has_header = False
            if len(self.df.columns) > 0 and isinstance(self.df.columns[0], str):
                has_header = self.df.columns[0].lower() in ['标题', 'title']
            
            # 保存回Excel文件
            self.df.to_excel(self.file_path, index=False, header=has_header)
            
        except Exception as e:
            print(f"更新Excel状态并保存时出错: {e}") 