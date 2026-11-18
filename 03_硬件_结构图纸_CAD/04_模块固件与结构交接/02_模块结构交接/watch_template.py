#!/usr/bin/env python3
"""Parametric 1:1 paper fit template for the SenseMind watch V1.

Print at 100% / actual size. Verify the 85.60 x 53.98 mm credit-card box
before trusting any outline. Edit the assumptions below after measuring
the real parts, then run:

    python3 mechanical/watch_template.py

The output SVG is written next to this script as fit-template.svg.
"""
from pathlib import Path
from xml.sax.saxutils import escape

# ---- assumptions: edit after measuring the real parts (mm) -------------
DISPLAY_W = 31.5          # ST7789V module PCB/glass, not just active area
DISPLAY_H = 33.7
DISPLAY_ACTIVE = 27.72    # 1.54" 240x240 active area
BOARD_W = 18.0             # SuperMini nRF52840, assumed
BOARD_H = 28.0
MAX_W = 20.0               # MAX30102 breakout, vendor image
MAX_H = 15.5
MPU_W = 20.26              # MPU6050 breakout, vendor drawing
MPU_H = 15.56
BATTERIES = [(20.0, 30.0, 4.0), (25.0, 30.0, 4.5)]
CASE_W = 42.0
CASE_H = 46.0
CASE_T = 18.0
STRAP_W = 20.0
BUTTON = 6.0
USBC_W = 9.5
USBC_H = 3.5
# -----------------------------------------------------------------------

PAGE_W, PAGE_H = 210, 297
CARD_W, CARD_H = 85.60, 53.98
parts = []


def rect(x, y, w, h, stroke="#333", fill="none", sw=0.35, dash=None, rx=0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
        f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def circle(cx, cy, r, stroke="#333", fill="none", sw=0.35, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{r:.3f}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def line(x1, y1, x2, y2, stroke="#333", sw=0.25, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
        f'stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def text(x, y, s, size=3, color="#111", anchor="start", weight="normal"):
    parts.append(
        f'<text x="{x:.3f}" y="{y:.3f}" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="{size}" fill="{color}" text-anchor="{anchor}" '
        f'font-weight="{weight}">{escape(s)}</text>'
    )


def build():
    parts.append(f'<rect x="0" y="0" width="{PAGE_W}" height="{PAGE_H}" fill="white"/>')
    text(10, 10, "SenseMind 手表 V1 - 1:1 尺寸校验模板", size=5, weight="bold")
    text(10, 15, "标准尺寸假设，不是最终图纸；打印必须 100% / 实际大小（关闭“适合页面”）。实测后改参数。",
         size=2.8, color="#444")

    # 1. credit card calibration
    text(10, 24, "① 打印比例校准：把银行卡/信用卡放在框内，四边应重合", size=3, weight="bold")
    rect(10, 28, CARD_W, CARD_H, "#111", "#f7f7f7", 0.45)
    text(10, 86, f"{CARD_W:.2f} × {CARD_H:.2f} mm（标准银行卡尺寸）", size=2.8, color="#444")

    # 2. display
    text(110, 24, '② ST7789V 1.54" 模块（假设）', size=3, weight="bold")
    rect(110, 28, DISPLAY_W, DISPLAY_H, "#0a7", "#f2fff9", 0.45)
    rect(110 + (DISPLAY_W - DISPLAY_ACTIVE) / 2,
         28 + (DISPLAY_H - DISPLAY_ACTIVE) / 2,
         DISPLAY_ACTIVE, DISPLAY_ACTIVE, "#0a7", "none", 0.35, "2,1")
    text(110 + DISPLAY_W / 2, 65, f"{DISPLAY_W:.2f} × {DISPLAY_H:.2f} 外形",
         size=2.6, anchor="middle", color="#0a7")
    text(110 + DISPLAY_W / 2, 68.5, f"有效区 {DISPLAY_ACTIVE:.2f} × {DISPLAY_ACTIVE:.2f}（虚线）",
         size=2.6, anchor="middle", color="#0a7")
    text(110 + DISPLAY_W / 2, 72, "排针/厚度/显示区偏移待实测",
         size=2.6, anchor="middle", color="#a00")

    # 3. board and sensors
    text(10, 96, "③ 主板与传感器模块", size=3, weight="bold")
    rect(10, 100, BOARD_W, BOARD_H, "#07a", "#f2f8ff", 0.45)
    text(10 + BOARD_W / 2, 131, f"nRF52840 {BOARD_W:.0f}×{BOARD_H:.0f}（假设）",
         size=2.5, anchor="middle", color="#07a")
    rect(35, 100, MAX_W, MAX_H, "#a50", "#fff8f2", 0.45)
    text(35 + MAX_W / 2, 118.5, f"MAX30102 {MAX_W:.0f}×{MAX_H:.1f}",
         size=2.5, anchor="middle", color="#a50")
    rect(60, 100, MPU_W, MPU_H, "#a0a", "#fff2ff", 0.45)
    text(60 + MPU_W / 2, 118.6, f"MPU6050 {MPU_W:.2f}×{MPU_H:.2f}",
         size=2.5, anchor="middle", color="#a0a")
    text(60 + MPU_W / 2, 122, "3.0 孔 / 2.54 排针",
         size=2.4, anchor="middle", color="#a0a")

    # 4. battery/buttons/usb
    text(10, 144, "④ 电池 / 按钮 / USB-C（假设）", size=3, weight="bold")
    bx = 10
    for w, h, t in BATTERIES:
        rect(bx, 148, w, h, "#888", "#fafafa", 0.45)
        text(bx + w / 2, 181, f"电池 {w:.0f}×{h:.0f}×{t:g}", size=2.5, anchor="middle")
        bx += w + 5
    rect(68, 148, BUTTON, BUTTON, "#333", "#eee", 0.45)
    text(68 + BUTTON / 2, 157.5, f"按钮 {BUTTON:.0f}×{BUTTON:.0f}", size=2.4, anchor="middle")
    rect(82, 148, USBC_W, USBC_H, "#333", "#eee", 0.45)
    text(82 + USBC_W / 2, 156, f"USB-C {USBC_W:.1f}×{USBC_H:.1f}", size=2.4, anchor="middle")

    # 5. case top view
    text(120, 100, f"⑤ 表壳顶视图（概念 {CASE_W:.0f}×{CASE_H:.0f}；厚度按堆叠）", size=3, weight="bold")
    cx, cy, cw, ch = 120, 120, CASE_W, CASE_H
    rect(cx, cy, cw, ch, "#333", "none", 0.5, None, 8)
    rect(cx + (cw - DISPLAY_W) / 2, cy + (ch - DISPLAY_H) / 2,
         DISPLAY_W, DISPLAY_H, "#0a7", "none", 0.3, "1.5,1")
    text(cx + cw / 2, cy - 10, f"{STRAP_W:.0f} mm 表带（耳位）", size=2.5, anchor="middle")
    for sx in (-STRAP_W / 2 + 1, STRAP_W / 2 - 1):
        x = cx + cw / 2 + sx
        line(x, cy - 4, x, cy, "#333", 0.5)
        line(x, cy + ch, x, cy + ch + 4, "#333", 0.5)
    circle(cx + cw, cy + 14, 2.6, "#333", "none", 0.4)
    circle(cx + cw, cy + 24, 2.6, "#333", "none", 0.4)
    text(cx + cw + 3, cy + 15, "按钮", size=2.2)
    text(cx + cw + 3, cy + 25, "按钮", size=2.2)
    rect(cx + cw - 10, cy + ch - USBC_H, USBC_W, USBC_H, "#333", "none", 0.4)
    text(cx + 2, cy + ch + 5, "USB-C", size=2.2)
    text(cx + cw / 2, cy + ch + 11,
         f"表壳 {CASE_W:.0f}×{CASE_H:.0f}；屏开窗 {DISPLAY_W:.1f}×{DISPLAY_H:.1f}",
         size=2.5, anchor="middle")

    # 6. scale + notes
    text(10, 250, "⑥ 50 mm 比例尺（打印后应正好 50 mm）", size=3, weight="bold")
    line(10, 256, 60, 256, "#111", 0.6)
    for i in range(0, 51, 5):
        line(10 + i, 256, 10 + i, 253 if i % 10 == 0 else 254.5, "#111", 0.4)
    text(10, 262, "0", size=2.4)
    text(60, 262, "50 mm", size=2.4, anchor="end")
    text(10, 270, "说明：标准尺寸仅用于第一版试装；把实物放在对应轮廓上，标记偏差（长/宽/孔位/排针/厚度）。",
         size=2.6, color="#444")
    text(10, 275, "关键未知：屏模块外形/排针/厚度、SuperMini USB-C/电池焊盘/天线端、MAX30102 光窗中心/厚度、按钮高度、电池实物。",
         size=2.6, color="#a00")
    text(10, 280, "参数化脚本：watch_template.py；改上方参数后重新运行即可生成新模板。",
         size=2.6, color="#444")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}mm" height="{PAGE_H}mm" '
        f'viewBox="0 0 {PAGE_W} {PAGE_H}">\n' + "\n".join(parts) + "\n</svg>\n"
    )


if __name__ == "__main__":
    out = Path(__file__).with_name("fit-template.svg")
    out.write_text(build())
    print(f"wrote {out}")
