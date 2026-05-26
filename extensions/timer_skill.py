# ============================
# 定时提醒技能 — 倒计时、定时器、重复提醒
# ============================
EXTENSION_NAME = "timer"
EXTENSION_DESC = "倒计时、定时提醒、周期性提醒（在控制台输出提示，支持蜂鸣提醒）"
EXTENSION_TOOLS = ["timer_countdown", "timer_remind_at", "timer_repeat", "timer_list", "timer_cancel"]
EXTENSION_DEPS = ["threading", "time", "winsound"]
EXTENSION_VERSION = "1.0"

import threading as _t
import time as _time
import winsound as _sound
import uuid as _uuid

# 存储所有运行的定时器
_active_timers = {}
_timer_lock = _t.Lock()

def _beep():
    """发出提示音"""
    try:
        _sound.Beep(800, 200)
        _time.sleep(0.15)
        _sound.Beep(1000, 300)
    except Exception:
        pass

def _timer_thread(timer_id, label, delay, repeat_interval):
    """定时器线程体"""
    _time.sleep(delay)
    with _timer_lock:
        if timer_id not in _active_timers:
            return  # 已被取消
    msg = f"\n⏰ [定时提醒] {label}"
    print(msg, flush=True)
    _beep()
    if repeat_interval > 0:
        # 周期性 task：重新注册
        _time.sleep(repeat_interval)
        with _timer_lock:
            if timer_id in _active_timers:
                t = _t.Thread(target=_timer_thread, args=(timer_id, label, 0, repeat_interval), daemon=True)
                _active_timers[timer_id]["thread"] = t
                t.start()

def timer_countdown(seconds: int, label: str = "倒计时"):
    """设置一个倒计时，到时间后提示
    
    Args:
        seconds: 倒计时秒数（如 300 = 5分钟）
        label: 提醒内容标签
    """
    if seconds <= 0:
        return {"success": False, "error": "秒数必须大于 0"}
    if seconds > 86400:
        return {"success": False, "error": "最长支持 24 小时（86400秒）"}
    tid = _uuid.uuid4().hex[:8]
    t = _t.Thread(target=_timer_thread, args=(tid, label, seconds, 0), daemon=True)
    with _timer_lock:
        _active_timers[tid] = {
            "id": tid, "label": label, "type": "countdown",
            "delay": seconds, "remaining": seconds,
            "created_at": _time.time(), "thread": t
        }
    t.start()
    return {"success": True, "timer_id": tid, "message": f"⏰ {label} 鈥斺 {seconds}秒后提醒"}

def timer_remind_at(seconds: int, label: str = "定时提醒"):
    """定时提醒（与倒计时相同，语义更清晰）
    
    Args:
        seconds: 多少秒后提醒
        label: 提醒内容
    """
    return timer_countdown(seconds, label)

def timer_repeat(interval_seconds: int, label: str = "重复提醒"):
    """设置周期性重复提醒
    
    Args:
        interval_seconds: 间隔秒数（如 1800 = 每30分钟）
        label: 提醒内容
    """
    if interval_seconds <= 0:
        return {"success": False, "error": "间隔必须大于 0"}
    if interval_seconds < 60:
        return {"success": False, "error": "周期提醒最短间隔 60 秒"}
    tid = _uuid.uuid4().hex[:8]
    t = _t.Thread(target=_timer_thread, args=(tid, label, 0, interval_seconds), daemon=True)
    with _timer_lock:
        _active_timers[tid] = {
            "id": tid, "label": label, "type": "repeat",
            "interval": interval_seconds,
            "created_at": _time.time(), "thread": t
        }
    t.start()
    return {"success": True, "timer_id": tid, "message": f"🔄 {label} 鈥斺 每{interval_seconds}秒提醒一次"}

def timer_list():
    """列出所有正在运行的定时器"""
    with _timer_lock:
        now = _time.time()
        result = []
        for tid, info in _active_timers.items():
            elapsed = now - info.get("created_at", now)
            remaining = max(0, info.get("delay", 0) - elapsed) if info.get("type") == "countdown" else -1
            result.append({
                "id": tid,
                "label": info.get("label", ""),
                "type": info.get("type", ""),
                "running": info.get("thread", None) is not None and info["thread"].is_alive(),
                "remaining_seconds": round(remaining) if remaining >= 0 else -1,
                "elapsed_seconds": round(elapsed)
            })
        return {"success": True, "timers": result, "total": len(result)}

def timer_cancel(timer_id: str = "", label: str = ""):
    """取消指定定时器（按 ID 或标签）
    
    Args:
        timer_id: 定时器 ID（从 timer_list 获取）
        label: 按标签取消（ID 和标签二选一）
    """
    with _timer_lock:
        to_remove = []
        if timer_id:
            if timer_id in _active_timers:
                to_remove.append(timer_id)
        elif label:
            for tid, info in _active_timers.items():
                if label.lower() in info.get("label", "").lower():
                    to_remove.append(tid)
        else:
            return {"success": False, "error": "请提供 timer_id 或 label"}
        for tid in to_remove:
            try:
                _active_timers.pop(tid, None)
            except Exception:
                pass
        return {"success": True, "cancelled": len(to_remove), "timer_ids": to_remove}

def setup(ext_mgr, agent):
    ext_mgr.register_tool("timer_countdown", timer_countdown, "设置倒计时，到时间后提醒")
    ext_mgr.register_tool("timer_remind_at", timer_remind_at, "多少秒后提醒（语义别名）")
    ext_mgr.register_tool("timer_repeat", timer_repeat, "设置周期性重复提醒")
    ext_mgr.register_tool("timer_list", timer_list, "列出所有正在运行的定时器")
    ext_mgr.register_tool("timer_cancel", timer_cancel, "取消指定定时器（按 ID 或标签）")
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
