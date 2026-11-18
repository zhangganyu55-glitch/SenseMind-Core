"""结构 + 电子件 的完整装配：干涉检查 + 装配 STEP + 交互爆炸图数据"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "ghtest/huashu-cad/scripts/mech"))

import watch_v1_cad as W
import watch_v1_electronics as E
from mech import Assembly

P, M = W.load_params()
D = W.derive(P)

STRUCT = [
    ("body", W.build_body, "plastic", "中框", (0, 0, 0)),
    ("bezel", W.build_bezel, "plastic", "表圈", (0, 0, 26)),
    ("back_cover", W.build_back_cover, "plastic", "下盖", (0, 0, -34)),
    ("sensor_carrier", W.build_sensor_carrier, "plastic", "传感器载板", (0, 0, -18)),
    ("battery_bay", W.build_battery_bay, "plastic", "电池仓", (0, 0, -8)),
    ("usbc_end_cap", W.build_usbc_cap, "plastic", "USB-C 端盖", (0, 0, 0)),
    ("button_caps", W.build_button_caps, "aluminum_black", "按键帽", (0, 0, 0)),
]
EXO = {  # 电子件爆炸位移 (mm)
    "pcb": 6, "header": 12, "display": 22, "battery": -18,
    "max30102": -24, "mpu6050": -24, "usb_conn": 6, "harness": 0,
}

asm = Assembly("SenseMind H3-05 V1.2 含电装", units="mm")
for name, fn, mat, role, ex in STRUCT:
    asm.add(fn(P, D), name, material=mat, role=role, explode=ex)

for name, (solid, mat, desc) in E.build_electronics(P, D).items():
    asm.add(solid, name, material=mat, role=desc, explode=(0, 0, EXO.get(name, 0)))

asm.save(HERE / "huashu_full")
print("saved ->", HERE / "huashu_full")
