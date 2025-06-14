# 写作助手应用

## 项目结构

```
write_tool/
│
├── main.py                # 程序入口，负责GUI启动和主流程调度
├── config.py              # 配置项定义与加载
├── model_config.json      # 平台-模型-网址配置文件
├── gui/
│   ├── __init__.py
│   ├── gui_main.py        # GUI主逻辑
│   └── elements.py        # 所有网页元素定义
│
├── modules/
│   ├── __init__.py
│   ├── title_reader.py    # 标题文件读取与进度管理
│   ├── article_collector.py # 文章采集与图片采集
│   ├── image_handler.py   # 图片下载、裁剪、上传七牛云
│   ├── model_operator.py  # 模型网页自动化操作
│   ├── file_manager.py    # 文件保存、md插图等
│
├── utils/
│   ├── __init__.py
│   └── helpers.py         # 通用工具函数
│
├── requirements.txt
└── README.md
```

## 功能简介
- 支持模型平台选择（poe/monica）和详细模型选择（如gpt-4.1、Claude3.7等），模型和网址均来源于`model_config.json`，用户可自定义维护，支持动态加载
- 创作提示词和继续创作提示词输入框为多行宽输入，便于查看和编辑
- 所有主流程和模块均可根据详细模型适配具体逻辑
- 支持文章/图片采集，自动处理Excel进度
- 自动化模型网页操作，生成md文件并插入图片链接
- 图片自动上传七牛云，返回md格式链接
- 界面元素集中管理，易于维护

## 模型配置文件说明

`model_config.json` 示例：
```json
{
  "poe": {
    "gpt-4.1": "https://poe.com/GPT-4-1",
    "Claude3.7": "https://poe.com/Claude-3.7-Sonnet"
  },
  "monica": {
    "gpt-4.1": "https://monica.im/home/chat/GPT-4.1/gpt_4_1",
    "Claude3.7": "https://monica.im/home/chat/Claude%203.7%20Sonnet/claude_3_7_sonnet"
  }
}
```
用户可随时编辑此文件，增删平台、模型和网址，界面会自动加载最新内容。 