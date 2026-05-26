# ============================
# OCR 技能 — 截图文字识别
# ============================
# 通过百度 OCR API（免费版，500次/天）识别图片中的文字
# 配置：ocr_set_api_key(api_key, secret_key) 或在 agent config 中设置
# 依赖：仅 requests（已安装），零本地安装
# ============================
EXTENSION_NAME = "ocr"
EXTENSION_DESC = "截图/图片文字识别（OCR），可从屏幕截图或图片文件中提取文字"
EXTENSION_TOOLS = ["ocr_screenshot", "ocr_image_file", "ocr_configure"]
EXTENSION_DEPS = ["requests", "PIL"]
EXTENSION_VERSION = "1.0"

import os, time, base64, json, requests as _req
from PIL import Image as _Image
import io as _io

# --- 配置（自动持久化到文件）---
_OCR_API_KEY = ""
_OCR_SECRET_KEY = ""
_OCR_TOKEN = ""
_OCR_TOKEN_EXPIRY = 0
_AGENT = None

try:
    _BASE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE = os.getcwd()
_CONFIG_FILE = os.path.join(_BASE, "..", "data", "ocr_config.json")

def _load_config():
    """从文件加载持久化的 OCR 配置"""
    global _OCR_API_KEY, _OCR_SECRET_KEY
    try:
        cf = os.path.abspath(_CONFIG_FILE)
        if os.path.exists(cf):
            with open(cf, 'r', encoding='utf-8') as f:
                d = json.load(f)
            _OCR_API_KEY = d.get("api_key", "")
            _OCR_SECRET_KEY = d.get("secret_key", "")
            if _OCR_API_KEY and _OCR_SECRET_KEY:
                return True
    except Exception:
        pass
    return False

def _save_config(api_key, secret_key):
    """保存 OCR 配置到文件"""
    global _OCR_API_KEY, _OCR_SECRET_KEY
    _OCR_API_KEY = api_key
    _OCR_SECRET_KEY = secret_key
    try:
        cf = os.path.abspath(_CONFIG_FILE)
        os.makedirs(os.path.dirname(cf), exist_ok=True)
        with open(cf, 'w', encoding='utf-8') as f:
            json.dump({"api_key": api_key, "secret_key": secret_key}, f)
        return True
    except Exception:
        return False

# --- 工具函数 ---

def _get_token():
    """获取百度 OCR access_token（自动缓存/刷新）"""
    global _OCR_TOKEN, _OCR_TOKEN_EXPIRY
    now = time.time()
    if _OCR_TOKEN and _OCR_TOKEN_EXPIRY > now + 60:
        return _OCR_TOKEN
    ak = _OCR_API_KEY
    sk = _OCR_SECRET_KEY
    if not ak or not sk:
        # 尝试从 agent config 读取
        if _AGENT and hasattr(_AGENT, 'config'):
            ak = _AGENT.config.get("ocr_api_key", "")
            sk = _AGENT.config.get("ocr_secret_key", "")
        if not ak or not sk:
            return None
    try:
        url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}"
        resp = _req.get(url, timeout=10)
        data = resp.json()
        _OCR_TOKEN = data.get("access_token", "")
        _OCR_TOKEN_EXPIRY = now + data.get("expires_in", 2592000) - 300
        return _OCR_TOKEN
    except Exception as e:
        return None

def _baidu_ocr(image_bytes):
    """调用百度 OCR API 识别图片文字"""
    token = _get_token()
    if not token:
        return None
    try:
        img_b64 = base64.b64encode(image_bytes).decode()
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={token}"
        resp = _req.post(url, data={"image": img_b64}, timeout=15)
        result = resp.json()
        if "words_result" in result:
            texts = [item["words"] for item in result["words_result"]]
            return "\n".join(texts)
        return None
    except Exception:
        return None

def _take_screenshot():
    """截取全屏截图并返回图片字节"""
    from PIL import ImageGrab as _grab
    img = _grab.grab()
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read(), img

def _read_image_file(path):
    """读取图片文件为字节"""
    with open(path, "rb") as f:
        return f.read()

# --- 公开工具 ---

def ocr_screenshot():
    """截图并识别屏幕上的文字"""
    try:
        img_bytes, img = _take_screenshot()
        text = _baidu_ocr(img_bytes)
        if text:
            return {"success": True, "text": text, "source": "screenshot",
                    "image_size": f"{img.width}x{img.height}"}
        # 备用：尝试通用文字识别
        token = _get_token()
        if token:
            img_b64 = base64.b64encode(img_bytes).decode()
            url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={token}"
            resp = _req.post(url, data={"image": img_b64}, timeout=15)
            result = resp.json()
            if "words_result" in result:
                texts = [item["words"] for item in result["words_result"]]
                if texts:
                    return {"success": True, "text": "\n".join(texts), "source": "screenshot",
                            "image_size": f"{img.width}x{img.height}"}
        return {"success": False, "error": "OCR 失败：未配置 API Key 或识别失败",
                "hint": "请先调用 ocr_configure(api_key, secret_key) 配置百度 OCR API（免费注册：https://console.bce.baidu.com/）"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def ocr_image_file(filepath: str):
    """识别图片文件中的文字
    
    Args:
        filepath: 图片文件路径
    """
    try:
        if not os.path.exists(filepath):
            return {"success": False, "error": f"文件不存在: {filepath}"}
        img_bytes = _read_image_file(filepath)
        text = _baidu_ocr(img_bytes)
        if text:
            return {"success": True, "text": text, "source": filepath}
        return {"success": False, "error": "OCR 失败：未配置 API Key 或识别失败"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def ocr_configure(api_key: str = "", secret_key: str = ""):
    """配置百度 OCR API 密钥（免费注册：https://console.bce.baidu.com/）
    
    Args:
        api_key: 百度 OCR API Key（从百度智能云控制台获取）
        secret_key: 百度 OCR Secret Key
    """
    global _OCR_API_KEY, _OCR_SECRET_KEY, _OCR_TOKEN
    if api_key:
        _OCR_API_KEY = api_key
    if secret_key:
        _OCR_SECRET_KEY = secret_key
    _OCR_TOKEN = ""  # 强制刷新
    # 持久化到文件（跨重启保持）
    if api_key and secret_key:
        _save_config(api_key, secret_key)
    # 测试连接
    token = _get_token()
    if token:
        return {"success": True, "message": "OCR 配置成功！API Key 已保存，重启后自动加载"}
    else:
        return {"success": False, "error": "配置失败：无法获取 access_token，请检查 API Key 和 Secret Key 是否正确",
                "hint": "请前往 https://console.bce.baidu.com/ 注册百度OCR服务（免费版即可）"}

# --- 加载时自动初始化 ---
# 模块加载时自动从文件加载配置（跨重启持久化）
_load_config()

def setup(ext_mgr, agent):
    global _AGENT
    _AGENT = agent
    # 后台预取 token（不阻塞启动）
    if _OCR_API_KEY and _OCR_SECRET_KEY:
        import threading as _th
        _th.Thread(target=_get_token, daemon=True).start()
    ext_mgr.register_tool("ocr_screenshot", ocr_screenshot, "截图并识别屏幕上的文字")
    ext_mgr.register_tool("ocr_image_file", ocr_image_file, "识别指定图片文件中的文字")
    ext_mgr.register_tool("ocr_configure", ocr_configure, "配置百度 OCR API Key（免费注册）")
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
