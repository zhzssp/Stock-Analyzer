import os
import subprocess

# 测试必须走内置样例，不能打麦蕊 / DeepSeek 现网。
os.environ["MAIRUI_OFFLINE"] = "1"
os.environ["MAIRUI_LICENCE"] = ""
os.environ["LLM_API_KEY"] = ""

# 中文 Windows 默认编码是 gbk。有些开发环境会往进程里注入 sitecustomize，
# 把 Path.unlink() 改成「移到回收站」（例如用 genie-trash.exe），
# 内部是 subprocess.run(..., text=True) 且**没指定 encoding** ——
# 子进程的中文输出被按 gbk 解码，在后台读线程里偶发抛
#   UnicodeDecodeError: 'gbk' codec can't decode byte 0xaa ...
# 那是环境的问题（我们改不了第三方 shim），但它会在测试里刷 warning、盖住真问题。
# 这里给文本模式的子进程默认按 UTF-8 解码，只作用于测试进程。
if os.name == "nt":
    _OrigPopen = subprocess.Popen

    class _Utf8Popen(_OrigPopen):
        def __init__(self, *args, **kwargs):
            if (kwargs.get("text") or kwargs.get("universal_newlines")) and not kwargs.get("encoding"):
                kwargs["encoding"] = "utf-8"
                kwargs.setdefault("errors", "replace")
            super().__init__(*args, **kwargs)

    subprocess.Popen = _Utf8Popen
