# ============================
# 进程管理技能 — 进程列表、信息查询、终止进程
# ============================
EXTENSION_NAME = "process"
EXTENSION_DESC = "系统进程管理（列出进程、查看详情、终止进程、按条件搜索）"
EXTENSION_TOOLS = ["process_list", "process_info", "process_kill", "process_search"]
EXTENSION_DEPS = ["psutil", "os"]
EXTENSION_VERSION = "1.0"

import psutil
import os as _os
import signal as _signal

def process_list(sort_by: str = "cpu", limit: int = 20):
    """列出当前运行的进程（按 CPU/内存排序）
    
    Args:
        sort_by: 排序方式 "cpu"(默认) / "memory" / "name" / "pid"
        limit: 返回的最大条数（默认 20）
    """
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent',
                                          'memory_info', 'status', 'create_time',
                                          'num_threads']):
            try:
                pinfo = proc.info
                processes.append({
                    "pid": pinfo['pid'],
                    "name": pinfo['name'] or "未知",
                    "cpu": round(pinfo['cpu_percent'] or 0, 1),
                    "memory_mb": round((pinfo['memory_info'].rss if pinfo['memory_info'] else 0) / 1024 / 1024, 1),
                    "memory_percent": round(pinfo['memory_percent'] or 0, 1),
                    "status": pinfo['status'] or "未知",
                    "threads": pinfo['num_threads'] or 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # 排序
        reverse = True
        key_map = {
            "cpu": lambda p: p["cpu"],
            "memory": lambda p: p["memory_mb"],
            "name": lambda p: p["name"].lower(),
            "pid": lambda p: p["pid"]
        }
        skey = key_map.get(sort_by, key_map["cpu"])
        if sort_by == "name" or sort_by == "pid":
            reverse = False
        processes.sort(key=skey, reverse=reverse)
        return {"success": True, "processes": processes[:limit], "total": len(processes)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def process_info(pid: int = 0, name: str = ""):
    """获取指定进程的详细信息
    
    Args:
        pid: 进程 ID（与 name 二选一）
        name: 进程名（模糊匹配，取第一个匹配结果）
    """
    try:
        target = None
        if pid > 0:
            try:
                target = psutil.Process(pid)
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"进程 {pid} 不存在"}
        elif name:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if name.lower() in (proc.info['name'] or "").lower():
                        target = psutil.Process(proc.info['pid'])
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        if target is None:
            return {"success": False, "error": "未找到匹配的进程，请提供 pid 或 name"}
        pinfo = target.as_dict(attrs=['pid', 'name', 'status', 'cpu_percent', 'memory_percent',
                                      'memory_info', 'create_time', 'num_threads',
                                      'cmdline', 'username', 'exe'])
        # connections 和 open_files 可能被拒访，单独包裹
        conn_count = 0
        of_count = 0
        try:
            conn_count = len(target.connections())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            conn_count = -1  # 拒访
        try:
            of_count = len(target.open_files())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            of_count = -1
        return {
            "success": True,
            "pid": pinfo['pid'],
            "name": pinfo['name'],
            "status": pinfo['status'],
            "cpu": round(pinfo['cpu_percent'] or 0, 1),
            "memory_mb": round((pinfo['memory_info'].rss if pinfo['memory_info'] else 0) / 1024 / 1024, 1),
            "threads": pinfo['num_threads'],
            "connections": conn_count,
            "open_files": of_count,
            "cmdline": " ".join(pinfo['cmdline'] or [])[:200],
            "username": pinfo['username'],
            "exe": pinfo.get('exe', ''),
            "created": _datetime_str(pinfo['create_time']) if pinfo['create_time'] else ''
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def process_kill(pid: int = 0, name: str = ""):
    """终止指定的进程
    
    Args:
        pid: 进程 ID（与 name 二选一）
        name: 进程名（模糊匹配，终止所有匹配的进程）
    """
    try:
        killed = []
        if pid > 0:
            try:
                proc = psutil.Process(pid)
                pname = proc.name()
                proc.terminate()
                killed.append({"pid": pid, "name": pname})
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"进程 {pid} 不存在"}
            except psutil.AccessDenied:
                return {"success": False, "error": f"权限不足，无法终止进程 {pid}（可能需要管理员权限）"}
        elif name:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if name.lower() in (proc.info['name'] or "").lower():
                        p = psutil.Process(proc.info['pid'])
                        p.terminate()
                        killed.append({"pid": proc.info['pid'], "name": proc.info['name']})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        if not killed:
            return {"success": False, "error": "未找到匹配的进程"}
        # 等待进程结束
        _os.system("timeout /t 2 /nobreak >nul 2>nul")  # 给进程2秒退出
        return {"success": True, "killed": killed, "count": len(killed)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def process_search(keyword: str):
    """按关键词搜索进程（进程名、命令行等）
    
    Args:
        keyword: 搜索关键词（如 "chrome", "notepad"）
    """
    try:
        kw = keyword.lower()
        results = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent',
                                          'status', 'cmdline']):
            try:
                pinfo = proc.info
                name = (pinfo['name'] or "").lower()
                cmd = " ".join(pinfo['cmdline'] or []).lower()
                if kw in name or kw in cmd:
                    results.append({
                        "pid": pinfo['pid'],
                        "name": pinfo['name'],
                        "cpu": round(pinfo['cpu_percent'] or 0, 1),
                        "memory_percent": round(pinfo['memory_percent'] or 0, 1),
                        "status": pinfo['status']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"success": True, "keyword": keyword, "results": results, "total": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _datetime_str(timestamp):
    from datetime import datetime as _dt
    return _dt.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

def setup(ext_mgr, agent):
    ext_mgr.register_tool("process_list", process_list, "列出进程（按CPU/内存排序）")
    ext_mgr.register_tool("process_info", process_info, "获取指定进程的详细信息")
    ext_mgr.register_tool("process_kill", process_kill, "终止指定进程（按PID或名称）")
    ext_mgr.register_tool("process_search", process_search, "按关键词搜索进程")
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
