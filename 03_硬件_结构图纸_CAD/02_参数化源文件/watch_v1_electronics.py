"""电子件占位体（包络模型）—— 只为装配检查与渲染，不是真实 PCB 设计。

尺寸全部取自 watch_v1_params.json（多数是 assumed，见 CSV 的 status 列）。
用途：
  1) 干涉检查：模块能不能真塞进壳里
  2) 爆炸图/交互图里能看到"里面有什么"
  3) 渲染时作为深色 PCB / 模块 / 线束的占位

刻意做成简单的长方体包络 + 直角走线示意，避免"看起来很真但是假的"细节。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build123d import Box, Pos  # noqa: E402

import watch_v1_cad as W  # noqa: E402


def _box(dx, dy, dz, x, y, d):
    """中心 (x,y)、深度中心 d 的长方体"""
    return Pos(x, y, -d) * Box(dx, dy, dz)


def _seg(p0, p1, w, h):
    """轴对齐线段（直角走线）：p=(x,y,depth)。w/h 为截面两个非轴向尺寸。"""
    (x0, y0, d0), (x1, y1, d1) = p0, p1
    dx, dy, dz = abs(x1 - x0), abs(y1 - y0), abs(d1 - d0)
    nz = (dx > 0) + (dy > 0) + (dz > 0)
    if nz != 1:
        raise ValueError(f"线段必须只沿一个轴: {p0} -> {p1}")
    cx, cy, cd = (x0 + x1) / 2, (y0 + y1) / 2, (d0 + d1) / 2
    if dz:                      # 沿 Z：截面 X×Y
        return _box(w, h, dz + 0.01, cx, cy, cd)
    if dy:                      # 沿 Y：截面 X×Z
        return _box(w, dy + 0.01, h, cx, cy, cd)
    return _box(dx + 0.01, w, h, cx, cy, cd)   # 沿 X：截面 Y×Z


def build_electronics(P, D):
    """返回 {名字: (实体, 材质, 中文说明)}"""
    yy = P["board_y_top"] - P["board_l"] / 2          # 主板中心 Y
    out = {}

    # 主板（SuperMini）
    out["pcb"] = (_box(P["board_w"], P["board_l"], P["board_t"], 0, yy,
                       (D["board_top"] + D["board_bot"]) / 2),
                  "plastic", "主控板 nRF52840")
    # 排针（两列 2.54 的包络）
    out["header"] = (_box(P["board_w"] - 4, P["board_l"] - 10, P["hdr_h"], 0, yy + 3,
                          (D["hdr_top"] + D["board_top"]) / 2),
                     "plastic", "2.54 排针")

    # 屏模块（含排针的总厚）
    out["display"] = (_box(P["disp_w"], P["disp_l"], P["disp_t"], 0, P["disp_y"],
                           (D["disp_front"] + D["disp_back"]) / 2),
                      "plastic", "ST7789V 模块")

    # 传感器
    out["max30102"] = (_box(P["max_w"], P["max_l"], P["max_t"], P["max_x"], P["sensor_y"],
                            (D["carrier_bot"] + D["sensor_bot"]) / 2),
                       "plastic", "MAX30102")
    out["mpu6050"] = (_box(P["mpu_w"], P["mpu_l"], P["mpu_t"], P["mpu_x"], P["sensor_y"],
                           (D["carrier_bot"] + D["sensor_bot"]) / 2),
                      "plastic", "MPU6050")

    # 电池
    by = (P["bat_y_min"] + P["bat_y_max"]) / 2
    out["battery"] = (W.slab(P["bat_w"], P["bat_l"], 2.0,
                             D["bat_top"], D["bat_top"] + P["bat_t"], (0, by)),
                      "plastic", "锂电池")   # 软包电池四角本来就是圆角

    # USB-C 连接器（板端）
    out["usb_conn"] = (_box(8.9, 6.0, 3.2, 0, P["board_y_top"] - P["board_l"] + 2.0,
                            D["board_top"] - 1.6),
                       "brass", "USB-C 母座")

    # ---- 线束（直角走线示意，不是真实线径）----
    # 布局：主板 y -21..12.5 / 屏幕 d 2.1..5.6 / 电池 y 1.5..21.5 / 传感器 y -19.9..0.9
    wires = []
    bt, bb = D["board_top"], D["board_bot"]          # 板顶/板底深度
    fy = P["disp_l"] / 2 - 0.5                        # 屏 FPC 出线边
    over = bt - 0.4                                   # 走线深度：板顶上方 0.4

    # 1) 屏 FPC：屏背面出线 → 跨到主板 +Y 端上表面
    wires += [_seg((0, fy, D["disp_back"] + 0.15), (0, fy, over), 10.0, 0.3),
              _seg((0, fy, over), (0, P["board_y_top"] - 0.5, over), 10.0, 0.3)]

    # 2) 电池线：电池 +Y 端引出 → 抬高跨过板顶 → 走到 BATTERY+ 焊盘端(-Y)
    bx = -7.8                                          # 避开 2.54 排针(±6.8)
    wires += [_seg((bx, P["bat_y_max"] - 1.0, D["bat_top"] + 0.15),
                   (bx, P["bat_y_max"] - 1.0, over), 0.5, 0.5),
              _seg((bx, P["bat_y_max"] - 1.0, over),
                   (bx, P["board_y_top"] - P["board_l"] + 2.5, over), 0.5, 0.5)]

    # 3) 传感器 FPC：载板 +Y 边 → 主板底面
    wires += [_seg((5.0, 1.1, D["sensor_bot"] - 0.3), (5.0, 1.1, bb), 0.3, 0.3)]

    harness = None
    for s in wires:
        harness = s if harness is None else harness + s
    out["harness"] = (harness, "rubber", "FPC / 电池线（走线示意）")
    return out


def main():
    P, M = W.load_params()
    D = W.derive(P)
    out = build_electronics(P, D)
    for k, (solid, mat, desc) in out.items():
        bb = solid.bounding_box()
        print(f"{k:12s} {desc:16s} bbox {bb.size.X:5.1f} x {bb.size.Y:5.1f} x {bb.size.Z:5.1f}  vol={solid.volume:8.1f}")


if __name__ == "__main__":
    main()
