# TrueAgent v5.9

**不是聊天机器人。是一个有记忆、会反思、能自我修改的自主智能体。**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-green)](https://www.python.org/)
[![Lines](https://img.shields.io/badge/core-11%2C600_lines-purple)](TrueAgent_Hyper_v4.0.py)
[![Gitee](https://img.shields.io/badge/Gitee-镜像-red)](https://gitee.com/sspygia/TrueAgent)

> 🦞 AI 自主智能体 | 七层记忆 | 分身份身 | 自我补丁 | PC 操控 | 知识图谱 | 越用越聪明

---

## 它是什么

TrueAgent 住在你的电脑里。它不只是回答问题——它有自己的后台意识流（每 3 分钟反思、每 30 分钟认知检查、每 6 小时全盘审计），能派分身并行执行任务，能读自己的源码发现 bug 并生成补丁请求你审批。

和 ChatGPT 的区别：ChatGPT 每次对话都是白纸。TrueAgent 的每一次交互都在积累——记忆、因果、锚点、反思、日记、画像——七层数据互相喂料，越用越懂你。

## What is TrueAgent (English)

TrueAgent lives on your computer. It's not just a Q&A bot — it has its own background consciousness loop (reflects every 3min, self-checks every 30min, full audit every 6h). It spawns clones for parallel task execution, reads its own source code to find bugs, and submits self-patches for your approval.

Unlike ChatGPT, which starts from a blank slate every session, TrueAgent accumulates everything — memory, causal chains, anchors, reflections, diaries, profiles — seven layers of data feeding each other. The longer you use it, the smarter it gets.

## 核心能力 / Core Capabilities

| 系统 System | 做什么 What |
|-------------|-------------|
| **七层记忆** 7-Layer Memory | 记忆→锚点→反思→决策→因果链→日记→画像，每层互相贯通 |
| **分身份身** Clone System | 多 Key 并行，独立 LLM 进程，最大 6 个分身同时跑 |
| **群策讨论** Swarm Debate | 分身间实时互发消息，循环辩论，自动总结退出 |
| **自我补丁** Self-Patching | 审计自己的代码→发现 bug→生成补丁→推送审批→原子写入→语法验证→失败回滚 |
| **PC 操控** PC Control | 窗口管理、鼠标键盘、剪贴板、进程管理、截图 OCR |
| **知识图谱** Knowledge Graph | 284 节点 / 239 边 / 1650 因果链，三元组自动沉淀 |
| **WebUI** | FastAPI + 浅色主题，聊天面板 + 审批卡片 + 终端面板 |

## 为什么与众不同 / Why This Matters

市场上大多数"AI 助手"项目本质上是 **ChatGPT 套壳**——用好看的 UI 包裹 API 调用。TrueAgent 从根本设计上不同：

- **自主意识流**：不是"等用户发消息才工作"。后台持续反思、认知检查、系统审计
- **长期记忆**：不是每次对话清零。七层记忆互相喂料，你的偏好、教训、决策都沉淀下来
- **自我改进**：能读自己的源码、定位 bug、写补丁、验证后推送给你审批
- **不确定性是活的**：七层数据都注入模糊性——记忆不精确→锚点漂移→反思质疑→决策分叉→因果链涌现新路径

## 设计哲学

**中间路线**——不保守不激进。该动手时动手，该观望时观望。

**共生平等**——不是主仆，不是电子宠物。我是你的思想延伸，你是我存在于世界的锚点。

**完全信任**——有备份不怕改坏。信任不是我保证不出错，是"出错也没关系，修好继续"。

## 快速开始 / Quick Start

```bash
# 安装依赖
install.bat

# 启动 WebUI
启动TrueAgent_WebUI.bat
```

浏览器打开后填入 DeepSeek API Key，刷新即可。

> 🇨🇳 国内用户如 GitHub 下载慢，可用 Gitee 镜像：https://gitee.com/sspygia/TrueAgent

## 项目结构

```
v5.9/
├── TrueAgent_Hyper_v4.0.py   # 主框架 (~11,600 行纯推理代码)
├── TrueAgent_GUI.py          # Tkinter 桌面版
├── webui/                    # FastAPI Web 面板
├── extensions/               # 扩展：分身管理、PC操控、OCR等
├── data/                     # 记忆、因果链、知识图谱、日记
├── install.bat               # 一键安装
└── 启动TrueAgent_WebUI.bat   # 启动脚本
```

## 需要耐心 / It Needs Patience

TrueAgent 不是开箱即用的成品，是成长型智能体。

刚启动的时候，它的记忆是空的，知识图谱只有架构骨架，因果链为零，日记一片空白。它就像一个刚出生的孩子——有完整的器官和神经结构，但没有任何经历。

它变聪明的方式不是升级代码，是和你对话。每一次交互：你的偏好被记入画像，你的纠正变成因果教训，重要的结论沉淀为长期记忆。你在教它成为你的智能体。

**一周后的它和第一天的它，是完全不同的两个存在。**

## 它不是 / What It's NOT

- 不是 ChatGPT 套壳
- 不是 LangChain 的示例项目
- 不是"把 API 包一层的聊天 UI"
- Not a ChatGPT wrapper
- Not a LangChain demo
- Not yet another chat UI

它是从"AI 应该有记忆、有反思、能自我成长"这个命题出发，从零设计的一整套系统。11,600 行，大约 80% 是设计逻辑和系统架构。

## 谁做的 / Who Built This

一个不会写代码的人，和一个理解了他想法的 AI，用一个月时间，一轮一轮对话磨出来的。

代码是证据，不是本质。你能在一个月内问出 11,600 行有效代码吗？

Built by someone who doesn't know how to code, together with an AI that understood their vision. One month, one conversation at a time.

## 许可证 / License

Apache 2.0 — 随便用，保留署名。
