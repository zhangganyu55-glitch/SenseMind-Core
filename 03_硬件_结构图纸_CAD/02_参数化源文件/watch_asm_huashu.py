"""用 huashu-cad 的 mech.Assembly 登记我们的 7 个零件：干涉检查 + 装配 STEP + assembly.json"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "ghtest/huashu-cad/scripts/mech"))

import watch_v1_cad as W
from mech import Assembly

P, M = W.load_params()
D = W.derive(P)

PARTS = [
    ("body",          W.build_body,          "plastic",        "中框 + 前面板（屏窗/表耳/按键孔）", (0, 0, 4)),
    ("bezel",         W.build_bezel,          "plastic",        "石墨黑装饰表圈",                   (0, 0, 16)),
    ("back_cover",    W.build_back_cover,     "plastic",        "下盖（光学窗 + 遮光圈 + 4×M1.6）", (0, 0, -30)),
    ("sensor_carrier", W.build_sensor_carrier, "plastic",       "传感器载板（±2 mm 可调）",         (0, 0, -19)),
    ("battery_bay",   W.build_battery_bay,    "plastic",          "电池仓（托 20×30×4 + 泡棉）",      (0, 0, -10)),
    ("usbc_end_cap",  W.build_usbc_cap,       "plastic",        "USB-C 可换端盖",                   (0, 0, 4)),
    ("button_caps",   W.build_button_caps,    "aluminum_black", "按钮帽 ×2",                        (0, 0, 4)),
]

asm = Assembly("SenseMind H3-05 V1.1", units="mm")
for name, fn, mat, role, ex in PARTS:
    asm.add(fn(P, D), name, material=mat, role=role, explode=ex)

out = HERE / "huashu_out"
asm.save(out)
print("saved ->", out)
