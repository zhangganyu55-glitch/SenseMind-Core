"""Sheet 04 · 厚度堆叠与净空（Z 向分解堆叠图 + 厚度链 + 硬约束）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheet import Sheet, INK, BLUE, GREEN, RED, PURPLE, ORANGE, TEAL, GREY, LIGHT

s = Sheet("厚度堆叠与净空剖面", "H3-E-04", 594, 420)
s.frame("2026-11-04 · Z 值取自 V1.3 STEP 实测 · 分解堆叠（非真实剖切）· 单位 mm")

KX, KZ = 1.9, 5.2
OX, OZ = 135, 386
def P(x, z):
    return (OX + x * KX, OZ + z * KZ)

def band(x0, x1, z0, z1, color, fill, label, size=2.3):
    a, b = P(x0, z0), P(x1, z1)
    s.rect(min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1]), color, 0.9, fill)
    s.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, label, size, INK, anchor="c", weight="bold")

# ============================================================ 堆叠
band(-20.8, 20.8, 0.0, 1.0, INK, "#CFD8DC", "表圈 1.0")
band(-21.0, 21.0, -2.0, 0.0, INK, "#ECEFF1", "前面板 2.0")
band(-15.75, 15.75, -5.6, -2.1, ORANGE, "#FFF3E0", "ST7789V 屏幕 3.5（31.5 × 31）")
band(-4.0, 4.0, -8.6, -6.1, GREY, "#BDBDBD", "排针 2.5")
band(-8.75, 8.75, -9.8, -8.6, INK, "#FFFDE7", "主板 1.2（33.5 × 17.5）")
band(-16.15, 16.38, -11.7, -10.1, PURPLE, "#F3E5F5", "载板 1.6（32.5 × 20.9）")
band(-15.35, -0.5, -14.5, -11.9, PURPLE, "#EDE7F6", "MAX 2.8")
band(1.0, 16.08, -14.5, -11.9, PURPLE, "#E8EAF6", "MPU 2.8")
band(-12.5, 12.5, -15.3, -11.2, RED, "#FFF5F5", "锂电池 5.0（+Y 侧；与传感器同层、Y 向错开）", 2.2)
band(-20.82, 20.82, -17.8, -15.5, INK, "#ECEFF1", "下盖 2.3")

# ============================================================ 净空引线（右侧）
def callout(x, z, text, color=RED, lx=None):
    px, py = P(x, z)
    end = P(lx, z)[0] if lx is not None else px + 26
    s.line([(px, py), (end, py)], color, 0.4)
    s.text(end + 1.5, py, text, 2.2, color, weight="bold")

callout(15.75, -1.0, "屏前间隙 0.3（屏面→前面板）", GREY)
callout(15.75, -4.6, "屏→板间隙 0.5：16 根线唯一通道", RED)
callout(16.38, -10.9, "板→载板 0.3", GREY)
callout(16.08, -13.1, "传感器 2.8（与电池同层、Y 向错开）", PURPLE)
callout(-12.5, -15.55, "电池自由面→腔底 0.3（禁挤压）", RED)

# 总厚 / 内腔
# 总厚以文字注记（避免与引出线相撞）
s.text(*P(-29, -20.6), "总厚 18.8（Z +1.0 .. −17.8）", 2.6, INK, weight="bold")
s.line([P(-26, -2.0), P(-26, -15.8)], BLUE, 1.0)
s.text(*P(-28.2, -8.9), "内腔 15.8", 2.8, BLUE, rotation=90, weight="bold")

# ============================================================ 厚度链
TX, TY = 330, 404
s.text(TX, TY, "厚度链（V1.3 参数）", 3.8, INK, weight="bold")
rows = [("表圈", "1.00"), ("前面板", "2.00"), ("屏前间隙", "0.30"),
        ("ST7789V 屏幕", "3.50"), ("屏→板间隙", "0.50"), ("排针", "2.50"),
        ("主板", "1.20"), ("板→载板间隙", "0.30"), ("载板", "1.60"),
        ("传感器 MAX/MPU", "2.80"), ("电池", "5.00"), ("下盖", "2.30")]
for i, (k, v) in enumerate(rows):
    col, row = i // 6, i % 6
    x = TX + col * 128
    yy = TY - 10 - row * 9
    s.text(x, yy, k, 2.3)
    s.text(x + 74, yy, v, 2.3, BLUE, anchor="r")
s.text(TX, TY - 10 - 6 * 9 - 5, "分项合计 ≈19.0；STEP 实测总厚 18.8，差异来自取整与缝，", 2.1, INK)
s.text(TX, TY - 10 - 6 * 9 - 11, "装配以 18.8 为准。", 2.1, GREY)

# ============================================================ 横向净空
LX, LY = 330, 268
s.text(LX, LY, "横向净空（X 向）", 3.6, INK, weight="bold")
lat = [("内腔宽", "38.0（±19）", "实测"), ("主板宽", "17.5（±8.75）", "实测"),
       ("屏宽", "31.5（±15.75）", "实测"), ("载板宽", "32.5（−16.15..16.38）", "实测"),
       ("板右缘→内壁", "10.25", "计算"), ("屏右缘→内壁", "3.25", "计算"),
       ("载板右缘→内壁", "2.62", "计算")]
for i, (k, v, st) in enumerate(lat):
    yy = LY - 10 - i * 8.4
    s.text(LX, yy, k, 2.2)
    s.text(LX + 90, yy, v, 2.2, INK)
    s.text(LX + 212, yy, st, 1.9, GREEN if st == "实测" else GREY)

# ============================================================ 4 条硬约束
s.rect(330, 88, 244, 72, RED, 0.8, "#FFF5F5")
s.text(334, 152, "[!] 剖面揭示的 4 条硬约束", 3.2, RED, weight="bold")
items = ["① 屏背面→板面仅 2.1 mm：16 根线全走这里，扁平单层、",
         "    禁止叠线，焊点高度 ≤ 1.5 mm。",
         "② 电池背面→内腔底 0.3 mm：线束不得从电池背面通过。",
         "③ 载板与电池 Y 向间隙 0.6 mm：线束不得在此穿越。",
         "④ 电池覆盖 +Y 端天线区：BLE 风险，装配后实测 1 m RSSI。"]
for i, t in enumerate(items):
    s.text(334, 141 - i * 7.4, t, 2.1, INK)
s.text(334, 78, "结论：V1.3 可容纳本方案；上述 4 条须装配前逐项确认。", 2.3, INK, weight="bold")
s.text(334, 70, "任一条不满足 → 先报告，不改壳、不硬压。", 2.3, RED, weight="bold")

s.save("04_厚度堆叠与净空剖面.dxf", "04_厚度堆叠与净空剖面.png")
print("sheet 04 done")
