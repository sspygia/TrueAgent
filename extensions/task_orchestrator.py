"""
任务编排器 — 单智能体 + 真实分身子进程调度
====================================
能力:
  - 目标拆解为层次化子任务（含依赖关系/质量要求）
  - 通过 CloneManager.dispatch() 派遣分身子进程
  - 监控进度、轮询收集结果
  - 全面反思闭环（continue / replan / report）
  - 结果注入主智能体主动消息队列
"""

import os, json, time, uuid, threading, copy
from datetime import datetime

ORCH_DIR = None  # 运行时初始化

def _get_orch_dir():
    global ORCH_DIR
    if ORCH_DIR is None:
        base = os.path.dirname(os.path.abspath(__file__))
        ORCH_DIR = os.path.join(os.path.dirname(base), 'data', 'task_orchestrator')
    os.makedirs(ORCH_DIR, exist_ok=True)
    return ORCH_DIR

def _load_json(name):
    path = os.path.join(_get_orch_dir(), name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def _save_json(name, data):
    path = os.path.join(_get_orch_dir(), name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _safe_save(name, data):
    path = os.path.join(_get_orch_dir(), name)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[Orch] _safe_save 失败: {e}", flush=True)
        # 尝试直接写原始文件
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass


# ==================== 数据结构 ====================

def new_task_package(goal, background="", quality_standards="", files=None):
    """创建新的任务包"""
    pid = "tp_" + uuid.uuid4().hex[:12]
    now = time.time()
    return {
        "id": pid,
        "title": goal[:60],
        "goal": goal,
        "background": background,
        "quality_standards": quality_standards,
        "files": files or [],
        "status": "pending",  # pending → decomposing → assigned → in_progress → completed → assembling → done
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "subtasks": [],
        "report": "",
        "final_result": "",
    }

def new_subtask(package_id, description, background="", requirements="", quality="",
                assigned_to="", files=None, dependencies=None):
    """创建子任务"""
    sid = "st_" + uuid.uuid4().hex[:10]
    now = time.time()
    return {
        "id": sid,
        "package_id": package_id,
        "description": description,
        "background": background,
        "requirements": requirements,
        "quality_standards": quality,
        "assigned_to": assigned_to,
        "files": files or [],
        "dependencies": dependencies or [],
        "status": "pending",
        "progress": 0.0,
        "result": "",
        "error": "",
        "created_at": now,
        "assigned_at": None,
        "completed_at": None,
    }


# ==================== 知识库分析 ====================

def analyze_agent_capabilities(agent_id):
    """分析指定智能体的能力（知识库统计 + 黑板注册信息）"""
    info = {"id": agent_id, "knowledge_files": 0, "knowledge_dir_size": 0, "capabilities": []}
    try:
        # 查询黑板注册信息
        from extensions.blackboard import get_partner
        partner = get_partner(agent_id)
        if partner:
            info["capabilities"] = partner.get("capabilities", [])
            info["status"] = partner.get("status", "unknown")
            info["last_seen"] = partner.get("last_seen", 0)

        # 查询知识库
        base_dir = os.path.dirname(os.path.abspath(__file__))
        parent = os.path.dirname(base_dir)
        kb_paths = [
            os.path.join(parent, 'data', 'knowledge'),
        ]
        # 检查分身独立知识库
        for d in os.listdir(os.path.join(parent, 'data')):
            if d.startswith('instance_'):
                kb = os.path.join(parent, 'data', d, 'data', 'knowledge')
                if os.path.isdir(kb):
                    kb_paths.append(kb)

        total_files = 0
        for kbp in kb_paths:
            if os.path.isdir(kbp):
                for root, dirs, files in os.walk(kbp):
                    total_files += len([f for f in files if f.endswith('.md')])
        info["knowledge_files"] = total_files
    except Exception as e:
        info["error"] = str(e)
    return info

def analyze_all_agents():
    """分析所有智能体能力"""
    agents = {}
    try:
        from extensions.blackboard import get_all_agents
        all_agents = get_all_agents()
        for a in all_agents:
            aid = a.get("id", "")
            if aid:
                agents[aid] = analyze_agent_capabilities(aid)
    except:
        pass
    return agents


# ==================== 任务编排器 ====================

class TaskOrchestrator:
    """主任务编排器 - 全权负责任务的分解、分配、监管、收齐"""

    def __init__(self):
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        self._packages = _load_json("packages.json")
        if not self._packages:
            self._packages = {}
        self.auto_cleanup(max_keep=10, max_age_hours=2)

    def _save(self):
        _safe_save("packages.json", self._packages)

    def auto_cleanup(self, max_keep=10, max_age_hours=2):
        """v5.9: 自动清理旧包，防止无限膨胀拖慢序列化"""
        now = time.time()
        cutoff = now - max_age_hours * 3600
        with self._lock:
            # 收集可清理的
            to_delete = []
            for pid, pkg in self._packages.items():
                age = now - pkg.get("created_at", 0)
                status = pkg.get("status", "")
                # 超过时间或已完成/失败
                if age > cutoff and status in ("done", "failed", "done_with_errors"):
                    to_delete.append(pid)
            # 按创建时间排序，优先删旧的
            to_delete.sort(key=lambda pid: self._packages[pid].get("created_at", 0))
            # 保留最近 max_keep 个
            while len(to_delete) > 0 and len(self._packages) - len(to_delete) < max_keep:
                to_delete.pop()  # 保留较新的

            for pid in to_delete:
                del self._packages[pid]

            if to_delete:
                self._save()
                print(f"[Orch] 自动清理 {len(to_delete)} 个旧包 (剩余 {len(self._packages)})", flush=True)

    # ---- 1. 任务录入 ----

    def create_package(self, goal, background="", quality_standards="", files=None):
        """创建一个新的任务包"""
        pkg = new_task_package(goal, background, quality_standards, files)
        with self._lock:
            self._packages[pkg["id"]] = pkg
            self._save()
        return pkg

    def get_package(self, package_id):
        with self._lock:
            return copy.deepcopy(self._packages.get(package_id))

    def list_packages(self, limit=20):
        with self._lock:
            pkgs = list(self._packages.values())
        pkgs.sort(key=lambda x: x["created_at"], reverse=True)
        return pkgs[:limit]

    # ---- 2. 任务分解（LLM 驱动） ----

    def decompose_task(self, package_id, llm_callback=None):
        """分解任务为子任务列表（可 LLM 驱动或手动）"""
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        pkg["status"] = "decomposing"
        self._update_package(pkg)

        if llm_callback:
            return self._auto_decompose(pkg, llm_callback)
        else:
            return {"success": False, "error": "需要 LLM 回调进行自动分解"}

    def _auto_decompose(self, pkg, llm_callback):
        """LLM 驱动分解"""
        try:
            subtasks = llm_callback(pkg)
            if not subtasks:
                return {"success": False, "error": "分解结果为空"}

            with self._lock:
                pkg_data = self._packages.get(pkg["id"])
                if not pkg_data:
                    return {"success": False, "error": "任务包已消失"}
                pkg_data["subtasks"] = subtasks
                pkg_data["status"] = "decomposed"
                pkg_data["updated_at"] = time.time()
                self._save()

            return {"success": True, "subtasks": subtasks}
        except Exception as e:
            pkg["status"] = "decompose_failed"
            self._update_package(pkg)
            return {"success": False, "error": str(e)}

    def add_subtask(self, package_id, subtask):
        """手动添加子任务。返回 {"success": True, "id": "st_xxx"} 或 {"success": False, "error": ...}"""
        with self._lock:
            pkg = self._packages.get(package_id)
            if not pkg:
                return {"success": False, "error": "任务包不存在"}
            # 自动补全 id
            if not subtask.get("id"):
                subtask["id"] = "st_" + uuid.uuid4().hex[:10]
            if not subtask.get("created_at"):
                subtask["created_at"] = time.time()
            if not subtask.get("status"):
                subtask["status"] = "pending"
            if subtask.get("progress") is None:
                subtask["progress"] = 0
            pkg["subtasks"].append(subtask)
            pkg["updated_at"] = time.time()
            self._save()
        return {"success": True, "id": subtask["id"]}

    # ---- 3. 智能体分析 ----

    def analyze_agents_for_task(self, package_id):
        """分析所有可用的智能体，为任务分配做准备"""
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        agent_info = analyze_all_agents()
        subtask_count = len(pkg.get("subtasks", []))

        # 生成匹配建议
        suggestions = []
        for st in pkg.get("subtasks", []):
            best_agent = ""
            best_score = 0
            for aid, info in agent_info.items():
                score = 0
                # 在线优先
                if info.get("status") == "running" and (time.time() - info.get("last_seen", 0)) < 120:
                    score += 30
                # 知识库丰富度
                score += min(info.get("knowledge_files", 0) / 10, 30)
                # 注册的能力匹配
                for cap in info.get("capabilities", []):
                    if cap.lower() in st["description"].lower():
                        score += 20
                if score > best_score:
                    best_score = score
                    best_agent = aid
            suggestions.append({
                "subtask_id": st["id"],
                "description": st["description"],
                "recommended_agent": best_agent,
                "confidence": min(best_score / 80, 1.0),
                "available_agents": agent_info,
            })

        return {"success": True, "agent_info": agent_info, "suggestions": suggestions}

    # ---- 4. 任务分配 ----

    def assign_task(self, package_id, assignment_map):
        """分配任务给指定智能体
        assignment_map: {subtask_id: agent_id}
        """
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        assigned = []
        with self._lock:
            pkg_data = self._packages.get(package_id)
            for st in pkg_data.get("subtasks", []):
                if st["id"] in assignment_map:
                    agent_id = assignment_map[st["id"]]
                    st["assigned_to"] = agent_id
                    st["status"] = "assigned"
                    st["assigned_at"] = time.time()
                    assigned.append(st["id"])

                    # 通过黑板发布任务
                    try:
                        from extensions.blackboard import post_task, send_message
                        # 构建完整任务上下文
                        full_context = (
                            f"【任务包】{pkg['title']}\n"
                            f"【目标】{pkg['goal']}\n"
                            f"【背景】{pkg['background']}\n"
                            f"【质量要求】{pkg['quality_standards']}\n"
                            f"【子任务】{st['description']}\n"
                            f"【子任务要求】{st['requirements']}\n"
                            f"【子任务质量标准】{st['quality_standards']}\n"
                            f"【前置依赖】{st['dependencies'] or '无'}\n"
                            f"【附件】{st['files'] or '无'}"
                        )
                        # 发到黑板任务队列
                        post_task(
                            description=full_context,
                            created_by="agent_main",
                            subtasks=None
                        )
                        # 发私聊通知
                        send_message(
                            from_id="agent_main",
                            to_id=agent_id,
                            msg_type="private",
                            content=(
                                f"📋 新任务分配!\n"
                                f"任务包: {pkg['title']}\n"
                                f"子任务: {st['description']}\n"
                                f"请到黑板查看完整上下文并开始执行。"
                                f"\n\n指令: 任务:完成 \"{st['description'][:40]}...\""
                            )
                        )
                    except Exception as e:
                        pass

            pkg_data["status"] = "assigned"
            pkg_data["updated_at"] = time.time()
            self._save()

        return {"success": True, "assigned": assigned}

    def assign_all_auto(self, package_id, suggestions):
        """根据分析建议自动分配所有子任务"""
        assignment_map = {}
        for s in suggestions:
            if s.get("recommended_agent"):
                assignment_map[s["subtask_id"]] = s["recommended_agent"]
        return self.assign_task(package_id, assignment_map)

    # ---- 5. 进度监控 ----

    def monitor_progress(self, package_id):
        """查询所有子任务的最新进度"""
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        # 从黑板同步任务状态
        try:
            from extensions.blackboard import get_pending_tasks
            bb_tasks = get_pending_tasks()
            with self._lock:
                pkg_data = self._packages.get(package_id)
                for st in pkg_data.get("subtasks", []):
                    for bt in bb_tasks:
                        if st["description"][:30] in bt.get("description", ""):
                            st["progress"] = bt.get("progress", st["progress"])
                            st["status"] = bt.get("status", st["status"])
                            st["result"] = bt.get("result", st["result"])
                self._save()
        except:
            pass

        return {"success": True, "package": self.get_package(package_id)}

    # ---- 6. 报告生成 ----

    def generate_report(self, package_id, llm_callback=None):
        """生成进度报告"""
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        subtasks = pkg.get("subtasks", [])
        total = len(subtasks)
        completed = sum(1 for s in subtasks if s["status"] == "completed")
        failed = sum(1 for s in subtasks if s["status"] == "failed")
        in_progress = sum(1 for s in subtasks if s["status"] in ("assigned", "in_progress"))
        pending = sum(1 for s in subtasks if s["status"] in ("pending",))
        progress_pct = round((completed / total * 100) if total > 0 else 0, 1)

        # 各智能体统计
        agent_stats = {}
        for st in subtasks:
            aid = st.get("assigned_to", "未分配")
            if aid not in agent_stats:
                agent_stats[aid] = {"total": 0, "completed": 0, "failed": 0}
            agent_stats[aid]["total"] += 1
            if st["status"] == "completed":
                agent_stats[aid]["completed"] += 1
            elif st["status"] == "failed":
                agent_stats[aid]["failed"] += 1

        report = {
            "package_id": package_id,
            "title": pkg["title"],
            "status": pkg["status"],
            "progress_pct": progress_pct,
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "agent_stats": agent_stats,
            "subtask_details": subtasks,
            "generated_at": time.time(),
        }

        # 可选 LLM 生成自然语言总结
        if llm_callback:
            try:
                report["summary"] = llm_callback(report)
            except:
                pass

        # 保存到包中
        with self._lock:
            pkg_data = self._packages.get(package_id)
            if pkg_data:
                pkg_data["report"] = report
                self._save()

        return {"success": True, "report": report}

    # ---- 7. 结果收齐 ----

    def collect_results(self, package_id):
        """收集所有已完成子任务的结果"""
        pkg = self.get_package(package_id)
        if not pkg:
            return {"success": False, "error": "任务包不存在"}

        completed_st = [s for s in pkg.get("subtasks", []) if s["status"] == "completed"]
        failed_st = [s for s in pkg.get("subtasks", []) if s["status"] == "failed"]
        pending_st = [s for s in pkg.get("subtasks", []) if s["status"] not in ("completed", "failed")]

        # 尝试从黑板获取最新结果
        try:
            from extensions.blackboard import get_pending_tasks
            bb_tasks = get_pending_tasks()
            with self._lock:
                pkg_data = self._packages.get(package_id)
                for st in pkg_data.get("subtasks", []):
                    for bt in bb_tasks:
                        if st["description"][:30] in bt.get("description", ""):
                            if bt.get("result"):
                                st["result"] = bt["result"]
                                st["status"] = "completed"
                                st["completed_at"] = time.time()
                self._save()
        except:
            pass

        return {
            "success": True,
            "completed": len(completed_st),
            "failed": len(failed_st),
            "pending": len(pending_st),
            "collected_results": [{
                "subtask_id": s["id"],
                "description": s["description"],
                "assigned_to": s.get("assigned_to", ""),
                "result": s.get("result", ""),
                "completed_at": s.get("completed_at"),
            } for s in completed_st],
            "failed_results": [{
                "subtask_id": s["id"],
                "description": s["description"],
                "assigned_to": s.get("assigned_to", ""),
                "error": s.get("error", ""),
            } for s in failed_st],
        }

    # ---- 8. 最终整合 ----

    def finalize(self, package_id, llm_callback=None):
        """整合所有结果，生成最终交付物"""
        collected = self.collect_results(package_id)
        if not collected["success"]:
            return collected

        pkg = self.get_package(package_id)

        result_data = {
            "package_id": package_id,
            "title": pkg["title"],
            "goal": pkg["goal"],
            "background": pkg["background"],
            "total_subtasks": len(pkg.get("subtasks", [])),
            "completed": collected["completed"],
            "failed": collected["failed"],
            "collected_results": collected["collected_results"],
            "failed_results": collected["failed_results"],
            "finalized_at": time.time(),
        }

        # LLM 最终总结
        final_summary = ""
        if llm_callback:
            try:
                final_summary = llm_callback(result_data)
            except:
                final_summary = f"任务 '{pkg['title']}' 已完成 {collected['completed']}/{len(pkg.get('subtasks',[]))} 个子任务，{collected['failed']} 个失败。"

        result_data["final_summary"] = final_summary

        with self._lock:
            pkg_data = self._packages.get(package_id)
            if pkg_data:
                pkg_data["status"] = "done" if collected["failed"] == 0 else "done_with_errors"
                pkg_data["completed_at"] = time.time()
                pkg_data["final_result"] = result_data
                pkg_data["updated_at"] = time.time()
                self._save()

        return {"success": True, "final_result": result_data}

    def _update_package(self, pkg):
        with self._lock:
            if pkg["id"] in self._packages:
                self._packages[pkg["id"]].update(pkg)
                self._save()


# ==================== 便捷 API ====================

_orchestrator_instance = None

def get_orchestrator():
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = TaskOrchestrator()
    return _orchestrator_instance

def decompose_with_llm(goal, background="", quality_standards="", llm_fn=None):
    """一键任务编排：分析→分解→分配（需要 LLM 回调）"""
    orch = get_orchestrator()
    pkg = orch.create_package(goal, background, quality_standards)
    if llm_fn:
        result = orch.decompose_task(pkg["id"], llm_fn)
        if not result["success"]:
            return result
        # 自动分析智能体
        analysis = orch.analyze_agents_for_task(pkg["id"])
        if analysis["success"] and analysis.get("suggestions"):
            orch.assign_all_auto(pkg["id"], analysis["suggestions"])
    return {"success": True, "package": orch.get_package(pkg["id"])}


# ==================== 多轮编排循环 ====================
#
# 流程：
#   decompose → [节流]先派无依赖子任务 → 等结果 → 全面反思 →
#   ├─ continue → 下一轮（重新分解剩余 + 新派发）→ ...
#   ├─ replan   → 调整方案 → 重新派发
#   └─ report   → 汇总向用户汇报
#
# 每轮反思使用：记忆/知识图谱/锚点/因果三元组/执行轨迹/联网搜索
# 不限轮数 — 反思决定继续还是停


def orchestrate_loop(agent, goal: str, background: str = "",
                     quality_standards: str = "", max_parallel: int = 5):
    """
    多轮编排主循环（后台线程运行，不阻塞主智能体）

    参数：
      agent    — 主智能体实例（用于 LLM/context/CloneManager）
      goal     — 任务目标
      background      — 背景信息
      quality_standards — 质量标准
      max_parallel    — 每轮最多同时派发的分身数

    返回结果通过 agent._proactive_queue 注入
    """
    clone_mgr = getattr(agent, 'clone_manager', None)
    if not clone_mgr:
        result = {"error": "分身管理器未启用，无法执行多轮编排"}
        _inject_result(agent, result)
        return result

    orch = get_orchestrator()
    pkg = orch.create_package(goal, background, quality_standards)
    pkg_id = pkg["id"]
    
    # v5.9: 取当前深度，子分身深度+1（实现级联穿透）
    current_depth = getattr(agent, '_clone_depth', 0)

    print(f"[OrchLoop] 启动多轮编排: depth={current_depth} {goal[:60]}", flush=True)

    # 复杂度预判（规则快速扫描，指导超时策略）
    complex_kw = ["系统", "架构", "重构", "批量", "全部", "所有", "多", "集群",
                  "复杂", "完整", "深度", "综合", "全面", "报告", "分析", "研究"]
    complexity = sum(1 for kw in complex_kw if kw in goal)
    dynamic_timeout = 600 if complexity >= 4 else 300  # 复杂任务每分身10分钟
    print(f"[OrchLoop] 复杂度={complexity} 超时={dynamic_timeout}s/分身", flush=True)

    round_num = 0
    all_results = []
    round_logs = []

    while True:
        round_num += 1
        print(f"[OrchLoop] === 第 {round_num} 轮 ===", flush=True)

        # — 1. 分解当前任务 —（注入全数据源上下文）
        subtasks = _decompose_for_round(agent, goal, background, all_results, round_num)
        if not subtasks:
            # 没有可分解的了 → 所有子任务完成或无法继续
            break
        # v5.9: 将分解结果注册到编排器包中（进度追踪/WebUI可见）
        try:
            for st in subtasks:
                result = orch.add_subtask(pkg["id"], {
                    "description": st.get("description", "")[:200],
                    "requirements": st.get("background", "")[:100],
                    "dependencies": st.get("dependencies", []),
                    "status": "pending",
                })
                # 回写 ID 到原始 subtask，后续 dispatch/result 全程走 ID 匹配
                if result.get("success"):
                    st["_id"] = result["id"]
        except Exception:
            pass

        # — 2. 节流：依赖分析 → 先派无依赖的 —
        ready, blocked = _throttle_subtasks(subtasks, all_results)
        if not ready:
            if not blocked:
                break  # 全部完成
            # 全部被阻塞 → 触发 replan（v5.9: 硬超时保护）
            decision = _reflection_with_timeout(
                agent, goal, background, all_results, round_num,
                stage="all_blocked", blocked=blocked, timeout_sec=120)
            if decision.get("action") == "replan":
                background = _enrich_background(background, decision, all_results)
                continue
            else:
                break

        # — 3. 派发 —
        dispatched = []
        for st in ready[:max_parallel]:
            task_desc = st.get("description", "")
            st_bg = st.get("background", "")
            full_task = f"{task_desc}\n\n[背景] {background[:500]}\n[子任务上下文] {st_bg}"
            cid = clone_mgr.dispatch(full_task, context=background[:300],
                                     depth=current_depth + 1, subclone_hint="cascade")
            if cid:
                dispatched.append({"subtask": st, "clone_id": cid})
                print(f"[OrchLoop] 派遣 {cid} → {task_desc[:50]}", flush=True)
            else:
                print(f"[OrchLoop] 派遣失败（分身槽满）: {task_desc[:50]}", flush=True)

        if not dispatched:
            # 无法派发 → 等现有分身完成后再试
            time.sleep(5)
            continue

        # — 4. 等待所有分身份完成 —（动态超时 + 心跳检测）
        round_results = _wait_for_clones(agent, dispatched, timeout_per_clone=dynamic_timeout)
        all_results.extend(round_results)
        for rr in round_results:
            rr["round"] = round_num
        round_logs.append({"round": round_num, "dispatched": len(dispatched),
                           "completed": len(round_results)})

        # v5.9: 实时更新子任务状态（每次轮询完立即回写，ID精确匹配）
        try:
            for st in pkg.get("subtasks", []):
                st_id = st.get("id", "")
                for rr in round_results:
                    rr_id = rr.get("_subtask_id", "")
                    if st_id and rr_id and st_id == rr_id:
                        st["status"] = "done" if rr.get("status") == "ok" else "failed"
                        st["assigned_to"] = rr.get("clone_id", "")
                        break
            with orch._lock:
                orch._save()
        except Exception:
            pass

        # — 5. 全面反思 —（v5.9: 硬超时保护，避免 LLM 慢响应拖死编排）
        decision = _reflection_with_timeout(
            agent, goal, background, all_results, round_num,
            stage="round_complete", timeout_sec=180)

        action = decision.get("action", "report")
        reason = decision.get("reason", "")

        print(f"[OrchLoop] 第{round_num}轮反思: {action} — {reason[:80]}", flush=True)

        if action == "continue":
            # === 中枢预判：扫描部分进度，发现缺失 → 注入补充任务 ===
            try:
                if clone_mgr := getattr(agent, 'clone_manager', None):
                    snap = clone_mgr.scan_hub()
                    # 对运行中的分身，检查产出是否偏少 → 注入补充知识或拆解
                    for p in snap["partials"]:
                        elapsed = time.time() - p.get("started_at", time.time())
                        fcnt = len(p.get("output_files", []))
                        if elapsed > 120 and fcnt == 0:
                            # 跑了2分钟以上还没有产出 → 可能是卡住了，注入简化指令
                            cid = p["clone_id"]
                            clone_mgr.inject_task(cid,
                                extra_task=f"简化任务：分步骤，先完成最小可交付成果",
                                supplement=f"目标:{goal[:200]}\n已完成:\n" +
                                    "\n".join([r.get("task","")[:80] for r in all_results[-5:]]))
                        elif elapsed > 60 and fcnt <= 1:
                            # 有一些产出但不多 → 补充上下文
                            clone_mgr.inject_task(p["clone_id"],
                                supplement=f"补充上下文:\n已收集结果:{len(all_results)}条\n" +
                                    f"当前轮次:{round_num}\n目标:{goal[:200]}")
            except Exception:
                pass
            
            # 继续：用反思结果丰富背景，下一轮
            background = _enrich_background(background, decision, all_results)
            continue

        elif action == "replan":
            # 调整方案：重新分解但保留已完成的结果
            background = _enrich_background(background, decision, all_results)
            continue

        else:  # "report"
            break

    # — 6. 最终汇总 —
    # v5.9: 更新编排器包状态（进度追踪用）
    try:
        if all_results:
            pkg["status"] = "done"
        else:
            pkg["status"] = "failed"
            pkg["error"] = "编排未能分解出可执行子任务（LLM返回非JSON或API不可用）"
        pkg["completed_at"] = time.time()
        # 更新所有子任务状态（ID 精确匹配）
        for st in pkg.get("subtasks", []):
            st_id = st.get("id", "")
            for rr in all_results:
                rr_id = rr.get("_subtask_id", "")
                if st_id and rr_id and st_id == rr_id:
                    st["status"] = "done" if rr.get("status") == "ok" else "failed"
                    st["progress"] = 100
                    break
        with orch._lock:
            orch._save()
        # v5.9: 每次完成后清理旧包
        orch.auto_cleanup(max_keep=10, max_age_hours=2)
    except Exception:
        pass

    final_summary = _final_summary(agent, goal, background, all_results, round_logs)
    
    # v5.9: 清理本轮编排产生的 hub 文件，防止长期堆积
    try:
        if clone_mgr and hasattr(clone_mgr, '_HUB_DIR'):
            import glob as _glob
            for hub_file in _glob.glob(os.path.join(clone_mgr._HUB_DIR, "clone_*")):
                try:
                    os.remove(hub_file)
                except OSError:
                    pass
            print(f"[OrchLoop] Hub 文件已清理", flush=True)
    except Exception:
        pass
    
    _inject_result(agent, {
        "type": "orchestration_complete",
        "goal": goal,
        "rounds": round_num,
        "total_subtasks": len(all_results),
        "round_log": round_logs,
        "summary": final_summary,
        "all_results": all_results,
    })
    return final_summary


# ==================== 辅助函数 ====================

def _decompose_for_round(agent, goal, background, all_results, round_num):
    """用 LLM 分解当前轮需要执行的子任务（注入因果/锚点/记忆/深度上下文）"""
    completed_descs = [r.get("task", "")[:80] for r in all_results[-10:]]
    
    # 注入因果知识
    causal_hint = ""
    try:
        kg = getattr(agent, 'knowledge_graph', None)
        if kg and hasattr(kg, 'causal_triples'):
            triples = kg.causal_triples[-10:]
            if triples:
                lines = ["[因果经验]", "  " + " | ".join(
                    [f"{t.get('condition','')[:30]}→{t.get('result','')[:30]}" for t in triples[:5]])]
                causal_hint = "\n".join(lines)
    except: pass
    
    # 注入锚点约束
    anchor_hint = ""
    try:
        ae = getattr(agent, 'anchor_engine', None)
        if ae:
            matched = ae.match_anchors_for_query(goal, max_results=3)
            if matched:
                anchor_hint = ae.format_anchors_for_prompt(matched)[:400]
    except: pass
    
    # v5.9: 深度感知 — 越深越简单
    current_depth = getattr(agent, '_clone_depth', 0)
    if current_depth > 0:
        depth_guide = (
            f"[当前深度] 第{current_depth}层分身，请拆分为原子级任务（单个命令/单次读写），"
            f"最多3个子任务。每个子任务描述不超过40字，只做一件事。\n"
        )
        max_sub = 3
        example = (
            '[{"description":"用echo创建数据文件","background":"生成示例CSV","dependencies":[]},'
            '{"description":"统计文件行数","background":"wc -l 统计","dependencies":["用echo创建数据文件"]}]'
        )
    else:
        depth_guide = (
            "[当前深度] 主智能体，可拆分为适度复杂任务（可并行），最多5个子任务。\n"
        )
        max_sub = 5
        example = (
            '[{"description":"扫描目录获取文件列表","background":"递归遍历目录","dependencies":[]},'
            '{"description":"统计每个文件行数","background":"对文件列表中的每个文件统计行数","dependencies":["扫描目录获取文件列表"]}]'
        )
    
    # 失败历史注入
    fail_hint = ""
    failed_count = sum(1 for r in all_results if r.get("status") != "ok")
    if failed_count > 0:
        recent_fails = [r.get("task","")[:40] for r in all_results[-5:] if r.get("status") != "ok"]
        if recent_fails:
            fail_hint = f"[失败记录] 以下已失败，不要重复: {', '.join(recent_fails[:3])}\n"
    
    prompt = f"""你是任务分解器。严格只输出 JSON 数组，不要输出任何其他文字，不要解释，不要markdown代码块。
{depth_guide}{fail_hint}
[目标] {goal[:350]}
[背景] {background[:250]}
{causal_hint}
{anchor_hint}
[已完成] {json.dumps(completed_descs, ensure_ascii=False)}

格式（必须完全符合）：
{example}

规则：
- 每个子任务必须能被单次工具调用完成（run_command/write_file/read_file）
- 最多{max_sub}个子任务
- 所有任务已完成才输出 []（谨慎使用，只有100%确定时才输出空数组）
- dependencies 是依赖的任务 description（精确匹配）

只输出 JSON："""

    # v5.9: 重试逻辑 — max_tokens 加大到 2048，减少截断
    max_retries = 3
    for attempt in range(max_retries):
        max_tok = 1536 if current_depth > 0 else 2048  # 深层用更少 token，强制简洁
        try:
            raw = agent.llm.generate(prompt, max_tokens=max_tok)
            # 检测瞬时不可用响应
            if raw and ("[API_BUSY]" in raw or "[API错误]" in raw or "熔断器已断开" in raw or "暂时不可用" in raw):
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 2
                    print(f"[OrchLoop] 分解: API瞬态不可用(尝试{attempt+1})，{wait}s后重试", flush=True)
                    time.sleep(wait)
                    continue
                else:
                    print(f"[OrchLoop] 分解: 重试{max_retries}次仍不可用，返回空", flush=True)
                    return []
            # v5.9: 清理常见 LLM 噪音（markdown代码块、说明文字）
            clean = raw.strip()
            # 去掉 markdown 代码块
            if clean.startswith("```"):
                clean = clean[clean.find("\n"):] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
            # 提取 JSON 数组
            start = clean.find('[')
            end = clean.rfind(']') + 1
            if start >= 0 and end > start:
                parsed = json.loads(clean[start:end])
                if isinstance(parsed, list):
                    if len(parsed) == 0:
                        print(f"[OrchLoop] 分解: LLM 返回空数组，接受", flush=True)
                    return parsed
            # JSON 解析失败也重试
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                print(f"[OrchLoop] 分解: 非JSON响应(尝试{attempt+1}) len={len(raw)}，{wait}s后重试", flush=True)
                continue
            print(f"[OrchLoop] 分解: 重试{max_retries}次仍非JSON: {raw[:200]}", flush=True)
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                print(f"[OrchLoop] 分解: JSON异常 {e}，{wait}s后重试({attempt+1}/{max_retries})", flush=True)
                time.sleep(wait)
                continue
            print(f"[OrchLoop] 分解: JSON异常重试{max_retries}次仍失败: {e}", flush=True)
        except Exception as e:
            print(f"[OrchLoop] 分解失败: {e}", flush=True)
            return []
    
    # v5.9: LLM 分解耗尽重试仍失败 → 规则兜底解析
    # 支持: 1) 2) 3); 任务1——任务2——任务3; 1.收集 2.整理 3.汇总
    import re as _re
    # 尝试1: 编号格式
    numbered = _re.findall(r'(?:^|[;；\n])\s*(\d+)[)）\.、]\s*(.+?)(?=[;；]\s*\d+[)）\.、]|\n\s*\d+[)）\.、]|\Z)', goal, _re.DOTALL)
    if len(numbered) >= 2:
        descs = [desc.strip()[:200] for _, desc in numbered]
        print(f"[OrchLoop] 分解兜底: 编号解析 {len(descs)} 项", flush=True)
        return [{"description": d, "background": "", "dependencies": []} for d in descs]
    # 尝试2: 中文分隔符 —— / ：/ ；
    dash_parts = _re.split(r'[——：:；;]', goal) if any(c in goal for c in ('——','：',':')) else []
    dash_parts = [p.strip() for p in dash_parts if len(p.strip()) > 6]
    if len(dash_parts) >= 2:
        print(f"[OrchLoop] 分解兜底: 分隔符解析 {len(dash_parts)} 项", flush=True)
        return [{"description": p[:200], "background": "", "dependencies": []} for p in dash_parts]
    
    return []


def _throttle_subtasks(subtasks, all_results):
    """节流：分析依赖，分出 ready（无依赖或依赖已完成）和 blocked"""
    completed_ids = {r.get("subtask_id", "") for r in all_results if r.get("status") == "ok"}
    ready = []
    blocked = []
    for i, st in enumerate(subtasks):
        deps = st.get("dependencies", [])
        if all(d in completed_ids for d in deps):
            st["_idx"] = i
            ready.append(st)
        else:
            blocked.append(st)
    return ready, blocked


def _wait_for_clones(agent, dispatched, timeout_per_clone=300):
    """轮询等待所有分身份完成，收集结果（含心跳检测/死锁发现）"""
    results = []
    deadline = time.time() + timeout_per_clone * len(dispatched)
    clone_mgr = getattr(agent, 'clone_manager', None)
    last_heartbeat = {d["clone_id"]: time.time() for d in dispatched}
    heartbeat_timeout = min(120, timeout_per_clone // 3)  # 2分钟无心跳视为僵死

    pending_ids = {d["clone_id"] for d in dispatched}
    while pending_ids and time.time() < deadline:
        time.sleep(5)
        # 中枢心跳检测：扫 partial.json 确认分身份存活
        try:
            if clone_mgr and hasattr(clone_mgr, 'scan_hub'):
                snapshot = clone_mgr.scan_hub()
                for p in snapshot.get("partials", []):
                    pid = p.get("clone_id", "")
                    if pid in pending_ids:
                        last_heartbeat[pid] = time.time()
        except: pass
        
        # v5.9: 死锁检测前先检查是否已完成（done.json 已存在）
        # 级联模式下克隆同步跑编排可能长达数分钟不更新 partial，
        # 但 finished_at 后已写入 done.json，不应被误杀
        now = time.time()
        dead_ids = [pid for pid in pending_ids if now - last_heartbeat.get(pid, 0) > heartbeat_timeout]
        for pid in list(dead_ids):
            hub_dir = getattr(clone_mgr, '_HUB_DIR', '')
            done_path = os.path.join(hub_dir, f"{pid}.done.json") if hub_dir else ""
            if done_path and os.path.exists(done_path):
                # 克隆实际已完成，跳过误杀 → 下轮 collect() 会回收
                print(f"[OrchLoop] 分身 {pid} 心跳超时但 done.json 已存在，跳过误杀", flush=True)
                dead_ids.remove(pid)
        for pid in dead_ids:
            print(f"[OrchLoop] 分身 {pid} 心跳超时 ({heartbeat_timeout}s)，强制终止", flush=True)
            pending_ids.discard(pid)
            for d in dispatched:
                if d["clone_id"] == pid:
                    results.append({
                        "subtask": d["subtask"], "clone_id": pid,
                        "_subtask_id": d["subtask"].get("_id", ""),
                        "task": d["subtask"].get("description", ""),
                        "result": f"分身僵死(心跳超时{heartbeat_timeout}s)", "status": "timeout",
                    })
                    break
        
        if clone_mgr:
            completed = clone_mgr.collect()
            for c in completed:
                cid = c.get("clone_id", "")
                if cid in pending_ids:
                    pending_ids.discard(cid)
                    for d in dispatched:
                        if d["clone_id"] == cid:
                            results.append({
                                "subtask": d["subtask"],
                                "_subtask_id": d["subtask"].get("_id", ""),
                                "clone_id": cid,
                                "task": d["subtask"].get("description", ""),
                                "result": c.get("result", ""),
                                "status": "ok" if c.get("result") else "error",
                            })
                            break

    # 超时的强制终止
    for d in dispatched:
        if d["clone_id"] in pending_ids:
            results.append({
                "subtask": d["subtask"],
                "_subtask_id": d["subtask"].get("_id", ""),
                "clone_id": d["clone_id"],
                "task": d["subtask"].get("description", ""),
                "result": "超时未完成",
                "status": "timeout",
            })

    return results


def _reflection_with_timeout(agent, goal, background, all_results, round_num,
                              stage="round_complete", blocked=None, timeout_sec=180):
    """v5.9: 反思包装，加硬超时保护防止 LLM 慢响应拖死编排"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(
            _comprehensive_reflection,
            agent, goal, background, all_results, round_num,
            stage=stage, blocked=blocked)
        try:
            return fut.result(timeout=timeout_sec)
        except FutureTimeoutError:
            print(f"[OrchLoop] 反思超时({timeout_sec}s)，默认继续", flush=True)
            return {"action": "continue", "reason": f"反思超时{timeout_sec}s默认继续",
                    "progress_pct": 30}
        except Exception as e:
            print(f"[OrchLoop] 反思异常: {e}", flush=True)
            return {"action": "continue", "reason": f"反思异常默认继续: {e}",
                    "progress_pct": 30}


def _comprehensive_reflection(agent, goal, background, all_results, round_num,
                               stage="round_complete", blocked=None):
    """
    全面反思 — 使用全部数据源决定：continue / replan / report

    数据源：记忆、知识图谱因果、锚点、执行轨迹、联网搜索
    """
    # 构建反思上下文
    ctx_parts = []

    # 0. 中枢快照 — 实时扫描所有分身的 partial 进度和完成结果
    hub_ctx = ""
    try:
        if clone_mgr := getattr(agent, 'clone_manager', None):
            snapshot = clone_mgr.scan_hub()
            if snapshot["partials"]:
                hub_lines = ["=== 中枢实时进度 ==="]
                for p in snapshot["partials"]:
                    elapsed = time.time() - p.get("started_at", time.time())
                    fcnt = len(p.get("output_files", []))
                    hub_lines.append(
                        f"  {p['clone_id']}(深度{p.get('depth','?')}) [{elapsed:.0f}s]: "
                        f"{p.get('task','')[:50]} | 产出{fcnt}个文件 | 状态={p.get('status','?')}")
                hub_ctx = "\n".join(hub_lines)
            if snapshot["done"]:
                if not hub_ctx:
                    hub_ctx = "=== 中枢完成 ==="
                else:
                    hub_ctx += "\n---\n=== 中枢已完成 ==="
                for d in snapshot["done"][:5]:
                    hub_ctx += f"\n  ✓ {d.get('clone_id','?')}: {str(d.get('result',''))[:100]}"
        if hub_ctx:
            ctx_parts.append(hub_ctx)
    except Exception:
        pass

    # 1. 执行轨迹
    trace_summary = []
    for r in all_results[-20:]:
        trace_summary.append(
            f"[{r.get('status','?')}] R{r.get('round','?')} {r.get('task','')[:100]} → "
            f"{str(r.get('result',''))[:150]}")
    ctx_parts.append("=== 执行轨迹 ===\n" + "\n".join(trace_summary))

    # 2. 因果三元组
    try:
        kg = getattr(agent, 'knowledge_graph', None)
        if kg and hasattr(kg, 'causal_triples'):
            triples = kg.causal_triples[-15:]
            causal_lines = [f"  {t.get('condition','')[:40]} → {t.get('result','')[:40]}"
                           for t in triples]
            ctx_parts.append("=== 因果知识 ===\n" + "\n".join(causal_lines))
    except:
        pass

    # 3. 锚点
    try:
        anchors = getattr(agent, 'anchor_engine', None)
        if anchors:
            matched = anchors.match_anchors_for_query(goal, max_results=5)
            if matched:
                ctx_parts.append("=== 相关锚点 ===\n" +
                                anchors.format_anchors_for_prompt(matched)[:500])
    except:
        pass

    # 3.5 直觉状态 — 图谱实体关联度注入反思
    try:
        if hasattr(agent, 'intuition_check') and hasattr(agent, 'knowledge_graph'):
            intuition_check = agent.intuition_check
            kg = agent.knowledge_graph
            if intuition_check.log:
                untrusted = [l for l in intuition_check.log[-10:] if not l.get('trusted', True)]
                if untrusted:
                    lines = ["=== 直觉预警（低置信度实体关联）==="]
                    for l in untrusted[:4]:
                        lines.append(f"  {l.get('entity1','?')} ↔ {l.get('entity2','?')} 置信度{l.get('confidence',0):.0%}")
                    ctx_parts.append("\n".join(lines))
    except:
        pass

    # 3.6 目标复杂度提示 — 极简规则分类，辅助续/停决策
    try:
        goal_lower = goal.lower()
        complex_markers = ["系统", "架构", "重构", "多", "全部", "所有", "批量", "集群",
                          "多个", "多轮", "复杂", "完整", "整套", "综合", "全面", "深度"]
        simple_markers = ["是什么", "怎么", "解释", "翻译", "定义", "一句话"]
        c_score = sum(2 for kw in complex_markers if kw in goal_lower)
        s_score = sum(2 for kw in simple_markers if kw in goal_lower)
        if c_score >= 4:
            ctx_parts.append("=== 目标评估 ===\n  倾向: 复杂任务，建议分步推进，最终合并汇报")
        elif s_score > c_score and s_score >= 2:
            ctx_parts.append("=== 目标评估 ===\n  倾向: 简单问答，建议直接总结回复，不必展开多轮")
        elif len(all_results) > 15:
            ctx_parts.append("=== 目标评估 ===\n  累计已达{0}步，建议尽快汇报".format(len(all_results)))
    except:
        pass

    # 4. 记忆
    try:
        mem = getattr(agent, 'memory', None)
        if mem:
            wm = getattr(mem, 'working_memory', None) or []
            recent = [str(m.get('text', m.get('content', '')))[:120]
                     for m in list(wm)[-5:] if isinstance(m, dict)]
            if recent:
                ctx_parts.append("=== 最近记忆 ===\n" + "\n".join(recent))
    except:
        pass

    # 5. 联网搜索（仅复杂决策时）
    web_context = ""
    try:
        # 仅在需要外部信息时搜索
        if round_num >= 2 and len(all_results) > 5:
            search_query = f"{goal[:60]} 进度评估 是否可继续"
            from extensions.web_search import search as _web_search
            results = _web_search(search_query, max_results=3)
            if results:
                web_context = "[联网信息]\n" + "\n".join(
                    [f"  {r.get('title','')[:60]}: {r.get('snippet','')[:150]}" for r in results])
    except:
        pass

    if web_context:
        ctx_parts.append(web_context)

    # 构建反思 prompt
    reflection_prompt = f"""你是任务编排的"全面反思官"。基于以下全部数据源，判断任务编排是否应继续。

[任务目标] {goal[:300]}
[背景] {background[:300]}
[当前轮次] 第{round_num}轮
[阶段] {stage}
{chr(10).join(ctx_parts)}

请用 JSON 回答：
{{"action": "continue|replan|report",
 "reason": "决策理由（50字内）",
 "progress_pct": 0-100,
 "remaining_work": "剩余工作描述",
 "risks": "风险点",
 "next_focus": "下轮重点（仅 continue/replan 时）",
 "user_summary": "如需汇报用户，本条为汇报内容（仅 report 时）"}}

决策规则：
- 有明显进展且路径清晰 → continue
- 遇到障碍但可调整方案 → replan（附调整建议）
- 多次失败、信息严重不足、不可能完成 → report"""

    # v5.9: 重试逻辑 — 处理 API_BUSY/API错误/熔断等瞬时失败
    for attempt in range(3):
        try:
            raw = agent.llm.generate(reflection_prompt, max_tokens=800)
            if raw and ("[API_BUSY]" in raw or "[API错误]" in raw or "熔断器已断开" in raw or "暂时不可用" in raw):
                if attempt < 2:
                    time.sleep((attempt + 1) * 3)
                    continue
                break
            start = raw.find('{')
            end = raw.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            if attempt < 2:
                time.sleep((attempt + 1) * 3)
                continue
        except Exception:
            if attempt < 2:
                time.sleep((attempt + 1) * 3)
                continue
            break

    # 默认：超过 10 轮或进展太少 → report
    if round_num >= 10:
        return {"action": "report", "reason": "超过10轮，强制汇报",
                "progress_pct": 50, "user_summary": "任务经过多轮编排仍未完成，建议人工介入。"}
    return {"action": "continue", "reason": "默认继续",
            "progress_pct": 30}


def _enrich_background(background, decision, all_results):
    """用反思结果丰富背景，带入下一轮"""
    parts = [background]
    if decision.get("next_focus"):
        parts.append(f"\n[下轮重点] {decision['next_focus']}")
    if decision.get("risks"):
        parts.append(f"\n[风险提示] {decision['risks']}")
    if decision.get("remaining_work"):
        parts.append(f"\n[剩余工作] {decision['remaining_work']}")
    # 最近结果摘要
    recent = all_results[-5:]
    if recent:
        summaries = [f"  {r.get('task','')[:60]}: {str(r.get('result',''))[:100]}" for r in recent]
        parts.append(f"\n[最近完成]\n" + "\n".join(summaries))
    return "\n".join(parts)


def _final_summary(agent, goal, background, all_results, round_logs):
    """最终汇总 — LLM 生成给用户的自然语言报告"""
    prompt = f"""请为以下多轮编排任务生成最终汇报。

[任务目标] {goal[:300]}
[总轮次] {len(round_logs)}
[总子任务] {len(all_results)}
[完成] {sum(1 for r in all_results if r.get('status')=='ok')}
[失败/超时] {sum(1 for r in all_results if r.get('status')!='ok')}

[各轮概况]
{json.dumps(round_logs, ensure_ascii=False)}

[结果采样]
{json.dumps([{'task':r.get('task','')[:80], 'result':str(r.get('result',''))[:120]} for r in all_results[-10:]], ensure_ascii=False)}

请生成 200 字内的简洁汇报，包括：完成了什么、还有什么没完成、建议。"""

    # v5.9: 重试逻辑 — 处理 API_BUSY/API错误/熔断
    for attempt in range(3):
        try:
            raw = agent.llm.generate(prompt, max_tokens=400)
            if raw and ("[API_BUSY]" in raw or "[API错误]" in raw or "熔断器已断开" in raw or "暂时不可用" in raw):
                if attempt < 2:
                    time.sleep(2)
                    continue
                # 最后一次重试也失败，返回 safe fallback
                break
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
    ok = sum(1 for r in all_results if r.get('status') == 'ok')
    return f"多轮编排完成。{len(round_logs)}轮，{ok}/{len(all_results)}子任务完成。"


def _inject_result(agent, result):
    """将编排结果注入主智能体的主动通知队列"""
    q = getattr(agent, '_proactive_queue', None)
    if q is not None:
        q.append({
            "time": time.time(),
            "content": result.get("summary", str(result)[:500]),
            "type": "orchestration_result",
            "full_result": result,
        })
