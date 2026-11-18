#!/usr/bin/env python3
"""全部零件的等轴测预览 (真实几何投影) -> out/watch_v1_preview.png"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_v1_cad as cad
from watch_v1_docs import _project, load

matplotlib.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Heiti SC", "DejaVu Sans"]


def main():
    stack, P, M = load()
    D = stack["derived"]
    items = [
        ("body 中框/上壳", cad.build_body),
        ("bezel 表圈", cad.build_bezel),
        ("back_cover 下盖", cad.build_back_cover),
        ("sensor_carrier 载板", cad.build_sensor_carrier),
        ("battery_bay 电池仓", cad.build_battery_bay),
        ("usbc_end_cap 端盖", cad.build_usbc_cap),
        ("button_caps 按钮帽", cad.build_button_caps),
        ("fit_check 试装件", cad.build_fit_check),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(16, 8.4))
    fig.suptitle("SenseMind H3-05 手表 V1 · 零件预览 (几何投影, 非渲染)", fontsize=14, weight="bold")
    for ax, (name, fn) in zip(axes.ravel(), items):
        ax.set_aspect("equal"); ax.axis("off")
        part = fn(P, D)
        for seg in _project(part, (150, -190, 130)):
            ax.plot([p[0] for p in seg], [p[1] for p in seg], color="#1a1a1a", lw=0.4)
        ax.set_title(name, fontsize=9)
        ax.autoscale_view()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    base = HERE / "out" if (HERE / "out").exists() else HERE
    out = base / "watch_v1_preview.png"
    fig.savefig(out, dpi=150)
    print("wrote", out)


if __name__ == "__main__":
    main()
