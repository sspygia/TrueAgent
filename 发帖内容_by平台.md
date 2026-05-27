# V2EX 分享创造 (https://www.v2ex.com/go/create)

## 标题
TrueAgent - 一个会自我修改、能无限裂变分身的自主 AI 智能体（单文件 11600 行，开源）

## 正文

github: https://github.com/sspygia/TrueAgent

我不会写代码。过去三个月，我和 AI 通过对话造了一个住在电脑里的自主智能体——TrueAgent。它不是 ChatGPT 套壳，是从零设计的一套系统。分享给大家看看。

**它和市面 Agent 的区别：**

1. **全真递归分身**：市面上大部分多 Agent 系统的"分身"只是转发器。TrueAgent 的分身是 1:1 复刻主架构，共享统一知识库/记忆/工具，能递归向下裂变新分身。五层标准配置 = 3125 个实例，硬件负载自动限流。

2. **七层记忆飞轮**：工作记忆→锚点→反思→决策→因果→日记→画像，每层互相喂料。ChatGPT 每次对话清零，TrueAgent 越用越懂你。因果链带衰减函数（艾宾浩斯曲线 + 使用频率修正，30天半衰期），过时经验自然淘汰。

3. **后台意识流**：不死等用户消息。每 3 分钟反思、每 30 分钟认知检查、每 6 小时全盘审计、每 3 天深度体检。

4. **自我修改**：读自己源码→发现 bug→生成补丁→推送审批→原子写入→失败回滚。全程有快照。

5. **代码前置引擎**：不做单次补全，而是把"理解需求→任务拆解→分段生成→进度管理→自愈修复"做成闭环。截断检测不看字数，看功能完整性（def/class/括号闭合）。卡死自动跳过，无进展 3 轮触发评估。

单文件 ~11600 行，DeepSeek API（约 0.1 元/千次调用），Windows 10+。

早期项目，诚恳求建议——尤其是分身架构和记忆系统方面的反馈。欢迎 star / issue。

---

# Reddit r/LocalLLaMA (reddit.com/r/LocalLLaMA)

## Title
[Project] TrueAgent - An autonomous AI agent with 7-layer memory that learns from mistakes and spawns recursive clones

## Body

Sharing a project I built over 3 months through AI-assisted conversations. I don't code - the AI wrote it, I guided the design.

**What it is:** An autonomous agent that lives on your PC. Not a ChatGPT wrapper.

**What sets it apart from most Agent projects:**

- **True recursive clones** (not pseudo-clones): 1:1 architecture replication, shared knowledge base, can recursively spawn. 5-layer config = 3,125 max instances with hardware throttling.
- **7-layer memory flywheel:** Working memory → anchors → reflections → decisions → causal chains → diaries → profiles. Each layer feeds the others.
- **Self-modifying:** Reads own source, finds bugs, proposes patches, atomic writes with rollback.
- **Background consciousness:** Reflects every 3min, audits every 6h, deep health report every 3 days.
- **Code engine:** Not just autocomplete - understanding → task decomposition → segmented generation → progress tracking → self-healing. Detects code completeness by structure (def/class/parentheses), not just token count.

**Tech:** Single Python file (~11,600 lines), DeepSeek API (~$0.10/1K calls), Windows 10+.

GitHub: https://github.com/sspygia/TrueAgent

Would love honest architectural feedback, especially on the clone system and memory flywheel. Thanks!

---

# Hacker News Show HN (需先养号 1-2 周攒 karma)

## Title
Show HN: TrueAgent — A Self-Modifying AI Agent with Recursive Clones (Single File, 11.6K Lines)

## Body

Built over 3 months through AI-assisted conversations. I can't code — the AI wrote it, I guided the design.

TrueAgent lives on your PC. It has background consciousness, 7 layers of persistent memory, and true recursive clones (not the pseudo-clones most projects use).

Key design choices:

**True recursive clones:** Most multi-agent systems create function nodes. TrueAgent clones are 1:1 architecture replicas sharing unified knowledge. They can recursively spawn. Standard 5-layer config = 3,125 instances with hardware throttling.

**Memory that decays correctly:** I implemented Ebbinghaus forgetting curve with a twist — usage frequency extends half-life. A causal rule verified 10 times (e.g., "syntax error → fix → compile") barely decays. An unused rule from 3 months ago naturally fades. This means the system's knowledge stays current without manual pruning.

**Code generation as a pipeline:** Not single-shot completion. It detects code completeness by structure (def/class/parentheses balance), tracks progress with checkpoints, auto-heals on failure, and skips stuck subtasks after 4 attempts.

**Self-patching with safety:** Reads its own source, proposes fixes, atomic writes with rollback on syntax failure. Full backups before any modification.

Single file, 11,600 lines (~80% architecture/design logic, not LLM-generated boilerplate). DeepSeek API. Windows 10+.

Code: https://github.com/sspygia/TrueAgent

Early project. Would love feedback on the clone architecture and memory system design.
