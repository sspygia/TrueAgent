# -*- coding: utf-8 -*-
"""
分身运行器 — 主智能体的临时执行分身

由 CloneManager 通过 subprocess 启动。
分身直接跑在主智能体的工作目录下，共享知识图谱/锚点/记忆（只读为主）。
任务通过 --task 参数传入，结果写入 data/clones/{clone_id}/result.json 后退出。

CloneManager 监控进程存活 → 进程退出 → 读取 result.json 回收结果。

分身 = 主智能体全部工具能力 - 后台维护线程
"""
import sys, os, json, time, signal, importlib.util, traceback, datetime

_terminated = False
def _on_term(sig, frame):
    global _terminated
    _terminated = True
signal.signal(signal.SIGTERM, _on_term)
signal.signal(signal.SIGINT, _on_term)


def run_as_clone():
    clone_id = parent_id = task_desc = None
    api_base = api_key = api_model = ""
    clone_depth = 1
    subclone_hint = "neutral"  # recommended / neutral / discouraged
    run_mode = "task"           # v5.9: task | discuss
    discuss_timeout = 300       # v5.9: 讨论模式超时（秒）默认 5 分钟

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--clone-id' and i+1 < len(sys.argv):
            clone_id = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--parent-id' and i+1 < len(sys.argv):
            parent_id = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--task' and i+1 < len(sys.argv):
            task_desc = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--depth' and i+1 < len(sys.argv):
            clone_depth = int(sys.argv[i+1]); i += 2
        elif sys.argv[i] == '--subclone-hint' and i+1 < len(sys.argv):
            subclone_hint = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--mode' and i+1 < len(sys.argv):
            run_mode = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--discuss-timeout' and i+1 < len(sys.argv):
            discuss_timeout = int(sys.argv[i+1]); i += 2
        elif sys.argv[i] == '--api-base' and i+1 < len(sys.argv):
            api_base = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--api-key' and i+1 < len(sys.argv):
            api_key = sys.argv[i+1]; i += 2
        elif sys.argv[i] == '--api-model' and i+1 < len(sys.argv):
            api_model = sys.argv[i+1]; i += 2
        else:
            i += 1

    if not clone_id or not parent_id or not task_desc:
        print("[clone] 缺参数", file=sys.stderr)
        sys.exit(1)

    _EXT_DIR  = os.path.dirname(os.path.abspath(__file__))
    _BASE_DIR = os.path.dirname(_EXT_DIR)

    # === 统一结果中枢: data/clones/_hub/ ===
    # 主智能体可随时扫描此目录，查看进度、注入新任务
    _HUB_DIR = os.path.join(_BASE_DIR, "data", "clones", "_hub")
    os.makedirs(_HUB_DIR, exist_ok=True)

    # 分身自己的结果目录（向后兼容）
    data_dir = os.path.join(_BASE_DIR, "data", "clones", clone_id)
    os.makedirs(data_dir, exist_ok=True)

    # 分身工作目录（所有文件输出写这里，自动建好）
    work_dir = os.path.join(data_dir, "work")
    os.makedirs(work_dir, exist_ok=True)

    # === 中枢心跳：每30秒写一次partial，让主智能体能实时看到进度 ===
    _partial_info = {
        "clone_id": clone_id, "parent_id": parent_id,
        "depth": clone_depth, "task": task_desc[:200],
        "status": "preparing", "started_at": time.time(),
        "last_update": time.time(), "output_files": [],
    }
    
    def _write_partial():
        """后台线程：每30秒向中枢写入一次进度快照"""
        while not _terminated:
            time.sleep(30)
            if _terminated:
                break
            try:
                _partial_info["last_update"] = time.time()
                # 扫描工作目录中的新产出
                if os.path.isdir(work_dir):
                    files = []
                    for fn in os.listdir(work_dir):
                        fp = os.path.join(work_dir, fn)
                        if os.path.isfile(fp):
                            files.append({"name": fn, "size": os.path.getsize(fp)})
                    _partial_info["output_files"] = files
                # 写入中枢
                pp = os.path.join(_HUB_DIR, f"{clone_id}.partial.json")
                with open(pp, "w", encoding="utf-8") as f:
                    json.dump(_partial_info, f, ensure_ascii=False)
            except Exception:
                pass
    
    def _check_new_order():
        """检查主智能体是否注入了新指令"""
        order_path = os.path.join(_HUB_DIR, f"{clone_id}.task.json")
        if os.path.exists(order_path):
            try:
                with open(order_path, "r", encoding="utf-8") as f:
                    order = json.load(f)
                os.remove(order_path)  # 一次性指令，取完删除
                return order
            except Exception:
                pass
        return None
    
    import threading
    _heartbeat_thread = threading.Thread(target=_write_partial, daemon=True)
    _heartbeat_thread.start()

    # 跑在主智能体目录下，共享知识图谱/锚点/记忆
    os.chdir(_BASE_DIR)
    sys.path.insert(0, _EXT_DIR)
    sys.path.insert(0, _BASE_DIR)

    # 加载 TrueAgent 核心
    core_path = os.path.join(_BASE_DIR, "TrueAgent_Hyper_v4.0.py")
    spec = importlib.util.spec_from_file_location("trueagent_core", core_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TrueAgent, CONFIG = mod.TrueAgent, mod.CONFIG

    if api_key:
        CONFIG["llm"]["direct_api_base_url"] = api_base.rstrip("/").rstrip("/v1")
        CONFIG["llm"]["direct_api_key"]      = api_key
        CONFIG["llm"]["direct_api_model"]    = api_model or "deepseek-v4-flash"

    # 创建分身实例（仅 __init__，共享主智能体的知识图谱/记忆/锚点）
    agent = TrueAgent(CONFIG)

    # 分身模式覆盖：用分配的专属 Key，不加载共享 api_config.json
    if api_key:
        agent.llm.api_keys = [api_key]
        agent.llm.direct_api_key = api_key
        agent.llm._current_key_idx = 0
        if api_model:
            agent.llm.direct_api_model = api_model

    agent._clone_mode = True
    agent._agent_id   = clone_id
    agent._clone_depth = clone_depth
    agent._subclone_hint = subclone_hint

    # v5.9: 文件日志（stdout 被 PIPE 捕获，主进程不读 → 用文件绕过）
    _log_path = os.path.join(_HUB_DIR, f"{clone_id}.log")
    def _clog(msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts} clone:{clone_id}] {msg}\n"
        try:
            with open(_log_path, "a", encoding="utf-8") as lf:
                lf.write(line)
        except: pass
        print(line.rstrip(), flush=True)
    _clog(f"启动 depth={clone_depth} cm={'YES' if hasattr(agent,'clone_manager') and agent.clone_manager else 'NO'}")
    agent._clone_log = _clog  # 注入给 TrueAgent 使用

    # === v5.9 分身消息系统：收件箱 ===
    _inbox_path = os.path.join(_HUB_DIR, f"{clone_id}.inbox.jsonl")
    # 确保收件箱文件存在
    if not os.path.exists(_inbox_path):
        open(_inbox_path, 'w', encoding='utf-8').close()
    
    _inbox_cursor = 0  # 已读行数
    
    def _read_new_messages():
        """读取收件箱中的新消息（自上次检查后）"""
        nonlocal _inbox_cursor
        new_msgs = []
        try:
            with open(_inbox_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            while _inbox_cursor < len(lines):
                line = lines[_inbox_cursor].strip()
                _inbox_cursor += 1
                if line:
                    try:
                        new_msgs.append(json.loads(line))
                    except:
                        pass
        except:
            pass
        return new_msgs
    
    def _inject_inbox_context(constrained_task: str) -> str:
        """在执行任务前，将收件箱新消息注入任务上下文"""
        msgs = _read_new_messages()
        if not msgs:
            return constrained_task
        # 只取最近 10 条，避免上下文爆炸
        recent = msgs[-10:]
        lines = ["\n\n[分身收件箱 — 以下是最新收到的消息，请考虑后决定如何回应]"]
        for m in recent:
            _from = m.get('from', '?')
            _bc = ' [广播]' if m.get('broadcast') else ''
            _text = m.get('msg', '')[:200]
            lines.append(f"  ← {_from}{_bc}: {_text}")
        inbox_block = '\n'.join(lines)
        return constrained_task + inbox_block
    
    agent._inbox = {
        "path": _inbox_path,
        "read_new": _read_new_messages,
        "inject": _inject_inbox_context,
    }
    agent._agent_id = clone_id  # 确保 agent_id 已设置

    # 级联分身机制：资源配额 × 任务建议 双重门禁
    # - 资源看门狗：psutil 实时检测 CPU+内存占用
    # - 任务建议：上级智能体分析任务性质，传递 recommended/neutral/discouraged
    #   推荐时放宽阈值+5%，劝阻时收紧-10%
    # - 弱机天然卡在第一层，强机/云平台可级联至5层
    if clone_depth >= 5:
        for forbidden in ("dispatch_clone", "get_clone_status", "collect_clone_results"):
            agent.tools.tools.pop(forbidden, None)
        print(f"[clone:{clone_id}] 深度={clone_depth}/5 已达上限，禁派生", flush=True)
    else:
        import psutil as _psutil
        from extensions.clone_manager import check_clone_quota as _chk, analyze_task_for_subclone as _analyze
        
        _orig_dispatch = agent.clone_manager.dispatch
        
        def _quota_dispatch(task_description: str, context: str = "", depth: int = None, subclone_hint: str = None):
            """资源配额 + 上级建议 + 本级分析 三重门禁"""
            use_depth = depth if depth is not None else clone_depth + 1
            
            # 1. 上级传来的建议（优先用传入值，否则用克隆初始化时的提示）
            parent_hint = subclone_hint if subclone_hint else getattr(agent, '_subclone_hint', 'neutral')
            
            # 2. 本级资源检查（融合上级建议调整阈值）
            ok, reason, sub_cap = _chk(clone_depth, parent_hint)
            if not ok:
                return None
            
            # 3. 本级任务分析：此任务是否适合再拆分？
            #   如果 hint 来自上级编排器 ("cascade")，说明 LLM 已分析过可拆分，
            #   本级关键词分析仅作参考，不否决
            local_hint, local_reason = _analyze(task_description)
            if subclone_hint == "cascade":
                # 编排器级联：跳过本级关键词否决（父 LLM 已确认可拆分）
                print(f"[clone:{clone_id}] 编排器级联 → 跳过本级分析 (本级判定:{local_hint})", flush=True)
            elif local_hint == "discouraged" and parent_hint != "recommended":
                # 上级没强烈建议时，本级劝阻即阻止
                print(f"[clone:{clone_id}] 本级分析拒绝派生: {local_reason}", flush=True)
                return None
            
            # 4. 通过，传递累计建议给子分身
            # 建议优先级: discouraged > recommended > neutral
            if local_hint == "recommended" or parent_hint == "recommended":
                combined_hint = "recommended"
            elif local_hint == "discouraged" and parent_hint == "discouraged":
                combined_hint = "discouraged"
            else:
                combined_hint = "neutral"
            
            return _orig_dispatch(task_description, context, depth=use_depth, subclone_hint=combined_hint)
        
        agent.clone_manager.dispatch = _quota_dispatch
        print(f"[clone:{clone_id}] 深度={clone_depth}/5 提示={subclone_hint}, 级联配额已注入", flush=True)

    # 分身启动：注入精确的工具约束 + 工作目录
    tool_list = list(agent.tools.tools.keys()) if hasattr(agent.tools, 'tools') else []
    constrained_task = (
        f"{task_desc}\n\n"
        f"[分身工作目录] {work_dir} （已自动建好，所有文件输出请写入此目录）\n"
        f"[分身工具清单（只能用这些名字）]\n"
        f"可用工具: {', '.join(tool_list)}\n"
        f"重要：write_file 的参数是 (filepath, content)，run_command 的参数是 (command)。\n"
        f"写文件前如果目录不存在，用 run_command 执行 mkdir 创建目录。\n"
        f"不能使用 execute_command/exec/shell/cmd/bash 等名字调用命令，只能用 run_command。"
    )

    # 执行任务（带重试）—— 讨论模式走独立循环
    print(f"[clone:{clone_id}] {task_desc[:100]}", flush=True)
    _partial_info["status"] = "working"
    result = None

    if run_mode == "discuss":
        result = _run_discussion_loop(agent, clone_id, task_desc, discuss_timeout, 
                                       _inject_inbox_context, _read_new_messages, _clog)
    else:
        result = _run_task_mode(agent, clone_id, task_desc, constrained_task,
                                 _check_new_order, _inject_inbox_context, _clog)

    # 收集工作目录中的产出文件
    output_files = []
    if os.path.isdir(work_dir):
        for fn in os.listdir(work_dir):
            fp = os.path.join(work_dir, fn)
            if os.path.isfile(fp):
                try:
                    sz = os.path.getsize(fp)
                    output_files.append({"name": fn, "size": sz, "path": fp})
                except Exception:
                    pass

    _partial_info["status"] = "completed"
    _partial_info["output_files"] = output_files
    _partial_info["completed_at"] = time.time()

    result_data = {
        "clone_id": clone_id, "parent_id": parent_id,
        "depth": clone_depth,
        "task": task_desc,
        "result": str(result) if result else "(空)",
        "output_files": output_files,
        "completed_at": time.time(),
    }

    # 写入原位置（向后兼容）
    rp = os.path.join(data_dir, "result.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    # 写入中枢 → 主智能体可即时扫描到
    done_path = os.path.join(_HUB_DIR, f"{clone_id}.done.json")
    with open(done_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    # 删除旧的 partial（如果有）
    partial_path = os.path.join(_HUB_DIR, f"{clone_id}.partial.json")
    try:
        os.remove(partial_path)
    except Exception:
        pass

    print(f"[clone:{clone_id}] 完成，产出 {len(output_files)} 个文件，已写入中枢", flush=True)


def _run_task_mode(agent, clone_id, task_desc, constrained_task, _check_new_order, _inject_inbox_context, _clog):
    """标准任务模式：执行一次 → 重试 → 退出（带完整错误捕获）"""
    import traceback as _tb
    result = None
    for attempt in range(2):
        new_order = _check_new_order()
        if new_order:
            extra = new_order.get("extra_task", "")
            supplement = new_order.get("supplement", "")
            if extra:
                constrained_task = f"{constrained_task}\n\n[主智能体补充指令] {extra}"
                _clog(f"收到补充指令: {extra[:80]}")
            if supplement:
                constrained_task = f"{constrained_task}\n\n[主智能体补充知识] {supplement}"
        
        constrained_task_with_inbox = _inject_inbox_context(constrained_task)
        
        try:
            result = agent.process_user_command(constrained_task_with_inbox)
            if result and '(空)' not in str(result):
                break
            else:
                _clog(f"第{attempt+1}次返回空结果")
        except Exception as e:
            tb_str = _tb.format_exc()
            result = f"[异常] {type(e).__name__}: {str(e)[:500]}"
            _clog(f"第{attempt+1}次异常:\n{tb_str[:800]}")
        if attempt == 0:
            # 重试时保留原任务描述，不简化为"最简单方式"（学习任务需要完整上下文）
            constrained_task = (
                f"[重试 mode=task]\n{task_desc}\n\n"
                f"⚠ 上一次执行返回了空结果或异常。请重新读取相关文件/目录，"
                f"用更直接的方式完成任务。如果任务涉及文件操作，先确认文件存在性和权限。"
            )
            _clog("重试...")
    return result


def _run_discussion_loop(agent, clone_id, topic, timeout, _inject_inbox_context, _read_new_messages, _clog):
    """讨论模式：持续收件→回应→收件，直到 STOP 或超时
    
    流程：
    1. 第一轮：读收件箱中主智能体已发布的话题 → 回应
    2. 循环：读新消息 → 有消息就回应 → 没消息等 3 秒
    3. 收到 [STOP] → 总结退出
    4. 超时 → 自动总结退出
    5. 连续 120 秒无新消息 → 讨论枯竭退出
    """
    import time as _time
    start = _time.time()
    last_activity = start
    
    # 第一轮：读话题并发表初始观点
    _clog("讨论模式启动，读话题...")
    init_prompt = (
        f"[群策讨论 — 你是 {clone_id}，角色设定如下]\n"
        f"{topic}\n\n"
        f"请先用 check_inbox() 查看主智能体发布的讨论话题。"
        f"然后用 send_message(to='all', msg=你的观点) 发表你的初始看法。"
        f"发表后不要主动退出，等待其他人的回应。"
    )
    result = agent.process_user_command(init_prompt)
    last_activity = _time.time()
    
    # 主循环
    round_num = 1
    while _time.time() - start < timeout:
        # 检查全局终止信号
        global _terminated
        if _terminated:
            _clog("收到 SIGTERM，准备退出")
            break
        
        # 读收件箱新消息
        msgs = _read_new_messages()
        
        if msgs:
            # 过滤掉自己发出的消息
            others = [m for m in msgs if m.get('from') != clone_id]
            if not others:
                _time.sleep(3)
                continue
            
            # 检查 STOP 信号
            for m in others:
                msg_text = m.get('msg', '')
                sender = m.get('from', '')
                if sender == 'agent_main' and '[STOP]' in msg_text:
                    _clog("收到 STOP → 总结退出")
                    wrap = agent.process_user_command(
                        f"[讨论结束] 主智能体要求结束讨论。"
                        f"请用 send_message(to='all', msg=你的最终总结) 发布你的最终观点，要简明扼要。"
                    )
                    return wrap
            
            # 有新消息 → 回应
            round_num += 1
            last_activity = _time.time()
            msgs_text = '\n'.join(
                f"  [{m.get('from')}]: {m.get('msg','')[:200]}"
                for m in others[-3:]  # 只给最近 3 条，防止上下文爆炸
            )
            _clog(f"轮{round_num}: 收到 {len(others)} 条消息 → 回应")
            
            prompt = (
                f"[群策讨论 第{round_num}轮]\n"
                f"最新消息：\n{msgs_text}\n\n"
                f"请发表你的看法。用 send_message(to='all', msg=你的回应) 回复。"
                f"如果认同已有观点可以说'同意'并补充理由。"
                f"如果讨论已充分可以说'已达成共识'并简要总结。"
            )
            result = agent.process_user_command(prompt)
        else:
            _time.sleep(3)
            # 120 秒无新消息 → 讨论干涸
            if _time.time() - last_activity > 120:
                _clog("2 分钟无新消息，讨论枯竭退出")
                break
    
    # 超时或枯竭 → 最终总结
    _clog("讨论结束(超时/枯竭) → 最终总结")
    remain = max(int(timeout - (_time.time() - start)), 10)
    final = agent.process_user_command(
        f"[讨论结束] 讨论时间结束。请用 send_message(to='all', msg=你的最终总结) 发表最终观点。"
    )
    return final if final else result


if __name__ == "__main__":
    try:
        run_as_clone()
    except Exception as e:
        print(f"[clone] 致命: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)
