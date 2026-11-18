"""Sheet 03 · 内部线束走线图（双视图：正面层 / 背面层）。
几何来自 STEP 装配体实测（mm）：壳体 ±21/±24（表耳 ±29.4）；内腔 38×44；
板 X −8.75..8.75, Y −21..12.5；屏 X ±15.75, Y ±15.5；电池 X ±12.5, Y 1.5..21.5；
载板 X −16.15..16.38, Y −19.93..0.93；USB-C 在 Y=−21 侧；按键在 X=+21 侧。
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheet import Sheet, INK, GREEN, RED, PURPLE, ORANGE, TEAL, GREY

s = Sheet("内部线束走线图 · 正面层 / 背面层", "H3-E-03", 594, 420)
s.frame("2026-11-04 · 几何取自 SenseMind H3-05 V1.3 STEP 实测 · 未修改外壳 · 比例 2.7:1")

def rounded_rect(w, h, r, n=10):
    pts, hw, hh = [], w / 2, h / 2
    for cx, cy, a0 in [(hw-r, hh-r, 0), (-hw+r, hh-r, 90), (-hw+r, -hh+r, 180), (hw-r, -hh+r, 270)]:
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts

class View:
    def __init__(self, ox, oy, k, title, subtitle):
        self.ox, self.oy, self.k, self.title, self.subtitle = ox, oy, k, title, subtitle
    def P(self, x, y): return (self.ox + x*self.k, self.oy + y*self.k)
    def poly(self, pts, c=INK, w=0.5, f=None): s.poly([self.P(x,y) for x,y in pts], c, w, f)
    def rect(self, x, y, w, h, c=INK, lw=0.5, f=None):
        p = self.P(x, y); s.rect(p[0], p[1], w*self.k, h*self.k, c, lw, f)
    def line(self, pts, c=INK, lw=0.5): s.line([self.P(x,y) for x,y in pts], c, lw)
    def circle(self, x, y, r, c=INK, lw=0.5, f=None): s.circle(*self.P(x,y), r*self.k, c, lw, f)
    def text(self, x, y, t, size=2.4, c=INK, a="l", w="normal"): s.text(*self.P(x,y), t, size*1.55, c, anchor=a, weight=w)
    def header(self):
        hx, hy = self.P(0, 28.0)
        s.text(hx, hy, self.title, 4.2, INK, anchor="c", weight="bold")
        s.text(hx, hy-6.0, self.subtitle, 2.6, GREY, anchor="c")
    def body(self, f="#FFFFFF"):
        self.poly(rounded_rect(42, 48, 9), INK, 1.0, f)
        for sy in (+1, -1):
            self.poly([(-5, sy*24), (-5, sy*29.4), (5, sy*29.4), (5, sy*24)], INK, 0.7, f)
            self.circle(0, sy*27.5, 0.8, INK, 0.5)

# ---------------- 正面层 ----------------
V1 = View(140, 196, 2.7, "A · 正面层（表镜侧）", "屏幕在前、主板在后；屏排针朝 −Y")
V1.header(); V1.body()
V1.poly([(-15.75,-15.5),(15.75,-15.5),(15.75,15.5),(-15.75,15.5)], ORANGE, 0.9, "#FFF3E0")
V1.text(-14.8, 13.0, "H1 屏幕 31.5×31×3.5", 2.1, ORANGE, w="bold")
V1.text(-14.8, 9.6, "8P 排针朝 −Y（USB-C 端）", 1.9, INK)
V1.rect(-13.86, -13.86, 27.72, 27.72, ORANGE, 0.5, "#FFFFFF")
V1.text(0, 0, "有效显示区 27.72²", 1.9, GREY, a="c")
V1.poly([(-8.75,-21),(8.75,-21),(8.75,12.5),(-8.75,12.5)], INK, 0.5, None)
V1.text(-8.0, -16.6, "U1 主板（屏后）", 1.9, INK)
V1.text(-8.0, -19.4, "33.0 × 17.78", 1.8, GREY)
for nm, y in [("SW1",6),("SW2",-4)]:
    V1.rect(18.9-2.6, y-2.5, 5.2, 5.0, TEAL, 0.8, "#E0F2F1")
    V1.text(21.6, y-0.9, nm, 1.7, TEAL)
V1.rect(-4.45, -22.6, 8.9, 4.2, INK, 0.6, "#ECEFF1")
V1.text(0, -25.9, "USB-C 开口", 1.8, INK, a="c")
s.line([V1.P(-21,-26.8), V1.P(21,-26.8)], GREY, 0.3)
s.text(*V1.P(0,-28.8), "42.0", 2.0, GREY, anchor="c")
s.line([V1.P(23.4,-24), V1.P(23.4,24)], GREY, 0.3)
s.text(*V1.P(24.8,0), "48.0", 2.0, GREY, anchor="c", rotation=90)

# ---------------- 背面层 ----------------
V2 = View(400, 196, 2.7, "B · 背面层（开盖后）", "电池 / 主板 / 载板 / 三束走线")
V2.header(); V2.body("#FAFAFA")
V2.poly(rounded_rect(38, 44, 7), GREY, 0.4, None)
V2.poly([(-15.75,-15.5),(15.75,-15.5),(15.75,15.5),(-15.75,15.5)], "#BDBDBD", 0.4, None)
V2.poly([(-8.75,-21),(8.75,-21),(8.75,12.5),(-8.75,12.5)], INK, 1.0, "#FFFDE7")
V2.text(-8.0, 9.6, "U1 主板", 2.1, INK, w="bold")
V2.text(-8.0, 6.8, "33.5 × 17.5", 1.8, GREY)
V2.rect(-7.5, 2.5, 15, 10, RED, 0.5, "#FFEBEE")
V2.text(-7.0, 8.2, "天线 keepout", 1.8, RED)
for i, nm in enumerate(["SCK","MOSI","CS"]):
    V2.rect(-3.8+i*3.8-1.2, -22.6, 2.4, 1.6, ORANGE, 0.4, "#FFE0B2")
    V2.text(-3.8+i*3.8, -24.6, nm, 1.4, ORANGE, a="c")
for i, nm in enumerate(["D4","D5","D6","D7","D8","D9"]):
    y = 10.5 - i*2.54
    V2.rect(-9.85, y-0.9, 2.2, 1.8, INK, 0.3, "#FFE0B2")
    V2.text(-10.7, y-0.7, nm, 1.4, INK, a="r")
V2.poly([(-12.5,1.5),(12.5,1.5),(12.5,21.5),(-12.5,21.5)], RED, 1.0, "#FFF5F5")
V2.text(-11.8, 19.2, "BT1 电池 25×20×5", 2.0, RED, w="bold")
V2.text(-11.8, 16.2, "0.2 双面胶固定", 1.7)
V2.text(-11.8, 13.4, "禁止挤压", 1.7, RED)
V2.poly([(-16.15,-19.93),(16.38,-19.93),(16.38,0.93),(-16.15,0.93)], PURPLE, 0.8, "#F3E5F5")
V2.text(-15.4, -1.2, "载板 32.5 × 20.9", 1.8, PURPLE, w="bold")
V2.rect(-15.35, -19.5, 15.5, 20, PURPLE, 0.6, "#FFFFFF")
V2.text(-7.6, -9.0, "MAX", 1.7, PURPLE, a="c")
V2.rect(0.52, -19.63, 15.56, 20.26, PURPLE, 0.6, "#FFFFFF")
V2.text(8.3, -9.0, "MPU", 1.7, PURPLE, a="c")
for nm, y in [("SW1",6),("SW2",-4)]:
    V2.rect(18.9-2.6, y-2.5, 5.2, 5.0, TEAL, 0.7, "#E0F2F1")
    V2.text(21.5, y-0.9, nm, 1.5, TEAL)
# 三束
V2.line([(-1.5,-21.4),(-18.0,-21.4),(-18.0,-12.5)], ORANGE, 3.4)
V2.line([(-18.0,-12.5),(-18.0,-17.2),(-15.2,-17.2)], ORANGE, 1.8)
V2.line([(-18.0,-20.2),(14.2,-20.2),(14.2,-12.2)], PURPLE, 1.6)
V2.text(-18.9, -15.6, "A", 2.4, ORANGE, a="r", w="bold")
V2.line([(-9.8,12.8),(-9.8,20.8),(18.0,20.8),(18.0,7.8)], TEAL, 2.4)
V2.line([(18.0,12.2),(18.0,-2.2)], TEAL, 1.6)
V2.text(-9.0, 22.2, "B 束（按键）", 1.8, TEAL)
V2.line([(-12.2,14.0),(-7.8,14.0),(-7.8,12.6)], RED, 2.2)
V2.text(-12.2, 15.6, "C 束（VBAT）", 1.7, RED)
V2.text(-8.6, 11.0, "x=−7.8 线槽", 1.4, GREY)
s.line([V2.P(-21,-26.8), V2.P(21,-26.8)], GREY, 0.3)
s.text(*V2.P(0,-28.8), "42.0", 2.0, GREY, anchor="c")

# ---------------- 说明 ----------------
X0 = 470
s.text(X0, 398, "三束走线", 3.6, INK, weight="bold")
items = [("A 束 · 屏 + 传感器（16 根）", ORANGE),
         ("板底 SPI + D4/D5 → 左内壁 x≈−18", INK),
         ("→ 屏背面 → 分支到载板两侧", INK),
         ("单层排布，每 15 mm 一点 UV 胶", INK),
         ("B 束 · 按键（4 根）", TEAL),
         ("D8/D9 → 内壁上沿 y≈20.8 → 右侧按键", INK),
         ("与电池保持 ≥ 2 mm", INK),
         ("C 束 · 电池（2 根，26AWG）", RED),
         ("B+/B− → x=−7.8 线槽 → 电池引线", INK),
         ("禁止与天线区并行走线", RED)]
y = 390
for text, col in items:
    s.text(X0, y, text, 2.1, col, weight="bold" if "·" in text else "normal")
    y -= 7.4
s.text(X0, 288, "固定与拆卸", 3.2, INK, weight="bold")
for i, f in enumerate(["1. 不开新孔，全部贴内壁走线，UV 胶点 3–4 处。",
                       "2. 拆卸顺序：断电池 → 取载板 → 取主板 → 取屏。",
                       "3. 焊点套 1.5 mm 热缩管，应力落在胶点。",
                       "4. 线不得压在电池表面或屏排针上。"]):
    s.text(X0, 280-i*7.0, f, 1.95)
s.rect(330, 62, 244, 56, RED, 0.6, "#FFF5F5")
s.text(334, 110, "[!] 走线相关结构冲突（已报告，未改 V1.3）", 2.7, RED, weight="bold")
for i, c in enumerate(["① 电池覆盖板 +Y 天线区，RF 风险；不擅自改壳。",
                       "② 电池背面到内腔底仅 0.3 mm，线不得穿过。",
                       "③ 屏背面到板面净空 2.1 mm，是屏线唯一通道。",
                       "④ 载板与电池 Y 向仅 0.6 mm，线不得从此穿过。"]):
    s.text(334, 101-i*7.0, c, 1.95)
s.save("03_内部线束走线图.dxf", "03_内部线束走线图.png")
print("sheet 03 done")
