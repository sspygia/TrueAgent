"""任务分解器完整设计文档"""
import json, os, time, re, threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from collections import deque

# ============================================================
# 1. 数据结构
# ============================================================

@dataclass
class TaskNode:
    id: str                # "root" / "root.0" / "root.0.1"
    description: str
    tool: Optional[str] = None
    args: Optional[dict] = None
    subtasks: List['TaskNode'] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"   # pending | running | success | failed | skipped | re_planning
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries_base: int = 3      # 工具级重试
    max_retries_replan: int = 2    # 规划级重试
    depth: int = 0
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    timeout_seconds: int = 60      # 按任务层级自动调整
    is_leaf: bool = False

    def to_dict(self):
        return {
            "id": self.id, "description": self.description[:100],
            "tool": self.tool, "status": self.status,
            "is_leaf": self.is_leaf, "depth": self.depth,
            "retry_count": self.retry_count,
            "dependencies": self.dependencies,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "error": (self.error or "")[:200],
            "result": (self.result or "")[:200],
        }


@dataclass
class TaskSession:
    session_id: str
    goal: str
    task_tree: Optional[TaskNode] = None
    status: str = "pending"   # pending | running | paused | completed | failed | user_intervention
    progress: float = 0.0
    current_phase: str = ""
    completed_leaves: List[str] = field(default_factory=list)
    failed_leaves: List[str] = field(default_factory=list)
    re_planned_nodes: List[str] = field(default_factory=list)
    checkpoints: List[Dict] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    last_heartbeat: float = 0.0
    total_leaves: int = 0
    api_calls: int = 0
    # 死锁检测
    max_idle_minutes: int = 15
    # 失败反思日志
    reflection_log: List[Dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "goal": self.goal[:80],
            "status": self.status,
            "progress": round(self.progress, 2),
            "phase": self.current_phase,
            "completed": len(self.completed_leaves),
            "total": self.total_leaves,
            "failed": len(self.failed_leaves),
            "re_planned": len(self.re_planned_nodes),
            "api_calls": self.api_calls,
            "uptime_sec": int(time.time() - self.created_at) if self.created_at else 0,
        }


# ============================================================
# 2. 超时策略（按复杂度动态调整）
# ============================================================

class TimeoutPolicy:
    """所有超时集中管理，确保不同规模任务有合理阈值"""

    @staticmethod
    def step_timeout(complexity: int, depth: int) -> int:
        """单步超时（秒）：复杂度越高、深度越浅 → 超时越长"""
        base = {1:30, 2:30, 3:30, 4:60, 5:60, 6:120, 7:120, 8:300, 9:300, 10:300}.get(complexity, 60)
        # 深度每+1，因子*0.7（深层任务更简单，超时可更短）
        factor = max(0.3, 1.0 - depth * 0.15)
        return int(base * factor)

    @staticmethod
    def total_timeout(complexity: int) -> int:
        """总任务硬上限（秒）"""
        return {1:30, 2:60, 3:120, 4:300, 5:600, 6:1800, 7:3600, 8:14400, 9:43200, 10:86400}.get(complexity, 3600)

    @staticmethod
    def idle_timeout(complexity: int) -> int:
        """无进展判定（分钟）"""
        return {1:1, 2:2, 3:3, 4:5, 5:8, 6:12, 7:15, 8:20, 9:30, 10:30}.get(complexity, 15)

    @staticmethod
    def label(complexity: int) -> str:
        if complexity <= 3: return "简单"
        elif complexity <= 5: return "中等"
        elif complexity <= 7: return "复杂"
        elif complexity <= 9: return "大型"
        else: return "超大规模(通宵级)"

    @staticmethod
    def estimate(complexity: int, total_steps: int) -> str:
        step_t = TimeoutPolicy.step_timeout(complexity, 0)
        est = step_t * total_steps
        if est < 60: return "约几秒"
        elif est < 300: return "约几分钟"
        elif est < 3600: return f"约{est//60}分钟"
        else: return f"约{est//3600}小时"


# ============================================================
# 3. TaskTreeBuilder — LLM驱动层次分解
# ============================================================

class TaskTreeBuilder:
    """将用户目标递归分解为任务树。三种复杂度模式"""

    def __init__(self, agent):
        self.agent = agent

    def analyze_complexity(self, goal: str) -> int:
        """LLM评估复杂度 1-10"""
        prompt = f"""评估用户目标的复杂度，只返回1-10之间的数字。

1-3: 单一步骤，30秒内完成（如查天气、搜信息）
4-6: 多步骤但线性执行（如爬取+保存、搜索+整理）
7-8: 多步骤且有依赖（如爬取→分析→报告，需按序）
9-10: 大规模、多层次、持续运行（如完整项目、批量处理）

目标：{goal[:200]}"""
        try:
            resp = self.agent.llm.generate(prompt, max_tokens=8)
            score = int(''.join(c for c in resp if c.isdigit()) or '3')
            return max(1, min(10, score))
        except:
            return 3

    def decompose(self, goal: str) -> Tuple[TaskNode, TaskSession]:
        """主入口"""
        complexity = self.analyze_complexity(goal)
        idle_timeout = TimeoutPolicy.idle_timeout(complexity)

        session = TaskSession(
            session_id=f"ts_{int(time.time())}",
            goal=goal,
            created_at=time.time(),
            last_heartbeat=time.time(),
            max_idle_minutes=idle_timeout,
        )

        if complexity <= 3:
            # 简单任务：扁平步骤
            root = self._simple_plan(goal)
        else:
            # 复杂任务：递归分解
            root = self._recursive_decompose(goal, depth=0, max_depth=3)

        session.total_leaves = self._count_leaves(root)
        session.task_tree = root
        self._inject_timeouts(root, complexity)

        est = TimeoutPolicy.estimate(complexity, session.total_leaves)
        session.current_phase = (
            f"[{TimeoutPolicy.label(complexity)}] "
            f"分解为{session.total_leaves}个步骤，{est}"
        )
        return root, session

    def _simple_plan(self, goal: str) -> TaskNode:
        """简单任务：扁平步骤"""
        prompt = f"""生成扁平执行计划。输出JSON：{{"steps":[{{"tool":"...","args":{{...}},"description":"..."}}]}}

工具：web_search, run_python, read_file, write_file, execute_shell

目标：{goal[:200]}"""
        try:
            resp = self.agent.llm.generate(prompt, max_tokens=1024)
            start, end = resp.find('{'), resp.rfind('}')
            if start >= 0 and end > start:
                data = json.loads(resp[start:end+1])
                steps = data.get("steps", [])
            else:
                steps = []
        except:
            steps = [{"tool": "web_search", "args": {"query": goal[:100]}, "description": goal[:80]}]

        root = TaskNode(id="root", description=goal, depth=0)
        for i, s in enumerate(steps):
            leaf = TaskNode(
                id=f"root.{i}", description=s.get("description", ""),
                tool=s.get("tool", "web_search"),
                args=s.get("args", {}),
                depth=1, is_leaf=True,
                dependencies=[f"root.{j}" for j in range(i)]
            )
            root.subtasks.append(leaf)
        return root

    def _resolve_deps(self, raw_deps: list, parent_id: str, sub_index: int) -> list:
        """转换LLM返回的依赖ID为完整的节点ID"""
        resolved = []
        for d in raw_deps:
            d_str = str(d)
            # 如果是简单数字如"0"，拼成 parent.0
            if d_str.isdigit():
                resolved.append(f"{parent_id}.{d_str}")
            elif not d_str.startswith("root"):
                resolved.append(f"{parent_id}.{d_str}")
            else:
                resolved.append(d_str)
        return resolved

    def _recursive_decompose(self, goal: str, depth: int, max_depth: int) -> TaskNode:
        """LLM递归分解"""
        depth_hint = (
            f"已达最大深度{depth}/{max_depth}，必须生成叶子节点"
            if depth >= max_depth else
            f"深度{depth}/{max_depth}，可继续分解"
        )
        prompt = f"""分析目标，生成子任务。{depth_hint}

规则：
- 叶子任务必须指定tool和args
- 标注dependencies（依赖的任务ID列表）
- 不可分解时 is_leaf=true

工具：web_search, run_python, read_file, write_file, execute_shell

输出JSON：{{"subtasks":[{{"id":"0","description":"...","tool":"web_search","args":{{"query":"..."}},"dependencies":[],"is_leaf":true}}]}}

目标：{goal[:200]}"""
        try:
            resp = self.agent.llm.generate(prompt, max_tokens=2048)
            start, end = resp.find('{'), resp.rfind('}')
            if start >= 0 and end > start:
                data = json.loads(resp[start:end+1])
                raw = data.get("subtasks", [])
            else:
                raw = []
        except:
            raw = []

        root = TaskNode(id=f"root", description=goal[:80], depth=depth)
        for i, st in enumerate(raw):
            is_leaf = st.get("is_leaf", len(st.get("subtasks", [])) == 0)
            raw_deps = st.get("dependencies", [])
            if is_leaf:
                node = TaskNode(
                    id=f"root.{i}", description=st.get("description", "")[:120],
                    tool=st.get("tool", "web_search"),
                    args=st.get("args", {}),
                    dependencies=self._resolve_deps(raw_deps, root.id, i),
                    depth=depth+1, is_leaf=True,
                )
            else:
                sub_goal = st.get("description", goal)[:200]
                child = self._recursive_decompose(sub_goal, depth+1, max_depth)
                node = TaskNode(
                    id=f"root.{i}", description=st.get("description", "")[:120],
                    subtasks=child.subtasks,
                    dependencies=self._resolve_deps(raw_deps, root.id, i),
                    depth=depth+1, is_leaf=False,
                )
            root.subtasks.append(node)
        return root

    def _count_leaves(self, node: TaskNode) -> int:
        if node.is_leaf: return 1
        return sum(self._count_leaves(s) for s in node.subtasks)

    def _inject_timeouts(self, node: TaskNode, complexity: int):
        node.timeout_seconds = TimeoutPolicy.step_timeout(complexity, node.depth)
        for s in node.subtasks:
            self._inject_timeouts(s, complexity)


# ============================================================
# 4. FailureReflector — 失败深度反思器（5路情报+LLM反思）
# ============================================================

class FailureReflector:
    """
    任务失败时的多维度深度反思：
    ① 收集5路情报
    ② LLM根因分析 + 反事实思考 + 方案生成
    ③ 可选联网搜索增强
    ④ 自动执行/跳过/推送WebUI
    """

    def __init__(self, agent):
        self.agent = agent

    def reflect(self, node: TaskNode, session: TaskSession) -> Dict:
        """对失败节点进行深度反思，返回恢复计划"""
        
        # ===== ① 收集5路情报 =====
        error_info = (
            f"工具: {node.tool}\n"
            f"参数: {str(node.args)[:200]}\n"
            f"错误: {(node.error or '未知错误')[:300]}"
        )

        # 1a. 因果三元组（历史经验）
        causal_hints = ""
        try:
            kg = self.agent.knowledge_graph
            if hasattr(kg, 'causal_triples'):
                triples = list(kg.causal_triples)[-20:]
                matched = []
                for ct in triples:
                    cond = (ct.get('condition', '') + ct.get('action', '')).lower()
                    kw = node.tool.lower() if node.tool else ""
                    if kw and kw in cond:
                        matched.append(
                            f"  [{ct.get('confidence',0):.1f}] "
                            f"{ct.get('condition','')[:40]}→{ct.get('result','')[:40]}"
                        )
                if matched:
                    causal_hints = "相似历史经验（因果库）：\n" + "\n".join(matched[:5])
        except:
            pass

        # 1b. 工作记忆（近期失败记录）
        memory_hints = ""
        try:
            wm = getattr(self.agent.memory, 'working_memory', None) or []
            recent_fails = []
            for m in list(wm)[-30:]:
                if isinstance(m, dict):
                    txt = str(m.get('text', m.get('content', '')))
                    if any(kw in txt for kw in ['失败', 'error', 'fault', '异常', 'timeout']):
                        recent_fails.append(txt[:120])
            if recent_fails:
                memory_hints = "近期失败记录：\n" + "\n".join(recent_fails[-3:])
        except:
            pass

        # 1c. 锚点/知识库
        kb_hints = ""
        try:
            if hasattr(self.agent, 'anchor_engine'):
                q = f"{node.tool or ''} {node.description}"
                anchors = self.agent.anchor_engine.match_anchors_for_query(q, max_results=3)
                if anchors:
                    parts = []
                    for a in anchors[:3]:
                        content = str(a.get('content', a.get('text', '')))[:100]
                        parts.append(f"  • {content}")
                    kb_hints = "知识锚点：\n" + "\n".join(parts)
        except:
            pass

        # ===== ② LLM深度反思 =====
        prompt = f"""分析任务失败原因，给出恢复方案。

[失败信息]
{error_info}

[任务描述]
{node.description[:200]}

[历史经验]
{causal_hints[:400] or '无'}

[近期失败]
{memory_hints[:300] or '无'}

[知识锚点]
{kb_hints[:300] or '无'}

分析步骤：
1. 根因分析：为什么失败？
2. 反事实思考：如果不这样做会怎样？
3. 替代方案：还有什么方法？
4. 联网搜索提示：搜什么关键词来找解决方案？

输出JSON：
{{
  "root_cause": "简要根因",
  "counterfactual": "如果不这样做的可能结果",
  "decision": "retry | replan | skip | need_user",
  "alternative_plan": {{"tool":"...","args":{{...}},"description":"..."}},
  "search_keywords": "如需联网搜索填这里",
  "confidence": 0.8,
  "reasoning": "分析过程"
}}"""
        try:
            resp = self.agent.llm.generate(prompt, max_tokens=1024)
            start, end = resp.find('{'), resp.rfind('}')
            reflection = json.loads(resp[start:end+1]) if start >= 0 and end > start else {"decision": "retry", "confidence": 0.3}
        except:
            reflection = {"decision": "retry", "confidence": 0.3}

        # ===== ③ 可选联网搜索增强 =====
        if reflection.get("confidence", 0) < 0.5 and reflection.get("search_keywords"):
            try:
                r = self.agent.tools.execute("web_search", {"query": reflection["search_keywords"]})
                if r.success:
                    reflection["web_hint"] = str(r.result)[:300]
                    reflection["confidence"] = min(1.0, reflection.get("confidence", 0) + 0.2)
            except:
                pass

        # 记录日志
        session.reflection_log.append({
            "time": time.time(),
            "node_id": node.id,
            "error": (node.error or "")[:200],
            "decision": reflection.get("decision", "retry"),
            "confidence": reflection.get("confidence", 0),
            "counterfactual": reflection.get("counterfactual", "")[:200],
        })
        return reflection


# ============================================================
# 5. ResilienceManager — 4层弹性执行器
# ============================================================

class ResilienceManager:
    """
    Layer 1: 工具调用级 — 指数退避重试（429/超时/断连）
    Layer 2: 规划级 — 深度反思 + 换参/换工具
    Layer 3: 子任务级 — 整体重构
    Layer 4: 会话级 — 死锁检测 + 用户介入
    """

    def __init__(self, agent, reflector: FailureReflector):
        self.agent = agent
        self.reflector = reflector
        self.log = deque(maxlen=100)

    def execute_leaf(self, node: TaskNode, session: TaskSession) -> bool:
        """执行叶子节点，返回True=成功"""
        tool = node.tool or "web_search"
        args = dict(node.args or {})

        # ===== Layer 1: 工具调用级重试 =====
        for attempt in range(1, node.max_retries_base + 1):
            node.retry_count = attempt
            session.api_calls += 1
            try:
                print(f"  ▶ {node.description[:40]} ({attempt}/{node.max_retries_base})", flush=True)
                result = self.agent.tools.execute(tool, args)
                if result.success:
                    node.status = "success"
                    node.result = str(result.result)[:500]
                    node.completed_at = time.time()
                    session.completed_leaves.append(node.id)
                    session.progress = len(session.completed_leaves) / max(session.total_leaves, 1)
                    session.updated_at = time.time()
                    self.log.append({"time": time.time(), "node": node.id, "success": True})
                    return True

                error = (result.error or "").lower()
                node.error = result.error or "未知错误"

                # 429限速
                if "rate limit" in error or "429" in error:
                    wait = 2 ** attempt
                    print(f"    [WAIT]  限速，等{wait}s", flush=True)
                    time.sleep(wait)
                    continue
                # token超限
                if "maximum context" in error or "token limit" in error:
                    if "max_tokens" in args and isinstance(args.get("max_tokens"), int):
                        args["max_tokens"] = max(256, args["max_tokens"] // 2)
                        print(f"    [TOKEN] 超限，减至{args['max_tokens']}", flush=True)
                    continue
                # 网络异常
                if "timeout" in error or "connection" in error or "reset" in error:
                    wait = 2 ** attempt
                    print(f"    [NET] 网络异常，等{wait}s", flush=True)
                    time.sleep(wait)
                    continue
                # 其他错误 → 进Layer 2
                break
            except Exception as e:
                node.error = f"{type(e).__name__}: {str(e)[:100]}"
                if attempt < node.max_retries_base:
                    time.sleep(2)
                    continue
                break

        # ===== Layer 2: 深度反思+重规划 =====
        if node.retry_count < node.max_retries_base + node.max_retries_replan:
            print(f"    [RETRY]  启动深度反思...", flush=True)
            reflection = self.reflector.reflect(node, session)
            decision = reflection.get("decision", "retry")
            conf = reflection.get("confidence", 0)
            session.re_planned_nodes.append(node.id)

            if decision == "retry" and conf > 0.3:
                alt = reflection.get("alternative_plan", {})
                if alt.get("tool"):
                    node.tool, node.args = alt["tool"], alt.get("args", {})
                    print(f"    [RETRY]  换参数重试: {alt.get('description','')[:40]}", flush=True)
                    return self.execute_leaf(node, session)
                return self.execute_leaf(node, session)
            elif decision == "replan" and conf > 0.4:
                alt = reflection.get("alternative_plan", {})
                if alt.get("tool"):
                    node.tool, node.args = alt["tool"], alt.get("args", {})
                    node.description = alt.get("description", node.description)
                    print(f"    [RETRY]  换方案: {alt.get('description','')[:40]}", flush=True)
                    return self.execute_leaf(node, session)
            elif decision == "skip":
                print(f"    鈴锔 跳过（非关键）", flush=True)
                node.status = "skipped"
                return True
            elif decision == "need_user":
                node.status = "pending"
                session.status = "user_intervention"
                session.current_phase = f"⛔ '{node.description[:40]}' 需用户决策"
                self._push_webui(session, "user_help",
                    f"'{node.description[:40]}' 失败，建议：{reflection.get('reasoning','')[:200]}")
                return False

        # 彻底失败
        node.status = "failed"
        session.failed_leaves.append(node.id)
        self.log.append({"time": time.time(), "node": node.id, "success": False, "error": node.error})
        print(f"    [FAIL]  彻底失败: {node.error[:80]}", flush=True)
        return False

    def _push_webui(self, session, typ, content):
        try:
            if hasattr(self.agent, '_proactive_queue'):
                self.agent._proactive_queue.append({
                    "time": time.time(), "type": f"task_{typ}",
                    "session_id": session.session_id,
                    "content": content[:200],
                })
        except:
            pass


# ============================================================
# 6. TaskExecutor — DAG执行引擎（并行+串行）
# ============================================================

class TaskExecutor:
    """DAG执行引擎：依赖分层 → 层内并行 → checkpoint → 推送"""

    def __init__(self, agent, resilience: ResilienceManager):
        self.agent = agent
        self.resilience = resilience
        self._stop = threading.Event()

    def execute(self, session: TaskSession):
        root = session.task_tree
        if not root:
            return
        session.status = "running"
        session.last_heartbeat = time.time()
        self._stop.clear()

        layers = self._build_layers(root)
        total_layers = len(layers)
        print(f"  [DAG] {session.total_leaves}叶节点 → {total_layers}个执行层", flush=True)

        for li, layer in enumerate(layers):
            if self._stop.is_set():
                session.status = "paused"
                self._save_checkpoint(session)
                return

            # 更新阶段
            names = [n.description[:25] for n in layer[:3]]
            session.current_phase = f"[层{li+1}/{total_layers}] " + ", ".join(names)
            if len(layer) > 3:
                session.current_phase += f" +{len(layer)-3}项"
            self._push_progress(session)

            # 层内并发执行
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(len(layer), 4)) as pool:
                futures = {pool.submit(self._run_node, n, session): n for n in layer}
                for f in as_completed(futures):
                    node = futures[f]
                    try:
                        f.result(timeout=node.timeout_seconds + 30)
                    except Exception as e:
                        node.status = "failed"
                        node.error = f"执行异常: {str(e)[:100]}"

            self._save_checkpoint(session)
            session.last_heartbeat = time.time()

        # 完成
        if session.status not in ("paused", "user_intervention"):
            has_fails = len(session.failed_leaves) > 0
            session.status = "completed_with_warnings" if has_fails else "completed"
            session.progress = 1.0
            session.current_phase = "[OK]  全部完成" if not has_fails else "[OK]  完成（部分跳过/失败）"
            self._push_progress(session)

    def _build_layers(self, root: TaskNode) -> List[List[TaskNode]]:
        """按依赖关系拓扑排序"""
        leaves = []
        def collect(n):
            if n.is_leaf: leaves.append(n)
            else:
                for s in n.subtasks: collect(s)
        collect(root)
        if not leaves:
            return []

        node_map = {n.id: n for n in leaves}
        resolved = set()
        layers = []
        while len(resolved) < len(leaves):
            layer = []
            for n in leaves:
                if n.id in resolved:
                    continue
                if all(d in resolved or d not in node_map for d in n.dependencies):
                    layer.append(n)
            if not layer:
                # 环检测 → 全部强制加入
                layer = [n for n in leaves if n.id not in resolved]
            for n in layer:
                resolved.add(n.id)
            layers.append(layer)
        return layers

    def _run_node(self, node: TaskNode, session: TaskSession):
        if self._stop.is_set():
            return
        if node.is_leaf:
            node.status = "running"
            node.started_at = time.time()
            self.resilience.execute_leaf(node, session)
            self._push_progress(session)
        else:
            for c in node.subtasks:
                if self._stop.is_set():
                    return
                self._run_node(c, session)

    def _push_progress(self, session: TaskSession):
        try:
            if hasattr(self.agent, '_proactive_queue'):
                self.agent._proactive_queue.append({
                    "time": time.time(), "type": "task_progress",
                    "session_id": session.session_id,
                    "progress": session.progress,
                    "phase": session.current_phase,
                    "completed": len(session.completed_leaves),
                    "total": session.total_leaves,
                    "failed": len(session.failed_leaves),
                    "status": session.status,
                })
        except:
            pass

    def _save_checkpoint(self, session: TaskSession):
        try:
            base = getattr(self.agent, '_source_file', '') or r'D:\Ai电脑智能体\v5.9'
            ck_dir = os.path.join(os.path.dirname(base), 'data', 'task_sessions')
            os.makedirs(ck_dir, exist_ok=True)
            ck = {
                "session_id": session.session_id, "goal": session.goal,
                "status": session.status, "progress": session.progress,
                "phase": session.current_phase,
                "completed_leaves": session.completed_leaves,
                "failed_leaves": session.failed_leaves,
                "re_planned_nodes": session.re_planned_nodes,
                "total_leaves": session.total_leaves,
                "api_calls": session.api_calls,
                "updated_at": session.updated_at,
                "task_tree": session.task_tree.to_dict() if session.task_tree else None,
            }
            with open(os.path.join(ck_dir, f"{session.session_id}.json"), 'w', encoding='utf-8') as f:
                json.dump(ck, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [checkpoint失败] {e}", flush=True)

    def stop(self):
        self._stop.set()


# ============================================================
# 7. ProgressTracker — WebUI多轮/分段/最终报告
# ============================================================

class ProgressTracker:
    """进度追踪 + 多轮报告生成"""

    def __init__(self, agent):
        self.agent = agent

    def final_summary(self, session: TaskSession) -> str:
        total = session.total_leaves
        done = len(session.completed_leaves)
        failed = len(session.failed_leaves)
        replan = len(session.re_planned_nodes)
        skipped = total - done - failed
        lines = [
            f"[STATS] 任务完成报告",
            f"  目标: {session.goal[:80]}",
            f"  步骤: 总{total} → 完成{done} 失败{failed} 跳过{skipped}",
            f"  重规划: {replan}次 | API调用: {session.api_calls}次",
        ]
        if session.created_at:
            secs = int(time.time() - session.created_at)
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            lines.append(f"  运行: {h}时{m}分{s}秒")
        if session.reflection_log:
            lines.append(f"  反思日志:")
            for log in session.reflection_log[-3:]:
                lines.append(f"    • {log.get('decision','?')} (置信{log.get('confidence',0):.0%})")
        return "\n".join(lines)


# ============================================================
# 8. TaskDecomposer — 统一入口 + 死锁检测看门狗
# ============================================================

class TaskDecomposer:
    """
    统一入口。职责：
    - 分解任务 → 后台执行 → WebUI推送 → 死锁检测
    - 支持：通宵挂跑、多轮进度、失败反思、恢复断点
    """

    def __init__(self, agent):
        self.agent = agent
        self.reflector = FailureReflector(agent)
        self.builder = TaskTreeBuilder(agent)
        self.resilience = ResilienceManager(agent, self.reflector)
        self.executor = TaskExecutor(agent, self.resilience)
        self.tracker = ProgressTracker(agent)
        self.sessions: Dict[str, TaskSession] = {}
        self._lock = threading.Lock()
        # 启动死锁看门狗
        threading.Thread(target=self._deadlock_watchdog, daemon=True).start()

    def start(self, goal: str) -> TaskSession:
        """启动一个任务，返回会话（后台执行）"""
        root, session = self.builder.decompose(goal)
        with self._lock:
            self.sessions[session.session_id] = session

        t = threading.Thread(
            target=self._run,
            args=(session,),
            daemon=True,
            name=f"td_{session.session_id[:8]}"
        )
        t.start()

        print(f"\n---[任务分解器] 已启动", flush=True)
        print(f"  ID: {session.session_id}", flush=True)
        print(f"  分级: {TimeoutPolicy.label(self.builder.analyze_complexity(goal))}", flush=True)
        print(f"  步骤: {session.total_leaves}个", flush=True)
        print(f"  状态: 后台运行中，WebUI可见进度", flush=True)
        return session

    def _run(self, session: TaskSession):
        try:
            self._push_report(session, "task_started", f"任务启动: {session.goal[:80]} ({session.total_leaves}步)")
            self.executor.execute(session)
            if session.status in ("completed", "completed_with_warnings"):
                summary = self.tracker.final_summary(session)
                self._push_report(session, "task_final_summary", summary)
                print(f"\n{summary}", flush=True)
        except Exception as e:
            session.status = "failed"
            session.current_phase = f"异常: {str(e)[:100]}"
            self._push_report(session, "task_final_summary", f"[异常终止] {str(e)[:200]}")
            print(f"  [FAIL]  异常: {e}", flush=True)
        finally:
            self.executor._save_checkpoint(session)

    def _push_report(self, session, typ, content):
        try:
            if hasattr(self.agent, '_proactive_queue'):
                self.agent._proactive_queue.append({
                    "time": time.time(), "type": typ,
                    "session_id": session.session_id, "content": content[:300],
                })
        except:
            pass

    def _deadlock_watchdog(self):
        """每分钟检查一次活跃会话，超时无心跳 → 暂停+推送"""
        while True:
            time.sleep(60)
            with self._lock:
                for sid, s in list(self.sessions.items()):
                    if s.status != "running":
                        continue
                    idle = (time.time() - s.last_heartbeat) / 60
                    if idle > s.max_idle_minutes:
                        print(f"\n  [[WARN]  死锁] {sid[:8]} 空闲{idle:.0f}分 > {s.max_idle_minutes}分", flush=True)
                        s.status = "paused"
                        s.current_phase = f"[WARN]  死锁: 空闲{idle:.0f}分钟"
                        self._push_report(s, "task_deadlock",
                            f"任务空闲{idle:.0f}分钟，已暂停。WebUI可恢复")

    def get_progress(self, session_id: str):
        with self._lock:
            s = self.sessions.get(session_id)
            return s.to_dict() if s else None

    def list_active(self):
        with self._lock:
            return [s.to_dict() for s in self.sessions.values()
                    if s.status in ("running", "pending", "paused", "user_intervention")]

    def stop(self, session_id: str) -> bool:
        with self._lock:
            s = self.sessions.get(session_id)
            if s:
                s.status = "paused"
                self.executor.stop()
                return True
            return False


# ============================================================
# 验证
# ============================================================
