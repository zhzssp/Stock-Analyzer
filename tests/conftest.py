import os

# 测试必须走内置样例，不能打麦蕊现网（licence 已写进默认配置）。
os.environ["MAIRUI_OFFLINE"] = "1"
os.environ["MAIRUI_LICENCE"] = ""
