#!/bin/bash
# 按 watch_v1_params.json 重新生成 STEP / STL / 图纸 / 预览图 / 渲染图
# 用法：双击运行，或 bash 重新生成.command
# 依赖：Python + build123d（必需）；Blender（仅渲染图，可选）
#      如未自动找到，可显式指定：PY=/path/to/python BL=/path/to/Blender bash 重新生成.command
cd "$(dirname "$0")" || exit 1

# ---- 输出根目录：若当前目录是“交付总包/源文件”结构，就输出回总包；否则输出到本目录 ----
OUT="."
if [ -d "../CAD模型_STEP" ] || [ -d "../图纸_PDF" ] || [ -d "../打印文件_STL" ]; then
  OUT=".."
fi

# ---- 定位 Python（优先 $PY，其次本目录 .venv，再次系统 python3）----
if [ -z "${PY:-}" ]; then
  if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  fi
fi
if [ -z "${PY:-}" ] || ! "$PY" -c "import build123d" >/dev/null 2>&1; then
  echo "找不到可用的 Python/build123d。"
  echo "请先安装：python3 -m venv .venv && .venv/bin/pip install build123d"
  echo "或指定：PY=/path/to/python bash 重新生成.command"
  exit 1
fi

# ---- 定位 Blender（可选，仅用于渲染图）----
if [ -z "${BL:-}" ]; then
  for c in "/Applications/Blender.app/Contents/MacOS/Blender" \
           "$HOME/Applications/Blender.app/Contents/MacOS/Blender" \
           "$(command -v blender 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] && BL="$c" && break
  done
fi

"$PY" watch_v1_cad.py --out . || exit 1
"$PY" watch_v1_docs.py   || exit 1
"$PY" watch_v1_render.py || exit 1

mkdir -p "$OUT/CAD模型_STEP" "$OUT/图纸_PDF" "$OUT/打印文件_STL" "$OUT/预览图" "$OUT/渲染图"
mv -f ./*.stl  "$OUT/打印文件_STL/" 2>/dev/null
mv -f ./*.step "$OUT/CAD模型_STEP/" 2>/dev/null
mv -f ./*.pdf  "$OUT/图纸_PDF/" 2>/dev/null
[ -d ./01_预览图 ] && mv -f ./01_预览图/*.png "$OUT/预览图/" 2>/dev/null && rmdir ./01_预览图 2>/dev/null

if [ -n "${BL:-}" ] && [ -x "$BL" ]; then
  "$BL" -b --factory-startup -P watch_v1_blender.py -- \
    --shot hero --samples 64 --res 1800x1350 \
    --out "$OUT/渲染图/01_主图_34.png"
else
  echo "未找到 Blender，跳过渲染图（其余产物已生成）。"
fi

echo "完成：STEP / STL / 图纸 / 预览图 已更新。"
read -r -p "按回车关闭" _
