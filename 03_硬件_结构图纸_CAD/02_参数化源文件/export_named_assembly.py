"""把 7 个零件导出成一个带英文零件名的 STEP 装配（供专利附图/其它 CAD 用）"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_v1_cad as W
from build123d import Compound, export_step

P, M = W.load_params()
D = W.derive(P)

parts = [
    ("body", W.build_body(P, D)),
    ("bezel", W.build_bezel(P, D)),
    ("back_cover", W.build_back_cover(P, D)),
    ("sensor_carrier", W.build_sensor_carrier(P, D)),
    ("battery_bay", W.build_battery_bay(P, D)),
    ("usbc_end_cap", W.build_usbc_cap(P, D)),
    ("button_caps", W.build_button_caps(P, D)),
]
for name, p in parts:
    p.label = name
comp = Compound(children=[p for _, p in parts])
comp.label = "SenseMind_H3-05_V1.1"
out = HERE / "out" / "SenseMind_H3-05_V1.1_assembly.step"
export_step(comp, str(out))
print("wrote", out)
