# TrueAgent Hyper v5.9 - 前卫风格 GUI
# 设计理念：极简交互 | 自然语言驱动 | 富媒体输出 | 未来感视觉
import sys, os, threading, time, json, traceback, base64, io as _io

# --- 日志 ---
_gui_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_error.log")
def _gui_log(msg):
    try:
        with open(_gui_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except: pass
_gui_log("="*40)
_gui_log("GUI v2 启动")

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- Tcl/Tk 路径 ---
_tcl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcl8.6")
if os.path.isdir(_tcl_dir): os.environ["TCL_LIBRARY"] = _tcl_dir
_tk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tk8.6")
if os.path.isdir(_tk_dir): os.environ["TK_LIBRARY"] = _tk_dir

# --- 加载核心模块 ---
_main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TrueAgent_Hyper_v4.0.py")
import importlib.util
_spec = importlib.util.spec_from_file_location("trueagent_core", _main_path)
_trueagent_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_trueagent_mod)
TrueAgent = _trueagent_mod.TrueAgent
CONFIG = _trueagent_mod.CONFIG

# --- Tkinter ---
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter

# ============================
# 配色方案 — 赛博朋克/玻璃拟态
# ============================
C = {
    "bg_deep": "#0a0e17",         # 最深底
    "bg_mid": "#111827",          # 中底
    "bg_card": "rgba(17,24,39,200)",  # 卡片半透明
    "bg_card_rgb": "#1a2236",
    "border": "#2a3a5c",
    "border_glow": "#3b82f6",
    "accent": "#3b82f6",          # 蓝
    "accent2": "#8b5cf6",         # 紫
    "accent3": "#06b6d4",         # 青
    "success": "#22c55e",
    "warning": "#eab308",
    "error": "#ef4444",
    "text": "#e2e8f0",
    "text_dim": "#94a3b8",
    "text_muted": "#475569",
    "user_bubble": "#1e40af",
    "agent_bubble": "#1e293b",
    "agent_border": "#334155",
    "font": ("Segoe UI", 10),
    "font_cn": ("Microsoft YaHei UI", 10),
    "font_small": ("Segoe UI", 9),
    "font_bold": ("Segoe UI", 10, "bold"),
    "font_header": ("Segoe UI", 13, "bold"),
    "mono": ("Cascadia Code", 10, "normal") if os.name == 'nt' else ("Consolas", 10),
}

# ============================
# 工具：生成渐变背景
# ============================
def make_gradient(width, height, color1="#0a0e17", color2="#1a1a3e", color3="#0f172a"):
    """生成垂直渐变色带"""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        ratio = y / height
        if ratio < 0.5:
            r = ratio * 2
            cr = int(int(color1[1:3],16)*(1-r) + int(color2[1:3],16)*r)
            cg = int(int(color1[3:5],16)*(1-r) + int(color2[3:5],16)*r)
            cb = int(int(color1[5:7],16)*(1-r) + int(color2[5:7],16)*r)
        else:
            r = (ratio - 0.5) * 2
            cr = int(int(color2[1:3],16)*(1-r) + int(color3[1:3],16)*r)
            cg = int(int(color2[3:5],16)*(1-r) + int(color3[3:5],16)*r)
            cb = int(int(color2[5:7],16)*(1-r) + int(color3[5:7],16)*r)
        for x in range(width):
            # 微妙的边缘光晕
            edge = 1.0 - abs(x - width/2) / (width/2) * 0.15
            pixels[x, y] = (min(255,int(cr*edge)), min(255,int(cg*edge)), min(255,int(cb*edge)))
    return img

def make_grid_overlay(width, height, spacing=40, color=(59,130,246,20)):
    """生成科技感网格叠加层"""
    img = Image.new("RGBA", (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    for x in range(0, width, spacing):
        alpha = 15 if x % (spacing*2) == 0 else 8
        draw.line([(x,0),(x,height)], fill=(59,130,246,alpha), width=1)
    for y in range(0, height, spacing):
        alpha = 15 if y % (spacing*2) == 0 else 8
        draw.line([(0,y),(width,y)], fill=(59,130,246,alpha), width=1)
    return img

# ============================
# 现代化仪表盘
# ============================
class ModernDashboard(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg_mid"])
        self.agent = None
        self._status = {}
        self._build()

    def set_agent(self, agent):
        self.agent = agent

    def _card(self, title, icon="", color=C["accent"]):
        """创建一个仪表盘卡片"""
        card = tk.Frame(self, bg=C["bg_card_rgb"], highlightbackground=C["border"],
                        highlightthickness=1, padx=10, pady=8)
        card.pack(fill=tk.X, padx=6, pady=3)
        # 标题行
        hdr = tk.Frame(card, bg=C["bg_card_rgb"])
        hdr.pack(fill=tk.X)
        if icon:
            tk.Label(hdr, text=icon, bg=C["bg_card_rgb"], fg=color,
                     font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0,4))
        tk.Label(hdr, text=title, bg=C["bg_card_rgb"], fg=C["text_dim"],
                 font=C["font_small"]).pack(side=tk.LEFT)
        return card

    def _row(self, parent, label, value, color=C["text"]):
        f = tk.Frame(parent, bg=C["bg_card_rgb"])
        f.pack(fill=tk.X, pady=1)
        tk.Label(f, text=label, bg=C["bg_card_rgb"], fg=C["text_dim"],
                 font=("Segoe UI", 8), width=8, anchor=tk.W).pack(side=tk.LEFT)
        val_label = tk.Label(f, text=value, bg=C["bg_card_rgb"], fg=color,
                 font=("Segoe UI", 9, "bold"), anchor=tk.E)
        val_label.pack(side=tk.RIGHT, fill=tk.X)
        return val_label

    def _mini_bar(self, parent, pct, color=C["accent"]):
        """迷你进度条"""
        bf = tk.Frame(parent, bg="#1e293b", height=6, width=140)
        bf.pack(fill=tk.X, pady=2)
        bf.pack_propagate(False)
        bar = tk.Frame(bf, bg=color, height=6, width=max(int(140*pct),2))
        bar.pack(side=tk.LEFT)

    def _build(self):
        # 标题
        tk.Label(self, text="● 系统状态", bg=C["bg_mid"], fg=C["accent"],
                 font=C["font_bold"]).pack(anchor=tk.W, padx=10, pady=(8,2))

        # 系统资源卡片
        self._sys_card = self._card("资源监控", "⚡", C["accent"])
        self._sys_rows = {}
        for k, c in [("CPU", C["accent"]), ("内存", C["success"]),
                     ("线程", C["warning"]), ("能量", C["accent3"])]:
            self._sys_rows[k] = self._row(self._sys_card, k, "--", c)

        # 工具/技能卡片
        self._tool_card = self._card("能力矩阵", "🧩", C["accent2"])
        self._tool_rows = {}
        for k, c in [("工具", C["accent"]), ("技能", C["accent2"]),
                     ("API调用", C["accent3"]), ("知识命中", C["success"])]:
            self._tool_rows[k] = self._row(self._tool_card, k, "--", c)

        # 记忆卡片
        self._mem_card = self._card("记忆", "🧠", C["success"])
        self._mem_rows = {}
        for k, c in [("长期", C["text"]), ("短期", C["accent"]),
                     ("画像", C["accent2"]), ("成功率", C["success"])]:
            self._mem_rows[k] = self._row(self._mem_card, k, "--", c)

        # 知识图谱卡片
        self._kg_card = self._card("知识图谱", "📊", C["accent3"])
        self._kg_rows = {}
        for k, c in [("节点", C["accent"]), ("因果", C["accent2"]),
                     ("锚点", C["warning"]), ("覆盖率", C["accent3"])]:
            self._kg_rows[k] = self._row(self._kg_card, k, "--", c)

        # 技能列表（动态）
        self._skill_card = self._card("已安装技能", "📦", C["accent2"])
        self._skill_frame = tk.Frame(self._skill_card, bg=C["bg_card_rgb"])
        self._skill_frame.pack(fill=tk.X)
        self._skill_labels = []

    def poll(self):
        if not self.agent:
            return
        try:
            st = self.agent.get_agent_status() if hasattr(self.agent, 'get_agent_status') else {}
        except Exception:
            return
        self._status = st
        sm = st.get("self_monitor", {})

        # 系统状态
        self._sys_rows["CPU"].config(text=f"{sm.get('cpu_usage',0):.1f}%")
        self._sys_rows["内存"].config(text=f"{sm.get('memory_usage',0):.0f} MB")
        self._sys_rows["线程"].config(text=str(sm.get('thread_count',0)))
        self._sys_rows["能量"].config(text=f"{sm.get('energy_level',0):.2f}")

        # 工具/技能（tools是列表，extensions可能不存在）
        tools_list = st.get("tools", [])
        tool_count = len(tools_list) if isinstance(tools_list, (list, tuple)) else 0
        stats = st.get("stats", {})
        self._tool_rows["工具"].config(text=str(tool_count))
        self._tool_rows["技能"].config(text=str(stats.get("total_skills", 0)))
        self._tool_rows["API调用"].config(text=str(stats.get("api_calls",0)))
        self._tool_rows["知识命中"].config(text=str(stats.get("knowledge_hits",0)))

        # 记忆（实际返回：working, long, types, avg_quality）
        mem = st.get("memory", {})
        self._mem_rows["长期"].config(text=str(mem.get("working", 0)))
        self._mem_rows["短期"].config(text=str(mem.get("long", 0)-mem.get("working", 0)))
        self._mem_rows["画像"].config(text=str(mem.get("profile_count", 0)))
        types = mem.get("types", {})
        s = types.get("tool_success",0)
        f = types.get("tool_failure",0)
        rate = f"{s*100//(s+f)}%" if (s+f)>0 else "--"
        self._mem_rows["成功率"].config(text=rate)

        # 知识图谱（实际返回：nodes, edges）
        kg = st.get("knowledge_graph", {}) or {}
        self._kg_rows["节点"].config(text=str(kg.get("nodes",0)))
        self._kg_rows["因果"].config(text=str(kg.get("edges",0)))
        ae = st.get("anchor_engine", {}) or {}
        self._kg_rows["锚点"].config(text=str(ae.get("total",0)))
        # 覆盖率 = 活跃锚点/锚点总数
        active = ae.get("active", 0) or 0
        total = ae.get("total", 0) or 1
        self._kg_rows["覆盖率"].config(text=f"{active*100//total}%" if total > 0 else "--")

        # 技能列表（从anchor_engine或stats获取技能名）
        skills_list = []
        self_anchor = ae.get("self_methodology", {}) if isinstance(ae, dict) else {}
        for lb in self._skill_labels:
            lb.destroy()
        self._skill_labels = []
        for sname in list(ae.get("modules", []))[:6]:
            lb = tk.Label(self._skill_frame, text=f"▸ {sname}", bg=C["bg_card_rgb"],
                         fg=C["accent3"], font=("Segoe UI", 8), anchor=tk.W)
            lb.pack(fill=tk.X)
            self._skill_labels.append(lb)
        if not self._skill_labels:
            lb = tk.Label(self._skill_frame, text=f"运行中（{tool_count}工具）", bg=C["bg_card_rgb"],
                         fg=C["text_muted"], font=("Segoe UI", 8))
            lb.pack(fill=tk.X)
            self._skill_labels.append(lb)


# ============================
# 主窗口
# ============================
class TrueAgentGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TrueAgent Hyper v5.9")
        self.root.geometry("1150x760")
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 设置窗口图标（用 PIL 生成一个小图标）
        self._set_icon()
        self.agent = None
        self._poller = None
        self._build_ui()
        self._start_background()

    def _set_icon(self):
        """生成一个简单的科技感图标"""
        try:
            img = Image.new("RGBA", (64, 64), (0,0,0,0))
            draw = ImageDraw.Draw(img)
            # 圆 + 箭头
            draw.ellipse([4,4,60,60], outline="#3b82f6", width=3)
            draw.polygon([(32,12),(48,32),(38,32),(38,52),(26,52),(26,32),(16,32)], fill="#3b82f6")
            img = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, img)
            self._icon_img = img
        except: pass

    def _build_ui(self):
        # === 根 Canvas 用于背景 ===
        self.bg_canvas = tk.Canvas(self.root, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._draw_bg()

        # === 主容器（半透明效果） ===
        main_frame = tk.Frame(self.root, bg=C["bg_mid"])
        main_frame.place(x=6, y=6, relwidth=1, relheight=1, width=-12, height=-12)

        # === 标题栏 ===
        title_bar = tk.Frame(main_frame, bg=C["bg_card_rgb"], highlightbackground=C["border"],
                             highlightthickness=1, height=40)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)

        tk.Label(title_bar, text="◈ TrueAgent", bg=C["bg_card_rgb"],
                 fg=C["text"], font=C["font_header"]).pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(title_bar, text="v5.9", bg=C["bg_card_rgb"],
                 fg=C["text_dim"], font=C["font_small"]).pack(side=tk.LEFT, padx=(0,8))

        self._status_dot = tk.Label(title_bar, text="●", bg=C["bg_card_rgb"],
                                     fg=C["warning"], font=("Segoe UI", 8))
        self._status_dot.pack(side=tk.RIGHT, padx=(0,4))
        self._status_lbl = tk.Label(title_bar, text="启动中...", bg=C["bg_card_rgb"],
                                     fg=C["text_dim"], font=C["font_small"])
        self._status_lbl.pack(side=tk.RIGHT, padx=(0,14))

        # === 主体：左右分栏 ===
        body = tk.Frame(main_frame, bg=C["bg_mid"])
        body.pack(fill=tk.BOTH, expand=True, pady=4)

        # 左侧：聊天
        left_frame = tk.Frame(body, bg=C["bg_mid"])
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 聊天容器
        chat_container = tk.Frame(left_frame, bg=C["bg_card_rgb"],
                                  highlightbackground=C["border"], highlightthickness=1)
        chat_container.pack(fill=tk.BOTH, expand=True, padx=(0,3))

        # 聊天框（富文本）
        self.chat = tk.Text(chat_container, bg="#0f172a", fg=C["text"],
                             font=C["font_cn"], padx=14, pady=10,
                             relief=tk.FLAT, wrap=tk.WORD, state=tk.DISABLED,
                             insertbackground=C["accent"], borderwidth=0,
                             highlightthickness=0)
        self.chat.pack(fill=tk.BOTH, expand=True)
        # 配置标签样式
        self.chat.tag_config("user_tag", foreground=C["user_bubble"], font=C["font_bold"])
        self.chat.tag_config("agent_tag", foreground=C["accent"], font=C["font_bold"])
        self.chat.tag_config("system_tag", foreground=C["text_muted"], font=C["font_small"])
        self.chat.tag_config("error_tag", foreground=C["error"], font=C["font_bold"])
        self.chat.tag_config("time_tag", foreground=C["text_muted"], font=("Segoe UI", 8))
        self.chat.tag_config("code_tag", background="#1e293b", foreground=C["accent3"],
                            font=C["mono"], lmargin1=20, lmargin2=20, rmargin=20,
                            spacing1=4, spacing2=4, spacing3=4)
        self.chat.tag_config("bold_tag", font=C["font_bold"])
        self.chat.tag_config("table_header", background="#1e3a5f", foreground=C["text"],
                            font=C["font_bold"], spacing1=4, spacing2=4)
        self.chat.tag_config("table_cell", background="#0f172a", foreground=C["text"],
                            font=C["font_small"], spacing1=2, spacing2=2)

        # 输入区域
        input_container = tk.Frame(left_frame, bg=C["bg_card_rgb"],
                                   highlightbackground=C["border"], highlightthickness=1)
        input_container.pack(fill=tk.X, pady=(4,0))

        # 工具栏按钮
        tools_row = tk.Frame(input_container, bg=C["bg_card_rgb"])
        tools_row.pack(fill=tk.X, padx=4, pady=(4,0))

        def _make_tool_btn(text, tooltip, cmd, color=C["text_dim"]):
            btn = tk.Label(tools_row, text=text, bg=C["bg_card_rgb"], fg=color,
                          font=("Segoe UI", 10), cursor="hand2", padx=6)
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Enter>", lambda e: btn.config(fg=C["accent"]))
            btn.bind("<Leave>", lambda e: btn.config(fg=color))
            btn.bind("<Button-1>", lambda e: cmd())
            return btn

        self._btn_upload = _make_tool_btn("📎", "上传文件", self._on_upload)
        self._btn_mic = _make_tool_btn("🎤", "语音输入（预留）", lambda: None)
        self._btn_api = _make_tool_btn("⚙", "API配置（预留）", lambda: None)

        # 输入框 + 发送
        input_row = tk.Frame(input_container, bg=C["bg_card_rgb"])
        input_row.pack(fill=tk.X, padx=4, pady=(2,4))

        self.input_box = tk.Text(input_row, bg="#0f172a", fg=C["text"],
                                  font=C["font_cn"], relief=tk.FLAT, height=1,
                                  insertbackground=C["accent"], borderwidth=0,
                                  highlightthickness=0, padx=8, pady=6)
        self.input_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_box.bind("<Return>", self._on_send)
        self.input_box.bind("<Shift-Return>", lambda e: self.input_box.insert(tk.INSERT, "\n"))

        self.send_btn = tk.Label(input_row, text="▶ 发送", bg=C["accent"], fg="#fff",
                                 font=C["font_bold"], padx=14, pady=4, cursor="hand2")
        self.send_btn.pack(side=tk.RIGHT, padx=(4,0))
        self.send_btn.bind("<Button-1>", lambda e: self._on_send_click())
        self.send_btn.bind("<Enter>", lambda e: self.send_btn.config(bg=C["accent2"]))
        self.send_btn.bind("<Leave>", lambda e: self.send_btn.config(bg=C["accent"]))

        # === 右侧：仪表盘 ===
        right_frame = tk.Frame(body, bg=C["bg_mid"], width=340)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        right_frame.pack_propagate(False)

        # 滚动仪表盘
        canvas = tk.Canvas(right_frame, bg=C["bg_mid"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(right_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = tk.Frame(canvas, bg=C["bg_mid"])

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.dashboard = ModernDashboard(scrollable)
        self.dashboard.pack(fill=tk.BOTH, expand=True)

        # 绑定鼠标滚轮到画布
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self._canvas = canvas  # 保存引用用于解绑

    def _draw_bg(self):
        """绘制科技感渐变背景"""
        self.root.update_idletasks()
        w = self.root.winfo_width() or 1150
        h = self.root.winfo_height() or 760
        if w < 100: w = 1150
        if h < 100: h = 760
        try:
            bg_img = make_gradient(w, h, "#0a0e17", "#0f172a", "#1a1a3e")
            grid = make_grid_overlay(w, h)
            bg_img = Image.alpha_composite(bg_img.convert("RGBA"), grid)
            self._bg_photo = ImageTk.PhotoImage(bg_img)
            self.bg_canvas.create_image(0, 0, anchor=tk.NW, image=self._bg_photo)
        except Exception as e:
            _gui_log(f"背景绘制: {e}")
            self.bg_canvas.configure(bg="#0a0e17")

    # ========== 交互方法 ==========
    def _append_chat(self, role, msg, tag="system_tag", extra_tags=None):
        self.chat.config(state=tk.NORMAL)
        ts = time.strftime("%H:%M")
        roles = {"user": "你", "agent": "TrueAgent", "system": "系统", "error": "错误"}
        label = roles.get(role, role)
        colors = {"user": C["user_bubble"], "agent": C["accent"],
                  "system": C["text_muted"], "error": C["error"]}
        color = colors.get(role, C["text"])

        # 时间戳
        self.chat.insert(tk.END, f"  {ts}  ", "time_tag")

        # 角色标签
        role_tag = f"{role}_tag"
        if role_tag in self.chat.tag_names():
            self.chat.insert(tk.END, f"{label}  ", role_tag)
        else:
            self.chat.insert(tk.END, f"{label}  ", "system_tag")

        # 消息内容（带简单 markdown 渲染）
        self._insert_formatted(msg, color)

        self.chat.insert(tk.END, "\n\n")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)

    def _insert_formatted(self, text, default_color=C["text"]):
        """插入格式化文本：支持 **bold** `code` ```code block``` 表格"""
        lines = text.split("\n")
        in_code_block = False
        code_lines = []
        for line in lines:
            # 代码块
            if line.startswith("```"):
                if in_code_block:
                    # 结束代码块
                    code_text = "\n".join(code_lines)
                    self.chat.insert(tk.END, code_text, "code_tag")
                    self.chat.insert(tk.END, "\n")
                    code_lines = []
                    in_code_block = False
                else:
                    in_code_block = True
                continue
            if in_code_block:
                code_lines.append(line)
                continue
            # 表格行（| col1 | col2 | 形式）
            if line.strip().startswith("|") and line.strip().endswith("|"):
                cells = [c.strip() for c in line.strip().split("|") if c.strip()]
                sep_line = all(c.replace("-", "").replace(":", "").strip() == "" for c in cells)
                if not sep_line:
                    self.chat.insert(tk.END, "  " + " | ".join(cells) + "\n", "table_cell")
                    continue
                else:
                    continue
            # 普通行：支持 **bold** 和 `code`
            parts = []
            i = 0
            while i < len(line):
                # **bold**
                if line[i:i+2] == "**":
                    j = line.find("**", i+2)
                    if j > i:
                        parts.append(("bold", line[i+2:j]))
                        i = j + 2
                        continue
                # `code`
                if line[i] == "`":
                    j = line.find("`", i+1)
                    if j > i:
                        parts.append(("code", line[i+1:j]))
                        i = j + 1
                        continue
                # 普通文本
                k = i + 1
                while k < len(line) and line[k] not in "*`":
                    k += 1
                parts.append(("text", line[i:k]))
                i = k
            if not parts:
                self.chat.insert(tk.END, line + "\n")
            else:
                for ptype, ptext in parts:
                    if ptype == "bold":
                        self.chat.insert(tk.END, ptext, "bold_tag")
                    elif ptype == "code":
                        self.chat.insert(tk.END, ptext, "code_tag")
                    else:
                        self.chat.insert(tk.END, ptext)
                self.chat.insert(tk.END, "\n")

    def _on_send(self, event=None):
        self._on_send_click()
        return "break"

    def _on_send_click(self):
        text = self.input_box.get("1.0", tk.END).strip()
        if not text:
            return
        self.input_box.delete("1.0", tk.END)
        self._append_chat("user", text)
        if self.agent:
            threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def _on_upload(self):
        files = filedialog.askopenfilenames(title="选择文件",
            filetypes=[("所有文件", "*.*"), ("文档", "*.txt *.md *.pdf *.docx"),
                       ("图片", "*.png *.jpg *.jpeg *.gif"), ("代码", "*.py *.js *.html *.css")])
        if not files:
            return
        names = "\n".join(f"📄 {os.path.basename(f)}" for f in files)
        self._append_chat("system", f"📎 已上传 {len(files)} 个文件:\n{names}")
        # 在后台线程中处理文件
        if self.agent:
            threading.Thread(target=self._process_files, args=(files,), daemon=True).start()

    def _process_files(self, files):
        summaries = []
        for fp in files:
            try:
                ext = os.path.splitext(fp)[1].lower()
                name = os.path.basename(fp)
                if ext in ('.png','.jpg','.jpeg','.gif','.bmp'):
                    # 图片文件 → 尝试 OCR
                    try:
                        from extensions.ocr_skill import ocr_image_file
                        r = ocr_image_file(fp)
                        if r.get("success"):
                            summaries.append(f"📷 {name}:\n{r['text'][:500]}")
                        else:
                            summaries.append(f"📷 {name}: (图片，无法OCR)")
                    except:
                        summaries.append(f"📷 {name}: (图片文件)")
                elif ext in ('.txt','.md','.py','.js','.html','.css','.json','.yaml','.yml','.xml'):
                    with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(2000)
                    summaries.append(f"📄 {name} ({len(content)}字符):\n{content[:800]}")
                elif ext in ('.docx',):
                    try:
                        import zipfile as _z
                        with _z.ZipFile(fp) as zf:
                            names = '\n'.join(zf.namelist()[:10])
                        summaries.append(f"📄 {name}: (文档包，含 {len(zf.namelist())} 个文件)\n{names}")
                    except:
                        summaries.append(f"📄 {name}: (文档)")
                else:
                    size = os.path.getsize(fp)
                    summaries.append(f"📄 {name} ({size/1024:.0f}KB)")
            except Exception as e:
                summaries.append(f"❌ {os.path.basename(fp)}: {e}")
        full = "\n\n".join(summaries)
        self.root.after(0, self._append_chat, "system", f"📋 文件内容摘要:\n{full}")

    def _process(self, text):
        try:
            self.send_btn.config(text="⏳ 思考中...")
            reply = self.agent.process_user_command(text)
            self.root.after(0, self._append_chat, "agent", str(reply)[:3000])
        except Exception as e:
            _gui_log(f"处理出错: {e}")
            self.root.after(0, self._append_chat, "error", str(e)[:300])
        finally:
            self.root.after(0, lambda: self.send_btn.config(text="▶ 发送"))

    def _start_background(self):
        def _bg():
            try:
                self.agent = TrueAgent(CONFIG)
                self.agent.start()
                self.dashboard.set_agent(self.agent)
                self.root.after(0, lambda: [
                    self._status_dot.config(fg=C["success"]),
                    self._status_lbl.config(text="运行中"),
                    self._append_chat("system",
                        "TrueAgent 已就绪 ✅  输入任何需求即可。\n"
                        "支持：自然语言指令 · 文件上传 📎 · 截图OCR · 桌面操作 · 定时提醒\n"
                        "输入 `list_skills` 查看所有可用能力")
                ])
                while self.agent.running:
                    try:
                        self.root.after(0, self.dashboard.poll)
                    except: pass
                    time.sleep(3)
            except Exception as e:
                _gui_log(f"后台启动: {e}")
                self.root.after(0, lambda: [
                    self._status_dot.config(fg=C["error"]),
                    self._status_lbl.config(text="异常"),
                    self._append_chat("error", f"启动异常: {str(e)[:200]}")
                ])
        threading.Thread(target=_bg, daemon=True).start()

    def _on_close(self):
        _gui_log("GUI 关闭")
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except: pass
        try:
            if self.agent:
                self.agent.stop()
        except: pass
        try:
            self.root.destroy()
        except: pass
        import os as _os; _os._exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    gui = TrueAgentGUI()
    gui.run()
