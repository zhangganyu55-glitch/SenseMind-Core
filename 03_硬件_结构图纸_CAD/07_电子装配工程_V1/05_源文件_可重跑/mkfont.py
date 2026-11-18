"""按当前绘图脚本用到的字符重建 CJK 子集字体（避免缺字）。"""
import os, sys, glob
from fontTools.ttLib import TTCollection
from fontTools import subset

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/System/Library/Fonts/STHeiti Medium.ttc"
OUT = os.path.join(HERE, "fonts", "SenseMindCJK.ttf")

chars = set(chr(c) for c in range(0x20, 0x7F))
for p in glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "*.md")):
    chars |= set(open(p, encoding="utf-8").read())
# 额外常用字保险
chars |= set("电压电流电阻电容接地信号引脚焊接线束走线长度规格连接器选型报告装配顺序"
             "上电检查清单联调测试计划外壳结构板屏幕电池传感器载板固定对位实测待核准确"
             "认风险冲突禁止事项图示说明整根管星形汇接倒灌短路测量通断绝缘热缩")

coll = TTCollection(SRC)
f = max(coll.fonts, key=lambda x: len(x.getBestCmap()))
tmp = "/tmp/STHeiti_full.ttf"
f.save(tmp)
opts = subset.Options(); opts.name_IDs = ["*"]; opts.notdef_outline = True
font = subset.load_font(tmp, opts)
sub = subset.Subsetter(opts)
sub.populate(text="".join(sorted(chars)))
sub.subset(font)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
font.save(OUT)
print(f"font rebuilt: {len(chars)} chars, {os.path.getsize(OUT)//1024} KB")
