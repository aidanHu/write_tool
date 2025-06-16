import pandas as pd

# 支持模型配置文件动态加载
class TitleReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.is_valid = False
        self.df = pd.DataFrame(columns=['标题', '状态']) # 准备一个空的、结构正确的df

        try:
            # 1. 始终以无表头模式读取，避免pandas的自动判断引入不确定性
            df_raw = pd.read_excel(file_path, header=None)

            # 2. 如果文件是空的，直接使用上面准备好的空df即可
            if df_raw.empty:
                self.is_valid = True
                return

            # 3. 检查第一行是否像表头
            first_row_values = [str(v).strip() for v in df_raw.iloc[0].values]
            if '标题' in first_row_values or 'title' in first_row_values or 'Title' in first_row_values:
                # 第一行是表头，用它来重命名列，并移除这一行
                self.df = df_raw.rename(columns=df_raw.iloc[0]).drop(df_raw.index[0]).reset_index(drop=True)
            else:
                # 第一行就是数据
                self.df = df_raw

            # 4. 标准化列名和结构
            # 确保至少有'标题'和'状态'两列，并按此顺序命名
            if len(self.df.columns) >= 2:
                self.df = self.df.iloc[:, :2] # 只取前两列
                self.df.columns = ['标题', '状态']
            elif len(self.df.columns) == 1:
                self.df.columns = ['标题']
                self.df['状态'] = pd.NA # 添加状态列

            self.is_valid = True

        except Exception as e:
            print(f"Excel文件处理失败: {str(e)}")
            self.is_valid = False

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