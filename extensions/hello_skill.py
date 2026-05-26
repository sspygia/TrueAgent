# ============================
# 示例扩展 — 模板
# 放入 extensions/ 目录自动加载
# ============================
EXTENSION_NAME = "hello_skill"
EXTENSION_DESC = "示例技能：扩展接入演示"

def setup(ext_mgr, agent):
    ext_mgr.register_hook("on_startup", lambda: print("[扩展] hello_skill 已激活！"))

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
