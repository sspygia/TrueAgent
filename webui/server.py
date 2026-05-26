# -*- coding: utf-8 -*-
"""
TrueAgent v5.9 WebUI 后端
FastAPI + pywebview 现代桌面界面
"""
import sys, os, io, base64, json, time, threading, traceback

# 尝试导入 psutil（跨平台 CPU 采集），不可用时回退
try:
    import psutil as _psutil
    psutil = _psutil
except ImportError:
    psutil = None

# 工作目录
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # v5.9/
BASE_DIR = os.getcwd()
sys.path.insert(0, BASE_DIR)

# ===== 会话存储 =====
CONV_DIR = os.path.join(BASE_DIR, "data", "conversations")
os.makedirs(CONV_DIR, exist_ok=True)
SESSIONS_FILE = os.path.join(CONV_DIR, "sessions.json")

def _load_sessions():
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return []

def _save_sessions(sessions):
    try:
        with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except: pass

def _ensure_default_session():
    """确保 default 会话注册到 sessions.json"""
    try:
        default_path = os.path.join(CONV_DIR, "default.jsonl")
        if not os.path.exists(default_path):
            return
        with open(default_path, 'r', encoding='utf-8') as f:
            count = len([l for l in f if l.strip()])
        if count == 0:
            return
        sessions = _load_sessions()
        if any(s.get("id") == "default" for s in sessions):
            return
        sessions.insert(0, {
            "id": "default",
            "title": "历史会话",
            "created": os.path.getctime(default_path),
            "updated": os.path.getmtime(default_path)
        })
        _save_sessions(sessions)
    except Exception:
        pass



def _save_message(session_id, role, content):
    """保存单条消息到会话文件（超过 5MB 自动裁剪旧消息）"""
    path = os.path.join(CONV_DIR, f"{session_id}.jsonl")
    MAX_SIZE = 5 * 1024 * 1024  # 5MB
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"role": role, "content": content, "time": time.time()}, ensure_ascii=False) + '\n')
        # 超过 5MB 时保留后半（约几千条消息）
        if os.path.getsize(path) > MAX_SIZE:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # 保留后 2/3，确保在 5MB 以下
            keep = max(100, len(lines) * 2 // 3)
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-keep:])
    except: pass

def _load_messages(session_id):
    """加载会话历史"""
    path = os.path.join(CONV_DIR, f"{session_id}.jsonl")
    msgs = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        msgs.append(json.loads(line))
        except: pass
    return msgs
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "webui", "static")), name="static")
# 上传文件静态服务（图片预览）
UPLOADS_DIR = os.path.join(BASE_DIR, "data", "cache", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# ===== 强制禁用缓存（防止浏览器使用旧版静态文件） =====
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ===== Agent 引用 =====
agent = None
_agent_lock = threading.Lock()

def get_agent():
    global agent
    if agent is None:
        with _agent_lock:
            if agent is None:
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        "trueagent_core", os.path.join(BASE_DIR, "TrueAgent_Hyper_v4.0.py"))
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    TrueAgent = mod.TrueAgent
                    CONFIG = mod.CONFIG
                    agent = TrueAgent(CONFIG)
                    agent._agent_id = os.environ.get('TRUEAGENT_ID') or getattr(globals(), '_agent_id_override', 'agent_main')
                    agent._agent_port = int(os.environ.get('TRUEAGENT_PORT') or str(getattr(globals(), '_agent_port_override', port)))
                    agent._start_time = time.time()
                    agent._proactive_queue = []  # 主动消息队列
                    agent._stop_requested = False  # 停止标志
                    agent._modify_proposals = []  # 修改提案队列
                    agent._trend_history = _load_trend_history() or []     # 趋势历史数据（从磁盘恢复 + 图表用）
                    agent._trend_lock = threading.Lock()
                    agent.start()
                    # 启动后才开启趋势录制（确保 agent.running==True 且 memory/kg 已就绪）
                    agent._trend_thread = threading.Thread(
                        target=_trend_recorder, args=(agent,), daemon=True
                    )
                    agent._trend_thread.start()
                    # 启动后30秒推送欢迎消息
                    def _push_welcome(a):
                        import time
                        time.sleep(30)
                        try:
                            if hasattr(a, '_proactive_queue') and a.running:
                                a._proactive_queue.append({
                                    "time": time.time(),
                                    "content": "系统启动完成，一切运行正常。有需要随时叫我。"
                                })
                                print("[WebUI] 启动欢迎消息已推送", flush=True)
                        except Exception:
                            pass
                    threading.Thread(target=_push_welcome, args=(agent,), daemon=True).start()
                except Exception as e:
                    print(f"[WebUI] Agent 启动失败: {e}")
                    traceback.print_exc()
                    return None
    try:
        _ensure_default_session()
    except Exception:
        pass
    return agent

# ===== 趋势数据记录器（后台线程，每分钟记录一次） =====
def _trend_recorder(a):
    """每分钟记录系统关键指标，供趋势图使用（agent.start() 之后启动）"""
    fail_count = 0
    while True:
        try:
            time.sleep(60)
            if not getattr(a, 'running', False):
                continue
            
            stats = getattr(a, '_stats', {}) or {}
            kg = a.knowledge_graph if hasattr(a, 'knowledge_graph') else None
            mem = a.memory if hasattr(a, 'memory') else None
            
            # 获取 CPU 使用率（跨平台）
            cpu_val = 0
            try:
                cpu_val = psutil.cpu_percent(interval=0.5) if psutil else 0
            except Exception:
                cpu_val = stats.get("cpu_percent", stats.get("cpu", 0)) if stats else 0
            
            # 能量（与 /api/status 同路径）
            energy_val = 0.5
            try:
                energy_val = a.self_monitor.get_current_status().get("energy_level", 0.5)
            except Exception:
                try:
                    energy_val = a.meta.energy_level if hasattr(a, 'meta') and hasattr(a.meta, 'energy_level') else 0.5
                except Exception:
                    pass
            
            record = {
                "time": time.time(),
                "cpu_usage": round(cpu_val, 1),
                "energy_level": round(energy_val, 2),
                "knowledge_hits": stats.get("knowledge_hits", 0),
                "api_calls": stats.get("api_calls", 0),
                "mem_working": len(mem.working_memory) if mem and hasattr(mem, 'working_memory') else 0,
                "mem_long": len(mem.long_term_memories) if mem and hasattr(mem, 'long_term_memories') else 0,
                "causal": len(getattr(kg, '_causal_triples', [])) if kg and hasattr(kg, '_causal_triples') else 0,
                "kg_nodes": kg.graph.number_of_nodes() if kg and hasattr(kg, 'graph') and kg.graph else 0,
            }
            with a._trend_lock:
                a._trend_history.append(record)
                if len(a._trend_history) > 1440:  # 保留24小时
                    a._trend_history = a._trend_history[-1440:]
                # 每次记录后落盘（轻量 JSON，60s 一次无压力）
                _save_trend_history(list(a._trend_history))
            fail_count = 0  # 成功后重置
        except Exception as e:
            fail_count += 1
            if fail_count <= 3:
                print(f"[趋势录制] 异常 #{fail_count}: {type(e).__name__}", flush=True)
            if fail_count > 10:
                time.sleep(300)  # 连续失败则降低频率

# ===== API 路由 =====

@app.get("/", response_class=HTMLResponse)
async def index():
    """直接返回HTML页面（不使用Jinja2模板引擎）"""
    html_path = os.path.join(BASE_DIR, "webui", "templates", "index.html")
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(
                f.read(),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    except Exception as e:
        return HTMLResponse(f"<h1>页面加载失败</h1><pre>{e}</pre>")

@app.get("/favicon.ico")
async def favicon():
    """返回一个极简 SVG favicon"""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="8" fill="#111827"/><text x="32" y="44" font-size="36" text-anchor="middle" fill="#3b82f6" font-family="sans-serif">T</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/download/{filename:path}")
async def api_download(filename: str):
    """提供文件下载"""
    # 安全检查：防止目录穿越
    safe_path = os.path.normpath(os.path.join(OUTPUT_DIR, filename))
    if not safe_path.startswith(os.path.normpath(OUTPUT_DIR)):
        return JSONResponse({"error": "禁止访问"}, status_code=403)
    if not os.path.isfile(safe_path):
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    
    # 根据扩展名推测 content-type
    ext_map = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.pdf': 'application/pdf',
        '.zip': 'application/zip',
        '.tar': 'application/x-tar',
        '.gz': 'application/gzip',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.txt': 'text/plain; charset=utf-8',
        '.md': 'text/markdown; charset=utf-8',
        '.py': 'text/plain; charset=utf-8',
        '.json': 'application/json',
        '.html': 'text/html; charset=utf-8',
        '.csv': 'text/csv; charset=utf-8',
    }
    ext = os.path.splitext(filename)[1].lower()
    media_type = ext_map.get(ext, 'application/octet-stream')
    
    with open(safe_path, 'rb') as f:
        content = f.read()
    
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content))
        }
    )

@app.get("/api/status")
async def api_status():
    """获取系统状态（含仪表盘友好字段）"""
    a = get_agent()
    if a is None:
        return {"running": False, "error": "Agent未启动"}
    try:
        # 直接获取监控数据（不依赖 get_agent_status，避免 self_monitor 未初始化）
        try:
            mon = a.security.monitor_system_resource()
            cpu_usage = mon.get("cpu_usage", 0)
            mem_usage = mon.get("mem_usage", 0)
        except Exception:
            cpu_usage = 0
            mem_usage = 0
        
        # 总物理内存
        try:
            import psutil
            mem_total = psutil.virtual_memory().total / (1024*1024)
        except Exception:
            mem_total = 16000
        
        # 模型名称
        model_name = getattr(a.llm, 'direct_api_model', 'deepseek-chat') if hasattr(a, 'llm') else 'deepseek-chat'
        
        # 统计数据
        stats = getattr(a, '_stats', {})
        api_calls = stats.get("api_calls", 0)
        tool_calls = stats.get("tool_calls", 0)
        knowledge_hits = stats.get("knowledge_hits", 0)
        
        # 记忆
        mem_working = len(a.memory.working_memory) if hasattr(a.memory, 'working_memory') else 0
        mem_long = len(a.memory.long_term_memories) if hasattr(a.memory, 'long_term_memories') else 0
        
        # 知识图谱
        try:
            kg = a.knowledge_graph
            kg_nodes = kg.graph.number_of_nodes() if kg and kg.graph else 0
            kg_edges = kg.graph.number_of_edges() if kg and kg.graph else 0
        except Exception:
            kg_nodes = 0
            kg_edges = 0
        
        # 因果三元组 (实际存储为 _causal_triples，且通过 _init_causal() 按需加载)
        try:
            kg = a.knowledge_graph
            if hasattr(kg, '_causal_triples') and kg._causal_triples:
                causal_count = len(kg._causal_triples)
            else:
                # 尝试从文件直接读取
                import os, json
                causal_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/knowledge/knowledge_graph_causal.json")
                if os.path.exists(causal_file):
                    with open(causal_file, 'r', encoding='utf-8') as f:
                        causal_count = len(json.load(f))
                else:
                    causal_count = 0
        except Exception:
            causal_count = 0
        
        # 执行轨迹
        try:
            traces = len(a.memory.execution_traces) if hasattr(a.memory, 'execution_traces') else 0
        except Exception:
            traces = 0
        
        # 锚点
        try:
            anchor_stats = a.anchor_engine.get_stats() if hasattr(a, 'anchor_engine') else {}
            anchors = anchor_stats.get("total", 0) if isinstance(anchor_stats, dict) else 0
        except Exception:
            anchors = 0
        
        # 平均质量
        try:
            mems = a.memory.long_term_memories[-200:]
            scores = [m.get("data", {}).get("quality_score", 0.5) for m in mems]
            avg_quality = round(sum(scores) / len(scores), 2) if scores else 0.5
        except Exception:
            avg_quality = 0.5
        
        # 进化次数
        evolution = getattr(a.meta, 'evolution_count', 0) if hasattr(a, 'meta') else 0
        
        # 对话轮次
        conv_count = len(getattr(a, 'conversation_history', [])) // 2
        
        # 运行时长
        start = getattr(a, '_start_time', None)
        if start:
            uptime_sec = time.time() - start
            h = int(uptime_sec // 3600)
            m = int((uptime_sec % 3600) // 60)
            uptime = f"{h}h {m}m" if h else f"{m}m"
        else:
            uptime = "00:00"
        
        # 能量
        try:
            energy = a.self_monitor.get_current_status().get("energy_level", 0.5)
        except Exception:
            energy = a.meta.energy_level if hasattr(a.meta, 'energy_level') else 0.5
        
        return {
            "running": a.running if hasattr(a, 'running') else True,
            "cpu_usage": cpu_usage,
            "mem_usage": mem_usage,
            "mem_total": mem_total,
            "model_name": model_name,
            "tool_calls": tool_calls,
            "api_calls": api_calls,
            "knowledge_hits": knowledge_hits,
            "conversation_count": conv_count,
            "uptime": uptime,
            "energy_level": energy,
            "kg_nodes": kg_nodes,
            "kg_edges": kg_edges,
            "causal_count": causal_count,
            "mem_working": mem_working,
            "mem_long": mem_long,
            "traces": traces,
            "avg_quality": avg_quality,
            "anchors": anchors,
            "evolution": evolution,
        }
    except Exception as e:
        traceback.print_exc()
        return {"running": False, "error": str(e)[:200]}

@app.get("/api/mode")
async def api_mode():
    """返回当前运行模式（单实例/多实例）"""
    a = get_agent()
    return {
        "single_instance": not getattr(globals(), '_multi_mode', False),
        "mode": "单实例" if not getattr(globals(), '_multi_mode', False) else "多实例",
        "hint": "重复打开窗口会复用已有实例" if not getattr(globals(), '_multi_mode', False) else "允许多个实例并行运行"
    }

@app.post("/api/config")
async def api_config(data: dict):
    """更新模型配置 — 支持多 Key 轮换和客户端热切换"""
    a = get_agent()
    if a is None:
        return {"success": False, "error": "Agent未启动"}
    try:
        model = data.get("model", "")
        api_key = data.get("api_key", "")
        api_keys_text = data.get("api_keys", "")  # 多Key换行文本
        api_url = data.get("api_url", "https://api.deepseek.com")
        temperature = float(data.get("temperature", 0.7))
        
        # 解析多Key列表
        api_keys = []
        if api_keys_text.strip():
            api_keys = [k.strip() for k in api_keys_text.strip().split('\n') if k.strip().startswith('sk-')]
        elif api_key.strip():
            api_keys = [api_key.strip()]
        
        if not api_keys:
            return {"success": False, "error": "至少需要一个 API Key"}
        if not model:
            return {"success": False, "error": "模型名称不能为空"}
        
        # 保存到持久化配置
        import os, json
        config_file = os.path.join(BASE_DIR, "data", "api_config.json")
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        config_data = {
            "model": model,
            "api_keys": [k[:4]+"***"+k[-4:] for k in api_keys],  # 脱敏存储
            "api_keys_full": api_keys,  # 完整Key（仅供本地使用）
            "url": api_url,
            "temperature": temperature
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        
        # 热更新 LLMWrapper
        llm = a.llm
        if hasattr(llm, 'direct_api_model'):
            llm.direct_api_model = model
        if hasattr(llm, 'direct_api_base_url'):
            llm.direct_api_base_url = api_url.rstrip('/').rstrip('/v1')
        if hasattr(llm, 'direct_api_temperature'):
            llm.direct_api_temperature = temperature
        
        # 设置多Key轮换列表
        if hasattr(llm, 'api_keys'):
            llm.api_keys = api_keys
            llm._current_key_idx = 0
        
        # 重新初始化 OpenAI 客户端（使用第一个Key）
        try:
            from openai import OpenAI
            llm.client = OpenAI(api_key=api_keys[0], base_url=api_url.rstrip('/').rstrip('/v1'))
            llm.direct_api_key = api_keys[0]
            llm.use_direct_api = True
            print(f"[API Config] 热切换 → {model} | {len(api_keys)} Keys", flush=True)
        except Exception as e:
            print(f"[API Config] 客户端重建失败: {e}", flush=True)
        
        return {"success": True, "message": f"已切换至 {model}（{len(api_keys)} 个Key轮换）", "model": model, "key_count": len(api_keys)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)[:200]}

@app.post("/api/test")
async def api_test(data: dict):
    """测试 API 连接"""
    try:
        api_key = data.get("api_key", "")
        api_url = data.get("api_url", "")
        if not api_key:
            return {"success": False, "error": "API Key 不能为空"}
        
        import requests as _req
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 10
        }
        r = _req.post(api_url.rstrip('/') + "/chat/completions", headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            return {"success": True, "message": f"连接成功，延迟 {r.elapsed.total_seconds():.1f}s"}
        else:
            err = r.json().get("error", {}).get("message", r.text[:200])
            return {"success": False, "error": f"HTTP {r.status_code}: {err}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@app.post("/api/chat")
async def api_chat(data: dict):
    """处理聊天消息，返回回复和可能的文件下载"""
    text = data.get("text", "")
    session_id = data.get("session", "default")
    if not text.strip():
        return {"error": "消息为空"}
    
    a = get_agent()
    if a is None:
        return {"error": "Agent未启动"}
    
    # 重置停止标志
    a._stop_requested = False
    
    # 保存用户消息
    _save_message(session_id, "user", text)
    
    # 记录执行前 outputs 目录的文件列表
    before = set(os.listdir(OUTPUT_DIR)) if os.path.isdir(OUTPUT_DIR) else set()
    
    try:
        # run_in_executor: 同步阻塞函数扔到线程池，不卡事件循环（终端可实时刷新）
        import asyncio as _asyncio
        reply = await _asyncio.get_event_loop().run_in_executor(None, a.process_user_command, text)
        reply_text = str(reply)
        # 检查是否被停止
        if a._stop_requested:
            reply_text = "⏹ 已停止处理"
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)[:500]}
    
    # 保存回复
    _save_message(session_id, "assistant", reply_text)
    
    # 检测新生成的文件
    after = set(os.listdir(OUTPUT_DIR)) if os.path.isdir(OUTPUT_DIR) else set()
    new_files = [f for f in (after - before) if not f.startswith('.')]
    
    result = {"reply": reply_text}
    if new_files:
        file_info = []
        for fname in new_files:
            fpath = os.path.join(OUTPUT_DIR, fname)
            size = os.path.getsize(fpath)
            file_info.append({
                "name": fname,
                "size": size,
                "url": f"/api/download/{fname}"
            })
        result["files"] = file_info
    
    return result

@app.post("/api/stop")
async def api_stop():
    """强制停止当前处理"""
    a = get_agent()
    if a is None:
        return {"success": False}
    a._stop_requested = True
    print("[WebUI] 用户请求停止处理", flush=True)
    return {"success": True, "message": "已发出停止信号"}

@app.get("/api/proactive")
async def api_proactive():
    """获取管家主动发起的消息（去重+过滤刷屏消息）"""
    a = get_agent()
    if a is None:
        return {"messages": []}
    msgs = list(getattr(a, '_proactive_queue', []))
    if msgs:
        a._proactive_queue.clear()
    
    # 去重：相同内容的消息只保留一条
    seen = set()
    filtered = []
    for m in msgs:
        content = m.get("content", "") if isinstance(m, dict) else str(m)
        # 过滤掉克隆数量提醒（每5秒刷屏）
        if "已有" in content and "分身在线" in content:
            continue
        if content not in seen:
            seen.add(content)
            filtered.append(m)
    
    # 写入历史（不丢消息，前端首次打开可回溯）
    if filtered:
        try:
            hist = getattr(a, '_proactive_history', None)
            if hist is None:
                a._proactive_history = []
                hist = a._proactive_history
            for m in filtered:
                hist.append(m)
            if len(hist) > 200:
                a._proactive_history = hist[-200:]
        except Exception:
            pass
    
    if filtered:
        print(f"[主动交付] {len(filtered)} 条消息推送到前端", flush=True)
    return {"messages": filtered}

@app.get("/api/proactive-history")
async def api_proactive_history():
    """获取最近主动消息历史（页面首次加载用）"""
    a = get_agent()
    if a is None:
        return {"messages": []}
    hist = list(getattr(a, '_proactive_history', []))
    return {"messages": hist[-20:]}

@app.get("/api/junk-bin")
async def api_junk_bin():
    """查看回收站内容（data/.junk_bin/）"""
    base = BASE_DIR if 'BASE_DIR' in dir() else os.path.dirname(os.path.abspath(__file__))
    # BASE_DIR 可能是 webui/ 目录，需要上移到 v5.9/
    if os.path.basename(base) == 'webui':
        base = os.path.dirname(base)
    junk_dir = os.path.join(base, 'data', '.junk_bin')
    if not os.path.isdir(junk_dir):
        return {"exists": False, "files": [], "total_size": 0}
    
    files = []
    total_size = 0
    for f in sorted(os.listdir(junk_dir), key=lambda x: os.path.getmtime(os.path.join(junk_dir, x)), reverse=True):
        fpath = os.path.join(junk_dir, f)
        if os.path.isfile(fpath):
            sz = os.path.getsize(fpath)
            total_size += sz
            mtime = os.path.getmtime(fpath)
            files.append({
                "name": f,
                "size": sz,
                "size_str": f"{sz/1024:.1f}KB" if sz < 1024*1024 else f"{sz/1024/1024:.1f}MB",
                "mtime": mtime,
                "mtime_str": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)),
                # 从文件名解析来源（时间戳_来源_原名）
                "source": f.split('_')[1] if len(f.split('_')) >= 2 else "未知"
            })
    
    return {
        "exists": True,
        "files": files,
        "total_files": len(files),
        "total_size": total_size,
        "total_size_str": f"{total_size/1024:.1f}KB" if total_size < 1024*1024 else f"{total_size/1024/1024:.1f}MB"
    }

@app.get("/api/pending-modify")
async def api_pending_modify():
    """获取待审批的自修改提案"""
    a = get_agent()
    if a is None:
        return {"proposals": []}
    proposals = list(getattr(a, '_modify_proposals', []))
    # 内存为空时从磁盘恢复（防重启丢失）
    if not proposals:
        try:
            import glob as _glob, json as _json_disk
            persist_dir = os.path.join(_BASE_DIR, 'data', 'proposals')
            disk_files = sorted(_glob.glob(os.path.join(persist_dir, '*.json')))
            for fp in disk_files[-10:]:
                try:
                    with open(fp, 'r', encoding='utf-8') as _df:
                        p = _json_disk.load(_df)
                    if p.get('status') == 'pending' and p.get('expire', 0) > time.time():
                        proposals.append(p)
                        if not hasattr(a, '_modify_proposals'):
                            a._modify_proposals = []
                        a._modify_proposals.append(p)
                except Exception:
                    pass
        except Exception:
            pass
    # 只返回待审批的（status=pending）
    pending = [p for p in proposals if p.get("status", "pending") == "pending"]
    # 返回最近5条
    result = pending[-5:]
    for p in result:
        # 清理时间戳为可读格式
        if "time" in p and isinstance(p["time"], (int, float)):
            p["time_str"] = __import__('time').strftime('%H:%M:%S', __import__('time').localtime(p["time"]))
    return {"proposals": result}

@app.get("/api/test-approval")
async def api_test_approval():
    """[TEST] 注入一条测试审批，验证UI链路"""
    a = get_agent()
    if a is None:
        return {"success": False, "error": "Agent not ready"}
    import uuid, time as _time
    pid = str(uuid.uuid4())[:8]
    proposal = {
        "id": pid,
        "summary": "【测试】验证审批UI链路",
        "detail": "这是一个测试补丁，用于验证审批面板是否正确显示。批准后不会修改任何文件。",
        "analysis": "影响范围：无。LLM分析认为此修改安全可执行。建议继续。",
        "snap_id": "",
        "time": _time.time(),
        "expire": _time.time() + 1800,
        "patches": []
    }
    if not hasattr(a, '_modify_proposals'):
        a._modify_proposals = []
    a._modify_proposals.append(proposal)
    return {"success": True, "proposal_id": pid, "message": "测试审批已注入，刷新页面查看"}

@app.post("/api/modify-decision")
async def api_modify_decision(request: Request):
    """审批自修改提案（批准/拒绝）—— v5.9-fix: 批准后实际执行补丁（含代码补丁）"""
    a = get_agent()
    if a is None:
        return {"success": False, "error": "Agent not ready"}
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON"}
    proposal_id = body.get("proposal_id", "")
    decision = body.get("decision", "reject")  # approve or reject
    if not proposal_id:
        return {"success": False, "error": "Missing proposal_id"}
    
    proposals = getattr(a, '_modify_proposals', [])
    matched = None
    for p in proposals:
        if p.get("id") == proposal_id:
            matched = p
            p["status"] = "approved" if decision == "approve" else "rejected"
            p["decided_at"] = __import__('time').time()
            print(f"[审批] {proposal_id[:12]} → {p['status']}", flush=True)
            break
    
    if matched is None:
        return {"success": False, "error": "Proposal not found"}
    
    # ═══ v5.9: 批准后执行实际修复（数据+代码）═══
    fix_result = {"applied": 0, "details": []}
    if decision == "approve":
        # 防闪退：等 2 秒确保后台线程稳定后再动文件
        __import__('time').sleep(2)
        q = getattr(a, '_proactive_queue', [])
        desc = str(matched.get("summary", matched.get("description", "自修改提案")))[:100]
        q.append({"time": __import__('time').time(), "content": f"✅ 已批准: {desc}"})
        
        try:
            analysis = str(matched.get("analysis", ""))
            detail = str(matched.get("detail", ""))
            text = analysis + " " + detail + " " + desc
            
            # 1. 经验修剪
            if hasattr(a, 'memory') and hasattr(a.memory, 'experiences'):
                mem = a.memory
                if any(kw in text for kw in ['经验', '质量', 'prune', '修剪', 'audit']):
                    before = len(mem.experiences)
                    mem.experiences = [e for e in mem.experiences if e.get('quality', 0.5) >= 0.05]
                    removed = before - len(mem.experiences)
                    if removed > 0:
                        fix_result["applied"] += 1
                        fix_result["details"].append(f"修剪{removed}条低质经验")
                        print(f"  [审批执行] 经验修剪: {before}→{len(mem.experiences)}", flush=True)
            
            # 2. 图谱保存
            if hasattr(a, 'knowledge_graph') and hasattr(a.knowledge_graph, 'save'):
                try:
                    a.knowledge_graph.save()
                    fix_result["applied"] += 1
                    fix_result["details"].append("知识图谱已保存")
                except Exception as e:
                    fix_result["details"].append(f"图谱保存失败: {e}")
            
            # 3. 记忆保存
            if hasattr(a, 'memory') and hasattr(a.memory, 'save'):
                try:
                    a.memory.save()
                    fix_result["applied"] += 1
                    fix_result["details"].append("记忆已保存")
                except Exception as e:
                    fix_result["details"].append(f"记忆保存失败: {e}")
            
            # 4. 知识缺口 → 触发实体发现
            if any(kw in text for kw in ['知识缺口', '零增长', '实体缺失', '知识图谱']):
                try:
                    if hasattr(a, 'maintainer') and hasattr(a.maintainer, '_discover_entities'):
                        a.maintainer._discover_entities()
                        fix_result["applied"] += 1
                        fix_result["details"].append("触发知识实体发现")
                        print(f"  [审批执行] 触发知识实体发现", flush=True)
                except Exception as e:
                    fix_result["details"].append(f"实体发现失败: {e}")
            
            # 5. 进化停滞 → 触发自进化
            if any(kw in text for kw in ['进化', '停滞', 'evolution']):
                try:
                    if hasattr(a, 'meta') and hasattr(a.meta, 'trigger_self_evolution'):
                        a.meta.trigger_self_evolution()
                        fix_result["applied"] += 1
                        fix_result["details"].append("触发自进化")
                        print(f"  [审批执行] 触发自进化", flush=True)
                except Exception as e:
                    fix_result["details"].append(f"自进化失败: {e}")
            
            # ═══ 6. 代码补丁 — 真改文件 + 自动备份（v5.9打通）═══
            patches = matched.get("patches", [])
            if not patches:
                # 兼容：从 detail 里解析补丁格式
                import re as _re3
                pm = _re3.search(r'文件=(.+?)\n旧内容=(.+?)\n新内容=(.+?)$', detail, _re3.DOTALL)
                if pm:
                    patches = [{
                        "file": pm.group(1).strip(),
                        "old_text": pm.group(2).strip(),
                        "new_text": pm.group(3).strip()
                    }]
            for patch in patches:
                try:
                    patch_file = patch.get("file", "")
                    patch_old = patch.get("old_text", "")
                    patch_new = patch.get("new_text", "")
                    if not patch_file or not patch_old:
                        continue
                    # ⚠️ 安全：只允许改主框架自身
                    if "TrueAgent_Hyper" not in patch_file and "webui" not in patch_file:
                        fix_result["details"].append(f"❌ 拒绝修补非框架文件: {os.path.basename(patch_file)}")
                        continue
                    # 📋 自动备份
                    backup_dir = os.path.join(_BASE_DIR, "backups")
                    os.makedirs(backup_dir, exist_ok=True)
                    ts = __import__('time').strftime("%Y%m%d_%H%M%S")
                    backup_path = os.path.join(backup_dir, f"{os.path.basename(patch_file)}_{ts}_patch.py")
                    if os.path.exists(patch_file):
                        import shutil as _shutil
                        _shutil.copy2(patch_file, backup_path)
                        fix_result["details"].append(f"📋 已备份: {os.path.basename(backup_path)}")
                    # ✏️ 原子写入：先写临时文件，再 rename（防读半截崩溃）
                    import tempfile as _tf, shutil as _sh2
                    with open(patch_file, 'r', encoding='utf-8') as _pf:
                        original = _pf.read()
                    if patch_old not in original:
                        fix_result["details"].append(f"⚠️ 补丁不匹配: {os.path.basename(patch_file)} (old_text未找到)")
                        continue
                    patched = original.replace(patch_old, patch_new, 1)
                    # 写临时文件
                    tmp_fd, tmp_path = _tf.mkstemp(suffix='.py', dir=os.path.dirname(os.path.abspath(patch_file)))
                    try:
                        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as _pf:
                            _pf.write(patched)
                        os.replace(tmp_path, patch_file)  # 原子替换
                    except:
                        try: os.unlink(tmp_path)
                        except: pass
                        raise
                    # 验证语法
                    try:
                        import ast as _ast
                        _ast.parse(patched)
                        fix_result["applied"] += 1
                        fix_result["details"].append(f"✅ 补丁已应用: {os.path.basename(patch_file)}")
                        print(f"  [审批执行] 代码补丁已应用: {os.path.basename(patch_file)}", flush=True)
                    except SyntaxError as se:
                        # 语法错误 → 回滚
                        with open(patch_file, 'w', encoding='utf-8') as _pf:
                            _pf.write(original)
                        fix_result["details"].append(f"❌ 补丁语法错误已回滚: {os.path.basename(patch_file)} ({se})")
                        print(f"  [审批执行] 补丁语法错误，已回滚: {se}", flush=True)
                except Exception as pe:
                    fix_result["details"].append(f"补丁执行异常: {str(pe)[:80]}")
                    print(f"  [审批执行] 补丁异常: {pe}", flush=True)
            
            # 推送执行结果
            if fix_result["applied"] > 0:
                summary = " | ".join(fix_result["details"][:3])
                q.append({"time": __import__('time').time(), "content": f"🔧 补丁已执行: {summary}"})
                print(f"  [审批执行] 完成，应用{fix_result['applied']}项修复", flush=True)
            else:
                q.append({"time": __import__('time').time(), "content": "ℹ️ 审批通过但未匹配到具体修复项"})
                
        except Exception as e:
            print(f"  [审批执行] 异常: {e}", flush=True)
            fix_result["details"].append(f"执行异常: {str(e)[:100]}")
    
    return {"success": True, "proposal_id": proposal_id, "decision": matched["status"], "fix": fix_result}

@app.post("/api/trigger_proactive")
async def api_trigger_proactive(request: Request):
    """手动触发一条主动消息（用于测试）"""
    a = get_agent()
    if a is None:
        return {"success": False, "error": "Agent not ready"}
    content = "我刚刚完成了一次自我检查，一切运行正常。有什么需要帮忙的吗？"
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("content"):
            content = body["content"]
    except Exception:
        pass
    try:
        q = getattr(a, '_proactive_queue', [])
        q.append({"time": __import__('time').time(), "content": content})
        print(f"[WebUI] 手动触发主动消息: {content[:50]}", flush=True)
        return {"success": True, "message": "已推送"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/trigger_learning")
async def api_trigger_learning():
    """手动触发综合性学习"""
    a = get_agent()
    if a is None:
        return {"success": False, "error": "Agent not ready"}
    if not hasattr(a, 'maintainer'):
        return {"success": False, "error": "Maintainer not available"}
    try:
        result = a.maintainer._scene_learning()
        result2 = None
        # 也触发知识整理（第二轮）
        try:
            result2 = a.maintainer._knowledge_organize()
            print(f"[WebUI] 知识整理: {result2}", flush=True)
        except Exception as e2:
            print(f"[WebUI] 知识整理异常: {e2}", flush=True)
        print(f"[WebUI] 场景学习: {result}", flush=True)
        return {"success": True, "scene_learning": str(result)[:300], "knowledge_organize": str(result2)[:300] if result2 else "none"}
        return {"success": True, "result": str(result)[:500]}
    except Exception as e:
        print(f"[WebUI] 综合性学习失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/conversations")
async def api_conversations():
    """获取会话列表"""
    return {"sessions": _load_sessions()}

@app.post("/api/conversations/new")
async def api_conversations_new(data: dict = None):
    """创建新会话"""
    import uuid
    sid = str(uuid.uuid4())[:8]
    title = (data or {}).get("title", f"会话 {len(_load_sessions())+1}")
    now = time.time()
    sessions = _load_sessions()
    sessions.append({"id": sid, "title": title, "created": now, "updated": now})
    _save_sessions(sessions)
    return {"session_id": sid}

@app.get("/api/conversations/{session_id}")
async def api_conversation_get(session_id: str):
    """获取指定会话的历史消息"""
    msgs = _load_messages(session_id)
    return {"messages": msgs, "session_id": session_id}

@app.delete("/api/conversations/{session_id}")
async def api_conversation_del(session_id: str):
    """删除会话"""
    sessions = _load_sessions()
    sessions = [s for s in sessions if s.get("id") != session_id]
    _save_sessions(sessions)
    path = os.path.join(CONV_DIR, f"{session_id}.jsonl")
    if os.path.exists(path):
        os.remove(path)
    return {"success": True}

@app.post("/api/upload")
async def api_upload(files: list[UploadFile] = File(...)):
    """上传文件（支持图片预览 + OCR + 文本读取）"""
    a = get_agent()
    if a is None:
        return {"error": "Agent未启动"}
    
    uploads_dir = os.path.join(BASE_DIR, "data", "cache", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    summaries = []
    image_urls = []
    for f in files:
        try:
            content = await f.read()
            ext = os.path.splitext(f.filename)[1].lower()
            safe_name = f"{int(time.time()*1000)}_{f.filename}"
            save_path = os.path.join(uploads_dir, safe_name)
            with open(save_path, 'wb') as fh:
                fh.write(content)
            
            if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'):
                # 图片 → OCR + 生成可预览URL
                image_urls.append(f"/uploads/{safe_name}")
                from extensions.ocr_skill import ocr_image_file
                r = ocr_image_file(str(save_path))
                if r.get("success"):
                    summaries.append(f"📷 {f.filename}: {r['text'][:300]}")
                else:
                    summaries.append(f"📷 {f.filename}: (图片)")
            elif ext in ('.txt', '.md', '.py', '.js', '.html', '.json', '.yaml', '.yml', '.xml', '.css'):
                text = content.decode('utf-8', errors='replace')
                summaries.append(f"📄 {f.filename} ({len(text)}字符):\n{text[:500]}")
            else:
                summaries.append(f"📎 {f.filename} ({len(content)}字节)")
        except Exception as e:
            summaries.append(f"❌ {f.filename}: {e}")
    
    full = "\n".join(summaries)
    
    # 送给agent处理
    try:
        reply = a.process_user_command(f"用户上传了文件:\n{full}")
        return {"summary": full, "reply": str(reply), "images": image_urls}
    except Exception as e:
        return {"summary": full, "reply": f"(处理完成，共{len(files)}个文件)", "images": image_urls}

@app.post("/api/screenshot-ocr")
async def api_screenshot_ocr():
    """截图 + OCR"""
    try:
        from extensions.ocr_skill import ocr_screenshot
        r = ocr_screenshot()
        if r.get("success"):
            return {"text": r["text"]}
        return {"error": r.get("error", "OCR无结果")}
    except Exception as e:
        return {"error": str(e)[:200]}

@app.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...)):
    """语音转文字（Whisper）"""
    try:
        import whisper
        import tempfile
        import numpy as np
        import soundfile as sf
        
        content = await audio.read()
        
        # 加载Whisper模型
        model = whisper.load_model("base")
        
        # 写入临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
        tmp.write(content)
        tmp.close()
        
        # 识别
        result = model.transcribe(tmp.name, language="zh")
        os.unlink(tmp.name)
        
        text = result.get("text", "").strip()
        if text:
            return {"text": text}
        return {"error": "未识别到语音"}
    except Exception as e:
        return {"error": f"语音识别失败: {str(e)[:200]}"}

# ===== 审批反馈接口 =====

def _run_maintenance(agent, summary, detail):
    """安全执行审批通过后的维护操作（防崩）"""
    try:
        cmd = f"执行系统维护: {summary}"
        if detail:
            cmd += f"\n详情: {detail[:200]}"
        agent.process_user_command(cmd)
    except Exception as e:
        print(f"[审批执行异常] {e}", flush=True)
        traceback.print_exc()


@app.get("/api/pending-modify")
async def api_pending_modify():
    """获取待审批的修改提案"""
    a = get_agent()
    if not a or not hasattr(a, '_modify_proposals'):
        return JSONResponse({"proposals": []})
    with a._trend_lock:
        return JSONResponse({"proposals": a._modify_proposals[-5:]})

@app.post("/api/modify-decision")
async def api_modify_decision(request: Request):
    """审批/拒绝修改提案"""
    a = get_agent()
    if not a or not hasattr(a, '_modify_proposals'):
        return JSONResponse({"error": "Agent未就绪"})
    data = await request.json()
    proposal_id = data.get("id", "")
    decision = data.get("decision", "")
    if not proposal_id or decision not in ("approve", "reject"):
        return JSONResponse({"error": "参数无效"})
    with a._trend_lock:
        for i, p in enumerate(a._modify_proposals):
            if p.get("id") == proposal_id:
                p["decision"] = decision
                a._modify_proposals.pop(i)
                msg = f"{'[OK] 已批准' if decision=='approve' else '[X] 已拒绝'}: {p.get('summary','?')}"
                a._proactive_queue.append({
                    "time": time.time(), "content": msg, "type": "approval_result"
                })
                if decision == "approve":
                    # 修复：闭包变量捕获（pop后p仍有效） + plan键缺失回退
                    _summary = p.get("summary", "系统维护")
                    _detail = p.get("detail", "")
                    threading.Thread(
                        target=lambda s=_summary, d=_detail: _run_maintenance(a, s, d),
                        daemon=True
                    ).start()
                return JSONResponse({"ok": True, "decision": decision})
    return JSONResponse({"error": "提案未找到"})

# ===== 趋势数据接口 =====
@app.get("/api/trends")
async def api_trends():
    """获取趋势数据（仪表盘图表用）鈥斺 合并系统趋势 + 智能体统计时间线"""
    a = get_agent()
    result = {"trends": [], "stats_history": []}
    # 系统趋势（CPU/内存/知识/causal等，由后台Recorder记录）
    if a and hasattr(a, '_trend_history'):
        with a._trend_lock:
            history = a._trend_history[-120:]
            if len(history) > 60:
                step = len(history) // 60
                history = history[::step]
            result["trends"] = history
    # 智能体统计时间线（由 _record_stats_snapshot 记录）
    if a and hasattr(a, '_stats_history'):
        try:
            hist = list(a._stats_history)[-200:]
            if len(hist) > 100:
                step = len(hist) // 100
                hist = hist[::step]
            result["stats_history"] = hist
        except Exception:
            pass
    return JSONResponse(result)

# ===== 任务分解器进度接口 =====
@app.get("/api/task-sessions")
async def api_task_sessions():
    """获取运行中的任务会话进度"""
    a = get_agent()
    if a and hasattr(a, 'task_decomposer') and a.task_decomposer is not None:
        try:
            # 返回活跃任务 + 最近10个已完成任务
            active = a.task_decomposer.list_active()
            all_sessions = []
            for sid, s in list(a.task_decomposer.sessions.items())[:10]:
                d = s.to_dict()
                if d not in active:
                    all_sessions.append(d)
            return JSONResponse({"sessions": active + all_sessions})
        except Exception as e:
            return JSONResponse({"sessions": [], "error": str(e)[:100]})
    return JSONResponse({"sessions": []})

# ===== 智能分身管理 =====

# 跟踪分身后台进程
_clone_processes = {}  # {agent_id: {"proc": subprocess.Popen, "port": int, "data_dir": str}}

# ===== 终端日志缓冲区（捕获 CMD 输出给 WebUI 显示） =====
import collections
_terminal_buffer = collections.deque(maxlen=500)

class TerminalCapture:
    def __init__(self, original):
        self.orig = original
    def write(self, text):
        if text:
            # WebUI 终端保留原始 UTF-8（不乱码），CMD 窗口用 GBK 安全版
            _terminal_buffer.append(text)
            if self.orig:
                try:
                    safe_text = text.encode('gbk', errors='replace').decode('gbk', errors='replace')
                    self.orig.write(safe_text)
                except Exception:
                    pass
        elif self.orig:
            try:
                self.orig.write(text)
            except Exception:
                pass
    def flush(self):
        if self.orig:
            try:
                self.orig.flush()
            except Exception:
                pass
    def isatty(self):
        return False
    def fileno(self):
        if self.orig and hasattr(self.orig, 'fileno'):
            return self.orig.fileno()
        return 0

# 安装终端捕获（第一次导入时）
import sys as _sys
if not isinstance(_sys.stdout, TerminalCapture):
    _sys.stdout = TerminalCapture(_sys.stdout)
    _sys.stderr = TerminalCapture(_sys.stderr)

@app.get("/api/terminal-log")
async def api_terminal_log():
    """返回最近500行的终端输出"""
    try:
        text = ''.join(_terminal_buffer)
        # 保留最后20000字符
        if len(text) > 20000:
            text = text[-20000:]
        return JSONResponse({"log": text})
    except Exception as e:
        return JSONResponse({"log": "", "error": str(e)[:100]})

@app.post("/api/notify")
async def api_notify(request: Request):
    """接收其他智能体的通知（@mention 唤醒等）"""
    try:
        data = await request.json()
        ntype = data.get("type", "info")
        content = data.get("content", "")
        source = data.get("from", "unknown")
        a = get_agent()
        if a and hasattr(a, '_proactive_queue'):
            a._proactive_queue.append({
                "time": time.time(),
                "content": f"📢 {source} 提到你了: {content[:100]}"
            })
        return JSONResponse({"success": True, "message": "通知已接收"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:100]})

@app.post("/api/spawn-clone")
async def api_spawn_clone(request: Request):
    """派遣智能分身——通过 CloneManager 统一调度，Key池自动分配"""
    try:
        a = get_agent()
        if not a or not hasattr(a, 'clone_manager') or not a.clone_manager:
            return {"success": False, "error": "分身管理器未启用"}
        
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        task = body.get("task", "") or body.get("description", "")
        if not task:
            task = "通用分析任务"
        
        cm = a.clone_manager
        clone_id = cm.dispatch(task)
        if not clone_id:
            active = cm.get_active_count()
            return {
                "success": False,
                "error": f"分身槽已满（{active}/{cm.MAX_CLONES}，Key池 {len(cm._key_pool)} 把）",
                "active_count": active,
                "max_clones": cm.MAX_CLONES,
                "key_pool_size": len(cm._key_pool),
            }
        
        return {
            "success": True,
            "clone_id": clone_id,
            "message": f"分身 {clone_id} 已派遣（Key池 {len(cm._key_pool)} 把自动分配）",
            "active_count": cm.get_active_count(),
            "max_clones": cm.MAX_CLONES,
            "key_pool_size": len(cm._key_pool),
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@app.post("/api/clone-stop")
async def api_clone_stop(request: Request):
    """停止指定分身——通过 CloneManager"""
    try:
        a = get_agent()
        body = await request.json()
        clone_id = body.get("clone_id", "") or body.get("agent_id", "")
        if not clone_id:
            return JSONResponse({"success": False, "error": "缺少 clone_id"})
        if not a or not hasattr(a, 'clone_manager') or not a.clone_manager:
            return JSONResponse({"success": False, "error": "分身管理器未启用"})
        a.clone_manager.terminate(clone_id)
        return JSONResponse({"success": True, "clone_id": clone_id, "message": f"分身 {clone_id} 已终止"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/clone-restart")
async def api_clone_restart(request: Request):
    """重启分身——先终止再重新派遣"""
    try:
        a = get_agent()
        body = await request.json()
        clone_id = body.get("clone_id", "") or body.get("agent_id", "")
        task = body.get("task", "") or body.get("description", "")
        if not clone_id:
            return JSONResponse({"success": False, "error": "缺少 clone_id"})
        if not a or not hasattr(a, 'clone_manager') or not a.clone_manager:
            return JSONResponse({"success": False, "error": "分身管理器未启用"})
        cm = a.clone_manager
        cm.terminate(clone_id)
        new_id = cm.dispatch(task or "通用分析任务")
        if not new_id:
            return JSONResponse({"success": False, "error": "重新派遣失败"})
        return JSONResponse({"success": True, "old_clone_id": clone_id, "new_clone_id": new_id,
                            "message": f"分身 {clone_id} → {new_id} 已重启"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.get("/api/clone-status")
async def api_clone_status():
    """查询所有分身状态（只读，不触发任何操作）"""
    try:
        a = get_agent()
        if not a or not hasattr(a, 'clone_manager') or not a.clone_manager:
            return JSONResponse({"clones": [], "active_count": 0})
        cm = a.clone_manager
        return JSONResponse({
            "clones": cm.get_status(),
            "active_count": cm.get_active_count(),
            "max_clones": cm.MAX_CLONES,
            "key_pool_size": len(cm._key_pool),
        })
    except Exception as e:
        return JSONResponse({"clones": [], "error": str(e)[:200]})

# ===== 返回主 API 端点 =====

# ===== Orchestrator LLM 任务分解 =====

def _build_decompose_prompt(pkg):
    """构建 LLM 分解任务的提示词"""
    return f"""你是任务分解专家。将以下目标拆分为可并行执行的子任务。

【目标】{pkg['goal']}
【背景】{pkg.get('background', '无')}
【质量标准】{pkg.get('quality_standards', '无')}

要求：
1. 每个子任务独立、可验证、有明确输出
2. 2-6个子任务为宜
3. 每个子任务包含：description（描述）、requirements（要求）、quality_standards（质量标准）

严格返回 JSON 数组格式，不要任何额外文本：
[
  {{"description": "...", "requirements": "...", "quality_standards": "..."}},
  ...
]"""

def _parse_decompose_json(raw):
    """从 LLM 原始输出中提取 JSON 数组"""
    import re
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'```\s*$', '', raw)
    start = raw.find('[')
    end = raw.rfind(']')
    if start >= 0 and end > start:
        raw = raw[start:end+1]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [{k: str(v) for k, v in st.items()} for st in data]
    except json.JSONDecodeError:
        pass
    lines = [l.strip() for l in raw.split('\n') if l.strip() and len(l.strip()) > 5]
    if len(lines) >= 2:
        return [{"description": l.strip('- ')} for l in lines if not l.startswith('[')]
    return None

# ===== 任务编排端点 =====

_orchestrator_sys = None
def _get_orch():
    global _orchestrator_sys
    if _orchestrator_sys is None:
        from extensions.task_orchestrator import get_orchestrator
        _orchestrator_sys = get_orchestrator()
    return _orchestrator_sys

@app.post("/api/orchestrator/create")
async def api_orch_create(request: Request):
    """创建任务包"""
    try:
        body = await request.json()
        goal = body.get("goal", "")
        background = body.get("background", "")
        quality = body.get("quality", "")
        files = body.get("files", [])
        if not goal:
            return JSONResponse({"success": False, "error": "缺少目标描述"})
        orch = _get_orch()
        pkg = orch.create_package(goal, background, quality, files)
        return JSONResponse({"success": True, "package": pkg})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/decompose")
async def api_orch_decompose(request: Request):
    """LLM 驱动分解任务为子任务列表"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        pkg = orch.get_package(pkg_id)
        if not pkg:
            return JSONResponse({"success": False, "error": "任务包不存在"})
        
        # 已有子任务则直接返回
        existing = pkg.get("subtasks", [])
        if existing:
            return JSONResponse({
                "success": True,
                "subtasks": existing,
                "package": orch.get_package(pkg_id),
                "cached": True
            })
        
        # === LLM 分解 ===
        a = get_agent()
        if not a:
            return JSONResponse({"success": False, "error": "Agent未启动"})
        
        prompt = _build_decompose_prompt(pkg)
        raw = a.generate(prompt, max_tokens=2048)
        
        # 解析 JSON
        subtasks = _parse_decompose_json(raw)
        if not subtasks:
            return JSONResponse({
                "success": False,
                "error": "LLM 分解结果无法解析",
                "raw": raw[:500]
            })
        
        # 写入 orchestrator
        for st in subtasks:
            orch.add_subtask(pkg_id, st)
        
        return JSONResponse({
            "success": True,
            "subtasks": subtasks,
            "package": orch.get_package(pkg_id),
            "cached": False
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/add-subtask")
async def api_orch_add_subtask(request: Request):
    """手动添加子任务"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        subtask = body.get("subtask", {})
        orch = _get_orch()
        result = orch.add_subtask(pkg_id, subtask)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.get("/api/orchestrator/packages")
async def api_orch_packages():
    """获取所有任务包"""
    try:
        orch = _get_orch()
        pkgs = orch.list_packages(20)
        return JSONResponse({"success": True, "packages": pkgs})
    except Exception as e:
        return JSONResponse({"success": True, "packages": [], "error": str(e)[:200]})

@app.get("/api/orchestrator/package/{package_id}")
async def api_orch_package(package_id: str):
    """获取单个任务包详情"""
    try:
        orch = _get_orch()
        pkg = orch.get_package(package_id)
        if not pkg:
            return JSONResponse({"success": False, "error": "任务包不存在"})
        return JSONResponse({"success": True, "package": pkg})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/analyze")
async def api_orch_analyze(request: Request):
    """智能体分析 + 自动分解（如无子任务则先 LLM 分解）"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        pkg = orch.get_package(pkg_id)
        if not pkg:
            return JSONResponse({"success": False, "error": "任务包不存在"})
        
        # 无子任务 → 先触发 LLM 分解
        if not pkg.get("subtasks"):
            a = get_agent()
            if a:
                prompt = _build_decompose_prompt(pkg)
                raw = a.generate(prompt, max_tokens=2048)
                subtasks = _parse_decompose_json(raw)
                if subtasks:
                    for st in subtasks:
                        orch.add_subtask(pkg_id, st)
                    pkg = orch.get_package(pkg_id)
        
        # 然后分析智能体匹配
        result = orch.analyze_agents_for_task(pkg_id)
        result["package"] = pkg
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/assign")
async def api_orch_assign(request: Request):
    """分配子任务给智能体"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        assignment = body.get("assignment", {})
        orch = _get_orch()
        result = orch.assign_task(pkg_id, assignment)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/monitor")
async def api_orch_monitor(request: Request):
    """监控任务进度"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        result = orch.monitor_progress(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/report")
async def api_orch_report(request: Request):
    """生成进度报告"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        result = orch.generate_report(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/collect")
async def api_orch_collect(request: Request):
    """收集结果"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        result = orch.collect_results(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/orchestrator/finalize")
async def api_orch_finalize(request: Request):
    """最终整合"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        orch = _get_orch()
        result = orch.finalize(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

# ===== 一键编排流水线 =====

@app.post("/api/orchestrator/pipeline")
async def api_orch_pipeline(request: Request):
    """一键完整流水线：创建 → LLM分解 → 智能体分析 → 自动分配 → 启动引擎"""
    try:
        body = await request.json()
        goal = body.get("goal", "")
        background = body.get("background", "")
        quality = body.get("quality", "")
        files = body.get("files", [])
        auto_start = body.get("auto_start", True)
        
        if not goal:
            return JSONResponse({"success": False, "error": "缺少目标描述"})
        
        a = get_agent()
        if not a:
            return JSONResponse({"success": False, "error": "Agent未启动"})
        
        orch = _get_orch()
        eng = _get_engine()
        
        steps = []
        
        # Step 1: 创建任务包
        pkg = orch.create_package(goal, background, quality, files)
        steps.append({"step": "create", "status": "ok", "package_id": pkg["id"]})
        
        # Step 2: LLM 分解
        prompt = _build_decompose_prompt(pkg)
        raw = a.generate(prompt, max_tokens=2048)
        subtasks = _parse_decompose_json(raw)
        if not subtasks:
            return JSONResponse({
                "success": False,
                "error": "LLM分解失败",
                "raw": raw[:500],
                "steps": steps
            })
        for st in subtasks:
            orch.add_subtask(pkg["id"], st)
        steps.append({"step": "decompose", "status": "ok", "subtask_count": len(subtasks)})
        
        # Step 3: 智能体分析
        analysis = orch.analyze_agents_for_task(pkg["id"])
        suggestions = analysis.get("suggestions", [])
        steps.append({"step": "analyze", "status": "ok", "agents_found": len(analysis.get("agents", {})), "suggestions": len(suggestions)})
        
        # Step 4: 自动分配
        if suggestions:
            result = orch.assign_all_auto(pkg["id"], suggestions)
            steps.append({"step": "assign", "status": "ok", "assigned": len(result.get("assigned", []))})
        else:
            steps.append({"step": "assign", "status": "skipped", "reason": "无分配建议"})
        
        # Step 5: 启动循环引擎
        if auto_start:
            eng_result = eng.start_cycle(pkg["id"])
            steps.append({"step": "engine_start", "status": "ok" if eng_result.get("success") else "error", "detail": eng_result.get("error", "")})
        else:
            steps.append({"step": "engine_start", "status": "skipped"})
        
        final_pkg = orch.get_package(pkg["id"])
        return JSONResponse({
            "success": True,
            "package": final_pkg,
            "steps": steps
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

# ===== 循环引擎端点 =====

_engine_instance = None
def _get_engine():
    global _engine_instance
    if _engine_instance is None:
        from extensions.task_loop_engine import TaskLoopEngine
        _engine_instance = TaskLoopEngine()
        # 注入主智能体用于自省
        try:
            a = get_agent()
            if a:
                _engine_instance.set_agent(a)
        except Exception:
            pass
    return _engine_instance

@app.post("/api/engine/start")
async def api_engine_start(request: Request):
    """启动任务循环"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        max_rounds = body.get("max_rounds", 3)
        ratio = body.get("dispatch_ratio", 0.5)
        if not pkg_id:
            return JSONResponse({"success": False, "error": "缺少 package_id"})
        eng = _get_engine()
        result = eng.start_cycle(pkg_id, max_rounds, ratio)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.get("/api/engine/status/{package_id}")
async def api_engine_status(package_id: str):
    """获取循环状态"""
    try:
        eng = _get_engine()
        result = eng.get_status(package_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/engine/pause")
async def api_engine_pause(request: Request):
    """暂停循环"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        eng = _get_engine()
        result = eng.pause_cycle(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.post("/api/engine/resume")
async def api_engine_resume(request: Request):
    """恢复循环"""
    try:
        body = await request.json()
        pkg_id = body.get("package_id", "")
        eng = _get_engine()
        result = eng.resume_cycle(pkg_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]})

@app.get("/api/engine/cycles")
async def api_engine_cycles():
    """列出所有循环"""
    try:
        eng = _get_engine()
        cycles = eng.list_cycles()
        return JSONResponse({"success": True, "cycles": cycles})
    except Exception as e:
        return JSONResponse({"success": True, "cycles": {}, "error": str(e)[:200]})

# ===== 启动器 =====
DEFAULT_PORT = 18765  # 用不太常见的端口避免冲突
PID_FILE = os.path.join(BASE_DIR, "data", "server.pid")
TREND_FILE = os.path.join(BASE_DIR, "data", "trend_history.json")

def _read_pid_file():
    """读取 PID 文件，返回 (pid, port) 或 (None, None)"""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                data = json.load(f)
            return data.get("pid"), data.get("port")
    except Exception:
        pass
    return None, None

def _is_pid_alive(pid):
    """检查进程是否还在运行"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False

def _write_pid_file(port):
    """写入 PID 文件"""
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, 'w') as f:
            json.dump({"pid": os.getpid(), "port": port, "started": time.time()}, f)
    except Exception:
        pass

def _remove_pid_file():
    """删除 PID 文件"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

def _load_trend_history():
    """从磁盘加载趋势历史"""
    try:
        if os.path.exists(TREND_FILE):
            with open(TREND_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                # 只保留最近 24h（1440 条）
                cutoff = time.time() - 86400
                return [r for r in data if isinstance(r, dict) and r.get("time", 0) > cutoff]
    except Exception:
        pass
    return []

def _save_trend_history(history):
    """趋势历史写入磁盘"""
    try:
        os.makedirs(os.path.dirname(TREND_FILE), exist_ok=True)
        with open(TREND_FILE, 'w', encoding='utf-8') as f:
            json.dump(history[-1440:], f, ensure_ascii=False)
    except Exception:
        pass

def find_free_port():
    """找个可用端口"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_browser(port=None, allow_multi=False):
    """浏览器模式启动
    
    allow_multi=False: 默认单实例，已有时直接打开已有窗口
    allow_multi=True: 允许启动多个实例（高阶用户 --multi 模式）
    """
    import webbrowser
    
    # === 单实例检测 ===
    if not allow_multi:
        existing_pid, existing_port = _read_pid_file()
        if existing_pid and _is_pid_alive(existing_pid) and existing_port:
            print(f"[启动] 检测到已有实例 (PID={existing_pid}, 端口={existing_port})")
            print(f"[启动] 直接打开浏览器: http://127.0.0.1:{existing_port}")
            try:
                webbrowser.open(f"http://127.0.0.1:{existing_port}")
            except Exception:
                pass
            return  # 不启动新实例
    
    if port is None:
        port = find_free_port()
    
    print(f"==> TrueAgent 启动中...")
    print(f"   地址: http://127.0.0.1:{port}")
    print(f"   按 Ctrl+C 停止服务")
    print()
    
    def _run():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(1.5)
    
    # 写入 PID 文件
    if not allow_multi:
        _write_pid_file(port)
    
    # 自动打开浏览器
    try:
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        _remove_pid_file()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TrueAgent WebUI")
    parser.add_argument("--port", type=int, default=0,
                        help="端口号（默认自动选择）")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    parser.add_argument("--server-only", action="store_true",
                        help="仅启动服务器，不打开浏览器")
    parser.add_argument("--agent-id", type=str, default="agent_main",
                        help="智能体标识（多实例协作）")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="数据目录（分身专用）")
    parser.add_argument("--multi", action="store_true",
                        help="允许多实例运行（高阶用户，默认关闭）")
    args = parser.parse_args()
    
    # 如果指定了分身数据目录，切换工作目录（BASE_DIR保持为v5.9/不变）
    if args.data_dir:
        abs_data = os.path.abspath(args.data_dir)
        os.makedirs(abs_data, exist_ok=True)
        # 创建分身所需的数据子目录
        for sub in ["memories", "knowledge", "conversations", "outputs", "logs", "backups"]:
            os.makedirs(os.path.join(abs_data, "data", sub), exist_ok=True)
        # 复制锚点库（共享知识，只读源）
        anchor_src = os.path.join(BASE_DIR, "data", "knowledge", "anchor-library.json")
        if os.path.exists(anchor_src):
            from shutil import copy2
            dst = os.path.join(abs_data, "data", "knowledge")
            os.makedirs(dst, exist_ok=True)
            dst_file = os.path.join(dst, "anchor-library.json")
            if not os.path.exists(dst_file):
                copy2(anchor_src, dst_file)
        # 切换工作目录到分身数据目录（让 TrueAgent 的 data/... 路径指向这里）
        os.chdir(abs_data)
        # 同时更新 CONV_DIR 和 OUTPUT_DIR 指向分身数据目录
        CONV_DIR = os.path.join(abs_data, "data", "conversations")
        os.makedirs(CONV_DIR, exist_ok=True)
        OUTPUT_DIR = os.path.join(abs_data, "data", "outputs")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    port = args.port if args.port else DEFAULT_PORT
    
    # 设置全局agent_id和port，供get_agent()使用
    # 用环境变量传递，避免 importlib 加载 TrueAgent 模块时的作用域问题
    os.environ['TRUEAGENT_ID'] = args.agent_id
    os.environ['TRUEAGENT_PORT'] = str(port)
    _agent_id_override = args.agent_id
    _agent_port_override = port
    
    # 标记多实例模式
    if args.multi:
        _multi_mode = True
    
    if args.server_only:
        pass  # 仅启动服务器，不额外初始化智能体

    # === 统一单实例检测（所有启动模式，--multi 除外） ===
    if not args.multi:
        existing_pid, existing_port = _read_pid_file()
        if existing_pid and _is_pid_alive(existing_pid) and existing_port:
            if args.no_browser or args.server_only:
                # 无头/纯服务模式：自动终止旧进程，接管端口
                print(f"[启动] 检测到旧实例 PID={existing_pid} 端口={existing_port}，自动终止...")
                try:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    h = kernel32.OpenProcess(0x0001, False, existing_pid)
                    if h:
                        kernel32.TerminateProcess(h, 0)
                        kernel32.CloseHandle(h)
                    _remove_pid_file()
                    time.sleep(1.5)
                except Exception:
                    pass
                # 使用旧端口保持一致性
                if not args.port:
                    port = existing_port
            else:
                # 浏览器模式：直接打开已有窗口，不启动新实例
                import webbrowser
                print(f"[启动] 检测到已有实例 (PID={existing_pid}, 端口={existing_port})")
                print(f"[启动] 直接打开浏览器: http://127.0.0.1:{existing_port}")
                try:
                    webbrowser.open(f"http://127.0.0.1:{existing_port}")
                except Exception:
                    pass
                sys.exit(0)  # 不启动新实例
    
    # 预初始化智能体（确保黑板注册在API请求之前）
    if args.agent_id and args.agent_id != "none":
        try:
            _a = get_agent()
        except Exception as e:
            print(f"[启动] 智能体预初始化: {e}", flush=True)
    
    if args.no_browser:
        print(f"服务运行于 http://127.0.0.1:{port}")
        if not args.multi:
            _write_pid_file(port)
        try:
            uvicorn.run(app, host="127.0.0.1", port=port)
        finally:
            if not args.multi:
                _remove_pid_file()
    else:
        # 默认浏览器模式
        if args.port:
            run_browser(args.port, allow_multi=args.multi)
        else:
            run_browser(allow_multi=args.multi)
