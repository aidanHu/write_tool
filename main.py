from gui.gui_main import run_gui

# 主流程需传递model、model_detail和model_url参数到model_operator
# 所有主流程可根据详细模型适配具体逻辑
# 支持模型配置文件动态加载

if __name__ == "__main__":
    run_gui() 