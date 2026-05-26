# ============================
# 剪贴板技能 — 系统剪贴板读写
# ============================
EXTENSION_NAME = "clipboard"
EXTENSION_DESC = "系统剪贴板读写操作（读取剪贴板内容、写入文本到剪贴板）"
EXTENSION_TOOLS = ["clipboard_read", "clipboard_write", "clipboard_append"]
EXTENSION_DEPS = ["pyperclip"]
EXTENSION_VERSION = "1.0"

import pyperclip
import time as _time

def clipboard_read():
    """读取系统剪贴板文本内容"""
    try:
        text = pyperclip.paste()
        return {"success": True, "content": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def clipboard_write(text: str):
    """写入文本到系统剪贴板
    
    Args:
        text: 要写入剪贴板的文本内容
    """
    try:
        pyperclip.copy(str(text))
        return {"success": True, "length": len(str(text))}
    except Exception as e:
        return {"success": False, "error": str(e)}

def clipboard_append(text: str, separator: str = "\n"):
    """追加文本到剪贴板（在原内容后添加）
    
    Args:
        text: 要追加的文本
        separator: 分隔符，默认换行
    """
    try:
        existing = pyperclip.paste()
        new_content = existing + separator + str(text)
        pyperclip.copy(new_content)
        return {"success": True, "new_length": len(new_content)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def setup(ext_mgr, agent):
    ext_mgr.register_tool("clipboard_read", clipboard_read, "读取系统剪贴板文本内容")
    ext_mgr.register_tool("clipboard_write", clipboard_write, "写入文本到系统剪贴板")
    ext_mgr.register_tool("clipboard_append", clipboard_append, "追加文本到剪贴板")
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
