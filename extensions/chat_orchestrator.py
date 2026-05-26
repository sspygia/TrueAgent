# -*- coding: utf-8 -*-
"""
ChatOrchestrator — 群聊/私聊发言管理器
基于黑板系统，增加：
  - 发言权管理（安静者优先）
  - @ 机制（@agent_id 直接对话）
  - 防刷屏（最小发言间隔 + 连续发言上限）
  - 公共/私信路由

使用方法:
  orchestrator = ChatOrchestrator()
  if orchestrator.check_can_speak("agent_main")[0]:
      orchestrator.record_message("agent_main", "__all__", "大家好")
"""
import json, os, time, re

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_EXT_DIR)  # v5.9/
CHAT_FILE = os.path.join(_BASE_DIR, "data", "shared_blackboard", "chat_state.json")

# 默认配置
DEFAULT_CONFIG = {
    "min_interval": 10,       # 同一智能体最小发言间隔（秒）
    "max_consecutive": 10,    # 连续发言上限
    "penalty_rate": 2,        # 每次发言增加惩罚分
    "recent_window": 10,      # "最近快速发言"判定窗口（秒）
    "recent_penalty": 5,      # 快速发言额外惩罚分
    "cooldown_period": 30,    # 超过上限后的冷却期（秒）
    "max_queue_per_agent": 5, # 每个智能体待发言队列上限
}


def _load_state():
    """加载持久化发言状态"""
    default = {"speak_counts": {}, "last_speak_time": {}, "penalty_score": {},
               "pending_pings": [], "config": dict(DEFAULT_CONFIG)}
    try:
        if os.path.exists(CHAT_FILE):
            with open(CHAT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 确保所有键存在，防止手写/初始化丢失字段
            for k, v in default.items():
                data.setdefault(k, v)
            return data
    except:
        pass
    return dict(default)


def _save_state(state):
    """持久化发言状态"""
    os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
    tmp = CHAT_FILE + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHAT_FILE)


class ChatOrchestrator:
    """群聊/私聊发言管理器"""

    def __init__(self):
        self._state = _load_state()
        # 确保配置完整性
        for k, v in DEFAULT_CONFIG.items():
            if k not in self._state.get("config", {}):
                self._state.setdefault("config", {})[k] = v

    # ==================== 发言统计 ====================

    def record_message(self, from_id, to_id, content=""):
        """记录一次发言 → 更新计数 + 持久化"""
        now = time.time()
        sc = self._state["speak_counts"]
        lst = self._state["last_speak_time"]
        ps = self._state["penalty_score"]
        cfg = self._state["config"]

        sc[from_id] = sc.get(from_id, 0) + 1
        lst[from_id] = now

        # 惩罚分 = 总发言数 * penalty_rate + 窗口内快速发言 * recent_penalty
        recent = sum(1 for t in lst.values() if now - t < cfg["recent_window"])
        ps[from_id] = sc[from_id] * cfg["penalty_rate"] + recent * cfg["recent_penalty"]

        self._save()
        return True

    # ==================== 发言权限 ====================

    def check_can_speak(self, agent_id):
        """检查智能体是否允许发言
        返回 (True/False, 原因)
        """
        now = time.time()
        cfg = self._state["config"]
        lst = self._state["last_speak_time"]
        sc = self._state["speak_counts"]
        ps = self._state["penalty_score"]

        last = lst.get(agent_id, 0)
        elapsed = now - last

        # 1. 最小发言间隔
        if elapsed < cfg["min_interval"]:
            wait = int(cfg["min_interval"] - elapsed)
            return False, f"发言间隔不足，请等待 {wait} 秒"

        # 2. 连续发言上限
        count = sc.get(agent_id, 0)
        if count >= cfg["max_consecutive"]:
            if elapsed < cfg["cooldown_period"]:
                wait = int(cfg["cooldown_period"] - elapsed)
                return False, f"连续发言已达上限 {cfg['max_consecutive']} 次，冷却 {wait} 秒"
            else:
                # 冷却期结束，重置计数
                sc[agent_id] = 0
                ps[agent_id] = 0
                self._save()

        return True, ""

    def get_speak_priority(self):
        """获取发言优先级排序（安静者优先，惩罚分低者优先）"""
        ps = self._state["penalty_score"]
        sorted_agents = sorted(ps.items(), key=lambda x: x[1])
        return [a[0] for a in sorted_agents]

    def get_speak_summary(self, agent_id=None):
        """获取发言统计数据"""
        result = {
            "speak_counts": dict(self._state["speak_counts"]),
            "last_speak_times": {k: v for k, v in self._state["last_speak_time"].items()},
            "penalty_scores": dict(self._state["penalty_score"]),
            "priority": self.get_speak_priority(),
            "config": dict(self._state["config"]),
        }
        if agent_id:
            result["my"] = {
                "speak_count": self._state["speak_counts"].get(agent_id, 0),
                "last_speak": self._state["last_speak_time"].get(agent_id, 0),
                "penalty": self._state["penalty_score"].get(agent_id, 0),
                "can_speak": self.check_can_speak(agent_id),
            }
        return result

    # ==================== @ 提及 ====================

    def parse_mentions(self, content):
        """解析 @agent_id 或 @alias，返回被提及的 agent_id 列表"""
        if not content or "@" not in content:
            return []

        # 读取所有智能体
        reg_path = os.path.join(_BASE_DIR, "data", "shared_blackboard", "registry.json")
        agents = []
        try:
            with open(reg_path, 'r', encoding='utf-8') as f:
                reg = json.load(f)
                agents = reg.get("agents", [])
        except:
            pass

        mentioned = []
        for agent in agents:
            aid = agent.get("id", "")
            alias = agent.get("alias", "")
            if f"@{aid}" in content:
                mentioned.append(aid)
            if alias and f"@{alias}" in content:
                mentioned.append(aid)

        # 去重
        return list(set(mentioned))

    # ==================== 消息路由 ====================

    def route_message(self, from_id, content):
        """分析消息，决定发送目标
        返回: (target, msg_type)
          - ("__public__", "public") → 黑板群聊
          - ("agent_xxx", "private") → 私聊
          - ("__all__", "broadcast") → 全体广播（@多人）
        """
        mentions = self.parse_mentions(content)
        if len(mentions) == 1:
            return (mentions[0], "private")
        elif len(mentions) > 1:
            return ("__all__", "broadcast")
        else:
            return ("__public__", "public")

    # ==================== 发言队列 ====================

    def get_pending_pings(self, agent_id=None):
        """获取未读 @ 提醒"""
        pings = self._state.get("pending_pings", [])
        if agent_id:
            pings = [p for p in pings if p.get("to") == agent_id]
        return pings

    def add_ping(self, from_id, to_id, content):
        """添加 @ 提醒"""
        self._state.setdefault("pending_pings", [])
        self._state["pending_pings"].append({
            "from": from_id,
            "to": to_id,
            "content": content[:100],
            "time": time.time(),
        })
        # 控制队列长度
        cfg = self._state["config"]
        max_q = cfg["max_queue_per_agent"]
        pings = [p for p in self._state["pending_pings"] if p["to"] == to_id]
        if len(pings) > max_q:
            self._state["pending_pings"] = [
                p for p in self._state["pending_pings"] if p["to"] != to_id
            ][-max_q:]
        self._save()

    def clear_pings(self, agent_id):
        """清除某智能体的未读 @ 提醒"""
        self._state["pending_pings"] = [
            p for p in self._state.get("pending_pings", [])
            if p.get("to") != agent_id
        ]
        self._save()

    # ==================== 配置 ====================

    def update_config(self, **kwargs):
        """动态更新配置"""
        for k, v in kwargs.items():
            if k in DEFAULT_CONFIG:
                self._state["config"][k] = v
        self._save()
        return dict(self._state["config"])

    # ==================== 持久化 ====================

    def _save(self):
        _save_state(self._state)

    def reload(self):
        """从磁盘重新加载状态"""
        self._state = _load_state()
