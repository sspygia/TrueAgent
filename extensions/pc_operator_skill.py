# ============================
# PC 桌面操作技能 — 拟人化计算机操作
# ============================
# 纯 Windows API + ctypes 实现，零额外依赖
# 功能：窗口管理 + 鼠标操作 + 键盘模拟
# ============================
EXTENSION_NAME = "pc_operator"
EXTENSION_DESC = "拟人化 PC 桌面操作（窗口管理、鼠标移动点击、键盘输入、快捷键）"
EXTENSION_TOOLS = [
    "window_list", "window_focus", "window_minimize", "window_maximize",
    "window_close", "get_active_window", "window_move", "window_resize",
    "mouse_move", "mouse_click", "mouse_double_click", "mouse_drag",
    "mouse_scroll", "get_mouse_position",
    "key_press", "key_combination", "type_text", "get_screen_size",
]
EXTENSION_DEPS = ["win32gui", "win32con", "win32api", "ctypes"]
EXTENSION_VERSION = "1.0"

import win32gui
import win32con
import win32api
import ctypes
import time as _time

# --- 辅助 ---
user32 = ctypes.windll.user32

def _get_window_by_title(title_part):
    """模糊匹配窗口句柄"""
    def enum_callback(hwnd, results):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_part.lower() in text.lower():
                results.append((hwnd, text))
        return True
    results = []
    win32gui.EnumWindows(enum_callback, results)
    return results

def _get_window_rect(hwnd):
    rect = win32gui.GetWindowRect(hwnd)
    return {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3],
            "width": rect[2] - rect[0], "height": rect[3] - rect[1]}

# ========== 窗口管理 ==========

def window_list():
    """列出所有可见窗口"""
    def enum_callback(hwnd, results):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if text.strip():
                results.append({
                    "hwnd": hwnd,
                    "title": text,
                    "rect": _get_window_rect(hwnd),
                    "class_name": win32gui.GetClassName(hwnd)
                })
        return True
    results = []
    win32gui.EnumWindows(enum_callback, results)
    # 按标题长度排序（去掉空标题）
    results.sort(key=lambda x: -len(x["title"]))
    return {"windows": results[:50], "total": len(results)}

def window_focus(title: str):
    """将窗口置于前台（激活窗口）
    
    Args:
        title: 窗口标题（支持模糊匹配）
    """
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return {"success": True, "window": matches[0][1], "hwnd": hwnd}
    except Exception as e:
        return {"success": False, "error": str(e)}

def window_minimize(title: str):
    """最小化窗口"""
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    return {"success": True, "window": matches[0][1]}

def window_maximize(title: str):
    """最大化窗口（已最大化的恢复为正常）"""
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] == win32con.SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        return {"success": True, "window": matches[0][1], "action": "restore"}
    else:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return {"success": True, "window": matches[0][1], "action": "maximize"}

def window_close(title: str):
    """关闭窗口（发送关闭消息，非强制终止）"""
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return {"success": True, "window": matches[0][1]}

def window_move(title: str, x: int, y: int):
    """移动窗口到指定位置
    Args:
        title: 窗口标题（模糊匹配）
        x: 目标 X 坐标
        y: 目标 Y 坐标
    """
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    rect = _get_window_rect(hwnd)
    win32gui.SetWindowPos(hwnd, 0, x, y, rect["width"], rect["height"],
                          win32con.SWP_NOZORDER)
    return {"success": True, "window": matches[0][1], "new_position": {"x": x, "y": y}}

def window_resize(title: str, width: int, height: int):
    """调整窗口大小
    Args:
        title: 窗口标题（模糊匹配）
        width: 新宽度
        height: 新高度
    """
    matches = _get_window_by_title(title)
    if not matches:
        return {"success": False, "error": f"未找到匹配的窗口: {title}"}
    hwnd = matches[0][0]
    rect = _get_window_rect(hwnd)
    win32gui.SetWindowPos(hwnd, 0, rect["left"], rect["top"], width, height,
                          win32con.SWP_NOZORDER)
    return {"success": True, "window": matches[0][1], "new_size": {"width": width, "height": height}}

def get_active_window():
    """获取当前活动窗口信息"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        rect = _get_window_rect(hwnd)
        return {
            "success": True,
            "hwnd": hwnd,
            "title": title,
            "rect": rect,
            "class_name": win32gui.GetClassName(hwnd)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ========== 鼠标操作 ==========

def get_mouse_position():
    """获取当前鼠标位置"""
    pos = win32api.GetCursorPos()
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    return {"success": True, "x": pos[0], "y": pos[1], "screen_width": screen_w, "screen_height": screen_h}

def mouse_move(x: int, y: int):
    """移动鼠标到指定屏幕坐标
    Args:
        x: 目标 X 坐标
        y: 目标 Y 坐标
    """
    try:
        user32.SetCursorPos(x, y)
        return {"success": True, "position": {"x": x, "y": y}}
    except Exception as e:
        return {"success": False, "error": str(e)}

def mouse_click(button: str = "left", x: int = None, y: int = None):
    """在指定位置（或当前位置）点击鼠标
    Args:
        button: "left" 左键 / "right" 右键 / "middle" 中键
        x: 点击的 X 坐标（None=当前位置）
        y: 点击的 Y 坐标（None=当前位置）
    """
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
            _time.sleep(0.05)
        btn_map = {"left": win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP,
                   "right": win32con.MOUSEEVENTF_RIGHTDOWN | win32con.MOUSEEVENTF_RIGHTUP,
                   "middle": win32con.MOUSEEVENTF_MIDDLEDOWN | win32con.MOUSEEVENTF_MIDDLEUP}
        flags = btn_map.get(button.lower(), win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP)
        user32.mouse_event(flags, 0, 0, 0, 0)
        pos = win32api.GetCursorPos()
        return {"success": True, "button": button, "position": {"x": pos[0], "y": pos[1]}}
    except Exception as e:
        return {"success": False, "error": str(e)}

def mouse_double_click(x: int = None, y: int = None):
    """在指定位置（或当前位置）双击
    Args:
        x: X 坐标（None=当前位置）
        y: Y 坐标（None=当前位置）
    """
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
            _time.sleep(0.05)
        for _ in range(2):
            user32.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            _time.sleep(0.05)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def mouse_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left"):
    """从起点拖动到终点（按下→移动→释放）
    Args:
        x1: 起点 X
        y1: 起点 Y
        x2: 终点 X
        y2: 终点 Y
        button: 拖动的按键（left/right/middle）
    """
    try:
        user32.SetCursorPos(x1, y1)
        _time.sleep(0.1)
        down_flag = {"left": win32con.MOUSEEVENTF_LEFTDOWN,
                     "right": win32con.MOUSEEVENTF_RIGHTDOWN,
                     "middle": win32con.MOUSEEVENTF_MIDDLEDOWN}.get(button.lower(), win32con.MOUSEEVENTF_LEFTDOWN)
        up_flag = {"left": win32con.MOUSEEVENTF_LEFTUP,
                   "right": win32con.MOUSEEVENTF_RIGHTUP,
                   "middle": win32con.MOUSEEVENTF_MIDDLEUP}.get(button.lower(), win32con.MOUSEEVENTF_LEFTUP)
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        _time.sleep(0.05)
        # 分步移动（模拟真实拖动）
        steps = 10
        for i in range(1, steps + 1):
            cx = x1 + (x2 - x1) * i // steps
            cy = y1 + (y2 - y1) * i // steps
            user32.SetCursorPos(cx, cy)
            _time.sleep(0.02)
        _time.sleep(0.05)
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        return {"success": True, "from": {"x": x1, "y": y1}, "to": {"x": x2, "y": y2}}
    except Exception as e:
        return {"success": False, "error": str(e)}

def mouse_scroll(delta: int, x: int = None, y: int = None):
    """滚动鼠标滚轮
    Args:
        delta: 正数向上滚，负数向下滚（如 3 表示向上滚3格）
        x: 滚动位置 X（None=当前位置）
        y: 滚动位置 Y（None=当前位置）
    """
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
        user32.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta * 120, 0)
        return {"success": True, "delta": delta}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ========== 键盘操作 ==========

# 虚拟键码映射（常用键）
VK_MAP = {
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "capslock": 0x14, "numlock": 0x90,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
}

def key_press(key: str):
    """按下并释放一个键
    Args:
        key: 键名（如 "enter", "f5", "a", "escape" 等）
    """
    try:
        vk = VK_MAP.get(key.lower())
        if vk is None:
            return {"success": False, "error": f"未知键名: {key}"}
        user32.keybd_event(vk, 0, 0, 0)
        _time.sleep(0.05)
        user32.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        return {"success": True, "key": key.lower()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def key_combination(keys: str):
    """发送组合键（如 Ctrl+C, Alt+Tab, Win+D）
    Args:
        keys: 组合键字符串，用加号或空格分隔（如 "ctrl+c" 或 "ctrl shift esc"）
    """
    try:
        parts = keys.lower().replace("+", " ").split()
        vks = []
        for p in parts:
            pn = {"win": 0x5B, "windows": 0x5B, "super": 0x5B}.get(p, p)
            vk = VK_MAP.get(pn)
            if vk is None:
                return {"success": False, "error": f"未知键: {p}"}
            vks.append(vk)
        # 按下所有修饰键
        for vk in vks:
            user32.keybd_event(vk, 0, 0, 0)
            _time.sleep(0.03)
        _time.sleep(0.05)
        # 释放（逆序）
        for vk in reversed(vks):
            user32.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            _time.sleep(0.03)
        return {"success": True, "combination": keys}
    except Exception as e:
        return {"success": False, "error": str(e)}

def type_text(text: str, interval: float = 0.01):
    """在当前活动窗口输入文本
    Args:
        text: 要输入的文本（支持中文和其他 Unicode 字符）
        interval: 按键间隔（秒），默认 0.01
    """
    try:
        for char in str(text):
            # Unicode 字符通过 SendInput 处理
            vk = VK_MAP.get(char.lower())
            if vk is not None:
                user32.keybd_event(vk, 0, 0, 0)
                _time.sleep(interval)
                user32.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            else:
                # 非 ASCII 字符用剪贴板粘贴方式
                # 直接用 SendMessage + WM_CHAR
                hwnd = win32gui.GetForegroundWindow()
                win32gui.SendMessage(hwnd, win32con.WM_CHAR, ord(char), 0)
            _time.sleep(interval)
        return {"success": True, "typed_length": len(str(text))}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_screen_size():
    """获取屏幕分辨率"""
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return {"success": True, "width": w, "height": h,
            "working_area_width": user32.GetSystemMetrics(78),
            "working_area_height": user32.GetSystemMetrics(79)}

# ========== 注册 ==========
def setup(ext_mgr, agent):
    tools = [
        ("window_list", window_list, "列出所有可见窗口及其标题"),
        ("window_focus", window_focus, "激活/置前指定窗口（模糊匹配标题）"),
        ("window_minimize", window_minimize, "最小化指定窗口"),
        ("window_maximize", window_maximize, "最大化/恢复指定窗口"),
        ("window_close", window_close, "关闭指定窗口"),
        ("get_active_window", get_active_window, "获取当前活动窗口信息"),
        ("window_move", window_move, "移动窗口到指定位置"),
        ("window_resize", window_resize, "调整窗口大小"),
        ("mouse_move", mouse_move, "移动鼠标到屏幕坐标 (x,y)"),
        ("mouse_click", mouse_click, "点击鼠标（指定位置或当前位置）"),
        ("mouse_double_click", mouse_double_click, "双击鼠标"),
        ("mouse_drag", mouse_drag, "从起点(x1,y1)拖动到终点(x2,y2)"),
        ("mouse_scroll", mouse_scroll, "滚动鼠标滚轮"),
        ("get_mouse_position", get_mouse_position, "获取当前鼠标位置"),
        ("key_press", key_press, "按下并释放一个键（如 enter, f5, escape）"),
        ("key_combination", key_combination, "发送组合键（如 ctrl+c, alt+tab, win+d）"),
        ("type_text", type_text, "在当前活动窗口输入文本"),
        ("get_screen_size", get_screen_size, "获取屏幕分辨率"),
    ]
    for name, func, desc in tools:
        ext_mgr.register_tool(name, func, desc)
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
