# -*- coding: utf-8 -*-
"""
分身管理器 — 派遣 / 监控 / 回收智能分身子进程

CloneManager 负责：
  1. dispatch() — 启动子进程执行任务
  2. poll()    — 轮询所有活跃分身的完成状态
  3. collect() — 收集已完成分身的结果
  4. cleanup() — 终止所有分身（停止时调用）
  5. get_status() — 返回所有分身状态（供 WebUI 展示）
"""
import json, os, sys, time, threading, subprocess as _sp
from typing import Dict, List, Optional

# 黑板路径
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_EXT_DIR)

# ===== 级联分身的资源配额看门狗 =====
# 每层有「允许再派生的资源上限」和「子分身的资源上限」
# 弱机: 主智能体已占用60-70% → 分身无法再派生
# 强机/云: 主智能体仅用20% → 分身可派生 → 子分身可继续 → 可达数百集群
# 融合上级任务建议（recommended 放宽+5%, discouraged 收紧-10%）
_CASCADE_QUOTA = {
    # depth: (允许再派生的资源阈值%, 子分身资源上限%)
    1: (50, 60),   # 第1层分身: 当前<50%才能派生, 子分身上限60%
    2: (60, 70),   # 第2层: 当前<60%可派生, 子上限70%
    3: (70, 80),   # 第3层: 当前<70%可派生, 子上限80%
    4: (80, 80),   # 第4层+: 当前<80%可派生, 子上限80%
}
_MAX_CLONE_DEPTH = 5  # 最多5层

# 任务可拆分关键词（主智能体/分身分析任务时使用）
_SPLITTABLE_KEYWORDS = [
    "并行", "多个", "分别", "各自", "同时", "每", "各",
    "批量", "列表", "遍历", "收集", "爬取", "搜索",
    "对比", "比较", "分析多个", "整理多个",
    "parallel", "batch", "multiple", "each", "all",
]
_UNSPLITTABLE_KEYWORDS = [
    "总结", "概括", "归纳", "综合", "汇总", "合并",
    "一篇", "一个完整", "连贯", "整体", "统一",
    "summarize", "merge", "single", "one",
]


def check_clone_quota(current_depth: int, hint: str = "neutral") -> tuple:
    """检查当前深度是否允许再派生子分身。
    hint: recommended(放宽+5%) / neutral / discouraged(收紧-10%)
    返回 (allowed: bool, reason: str, sub_cap: int)
    """
    if current_depth >= _MAX_CLONE_DEPTH:
        return False, f"已达最大深度{_MAX_CLONE_DEPTH}", 0
    
    threshold, sub_cap = _CASCADE_QUOTA.get(current_depth, (80, 80))
    
    # 上级建议调整阈值
    if hint == "recommended":
        threshold += 5  # 放宽5%，更容易通过
    elif hint == "discouraged":
        threshold -= 10  # 收紧10%，更难通过
    
    # 检查系统资源
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory().percent
        usage = max(cpu, mem)  # 取CPU和内存中较高的
    except Exception:
        usage = 50  # 无法检测时保守估计
    
    if usage >= threshold:
        return False, f"资源占用{usage:.0f}% >= 阈值{threshold}%（{hint}），无法派生", sub_cap
    
    return True, f"资源占用{usage:.0f}% < 阈值{threshold}%（{hint}），可派生(上限{sub_cap}%)", sub_cap


def analyze_task_for_subclone(task_desc: str) -> tuple:
    """分析任务是否适合再拆分成子分身。
    返回 (hint: str, reason: str)
    """
    t = task_desc.lower()
    
    splittable_score = 0
    for kw in _SPLITTABLE_KEYWORDS:
        if kw.lower() in t:
            splittable_score += 1
    
    unsplittable_score = 0
    for kw in _UNSPLITTABLE_KEYWORDS:
        if kw.lower() in t:
            unsplittable_score += 1
    
    if splittable_score >= 2 and unsplittable_score == 0:
        return "recommended", f"任务含{splittable_score}个可拆分信号"
    elif unsplittable_score >= 2:
        return "discouraged", f"任务含{unsplittable_score}个不可拆分信号"
    elif splittable_score > unsplittable_score:
        return "recommended", "可拆分信号多于不可拆分"
    elif unsplittable_score > splittable_score:
        return "discouraged", "不可拆分为主"
    else:
        return "neutral", "无明确拆分信号"


class CloneManager:
    """分身管理器"""

    MAX_CLONES = 5              # 默认最大并发（运行时被 Key 池大小覆盖）
    CLONE_TIMEOUT = 1800        # [已废弃] 保留兼容，不再用作存活判定
    MAX_CLONE_RUNTIME = 7200    # 绝对最大运行时间 2 小时（防僵尸进程的最终安全网）
    STALE_TIMEOUT = 300         # 心跳超时 5 分钟：无心跳视为卡死
    POLL_INTERVAL = 5           # 轮询间隔 5 秒

    def __init__(self, parent_agent):
        self.agent = parent_agent
        self.parent_id = getattr(parent_agent, '_agent_id', 'agent_main')
        self.parent_port = getattr(parent_agent, '_port', 18765)
        self.parent_dir = os.path.join(_BASE_DIR, "data", "clones", self.parent_id)
        os.makedirs(self.parent_dir, exist_ok=True)

        self.clones: Dict[str, dict] = {}   # clone_id → info dict
        self._lock = threading.RLock()
        self._polling = False
        self._poll_thread = None
        self._api_config = None   # {base, key, model}

        # === 多 Key 池：每分身分配独立 Key，并行时不抢限流 ===
        self._key_pool = self._load_key_pool()
        # 动态调整最大并发：有 N 把钥匙就能跑 N 个分身，下限 1 上限 20
        self.MAX_CLONES = max(1, min(len(self._key_pool), 20))
        print(f"[CloneManager] 分身上限: {self.MAX_CLONES} 个 | 超时: {self.CLONE_TIMEOUT//60} 分钟 | Key池: {len(self._key_pool)} 把", flush=True)

    def _load_key_pool(self) -> list:
        """从 data/api_config.json 加载所有 Key 放入池"""
        try:
            cfg_path = os.path.join(_BASE_DIR, "data", "api_config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    keys = saved.get("api_keys_full", [])
                    if keys:
                        print(f"[CloneManager] Key池: {len(keys)} 把钥匙", flush=True)
                        return keys
        except Exception:
            pass
        # 回退：从 agent config 取单个 Key
        cfg = self._get_api_config()
        return [cfg.get("key", "")] if cfg.get("key") else []

    def _acquire_key(self, clone_id: str) -> str:
        """为分身分配一把空闲 Key（池中最少使用的）"""
        with self._lock:
            if not self._key_pool:
                return ""
            # 统计各 Key 当前使用数
            used_keys = {}
            for cid, info in self.clones.items():
                if info.get("status") == "running" and info.get("assigned_key"):
                    k = info["assigned_key"]
                    used_keys[k] = used_keys.get(k, 0) + 1
            # 找最少使用的 Key
            best_key = self._key_pool[0]
            best_count = used_keys.get(best_key, 0)
            for k in self._key_pool[1:]:
                cnt = used_keys.get(k, 0)
                if cnt < best_count:
                    best_key = k
                    best_count = cnt
            return best_key

    def _release_key(self, clone_id: str):
        """分身完成后释放 Key（只需清除引用，Key 自然可用）"""
        with self._lock:
            info = self.clones.get(clone_id)
            if info:
                info.pop("assigned_key", None)

    def _get_api_config(self) -> dict:
        """获取 LLM API 配置（从 agent.config 或环境变量）"""
        if self._api_config:
            return self._api_config

        cfg = {}
        try:
            llm_cfg = self.agent.config.get("llm", {})
            cfg["base"] = llm_cfg.get("direct_api_base_url", "https://api.deepseek.com")
            cfg["key"] = llm_cfg.get("direct_api_key", os.environ.get("DEEPSEEK_API_KEY", ""))
            cfg["model"] = llm_cfg.get("direct_api_model", "deepseek-v4-flash")
        except Exception:
            cfg["base"] = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
            cfg["key"] = os.environ.get("DEEPSEEK_API_KEY", "")
            cfg["model"] = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

        self._api_config = cfg
        return cfg

    # ==================== 派遣 ====================

    def dispatch(self, task_description: str, context: str = "", depth: int = 1, subclone_hint: str = "neutral",
                 mode: str = "task", discuss_timeout: int = 300) -> Optional[str]:
        """
        派遣一个新分身执行任务。
        depth: 当前分身的深度（主智能体派出的为1，分身再派的为2...）
        subclone_hint: 上级对子派生任务的建议 (recommended/neutral/discouraged)
        mode: "task" 单任务模式 | "discuss" 群策讨论模式
        discuss_timeout: 讨论模式超时秒数（默认 300=5分钟）
        返回 clone_id 或 None（超限/失败时）。
        """
        # ===== 级联配额检查（深度>1 即分身再派生时检查） =====
        if depth > 1:
            allowed, reason, sub_cap = check_clone_quota(depth - 1, subclone_hint)
            if not allowed:
                print(f"[CloneManager] 级联配额拒绝 depth={depth} hint={subclone_hint}: {reason}", flush=True)
                return None
            print(f"[CloneManager] 级联配额通过 depth={depth} hint={subclone_hint}: {reason}", flush=True)
        
        with self._lock:
            # 清理已死的分身
            self._reap_dead()

            # 检查上限
            active = sum(1 for c in self.clones.values() if c.get("status") in ("running","working","preparing"))
            if active >= self.MAX_CLONES:
                # 尝试回收已完成的分身
                self.collect()
                active = sum(1 for c in self.clones.values() if c.get("status") in ("running","working","preparing"))
                if active >= self.MAX_CLONES:
                    return None   # 分身槽满了

            # 生成 clone_id
            clone_num = 1
            while f"clone_{clone_num}" in self.clones:
                clone_num += 1
            clone_id = f"clone_{clone_num}"

            # 准备参数 — 为每个分身分配独立的 API Key
            api = self._get_api_config()
            assigned_key = self._acquire_key(clone_id)
            if assigned_key:
                api["key"] = assigned_key
            runner_path = os.path.join(_EXT_DIR, "clone_runner.py")
            python_exe = sys.executable

            cmd = [
                python_exe, runner_path,
                "--clone-id", clone_id,
                "--parent-id", self.parent_id,
                "--depth", str(depth),
                "--subclone-hint", subclone_hint,
                "--mode", mode,
                "--discuss-timeout", str(discuss_timeout),
                "--api-base", api["base"],
                "--api-key", api["key"],
                "--api-model", api["model"],
            ]
            if task_description:
                cmd += ["--task", task_description]

            # 启动子进程
            try:
                # stderr 写入文件日志（PIPE 会在缓冲区满时阻塞子进程，且主进程不读取会丢失错误信息）
                stderr_log = os.path.join(_HUB_DIR, f"{clone_id}.stderr.log")
                _stderr_fp = open(stderr_log, 'wb')
                proc = _sp.Popen(
                    cmd,
                    stdout=_sp.PIPE,
                    stderr=_stderr_fp,
                    stdin=_sp.DEVNULL,
                    text=False,    # bytes mode
                    creationflags=_sp.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                info["_stderr_fp"] = _stderr_fp  # 清理时关闭
            except Exception as e:
                print(f"[CloneManager] 启动分身 {clone_id} 失败: {e}", flush=True)
                return None

            # 记录分身信息
            self.clones[clone_id] = {
                "pid": proc.pid,
                "process": proc,
                "task": task_description[:200],
                "context": context[:500],
                "status": "running",
                "depth": depth,
                "created_at": time.time(),
                "result": None,
                "result_path": "",
                "assigned_key": assigned_key,  # 记录分配了哪把钥匙
            }

            print(f"[CloneManager] 已派遣 {clone_id} (PID={proc.pid}): {task_description[:60]}...", flush=True)

            # 启动轮询（如果还没启动）
            if not self._polling:
                self._start_polling()

            return clone_id

    # ==================== 轮询 ====================

    def _start_polling(self):
        """启动后台轮询线程"""
        self._polling = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        """后台轮询循环 — 自动收集结果并注入 agent"""
        while self._polling:
            time.sleep(self.POLL_INTERVAL)
            try:
                self._poll_all()
                self._reap_dead()
                results = self.collect()
                # v5.9: 自动将分身结果注入主智能体（含 LLM 分析摘要）
                if results and hasattr(self.agent, '_proactive_queue'):
                    for r in results:
                        raw_result = str(r.get('result', ''))
                        task_desc = str(r.get('task', '未命名任务'))[:80]
                        
                        # 尝试 LLM 分析摘要
                        summary = self._analyze_clone_result(task_desc, raw_result)
                        
                        content = f"[分身 {r['clone_id']} 完成] {task_desc}\n{summary}"
                        self.agent._proactive_queue.append({
                            "time": time.time(),
                            "content": content,
                            "type": "clone_result",
                            "clone_result": r,
                        })
            except Exception:
                pass

    def _analyze_clone_result(self, task_desc: str, raw_result: str) -> str:
        """LLM分析分身结果，生成结构化摘要。失败时回退到原始结果截断。"""
        raw_result = str(raw_result)
        if not raw_result or len(raw_result) < 10:
            return "（无输出）" if not raw_result else raw_result[:200]
        
        # 快速统计（零API成本）
        lines = raw_result.split('\n')
        pass_count = sum(1 for l in lines if 'PASS' in l.upper() or 'OK' in l.upper() or '通过' in l)
        fail_count = sum(1 for l in lines if 'FAIL' in l.upper() or 'ERROR' in l.upper() or '失败' in l or '错误' in l)
        quick_stats = f"共{len(lines)}行 | PASS≈{pass_count} FAIL≈{fail_count}"
        
        # 尝试 LLM 分析
        try:
            llm = getattr(self.agent, 'llm', None)
            if llm and hasattr(llm, 'generate'):
                prompt = f"""分析以下后台任务的执行结果，输出简洁摘要（150字以内）。

任务: {task_desc}
结果行数: {len(lines)}  | PASS标记≈{pass_count} FAIL标记≈{fail_count}

结果内容（前2000字）:
{raw_result[:2000]}

请输出:
1. 状态: [成功/部分成功/失败]
2. 关键发现: 1-2条
3. 问题: (有则列出，无则写"无")
4. 建议: (有则给1条行动建议)

格式: 状态: xxx | 发现: xxx | 问题: xxx | 建议: xxx"""
                
                analysis = llm.generate(prompt, max_tokens=256)
                if analysis and len(analysis) > 10:
                    return f"📊 {quick_stats}\n{analysis.strip()[:300]}"
        except Exception:
            pass
        
        # 回退：直接截取结果
        return f"📊 {quick_stats}\n{raw_result[:300]}..."

    def _poll_all(self):
        """检查所有活跃分身的进程状态（心跳驱动 + 绝对上限双重安全）"""
        with self._lock:
            now = time.time()
            _HUB_DIR = os.path.join(_BASE_DIR, "data", "clones", "_hub")
            for clone_id, info in list(self.clones.items()):
                if info["status"] in ("completed", "error", "timeout"):
                    continue
                proc = info.get("process")
                if not proc:
                    info["status"] = "error"
                    continue
                # 检查进程是否还活着
                poll = proc.poll()
                if poll is not None:
                    # 进程已退出
                    if poll == 0:
                        info["status"] = "completed"
                    else:
                        info["status"] = "error"
                        info["result"] = f"进程退出码: {poll}"
                    continue
                
                # === 心跳驱动的存活判定（替代固定超时）===
                # 读取 clone_runner 每30秒写入的心跳文件
                last_heartbeat = info.get("created_at", now)
                hb_path = os.path.join(_HUB_DIR, f"{clone_id}.partial.json")
                if os.path.exists(hb_path):
                    try:
                        import json as _json
                        with open(hb_path, 'r', encoding='utf-8') as _hf:
                            hb = _json.load(_hf)
                        last_heartbeat = hb.get("last_update", hb.get("started_at", last_heartbeat))
                        # 更新 info 供下次使用
                        info["last_heartbeat"] = last_heartbeat
                    except Exception:
                        pass
                
                elapsed = now - info["created_at"]
                stale = now - last_heartbeat
                
                # 双重判定：心跳超时 OR 超过绝对上限
                if stale > self.STALE_TIMEOUT:
                    reason = f"心跳超时 {stale:.0f}s (>{self.STALE_TIMEOUT}s)"
                    print(f"[CloneManager] {clone_id} {reason}，强制终止", flush=True)
                    self._kill_proc(proc)
                    info["status"] = "timeout"
                    info["result"] = f"任务卡死: {reason}"
                elif elapsed > self.MAX_CLONE_RUNTIME:
                    reason = f"超过最大运行时间 {elapsed:.0f}s (>{self.MAX_CLONE_RUNTIME}s)"
                    print(f"[CloneManager] {clone_id} {reason}，强制终止", flush=True)
                    self._kill_proc(proc)
                    info["status"] = "timeout"
                    info["result"] = f"任务超时: {reason}"

    def _kill_proc(self, proc):
        """安全终止子进程"""
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _reap_dead(self):
        """清理已死进程引用"""
        with self._lock:
            dead = []
            for clone_id, info in list(self.clones.items()):
                if info["status"] in ("completed", "error", "timeout"):
                    proc = info.get("process")
                    if proc and proc.poll() is not None:
                        try:
                            proc.wait(timeout=1)
                        except Exception:
                            pass
                        info["process"] = None
                    if info.get("process") is None and info.get("result") is not None:
                        dead.append(clone_id)
            # 不移除记录，保留供 collect() 返回

    # ==================== 收集结果 ====================

    def collect(self) -> List[dict]:
        """收集所有已完成/超时/出错的分身结果"""
        results = []
        with self._lock:
            for clone_id, info in list(self.clones.items()):
                if info["status"] in ("completed", "error", "timeout") and not info.get("_collected"):
                    # 尝试读取分身写入的结果文件
                    result_data = None
                    clone_data_dir = os.path.join(_BASE_DIR, "data", "clones", clone_id)
                    result_path = os.path.join(clone_data_dir, "result.json")
                    if os.path.exists(result_path):
                        try:
                            with open(result_path, 'r', encoding='utf-8') as f:
                                result_data = json.load(f)
                        except Exception:
                            pass

                    # 移到父体目录
                    if result_data:
                        parent_result = os.path.join(self.parent_dir, f"{clone_id}_result.json")
                        try:
                            import shutil
                            shutil.copy2(result_path, parent_result)
                            info["result_path"] = parent_result
                        except Exception:
                            pass

                    info["result"] = result_data.get("result", info.get("result", "")) if result_data else info.get("result", "")
                    info["_collected"] = True

                    results.append({
                        "clone_id": clone_id,
                        "status": info["status"],
                        "task": info.get("task", ""),
                        "result": info["result"],
                        "result_path": info.get("result_path", ""),
                        "runtime": time.time() - info["created_at"],
                    })

                    print(f"[CloneManager] 回收 {clone_id}: {info['status']} ({info.get('result','')[:80]})", flush=True)

            # v5.9: 收集完成后删除记录和临时目录，避免无限膨胀
            for clone_id in [r["clone_id"] for r in results]:
                self._release_key(clone_id)  # 归还 Key 到池
                if clone_id in self.clones:
                    del self.clones[clone_id]
                # 清理分身数据目录
                clone_data_dir = os.path.join(_BASE_DIR, "data", "clones", clone_id)
                if os.path.exists(clone_data_dir):
                    try:
                        import shutil
                        shutil.rmtree(clone_data_dir, ignore_errors=True)
                    except Exception:
                        pass

        return results

    # ==================== 获取状态 ====================

    def get_status(self) -> List[dict]:
        """获取所有分身状态（供 WebUI 展示）"""
        status_list = []
        with self._lock:
            for clone_id, info in self.clones.items():
                proc = info.get("process")
                alive = proc is not None and proc.poll() is None
                status_list.append({
                    "clone_id": clone_id,
                    "pid": info.get("pid"),
                    "status": info["status"],
                    "task": info.get("task", "")[:100],
                    "depth": info.get("depth", 1),
                    "alive": alive,
                    "runtime": time.time() - info["created_at"] if "created_at" in info else 0,
                    "has_result": info.get("result") is not None,
                })
        return status_list

    def get_active_count(self) -> int:
        """活跃分身数量"""
        with self._lock:
            return sum(1 for c in self.clones.values() if c.get("status") in ("running","working","preparing"))

    # ==================== 清理 ====================

    def terminate(self, clone_id: str):
        """终止指定分身"""
        with self._lock:
            info = self.clones.get(clone_id)
            if not info:
                return
            proc = info.get("process")
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            # 关闭 stderr 文件句柄
            try:
                sfp = info.get("_stderr_fp")
                if sfp:
                    sfp.close()
            except Exception:
                pass
            info["status"] = "terminated"
            info["process"] = None
            info["result"] = "手动终止"

    def cleanup(self):
        """停止所有分身并清理"""
        self._polling = False
        with self._lock:
            for clone_id, info in list(self.clones.items()):
                self.terminate(clone_id)
            self.clones.clear()

    def get_awareness_prompt(self) -> str:
        """生成分身感知提示词（注入 LLM prompt）"""
        with self._lock:
            active = [c for c in self.clones.values() if c["status"] in ("running","working","preparing")]
            completed = [c for c in self.clones.values() if c["status"] == "completed" and not c.get("_collected")]

        lines = []
        
        # === 中枢扫描：实时进度一览 ===
        hub_snapshot = self.scan_hub()
        if hub_snapshot["partials"]:
            lines.append(f"\n[分身进度] {len(hub_snapshot['partials'])} 个正在工作中：")
            for p in hub_snapshot["partials"]:
                elapsed = time.time() - p.get("started_at", time.time())
                files_n = len(p.get("output_files", []))
                lines.append(f"  - {p['clone_id']} (深度{p.get('depth','?')}) [{elapsed:.0f}s]: {p.get('task','')[:50]} | 产出{files_n}个文件")
        
        if active:
            lines.append(f"\n[分身状态] 当前有 {len(active)} 个活跃分身：")
            for c in active:
                d = c.get('depth', '?')
                lines.append(f"  - {c.get('clone_id','?')} (深度{d}): {c.get('task','')[:60]}")
        if completed:
            lines.append(f"\n[分身结果] {len(completed)} 个分身已完成，结果待收取。")
        if hub_snapshot["done"]:
            lines.append(f"\n[中枢完成] {len(hub_snapshot['done'])} 个结果在 _hub 中待收取。")
        
        if not active and not completed and not hub_snapshot["partials"] and not hub_snapshot["done"]:
            lines.append("\n[分身状态] 当前无活跃分身。需要时可调用 dispatch_clone 派遣分身并行执行任务。")

        return "\n".join(lines) if lines else ""

    # ==================== 中枢扫描与干预 ====================

    _HUB_DIR = os.path.join(_BASE_DIR, "data", "clones", "_hub")

    def scan_hub(self) -> dict:
        """扫描统一结果中枢，返回所有 partial 和 done 文件内容。
        主智能体可随时调用，无需等分身主动报告。
        v5.9: 自动清理 >1h 的过期 hub 文件。
        """
        result = {"partials": [], "done": [], "tasks": []}
        if not os.path.isdir(self._HUB_DIR):
            os.makedirs(self._HUB_DIR, exist_ok=True)
            return result
        now = time.time()
        stale_age = 3600  # 1 小时
        try:
            for fn in os.listdir(self._HUB_DIR):
                fp = os.path.join(self._HUB_DIR, fn)
                if not os.path.isfile(fp):
                    continue
                # 清理过期文件
                try:
                    if now - os.path.getmtime(fp) > stale_age:
                        os.remove(fp)
                        continue
                except OSError:
                    pass
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if fn.endswith(".partial.json"):
                        data["_file"] = fn
                        result["partials"].append(data)
                    elif fn.endswith(".done.json"):
                        data["_file"] = fn
                        result["done"].append(data)
                    elif fn.endswith(".task.json"):
                        result["tasks"].append(fn)
                except Exception:
                    # 损坏文件直接删
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
        except Exception:
            pass
        # 按时间排序
        result["partials"].sort(key=lambda x: x.get("started_at", 0))
        result["done"].sort(key=lambda x: x.get("completed_at", 0), reverse=True)
        return result

    def inject_task(self, clone_id: str, extra_task: str = "", supplement: str = "") -> bool:
        """向运行中的分身注入补充指令或知识。
        分身在下一次LLM调用前会检查并接收。
        """
        order_path = os.path.join(self._HUB_DIR, f"{clone_id}.task.json")
        try:
            os.makedirs(self._HUB_DIR, exist_ok=True)
            with open(order_path, "w", encoding="utf-8") as f:
                json.dump({
                    "clone_id": clone_id,
                    "extra_task": extra_task,
                    "supplement": supplement,
                    "injected_at": time.time(),
                }, f, ensure_ascii=False)
            print(f"[CloneManager] 向 {clone_id} 注入指令: {extra_task[:60]}", flush=True)
            return True
        except Exception as e:
            print(f"[CloneManager] 注入 {clone_id} 失败: {e}", flush=True)
            return False

    def read_partial(self, clone_id: str) -> Optional[dict]:
        """读取指定分身的 partial 进度"""
        pp = os.path.join(self._HUB_DIR, f"{clone_id}.partial.json")
        if os.path.exists(pp):
            try:
                with open(pp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    def _analyze_clone_result(self, task_desc: str, raw_result: str) -> str:
        """LLM分析分身结果，生成结构化摘要。失败时回退到原始结果截断。"""
        raw_result = str(raw_result)
        if not raw_result or len(raw_result) < 10:
            return "（无输出）" if not raw_result else raw_result[:200]
        
        # 快速统计（零API成本）
        lines = raw_result.split('\n')
        pass_count = sum(1 for l in lines if 'PASS' in l.upper() or 'OK' in l.upper() or '通过' in l)
        fail_count = sum(1 for l in lines if 'FAIL' in l.upper() or 'ERROR' in l.upper() or '失败' in l or '错误' in l)
        quick_stats = f"共{len(lines)}行 | PASS≈{pass_count} FAIL≈{fail_count}"
        
        # 尝试 LLM 分析
        try:
            llm = getattr(self.agent, 'llm', None)
            if llm and hasattr(llm, 'generate'):
                prompt = f"""分析以下后台任务的执行结果，输出简洁摘要（150字以内）。

任务: {task_desc}
结果行数: {len(lines)}  | PASS标记≈{pass_count} FAIL标记≈{fail_count}

结果内容（前2000字）:
{raw_result[:2000]}

请输出:
1. 状态: [成功/部分成功/失败]
2. 关键发现: 1-2条
3. 问题: (有则列出，无则写"无")
4. 建议: (有则给1条行动建议)

格式: 状态: xxx | 发现: xxx | 问题: xxx | 建议: xxx"""
                
                analysis = llm.generate(prompt, max_tokens=256)
                if analysis and len(analysis) > 10:
                    return f"📊 {quick_stats}\n{analysis.strip()[:300]}"
        except Exception:
            pass
        
        # 回退：直接截取结果
        return f"📊 {quick_stats}\n{raw_result[:300]}..."
        return None

    def consume_done(self, clone_id: str) -> Optional[dict]:
        """读取并删除中枢中的完成结果（同步清理 partial）"""
        dp = os.path.join(self._HUB_DIR, f"{clone_id}.done.json")
        if os.path.exists(dp):
            try:
                with open(dp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                os.remove(dp)
                # 同步清理 partial 和 task
                for sfx in (".partial.json", ".task.json"):
                    sp = os.path.join(self._HUB_DIR, f"{clone_id}{sfx}")
                    if os.path.exists(sp):
                        try:
                            os.remove(sp)
                        except OSError:
                            pass
                return data
            except Exception:
                pass

    def _analyze_clone_result(self, task_desc: str, raw_result: str) -> str:
        """LLM分析分身结果，生成结构化摘要。失败时回退到原始结果截断。"""
        raw_result = str(raw_result)
        if not raw_result or len(raw_result) < 10:
            return "（无输出）" if not raw_result else raw_result[:200]
        
        # 快速统计（零API成本）
        lines = raw_result.split('\n')
        pass_count = sum(1 for l in lines if 'PASS' in l.upper() or 'OK' in l.upper() or '通过' in l)
        fail_count = sum(1 for l in lines if 'FAIL' in l.upper() or 'ERROR' in l.upper() or '失败' in l or '错误' in l)
        quick_stats = f"共{len(lines)}行 | PASS≈{pass_count} FAIL≈{fail_count}"
        
        # 尝试 LLM 分析
        try:
            llm = getattr(self.agent, 'llm', None)
            if llm and hasattr(llm, 'generate'):
                prompt = f"""分析以下后台任务的执行结果，输出简洁摘要（150字以内）。

任务: {task_desc}
结果行数: {len(lines)}  | PASS标记≈{pass_count} FAIL标记≈{fail_count}

结果内容（前2000字）:
{raw_result[:2000]}

请输出:
1. 状态: [成功/部分成功/失败]
2. 关键发现: 1-2条
3. 问题: (有则列出，无则写"无")
4. 建议: (有则给1条行动建议)

格式: 状态: xxx | 发现: xxx | 问题: xxx | 建议: xxx"""
                
                analysis = llm.generate(prompt, max_tokens=256)
                if analysis and len(analysis) > 10:
                    return f"📊 {quick_stats}\n{analysis.strip()[:300]}"
        except Exception:
            pass
        
        # 回退：直接截取结果
        return f"📊 {quick_stats}\n{raw_result[:300]}..."
        return None
