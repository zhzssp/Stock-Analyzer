import os

# 测试必须走内置样例，不能打麦蕊 / DeepSeek 现网。
os.environ["MAIRUI_OFFLINE"] = "1"
os.environ["MAIRUI_LICENCE"] = ""
os.environ["LLM_API_KEY"] = ""
