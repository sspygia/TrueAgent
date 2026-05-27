# Reddit 推广帖 — 两篇，不同板块不同风格

发帖方式：你复制粘贴，不要我用浏览器自动发（Reddit反自动化极严）

---

## 第一篇：r/LocalLLaMA（技术向，适配掘金那篇）

板块：reddit.com/r/LocalLLaMA — 本地LLM/Agent开发者聚集地

### 标题
[Project] TrueAgent — 11.6K-line autonomous agent with 7-layer memory flywheel, recursive clones, and a code engine that actually plans before writing

### 正文

I spent 3 months building this with an AI through conversation. I don't code — the AI wrote it, I designed the architecture.

Repo: https://github.com/sspygia/TrueAgent

This isn't a ChatGPT wrapper. It's a from-scratch autonomous agent that lives on your PC. What I think makes it worth your attention:

**1. The Code Engine is Not Just Autocomplete**

Most AI coding tools (Cursor, Copilot) do single-shot completion. TrueAgent's `CodeContinuationManager` is a full pipeline:

- Detects code completeness by **structure**, not token count (checks for def/class/parentheses balance)
- Breaks complex tasks into subtasks using keyword templates (no LLM call for decomposition — fast and deterministic)
- Segmented generation with automatic dedup (catches LLM repeating itself)
- Stuck detection: 3 rounds no progress → meta-evaluation; 4 rounds same subtask → force skip
- Self-healing: runs code, catches errors, asks LLM to analyze + search for fix + rewrite (3 retries max)

This is closer to "AI software engineer" than "AI autocomplete".

**2. 7-Layer Memory with Real Forgetting**

Not vector DB + "remember everything." Each memory layer feeds the next, with a decay function:

```python
decay = max(0.3, 1.0 / (1 + age_days / (30 + count * 10)))
```

Ebbinghaus curve + usage frequency correction. A causal rule verified 10 times (e.g. "syntax error → fix → compiles") basically never decays. An unused rule from 3 months ago naturally fades. This is **experience lifecycle management**, not a static rule base.

**3. True Recursive Clones (Not Pseudo-Clones)**

Most multi-agent systems create function nodes. TrueAgent clones are 1:1 architecture replicas with shared knowledge/memory/tools. They can recursively spawn. 5-layer config = 3,125 max instances, with hardware load throttling.

Spawning thresholds are deliberate — heavy keywords (crawl, research, deploy) trigger clones solo; light keywords need ≥3 concurrent matches before spawning. Prevents "check the weather" from launching a clone.

**4. Counterfactual Reasoning in Prompts**

One line in the planning prompt that has outsized impact:

> "If I've misunderstood the user's intent, what might they actually want? Think about this first, then output the plan."

20 words. Forces the LLM to question its first interpretation before generating. ROI on this single line is absurd.

**5. Conscious Engineering Trade-offs**

The clone messaging system deliberately has no file locks. Why? Adding locks means cross-process coordination → deadlock risk. And clone messages are auxiliary — losing one doesn't affect core tasks. "Eventual consistency over strong consistency" applied at the right granularity.

**Stack:** Single Python file (~11,600 lines), DeepSeek API (~$0.10/1K calls), Windows 10+.

**Looking for feedback on:**
- Is the clone architecture overkill or underbaked?
- Does the memory decay formula make sense, or am I missing edge cases?
- What would you add to the code engine pipeline?

Repo: https://github.com/sspygia/TrueAgent

---

## 第二篇：r/artificial 或 r/selfhosted（叙事向，适配知乎那篇）

板块选项：
- reddit.com/r/artificial — 780K成员，AI讨论
- reddit.com/r/selfhosted — 550K成员，自托管爱好者

### 标题
I can't code. I spent 3 months teaching an AI to "remember" — here's what I learned about memory, time, and what makes something intelligent

### 正文

I'm not a programmer. Three months ago, I got frustrated that ChatGPT resets every session. Every conversation is a blank slate. It never learns who I am.

So I decided to build something different: an AI agent that remembers. Not "stores chat logs" — remembers like a person. Some things fade, some things stick, some things change you.

I talked to an AI for 3 months. It wrote 11,600 lines of Python. I designed the architecture. The result is TrueAgent.

Here's what I learned about designing memory for AI:

**Memory isn't storage — it's metabolism.**

I built 7 layers that feed each other:
Working memory → anchors → reflections → decisions → causal chains → diaries → profiles

A fact enters working memory → gets distilled into an anchor → triggers a reflection → influences future decisions → gets validated repeatedly → enters the causal chain → reviewed in the diary → becomes part of understanding the user.

**Forgetting is a feature, not a bug.**

Remembering everything means remembering nothing — no priorities, no decay, old info drowning new. So I implemented a decay formula:

```
decay = max(0.3, 1.0 / (1 + age_days / (30 + count * 10)))
```

Standard Ebbinghaus curve, but with a twist — `count` is usage frequency. A lesson verified 10 times barely decays. An unused rule from 3 months ago quietly fades. The system stays current without manual pruning.

**Time is the fourth dimension.**

Every subsystem carries timestamps — not just "when," but "in what order, at what rate, with what trend." The knowledge graph can answer "what was the relationship between A and B before 2023?" The system sees its own CPU/memory trends, not just snapshots. Its diary entries form a continuous story, not isolated journal entries.

**How does a non-coder build 11.6K lines?**

Architecture isn't code. I don't need to know `def __init__(self)`. I need to know: "on startup, check for unfinished conversations and restore the last 10." The AI translates that into Python.

The hard part isn't the code. The hard part is thinking clearly enough about what the system should do, what can go wrong, and what the fallback is. Every instruction I gave had run through my head at least 3 times before I typed it.

This is a new creative paradigm: idea → conversation → code → validate → iterate. No IDE, no compiler. Just a text input and the will to think things through.

**It's early.** Memory is empty, knowledge graph is skeletal. But it proves something: an AI can have real memory. It can learn from that memory. And it can grow across time.

And you don't need to know how to code to build it.

GitHub: https://github.com/sspygia/TrueAgent

Would love to hear from anyone who's thought about memory architectures for AI, or anyone building in the self-hosted agent space.
