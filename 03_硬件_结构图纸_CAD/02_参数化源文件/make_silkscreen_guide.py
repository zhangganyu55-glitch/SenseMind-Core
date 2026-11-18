"""示意图：nRF52840 SuperMini 板上，丝印在哪几个位置。"""
from PIL import Image, ImageDraw, ImageFont

SS = 2
W, H = 1600, 760
img = Image.new("RGB", (W*SS, H*SS), "white")
d = ImageDraw.Draw(img)

F = "/System/Library/Fonts/STHeiti Medium.ttc"
f_title = ImageFont.truetype(F, 34*SS)
f_head  = ImageFont.truetype(F, 24*SS)
f_body  = ImageFont.truetype(F, 19*SS)
f_tag   = ImageFont.truetype(F, 19*SS)
f_num   = ImageFont.truetype(F, 20*SS)

S = 21 * SS
BX, BY = 100*SS, 120*SS
BW, BH = 18*S, 28*S

def P(x, y):
    return BX + x*S, BY + (28 - y)*S

def rect(x0, y0, x1, y1, **kw):
    d.rectangle([P(x0, y1), P(x1, y0)], **kw)

def mark(n, x, y, color):
    cx, cy = P(x, y)
    r = 13*SS
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=color, outline="white", width=2*SS)
    d.text((cx, cy), str(n), font=f_num, fill="white", anchor="mm")

# 板
d.rounded_rectangle([BX, BY, BX+BW, BY+BH], radius=1.1*S,
                    fill=(233, 239, 235), outline=(60, 95, 72), width=3*SS)

# USB-C
rect(4.55, 0, 13.45, 6.0, fill=(182, 187, 192), outline=(70, 70, 70))
d.text(P(9, 3.0), "USB-C", font=f_tag, fill=(25, 25, 25), anchor="mm")

# 充电 IC
rect(5.2, 8.4, 8.1, 10.0, fill=(32, 32, 32), outline=(0, 0, 0))
for i in range(3):
    rect(4.85, 8.55+i*0.5, 5.2, 8.75+i*0.5, fill=(198, 198, 198))
for i in range(2):
    rect(8.1, 8.8+i*0.5, 8.45, 9.0+i*0.5, fill=(198, 198, 198))

# B+/B-
rect(11.5, 24.6, 13.7, 26.6, fill=(216, 165, 95), outline=(120, 80, 40))
rect(14.3, 24.6, 16.5, 26.6, fill=(216, 165, 95), outline=(120, 80, 40))
d.text(P(12.6, 25.6), "B+", font=f_tag, fill=(45, 32, 20), anchor="mm")
d.text(P(15.4, 25.6), "B−", font=f_tag, fill=(45, 32, 20), anchor="mm")

# 天线区
d.rounded_rectangle([P(2.2, 20.0), P(15.8, 12.0)], radius=6*SS,
                    outline=(140, 140, 190), width=2*SS)

# 编号标记
mark(1, 10.2, 9.2,  (200, 60, 40))
mark(2, 9.0, 6.9,   (205, 130, 25))
mark(3, 14.0, 23.4, (40, 125, 190))
mark(4, 9.0, 16.0,  (120, 120, 190))

# 图例
LX = 520*SS
rows = [
    (1, (200, 60, 40),  "充电芯片（5 脚，SOT-23-5）",
        ["就在 USB-C 口内侧 2~5 mm 处", "顶面刻的 3~4 位短码 = 丝印"]),
    (2, (205, 130, 25), "USB-C 座",
        ["充电从这里进，5V 走线最短的地方"]),
    (3, (40, 125, 190), "电池焊盘 B+ / B−",
        ["这两个白字是 PCB 丝印", "（和芯片丝印不是一回事）"]),
    (4, (120, 120, 190), "天线净空区",
        ["这上面别贴电池、别放金属"]),
]
y = 150*SS
for n, col, head, lines in rows:
    r = 13*SS
    d.ellipse([LX-r, y-r, LX+r, y+r], fill=col)
    d.text((LX, y), str(n), font=f_num, fill="white", anchor="mm")
    d.text((LX+26*SS, y), head, font=f_head, fill=(20, 20, 20), anchor="lm")
    y += 34*SS
    for ln in lines:
        d.text((LX+26*SS, y), ln, font=f_body, fill=(95, 95, 95), anchor="lm")
        y += 27*SS
    y += 26*SS

d.text((60*SS, 46*SS), "丝印在哪：nRF52840 SuperMini 主板", font=f_title, fill=(20, 20, 20))
d.text((60*SS, 86*SS), "示意图，非实物照片；B+ / B− 的实际位置随板子版本不同",
       font=f_body, fill=(120, 120, 120))

img.resize((W, H), Image.LANCZOS).save("board_silkscreen_guide.png")
print("saved")
