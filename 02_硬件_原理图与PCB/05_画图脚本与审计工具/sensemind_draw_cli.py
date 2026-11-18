#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyEDA Draw CLI - 原理图绘制命令行工具 (Python 版)

用法:
    ./draw_cli.py <command> [options]
    python3 draw_cli.py <command> [options]

环境变量:
    EDA_BRIDGE_PORT    Bridge server 端口 (默认 49620)

设计原则:
    1. 移除 exec 命令——强制使用语义化命令，禁止传任意代码字符串
    2. 默认紧凑输出 (单行 JSON, 只含关键字段)，避免 AI 输出截断
       --verbose / -v: 完整缩进 JSON (调试用)
       --quiet   / -q: 只输出 id (shell 管道用)
    3. 所有防护函数封装已探明的 API 坑 (rotation 反转/Y 轴方向/参数顺序)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import subprocess
import base64
import hashlib
import time
from pathlib import Path

# Optional official client backend. The inherited semantic commands remain the
# only public execution surface; no arbitrary-code command is exposed.
NATIVE_CLI = os.environ.get("SENSEMIND_EDA_CLI")
NATIVE_SESSION = os.environ.get("SENSEMIND_EDA_SESSION")
NATIVE_TIMEOUT_MS = int(os.environ.get("SENSEMIND_EDA_TIMEOUT_MS", "120000"))
EVIDENCE_DIR = Path(os.environ.get("SENSEMIND_EDA_EVIDENCE_DIR", str(Path(__file__).parent / "eda-api-evidence")))
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def native_call(arguments):
    """Run the vendor client directly without invoking a shell."""
    if not NATIVE_CLI:
        raise RuntimeError("Set SENSEMIND_EDA_CLI to the official client executable")
    completed = subprocess.run(
        [NATIVE_CLI] + arguments, capture_output=True, text=True,
        timeout=NATIVE_TIMEOUT_MS / 1000 + 30,
    )
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("Official CLI did not return JSON: %s" % completed.stdout[:1000])
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = str(time.time_ns())
    (EVIDENCE_DIR / (stamp + ".json")).write_text(json.dumps({
        "arguments": arguments, "returncode": completed.returncode,
        "envelope": envelope, "stderr": completed.stderr,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if completed.returncode or envelope.get("ok") is not True:
        raise RuntimeError("Official CLI failed: %s" % json.dumps(envelope, ensure_ascii=False))
    return envelope.get("value")

# ═══════════════════════════════════════════════════════════════════
# 常量：已探明的 API 坑，用常量固化，防止 AI 遗忘
# ═══════════════════════════════════════════════════════════════════

# Bridge server 端口范围 (与 easyeda-api skill 一致)
BRIDGE_PORT_RANGE = range(49620, 49630)
# 用户可通过 EDA_BRIDGE_PORT 环境变量强制指定端口，跳过自动发现
BRIDGE_PORT_FORCED = os.environ.get("EDA_BRIDGE_PORT")
BRIDGE_PORT_CACHED = None  # 自动发现后缓存

# sch_PrimitivePin.create() 的 rotation 参数会被 API 反转存储。
# 调用方传下面的值，API 内部会存为相反值，但视觉效果正确。
# 映射: side -> 应传入的 rotation 值
PIN_ROTATION_BY_SIDE = {
    "left": 0,       # 传 0 -> 存储 180 -> 向左延伸
    "right": 180,    # 传 180 -> 存储 0 -> 向右延伸
    "top": 270,      # 传 270 -> 存储 90 -> 向上延伸
    "bottom": 90,    # 传 90 -> 存储 270 -> 向下延伸
}

# 网络标签 (NetPort/NetFlag) 的 rotation 决定文字延伸方向和连接点位置。
# 核心原则: 文字远离芯片，连接点朝向芯片。
LABEL_ROTATION_BY_SIDE = {
    "left": 180,
    "right": 0,
    "top": 270,
    "bottom": 90,
}

# 标签与引脚之间的最小距离 (导线长度)。
# 距离太小会导致标签文字与引脚名/器件体重叠。
LABEL_WIRE_LENGTH = 100

# sch_PrimitiveComponent.getAllPrimitiveId(componentType, allPages) 关键经验:
# 不加 componentType 参数 -> 只返回 Component(器件)，不包含 netport/netflag/netlabel!
COMPONENT_TYPES = {
    "PART": "part",
    "NET_PORT": "netport",
    "NET_LABEL": "netlabel",
    "NET_FLAG": "netflag",
    "SHEET": "sheet",
    "NON_ELECTRICAL": "nonElectrical_symbol",
    "SHORT_CIRCUIT": "short_symbol",
}

# lib_Device.delete() 和 lib_Symbol.delete() 的参数顺序是 (uuid, libraryUuid)，
# 不是 (libraryUuid, uuid)。
DELETE_API_PARAM_ORDER = "delete(uuid, libraryUuid)"


# ═══════════════════════════════════════════════════════════════════
# HTTP 通信层
# ═══════════════════════════════════════════════════════════════════

def _http_get_json(url, timeout=2):
    """GET 请求并解析 JSON，失败返回 None"""
    try:
        with LOCAL_HTTP.open(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def discover_bridge_port():
    """扫描 49620-49629 端口范围，返回 bridge server 的端口号。

    优先级:
        1. EDA_BRIDGE_PORT 环境变量 (强制指定)
        2. 自动扫描端口范围，验证 /health 返回 {"service":"easyeda-bridge"}
        3. 缓存发现结果，避免重复扫描
    """
    global BRIDGE_PORT_CACHED
    if BRIDGE_PORT_CACHED:
        return BRIDGE_PORT_CACHED
    if BRIDGE_PORT_FORCED:
        BRIDGE_PORT_CACHED = int(BRIDGE_PORT_FORCED)
        return BRIDGE_PORT_CACHED
    for port in BRIDGE_PORT_RANGE:
        data = _http_get_json("http://localhost:%d/health" % port)
        if data and data.get("service") == "easyeda-bridge":
            BRIDGE_PORT_CACHED = port
            return port
    return None


def get_bridge_url(path="/execute"):
    """获取 bridge server 的完整 URL，自动发现端口"""
    port = discover_bridge_port()
    if port is None:
        raise RuntimeError(
            "Cannot find bridge server. Scanned ports 49620-49629, none responded.\n"
            "请确认:\n"
            "  1. EasyEDA Pro 已打开\n"
            "  2. bridge-server 已启动 (见 easyeda-api skill)\n"
            "  3. run-api-gateway.eext 扩展已加载\n"
            "或手动指定端口: export EDA_BRIDGE_PORT=49620"
        )
    return "http://localhost:%d%s" % (port, path)


def check_health():
    """检查 bridge server 和 EDA 连通性

    返回 dict:
        {bridge: bool, port: int, edaConnected: bool, windows: [...], activeWindow: str}
    """
    if NATIVE_CLI:
        doctor = native_call(["doctor"])
        sessions = native_call(["session", "list"])
        return {"backend": "official-cli", "doctor": doctor,
                "sessions": sessions, "session": NATIVE_SESSION,
                "edaConnected": bool(doctor and doctor.get("connected")),
                "summary": "Official client probed; inspect doctor and session fields"}
    port = discover_bridge_port()
    if port is None:
        return {"bridge": False, "port": None, "edaConnected": False,
                "windows": [], "summary": "Bridge server 未运行"}
    health = _http_get_json("http://localhost:%d/health" % port, timeout=3) or {}
    windows_data = _http_get_json("http://localhost:%d/eda-windows" % port, timeout=3) or {}
    windows = windows_data.get("windows", [])
    active = windows_data.get("activeWindowId")
    return {
        "bridge": True,
        "port": port,
        "edaConnected": health.get("edaConnected", False),
        "windows": [{"id": w.get("windowId"), "active": w.get("active"),
                     "connected": w.get("connected")} for w in windows],
        "activeWindow": active,
        "summary": "Bridge OK (port %d), EDA %s" % (
            port, "connected" if health.get("edaConnected") else "NOT connected"),
    }


def exec_code(code):
    """Execute internally generated code via the selected client transport."""
    if NATIVE_CLI:
        if not NATIVE_SESSION:
            raise RuntimeError("Set SENSEMIND_EDA_SESSION to the dedicated SenseMind session ID")
        return native_call(["invoke", "--session", NATIVE_SESSION,
                            "--ext-uuid", "eda", "--timeout", str(NATIVE_TIMEOUT_MS),
                            "--code", code])
    url = get_bridge_url("/execute")
    payload = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with LOCAL_HTTP.open(req, timeout=NATIVE_TIMEOUT_MS / 1000) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success"):
                raise RuntimeError(data.get("error", "Unknown error"))
            return data.get("result")
    except urllib.error.URLError as e:
        raise RuntimeError(
            "Cannot connect to bridge server at %s: %s\n"
            "请确认 EasyEDA 已打开且 bridge-server 扩展已启动。"
            % (url, e)
        )


# ═══════════════════════════════════════════════════════════════════
# 输出层 (精简输出, 解决"输出截断"痛点)
# ═══════════════════════════════════════════════════════════════════

def emit(result, summary=None, verbose=False, quiet=False, extra_keys=None):
    """统一输出格式

    默认: 完整数据, 单行 JSON (紧凑但不隐藏数据)
    --verbose: 完整数据, 缩进 JSON (调试用)
    --quiet: 只输出 id (管道友好)
    """
    if quiet:
        if isinstance(result, dict) and "id" in result:
            print(result["id"])
        elif isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, ensure_ascii=False))
        return

    if verbose:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # 默认: 完整数据, 单行紧凑 JSON
    if isinstance(result, dict):
        out = dict(result)
        if summary and "summary" not in out:
            out["summary"] = summary
        print(json.dumps(out, ensure_ascii=False))
    elif isinstance(result, list):
        wrapper = {"ok": True, "count": len(result), "items": result}
        if summary:
            wrapper["summary"] = summary
        print(json.dumps(wrapper, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))


def emit_error(msg):
    """错误输出到 stderr, 退出码 1"""
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
          file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# 环境检查
# ═══════════════════════════════════════════════════════════════════

def ensure_schematic():
    doc = exec_code("return await eda.dmt_SelectControl.getCurrentDocumentInfo();")
    if not doc or doc.get("documentType") != 1:
        dt = doc.get("documentType") if doc else "null"
        raise RuntimeError("Current document is not a schematic page (documentType=%s)" % dt)
    return True


def ensure_symbol_editor():
    doc = exec_code("return await eda.dmt_SelectControl.getCurrentDocumentInfo();")
    if not doc or doc.get("documentType") != 2:
        dt = doc.get("documentType") if doc else "null"
        raise RuntimeError("Current document is not a symbol editor (documentType=%s). Open a symbol in editor first." % dt)
    return True


# ═══════════════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════════════

def js_str(s):
    """转义为 JS 字符串字面量 (带双引号)"""
    if s is None:
        return "null"
    return json.dumps(str(s), ensure_ascii=False)


def js_val(v):
    """转义为 JS 值: None->null, bool->true/false, str->"...", num->数字"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return js_str(v)


# ═══════════════════════════════════════════════════════════════════
# 原理图操作防护函数
# ═══════════════════════════════════════════════════════════════════

def clear_page(keep_ids=None, delete_text=False, delete_rects=False):
    keep_ids = keep_ids or []
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const keepSet = new Set(%s);
        const toDelete = compIds.filter(id => !keepSet.has(id));
        if (toDelete.length > 0) await eda.sch_PrimitiveComponent.delete(toDelete);

        let textCount = 0, rectCount = 0;
        %s
        %s

        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        if (wireIds.length > 0) await eda.sch_PrimitiveWire.delete(wireIds);

        return {
            components: toDelete.length,
            texts: textCount,
            rectangles: rectCount,
            wires: wireIds.length,
        };
    ''' % (
        json.dumps(keep_ids),
        '''
        const textIds = await eda.sch_PrimitiveText.getAllPrimitiveId();
        if (textIds.length > 0) { await eda.sch_PrimitiveText.delete(textIds); textCount = textIds.length; }
        ''' if delete_text else '',
        '''
        const rectIds = await eda.sch_PrimitiveRectangle.getAllPrimitiveId();
        if (rectIds.length > 0) { await eda.sch_PrimitiveRectangle.delete(rectIds); rectCount = rectIds.length; }
        ''' if delete_rects else '',
    )
    return exec_code(code)


def delete_wires(region=None, nets=None, exclude_nets=None):
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const details = [];
        const toDelete = [];

        const netFilter = %s;
        const excludeSet = %s;
        const region = %s;

        for (const id of wireIds) {
            const wires = await eda.sch_PrimitiveWire.get([id]);
            const w = wires[0];
            if (!w) continue;

            const coords = w.getState_Line();
            const net = w.getState_Net();

            if (region) {
                let inRegion = false;
                const flat = Array.isArray(coords[0]) ? coords.flat() : coords;
                for (let i = 0; i < flat.length - 1; i += 2) {
                    if (flat[i] >= region.minX && flat[i] <= region.maxX &&
                        flat[i+1] >= region.minY && flat[i+1] <= region.maxY) {
                        inRegion = true;
                        break;
                    }
                }
                if (!inRegion) continue;
            }

            if (netFilter && !netFilter.includes(net)) continue;
            if (excludeSet && excludeSet.has(net)) continue;

            toDelete.push(id);
            details.push({ id, net, coords });
        }

        if (toDelete.length > 0) await eda.sch_PrimitiveWire.delete(toDelete);

        return { deleted: toDelete.length, total: wireIds.length, details };
    ''' % (
        json.dumps(nets) if nets else "null",
        "new Set(%s)" % json.dumps(exclude_nets) if exclude_nets else "null",
        json.dumps(region) if region else "null",
    )
    return exec_code(code)


def delete_wires_by_coords(coord_sets):
    """按坐标精确删除导线 (忽略坐标方向)"""
    def normalize(flat):
        if len(flat) < 4:
            return flat
        a = [flat[0], flat[1]]
        b = [flat[2], flat[3]]
        pts = sorted([a, b], key=lambda p: (p[0], p[1]))
        return pts[0] + pts[1]

    targets = [json.dumps(normalize(c)) for c in coord_sets]
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const targets = new Set(%s);
        const toDelete = [];
        const details = [];

        const normalize = (flat) => {
            if (flat.length < 4) return flat;
            const a = [flat[0], flat[1]];
            const b = [flat[2], flat[3]];
            const pts = [a, b].sort((p, q) => p[0] === q[0] ? p[1] - q[1] : p[0] - q[0]);
            return [...pts[0], ...pts[1]];
        };

        for (const id of wireIds) {
            const wires = await eda.sch_PrimitiveWire.get([id]);
            const w = wires[0];
            if (!w) continue;
            const coords = w.getState_Line();
            const flat = Array.isArray(coords[0]) ? coords.flat() : coords;
            const key = JSON.stringify(normalize(flat));
            if (targets.has(key)) {
                toDelete.push(id);
                details.push({ id, coords: flat });
            }
        }

        if (toDelete.length > 0) await eda.sch_PrimitiveWire.delete(toDelete);
        return { deleted: toDelete.length, details };
    ''' % json.dumps(targets)
    return exec_code(code)


def delete_net_labels(region=None, nets=None, exclude_nets=None):
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const netFilter = %s;
        const excludeSet = %s;
        const region = %s;
        const toDelete = [];
        const details = [];

        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps[0];
            if (!c) continue;
            if (c.componentType !== 'netport' && c.componentType !== 'netflag') continue;

            const net = c.net || c.netName || '';

            if (netFilter && !netFilter.includes(net)) continue;
            if (excludeSet && excludeSet.has(net)) continue;

            if (region) {
                if (c.x < region.minX || c.x > region.maxX || c.y < region.minY || c.y > region.maxY) continue;
            }

            toDelete.push(id);
            details.push({ id, type: c.componentType, net, x: c.x, y: c.y });
        }

        if (toDelete.length > 0) await eda.sch_PrimitiveComponent.delete(toDelete);
        return { deleted: toDelete.length, details };
    ''' % (
        json.dumps(nets) if nets else "null",
        "new Set(%s)" % json.dumps(exclude_nets) if exclude_nets else "null",
        json.dumps(region) if region else "null",
    )
    return exec_code(code)


def place_component(library_uuid, uuid, x, y, designator=None, rotation=0, mirror=False, name=None):
    """放置器件。name 为器件值/规格 (如 '10kΩ', '100nF', 'nRF52840')"""
    modify_parts = []
    if designator:
        modify_parts.append('designator: "%s"' % designator)
    if name:
        modify_parts.append('name: "%s"' % name)
    modify_code = 'await eda.sch_PrimitiveComponent.modify(id, { %s });' % ", ".join(modify_parts) if modify_parts else ''
    code = '''
        const result = await eda.sch_PrimitiveComponent.create(
            { libraryUuid: "%s", uuid: "%s" },
            %d, %d, "", %d, %s, true, true
        );
        const id = result?.primitiveId;
        %s
        return id;
    ''' % (
        library_uuid, uuid, x, y, rotation,
        "true" if mirror else "false",
        modify_code,
    )
    return exec_code(code)


def modify_component(primitive_id, changes):
    parts = []
    if "x" in changes: parts.append("x: %d" % changes["x"])
    if "y" in changes: parts.append("y: %d" % changes["y"])
    if "rotation" in changes: parts.append("rotation: %d" % changes["rotation"])
    if "mirror" in changes: parts.append("mirror: %s" % ("true" if changes["mirror"] else "false"))
    if "addIntoBom" in changes: parts.append("addIntoBom: %s" % ("true" if changes["addIntoBom"] else "false"))
    if "addIntoPcb" in changes: parts.append("addIntoPcb: %s" % ("true" if changes["addIntoPcb"] else "false"))
    if "designator" in changes:
        parts.append("designator: %s" % ("null" if changes["designator"] is None else js_str(changes["designator"])))
    if "name" in changes:
        parts.append("name: %s" % ("null" if changes["name"] is None else js_str(changes["name"])))
    if "manufacturer" in changes:
        parts.append("manufacturer: %s" % ("null" if changes["manufacturer"] is None else js_str(changes["manufacturer"])))
    if "manufacturerId" in changes:
        parts.append("manufacturerId: %s" % ("null" if changes["manufacturerId"] is None else js_str(changes["manufacturerId"])))
    if "supplier" in changes:
        parts.append("supplier: %s" % ("null" if changes["supplier"] is None else js_str(changes["supplier"])))
    if "supplierId" in changes:
        parts.append("supplierId: %s" % ("null" if changes["supplierId"] is None else js_str(changes["supplierId"])))

    code = '''
        await eda.sch_PrimitiveComponent.modify("%s", { %s });
        return true;
    ''' % (primitive_id, ", ".join(parts))
    return exec_code(code)


def get_component(primitive_id):
    code = '''
        const comps = await eda.sch_PrimitiveComponent.get(["%s"]);
        const c = comps[0];
        const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId("%s");
        return {
            id: c.primitiveId,
            name: c.name,
            designator: c.designator,
            x: c.x, y: c.y,
            rotation: c.rotation,
            mirror: c.mirror,
            symbolName: c.symbol?.name,
            pinCount: pins?.length,
            pinPositions: pins?.map(p => ({x: p.x, y: p.y})),
        };
    ''' % (primitive_id, primitive_id)
    return exec_code(code)


def get_all_components(component_type="part"):
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("%s", false);
        const results = [];
        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            if (comps && comps.length > 0) {
                const c = comps[0];
                const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
                results.push({
                    id: c.primitiveId,
                    name: c.name,
                    designator: c.designator,
                    componentType: c.componentType,
                    x: c.x, y: c.y,
                    rotation: c.rotation,
                    mirror: c.mirror,
                    net: c.net || '',
                    direction: c.direction || '',
                    symbolName: c.symbol?.name,
                    pinCount: pins?.length,
                });
            }
        }
        return results;
    ''' % component_type
    return exec_code(code)


def find_free_space(width=100, height=100, start_x=100, start_y=100,
                    end_x=1200, end_y=900, step=50, margin=30):
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const occupied = [];
        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps[0];
            if (!c || c.componentType !== 'part') continue;
            const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
            if (!pins || pins.length === 0) {
                occupied.push({minX: c.x - 30, maxX: c.x + 30, minY: c.y - 30, maxY: c.y + 30});
                continue;
            }
            let minX=Infinity, maxX=-Infinity, minY=Infinity, maxY=-Infinity;
            for (const p of pins) {
                minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
                minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
            }
            occupied.push({
                minX: minX - %d, maxX: maxX + %d,
                minY: minY - %d, maxY: maxY + %d + 30
            });
        }

        const w = %d, h = %d;
        const sX = %d, sY = %d, eX = %d, eY = %d, step = %d;

        function overlaps(x, y) {
            const x2 = x + w, y2 = y + h;
            for (const o of occupied) {
                if (x < o.maxX && x2 > o.minX && y < o.maxY && y2 > o.minY) return true;
            }
            return false;
        }

        for (let y = sY; y < eY; y += step) {
            for (let x = sX; x < eX; x += step) {
                if (!overlaps(x, y)) return { x, y };
            }
        }
        return null;
    ''' % (margin, margin, margin, margin, width, height, start_x, start_y, end_x, end_y, step)
    return exec_code(code)


def add_text(x, y, text, rotation=0, text_color=None, font_name=None,
             font_size=8, bold=False, italic=False, underline=False, align_mode=0):
    code = '''
        const r = await eda.sch_PrimitiveText.create(
            %d, %d, %s,
            %d,
            %s,
            %s,
            %s,
            %s, %s, %s, %d
        );
        return r?.primitiveId;
    ''' % (
        x, y, js_str(text), rotation,
        js_val(text_color), js_val(font_name),
        "null" if font_size is None else str(font_size),
        "true" if bold else "false",
        "true" if italic else "false",
        "true" if underline else "false",
        align_mode,
    )
    return exec_code(code)


def get_text(primitive_id):
    code = '''
        const texts = await eda.sch_PrimitiveText.get(["%s"]);
        const t = texts[0];
        if (!t) return null;
        return {
            id: t.getState_PrimitiveId(),
            x: t.getState_X(), y: t.getState_Y(),
            content: t.getState_Content(),
            rotation: t.getState_Rotation(),
            textColor: t.getState_TextColor(),
            fontName: t.getState_FontName(),
            fontSize: t.getState_FontSize(),
            bold: t.getState_Bold(),
            italic: t.getState_Italic(),
            underLine: t.getState_UnderLine(),
            alignMode: t.getState_AlignMode(),
        };
    ''' % primitive_id
    return exec_code(code)


def get_all_texts():
    code = '''
        const texts = await eda.sch_PrimitiveText.getAll();
        return (texts || []).map(t => ({
            id: t.getState_PrimitiveId(),
            x: t.getState_X(), y: t.getState_Y(),
            content: t.getState_Content(),
            rotation: t.getState_Rotation(),
        }));
    '''
    return exec_code(code)


def delete_texts(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    code = 'return await eda.sch_PrimitiveText.delete(%s);' % json.dumps(ids_arg)
    return exec_code(code)


def modify_text(primitive_id, changes):
    setters = []
    if "x" in changes: setters.append("at.setState_X(%d);" % changes["x"])
    if "y" in changes: setters.append("at.setState_Y(%d);" % changes["y"])
    if "content" in changes: setters.append("at.setState_Content(%s);" % js_str(changes["content"]))
    if "rotation" in changes: setters.append("at.setState_Rotation(%d);" % changes["rotation"])
    if "textColor" in changes: setters.append("at.setState_TextColor(%s);" % js_val(changes["textColor"]))
    if "fontName" in changes: setters.append("at.setState_FontName(%s);" % js_val(changes["fontName"]))
    if "fontSize" in changes: setters.append("at.setState_FontSize(%s);" % js_val(changes["fontSize"]))
    if "bold" in changes: setters.append("at.setState_Bold(%s);" % ("true" if changes["bold"] else "false"))
    if "italic" in changes: setters.append("at.setState_Italic(%s);" % ("true" if changes["italic"] else "false"))
    if "underLine" in changes: setters.append("at.setState_UnderLine(%s);" % ("true" if changes["underLine"] else "false"))
    if "alignMode" in changes: setters.append("at.setState_AlignMode(%d);" % changes["alignMode"])

    code = '''
        const texts = await eda.sch_PrimitiveText.get(["%s"]);
        const t = texts[0];
        if (!t) return null;
        const at = t.toAsync();
        %s
        await at.done();
        return { id: "%s" };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def add_rect(x, y, width, height, corner_radius=0, rotation=0,
             color=None, fill_color=None, line_width=None, line_type=None, fill_style=None):
    code = '''
        const r = await eda.sch_PrimitiveRectangle.create(
            %d, %d, %d, %d,
            %d, %d,
            %s,
            %s,
            %s,
            %s,
            %s
        );
        return r?.primitiveId;
    ''' % (
        x, y, width, height, corner_radius, rotation,
        js_val(color), js_val(fill_color),
        js_val(line_width), js_val(line_type), js_val(fill_style),
    )
    return exec_code(code)


def get_rect(primitive_id):
    code = '''
        const rects = await eda.sch_PrimitiveRectangle.get(["%s"]);
        const r = rects[0];
        if (!r) return null;
        return {
            id: r.getState_PrimitiveId(),
            topLeftX: r.getState_TopLeftX(), topLeftY: r.getState_TopLeftY(),
            width: r.getState_Width(), height: r.getState_Height(),
            cornerRadius: r.getState_CornerRadius(), rotation: r.getState_Rotation(),
            color: r.getState_Color(), fillColor: r.getState_FillColor(),
            lineWidth: r.getState_LineWidth(), lineType: r.getState_LineType(),
            fillStyle: r.getState_FillStyle(),
        };
    ''' % primitive_id
    return exec_code(code)


def get_all_rects():
    code = '''
        const rects = await eda.sch_PrimitiveRectangle.getAll();
        return (rects || []).map(r => ({
            id: r.getState_PrimitiveId(),
            topLeftX: r.getState_TopLeftX(), topLeftY: r.getState_TopLeftY(),
            width: r.getState_Width(), height: r.getState_Height(),
        }));
    '''
    return exec_code(code)


def delete_rects(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitiveRectangle.delete(%s);" % json.dumps(ids_arg))


def modify_rect(primitive_id, changes):
    setters = []
    for k, setter in [("topLeftX", "TopLeftX"), ("topLeftY", "TopLeftY"),
                       ("width", "Width"), ("height", "Height"),
                       ("cornerRadius", "CornerRadius"), ("rotation", "Rotation")]:
        if k in changes:
            setters.append("ar.setState_%s(%d);" % (setter, changes[k]))
    if "color" in changes: setters.append("ar.setState_Color(%s);" % js_val(changes["color"]))
    if "fillColor" in changes: setters.append("ar.setState_FillColor(%s);" % js_val(changes["fillColor"]))
    if "lineWidth" in changes: setters.append("ar.setState_LineWidth(%s);" % js_val(changes["lineWidth"]))
    if "lineType" in changes: setters.append("ar.setState_LineType(%s);" % js_val(changes["lineType"]))
    if "fillStyle" in changes: setters.append("ar.setState_FillStyle(%s);" % js_val(changes["fillStyle"]))

    code = '''
        const rects = await eda.sch_PrimitiveRectangle.get(["%s"]);
        const r = rects[0];
        if (!r) return null;
        const ar = r.toAsync();
        %s
        await ar.done();
        return { id: "%s" };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def add_net_flag(flag_type, net, x, y, rotation=0):
    code = '''
        const r = await eda.sch_PrimitiveComponent.createNetFlag(
            "%s", "%s", %d, %d, %d, false
        );
        return r?.primitiveId;
    ''' % (flag_type, net, x, y, rotation)
    return exec_code(code)


def add_net_port(direction, net, x, y, rotation=0):
    code = '''
        const r = await eda.sch_PrimitiveComponent.createNetPort(
            "%s", "%s", %d, %d, %d, false
        );
        return r?.primitiveId;
    ''' % (direction, net, x, y, rotation)
    return exec_code(code)


def add_wire(points, net=None, color=None, line_width=None, line_type=None):
    """创建导线。

    改进: 当 net 为 None 时传空字符串 "" 而非 undefined，
    防止 API 自动从触碰的图元继承网络名（跨网络合并的根因）。
    """
    # 显式传空字符串，阻止 API 自动继承网络
    net_val = js_str(net) if net is not None else '""'
    code = '''
        const r = await eda.sch_PrimitiveWire.create(
            %s,
            %s,
            %s,
            %s,
            %s
        );
        if (!r) return { error: "Wire creation failed (possibly touching multiple different nets)" };
        return r?.primitiveId;
    ''' % (
        json.dumps(points),
        net_val,
        js_val(color), js_val(line_width), js_val(line_type),
    )
    return exec_code(code)


def check_wire_conflicts(points, net):
    """检查导线坐标是否触碰不同网络的导线/标签。

    返回: { conflicts: [{x, y, existingNet, newNet}], touchedEmpty: [{x, y}] }
    """
    code = '''
        const points = %s;
        const targetNet = %s;

        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const allComps = await eda.sch_PrimitiveComponent.getAll();

        // 建立 pointKey -> net 映射 (导线端点 + 网络标签位置)
        const pointNet = new Map();
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.line) continue;
            const wNet = w.net || "";
            for (let i = 0; i < w.line.length; i += 2) {
                const k = w.line[i] + "," + w.line[i+1];
                if (!pointNet.has(k)) pointNet.set(k, wNet);
                else if (pointNet.get(k) !== wNet && wNet && pointNet.get(k)) {
                    // 已有两个不同网络在此点
                }
            }
        }
        for (const c of allComps || []) {
            if (c.net && (c.componentType === "netflag" || c.componentType === "netport" || c.componentType === "netlabel")) {
                const k = c.x + "," + c.y;
                if (!pointNet.has(k)) pointNet.set(k, c.net);
            }
        }

        const conflicts = [];
        const touchedEmpty = [];
        for (let i = 0; i < points.length; i += 2) {
            const k = points[i] + "," + points[i+1];
            const existingNet = pointNet.get(k);
            if (existingNet === undefined) continue;  // 没碰到任何东西
            if (existingNet === "") {
                touchedEmpty.push({ x: points[i], y: points[i+1], existingNet: "(empty)" });
                continue;
            }
            if (targetNet && existingNet !== targetNet) {
                conflicts.push({ x: points[i], y: points[i+1], existingNet, newNet: targetNet });
            }
        }

        return { conflicts, touchedEmpty };
    ''' % (json.dumps(points), js_str(net) if net else '""')
    return exec_code(code)


def add_wire_safe(points, net=None, color=None, line_width=None, line_type=None):
    """安全创建导线: 先检查冲突，再创建。

    - 如果坐标触碰已有不同网络的导线 → 中止，返回冲突信息
    - 如果坐标触碰已有空网络导线 → 警告但继续 (API 会自动赋网络名)
    - 否则正常创建
    """
    conflicts = check_wire_conflicts(points, net or "")
    if isinstance(conflicts, dict) and conflicts.get("conflicts"):
        return {
            "error": "Wire creation aborted: coordinates touch existing wires with different nets",
            "conflicts": conflicts["conflicts"],
        }
    wire_id = add_wire(points, net=net, color=color, line_width=line_width, line_type=line_type)
    result = {"id": wire_id}
    if isinstance(conflicts, dict) and conflicts.get("touchedEmpty"):
        result["warnings"] = conflicts["touchedEmpty"]
    return result


def add_wire_batch(wire_specs):
    """批量创建多条导线。

    wire_specs: [{ points: [x1,y1,...], net: "NET" }, ...]
    使用 Array<Array<number>> 一次性创建多条导线 (API 支持但要求互不连接的段需分别指定 net)。

    注意: API 的 Array<Array<number>> 要求所有段连续连接，否则失败。
    对于不连续的导线，需逐条创建。此函数逐条调用 add_wire_safe。
    """
    results = []
    for spec in wire_specs:
        r = add_wire_safe(
            spec["points"],
            net=spec.get("net"),
            color=spec.get("color"),
            line_width=spec.get("line_width"),
            line_type=spec.get("line_type"),
        )
        results.append(r)
    return {"count": len(results), "results": results}


def detect_wire_conflicts():
    """检测所有导线中存在的网络冲突: 触碰不同网络的导线。"""
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wires = [];
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w) continue;
            wires.push({
                id: w.primitiveId,
                net: w.net || "",
                line: w.line || [],
            });
        }

        // pointKey -> [{wireId, net}]
        const pointMap = new Map();
        for (const w of wires) {
            for (let i = 0; i < w.line.length; i += 2) {
                const k = w.line[i] + "," + w.line[i+1];
                if (!pointMap.has(k)) pointMap.set(k, []);
                pointMap.get(k).push({ wireId: w.id, net: w.net });
            }
        }

        // 找出有多个不同网络的点
        const conflicts = [];
        for (const [pt, items] of pointMap) {
            const nets = [...new Set(items.map(i => i.net).filter(n => n))];
            if (nets.length >= 2) {
                conflicts.push({
                    point: pt,
                    nets: nets,
                    wires: items.map(i => ({ id: i.wireId, net: i.net })),
                });
            }
        }

        return {
            conflictCount: conflicts.length,
            conflicts,
            passed: conflicts.length === 0,
            summary: conflicts.length === 0 ? "PASS" : "FAIL: " + conflicts.length + " conflict point(s)",
        };
    '''
    return exec_code(code)


def collect_nets():
    """扫描原理图中所有网络标签/端口/标志 + 导线网络，按网络名分组。

    返回: { nets: { "ROW0": [{type, x, y, source}], ... }, totalNets, totalPoints }
    """
    code = '''
        const allComps = await eda.sch_PrimitiveComponent.getAll();
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();

        // net name -> [{type, x, y, source}]
        const nets = {};

        const addNet = (net, type, x, y, source) => {
            if (!net) return;
            if (!nets[net]) nets[net] = [];
            nets[net].push({ type, x, y, source: source || "" });
        };

        // 1. 扫描 NetFlag / NetPort / NetLabel
        for (const c of allComps || []) {
            if (!c.net) continue;
            const compType = c.componentType || "";
            if (compType === "netflag" || compType === "netport" || compType === "netlabel") {
                addNet(c.net, compType, c.x, c.y, c.designator || "");
            }
        }

        // 2. 扫描导线
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.net || !w.line) continue;
            // 只取导线端点 (首尾各一个点)
            const pts = w.line;
            const start = { type: "wire-start", x: pts[0], y: pts[1], source: w.primitiveId };
            const end = { type: "wire-end", x: pts[pts.length-2], y: pts[pts.length-1], source: w.primitiveId };
            addNet(w.net, start.type, start.x, start.y, start.source);
            addNet(w.net, end.type, end.x, end.y, end.source);
        }

        // 统计
        const netNames = Object.keys(nets);
        let totalPoints = 0;
        for (const n of netNames) totalPoints += nets[n].length;

        return {
            nets,
            totalNets: netNames.length,
            totalPoints,
        };
    '''
    return exec_code(code)


def export_net_summary():
    """生成紧凑的网络摘要文本，供子 Agent 使用。

    格式:
        === Net Summary (5 nets, 12 points) ===
        COL0: 2 wire points (620,80) (820,80)
        COL1: 2 wire points (620,180) (820,180)
        GND: 1 netflag (500,400)
        ROW0: 1 netport (700,300) + 1 wire point (620,320)
        VCC: 1 netflag (300,100)
    """
    data = collect_nets()
    if not isinstance(data, dict):
        return data

    nets = data.get("nets", {})
    lines = []
    lines.append("=== Net Summary (%d nets, %d points) ===" % (
        data.get("totalNets", 0), data.get("totalPoints", 0)))

    for net_name in sorted(nets.keys()):
        points = nets[net_name]
        # 按类型分组
        flags = [(p["x"], p["y"]) for p in points if p["type"] == "netflag"]
        ports = [(p["x"], p["y"]) for p in points if p["type"] == "netport"]
        labels = [(p["x"], p["y"]) for p in points if p["type"] == "netlabel"]
        wires = [(p["x"], p["y"]) for p in points if p["type"].startswith("wire")]

        parts = []
        if flags:
            coords = " ".join("(%d,%d)" % (x, y) for x, y in flags)
            parts.append("%d netflag %s" % (len(flags), coords))
        if ports:
            coords = " ".join("(%d,%d)" % (x, y) for x, y in ports)
            parts.append("%d netport %s" % (len(ports), coords))
        if labels:
            coords = " ".join("(%d,%d)" % (x, y) for x, y in labels)
            parts.append("%d netlabel %s" % (len(labels), coords))
        if wires:
            coords = " ".join("(%d,%d)" % (x, y) for x, y in wires)
            parts.append("%d wire pts %s" % (len(wires), coords))

        lines.append("%s: %s" % (net_name, " + ".join(parts) if parts else "(no points)"))

    return "\n".join(lines)


def get_wire_info(primitive_id):
    code = '''
        const wires = await eda.sch_PrimitiveWire.get(["%s"]);
        const w = wires[0];
        if (!w) return null;
        return {
            id: w.getState_PrimitiveId(),
            net: w.getState_Net(),
            line: w.getState_Line(),
            lineWidth: w.getState_LineWidth(),
            lineType: w.getState_LineType(),
            color: w.getState_Color(),
        };
    ''' % primitive_id
    return exec_code(code)


def modify_wire(primitive_id, changes):
    setters = []
    if "net" in changes: setters.append('aw.setState_Net("%s");' % changes["net"])
    if "line" in changes: setters.append("aw.setState_Line(%s);" % json.dumps(changes["line"]))
    if "color" in changes: setters.append("aw.setState_Color(%s);" % js_val(changes["color"]))
    if "lineWidth" in changes: setters.append("aw.setState_LineWidth(%s);" % js_val(changes["lineWidth"]))
    if "lineType" in changes: setters.append("aw.setState_LineType(%s);" % js_val(changes["lineType"]))

    code = '''
        const wires = await eda.sch_PrimitiveWire.get(["%s"]);
        const w = wires[0];
        if (!w) return null;
        const aw = w.toAsync();
        %s
        await aw.done();
        const updated = await eda.sch_PrimitiveWire.get(["%s"]);
        const u = updated[0];
        return {
            id: u.getState_PrimitiveId(),
            net: u.getState_Net(),
            line: u.getState_Line(),
            lineWidth: u.getState_LineWidth(),
            lineType: u.getState_LineType(),
            color: u.getState_Color(),
        };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def add_bus(bus_name, points, color=None, line_width=None, line_type=None):
    code = '''
        const r = await eda.sch_PrimitiveBus.create(
            %s,
            %s,
            %s,
            %s,
            %s
        );
        return r?.primitiveId;
    ''' % (
        js_str(bus_name), json.dumps(points),
        js_val(color), js_val(line_width), js_val(line_type),
    )
    return exec_code(code)


def get_all_buses():
    code = '''
        const buses = await eda.sch_PrimitiveBus.getAll();
        return (buses || []).map(b => ({
            id: b.getState_PrimitiveId(),
            busName: b.getState_BusName(),
            line: b.getState_Line(),
            lineWidth: b.getState_LineWidth(),
        }));
    '''
    return exec_code(code)


def delete_buses(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitiveBus.delete(%s);" % json.dumps(ids_arg))


def get_bus(primitive_id):
    code = '''
        const buses = await eda.sch_PrimitiveBus.get(["%s"]);
        const b = buses[0];
        if (!b) return null;
        return {
            id: b.getState_PrimitiveId(),
            busName: b.getState_BusName(),
            line: b.getState_Line(),
            lineWidth: b.getState_LineWidth(),
            lineType: b.getState_LineType(),
            color: b.getState_Color(),
        };
    ''' % primitive_id
    return exec_code(code)


def modify_bus(primitive_id, changes):
    setters = []
    if "busName" in changes: setters.append('ab.setState_BusName("%s");' % changes["busName"])
    if "line" in changes: setters.append("ab.setState_Line(%s);" % json.dumps(changes["line"]))
    if "color" in changes: setters.append("ab.setState_Color(%s);" % js_val(changes["color"]))
    if "lineWidth" in changes: setters.append("ab.setState_LineWidth(%s);" % js_val(changes["lineWidth"]))
    if "lineType" in changes: setters.append("ab.setState_LineType(%s);" % js_val(changes["lineType"]))

    code = '''
        const buses = await eda.sch_PrimitiveBus.get(["%s"]);
        const b = buses[0];
        if (!b) return null;
        const ab = b.toAsync();
        %s
        await ab.done();
        return { id: "%s" };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def add_polygon(points, color=None, fill_color=None, line_width=None, line_type=None):
    code = '''
        const r = await eda.sch_PrimitivePolygon.create(
            %s,
            %s,
            %s,
            %s,
            %s
        );
        return r?.primitiveId;
    ''' % (
        json.dumps(points),
        js_val(color), js_val(fill_color),
        js_val(line_width), js_val(line_type),
    )
    return exec_code(code)


def get_all_polygons():
    code = '''
        const polygons = await eda.sch_PrimitivePolygon.getAll();
        return (polygons || []).map(p => ({
            id: p.getState_PrimitiveId(),
            line: p.getState_Line(),
            lineWidth: p.getState_LineWidth(),
            color: p.getState_Color(),
            fillColor: p.getState_FillColor(),
        }));
    '''
    return exec_code(code)


def delete_polygons(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitivePolygon.delete(%s);" % json.dumps(ids_arg))


def get_polygon(primitive_id):
    code = '''
        const polys = await eda.sch_PrimitivePolygon.get(["%s"]);
        const p = polys[0];
        if (!p) return null;
        return {
            id: p.getState_PrimitiveId(),
            line: p.getState_Line(),
            lineWidth: p.getState_LineWidth(),
            lineType: p.getState_LineType(),
            color: p.getState_Color(),
            fillColor: p.getState_FillColor(),
        };
    ''' % primitive_id
    return exec_code(code)


def modify_polygon(primitive_id, changes):
    setters = []
    if "line" in changes: setters.append("ap.setState_Line(%s);" % json.dumps(changes["line"]))
    if "color" in changes: setters.append("ap.setState_Color(%s);" % js_val(changes["color"]))
    if "fillColor" in changes: setters.append("ap.setState_FillColor(%s);" % js_val(changes["fillColor"]))
    if "lineWidth" in changes: setters.append("ap.setState_LineWidth(%s);" % js_val(changes["lineWidth"]))
    if "lineType" in changes: setters.append("ap.setState_LineType(%s);" % js_val(changes["lineType"]))

    code = '''
        const polys = await eda.sch_PrimitivePolygon.get(["%s"]);
        const p = polys[0];
        if (!p) return null;
        const ap = p.toAsync();
        %s
        await ap.done();
        return { id: "%s" };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def add_circle(center_x, center_y, radius, color=None, fill_color=None,
               line_width=None, line_type=None, fill_style=None):
    code = '''
        const r = await eda.sch_PrimitiveCircle.create(
            %d, %d, %d,
            %s,
            %s,
            %s,
            %s,
            %s
        );
        return r?.primitiveId;
    ''' % (
        center_x, center_y, radius,
        js_val(color), js_val(fill_color),
        js_val(line_width), js_val(line_type), js_val(fill_style),
    )
    return exec_code(code)


def get_all_circles():
    code = '''
        const circles = await eda.sch_PrimitiveCircle.getAll();
        return (circles || []).map(c => ({
            id: c.getState_PrimitiveId(),
            centerX: c.getState_CenterX(), centerY: c.getState_CenterY(),
            radius: c.getState_Radius(),
        }));
    '''
    return exec_code(code)


def delete_circles(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitiveCircle.delete(%s);" % json.dumps(ids_arg))


def add_arc(start_x, start_y, reference_x, reference_y, end_x, end_y,
            color=None, fill_color=None, line_width=None, line_type=None):
    code = '''
        const r = await eda.sch_PrimitiveArc.create(
            %d, %d, %d, %d, %d, %d,
            %s,
            %s,
            %s,
            %s
        );
        return r?.primitiveId;
    ''' % (
        start_x, start_y, reference_x, reference_y, end_x, end_y,
        js_val(color), js_val(fill_color),
        js_val(line_width), js_val(line_type),
    )
    return exec_code(code)


def get_all_arcs():
    code = '''
        const arcs = await eda.sch_PrimitiveArc.getAll();
        return (arcs || []).map(a => ({
            id: a.getState_PrimitiveId(),
            startX: a.getState_StartX(), startY: a.getState_StartY(),
            endX: a.getState_EndX(), endY: a.getState_EndY(),
            referenceX: a.getState_ReferenceX(), referenceY: a.getState_ReferenceY(),
        }));
    '''
    return exec_code(code)


def delete_arcs(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitiveArc.delete(%s);" % json.dumps(ids_arg))


def search_device(keyword, library_uuid="0819f05c4eef4c71ace90d822a990e87", limit=10):
    code = '''
        const r = await eda.lib_Device.search("%s", "%s", undefined, undefined, %d, 1);
        return r.slice(0, %d).map(d => ({name: d.name, uuid: d.uuid, libraryUuid: d.libraryUuid}));
    ''' % (keyword, library_uuid, limit, limit)
    return exec_code(code)


# 系统库 UUID (相对稳定)
SYSTEM_LIBRARY_UUID = "0819f05c4eef4c71ace90d822a990e87"


def get_personal_library_uuid():
    """获取个人库 UUID"""
    return exec_code("return await eda.lib_LibrariesList.getPersonalLibraryUuid();")


def get_project_library_uuid():
    """获取工程库 UUID"""
    return exec_code("return await eda.lib_LibrariesList.getProjectLibraryUuid();")


def list_all_libraries():
    """列出所有库"""
    code = '''
        const libs = await eda.lib_LibrariesList.getAllLibrariesList();
        return (libs || []).map(l => ({
            name: l.name || l.libraryName || "",
            uuid: l.uuid || l.libraryUuid || "",
            type: l.type || l.libraryType || "",
        }));
    '''
    return exec_code(code)


def get_project_info():
    return exec_code("return await eda.dmt_Project.getCurrentProjectInfo();")


def list_tabs():
    code = '''
        const tree = await eda.dmt_EditorControl.getSplitScreenTree();
        const tabs = [];
        function walk(node) {
            if (node.tabs) {
                for (const t of node.tabs) {
                    tabs.push({
                        tabId: t.tabId,
                        title: t.title,
                        doctype: t.data?.doctype ?? -1,
                    });
                }
            }
            if (node.children) node.children.forEach(walk);
        }
        walk(tree);
        return tabs;
    '''
    return exec_code(code)


def switch_tab(doctype):
    tabs = list_tabs()
    target = next((t for t in tabs if t.get("doctype") == doctype), None)
    if not target:
        type_names = {1: "schematic", 2: "symbol editor", -1: "start page"}
        raise RuntimeError("No %s tab found. Open tabs: %s"
                           % (type_names.get(doctype, "matching"), json.dumps(tabs)))
    exec_code('await eda.dmt_EditorControl.activateDocument("%s"); return true;' % target["tabId"])
    return {"tabId": target["tabId"], "title": target["title"]}


def get_page_info():
    return exec_code("return await eda.dmt_Schematic.getCurrentSchematicPageInfo();")


def set_page_size(size):
    """修改原理图图纸尺寸(通过标题栏图框符号切换)。
    size: A4 / A3 / A2 / A1"""
    sizes = {"A4": (1170, 825), "A3": (1654, 1169),
             "A2": (2339, 1654), "A1": (3307, 2339)}
    key = str(size).upper()
    wh = sizes.get(key)
    if not wh:
        raise RuntimeError("unsupported page size: %s (支持 %s)" % (size, "/".join(sizes)))
    data = {
        "Symbol":    {"showTitle": False, "showValue": False, "value": "Drawing-Symbol_%s" % key},
        "Page Size": {"showTitle": False, "showValue": False, "value": key},
        "Size":      {"showTitle": None,  "showValue": None,  "value": key},
        "Width":     {"showTitle": None,  "showValue": None,  "value": str(wh[0])},
        "Height":    {"showTitle": None,  "showValue": None,  "value": str(wh[1])},
    }
    code = (
        "const d = %s;"
        "const ok = await eda.dmt_Schematic.modifySchematicPageTitleBlock(true, d);"
        "const a = await eda.dmt_Schematic.getCurrentSchematicPageInfo();"
        "const tb = a && a.titleBlockData ? a.titleBlockData : {};"
        "return { ok: ok,"
        " symbol: tb['Symbol'] ? tb['Symbol'].value : null,"
        " pageSize: tb['Page Size'] ? tb['Page Size'].value : null,"
        " width: tb['Width'] ? tb['Width'].value : null,"
        " height: tb['Height'] ? tb['Height'].value : null };"
    ) % json.dumps(data)
    return exec_code(code)


def zoom_to_all():
    return exec_code("return await eda.dmt_EditorControl.zoomToAllPrimitives();")


def restore_title_block(data=None):
    default_data = {
        "@Project Name": {"showTitle": True, "showValue": True, "value": "Project"},
        "Version": {"showTitle": True, "showValue": True, "value": "V1.0"},
        "Drawed": {"showTitle": True, "showValue": True, "value": "AI"},
    }
    if data:
        default_data.update(data)
    code = "return await eda.dmt_Schematic.modifySchematicPageTitleBlock(true, %s);" % json.dumps(default_data)
    return exec_code(code)


def save_document():
    return exec_code("const EDMT_EditorDocumentType = {PCB:3};"
                     "const d = await eda.dmt_SelectControl.getCurrentDocumentInfo();"
                     "if (!d) throw new Error('No current document');"
                     "return d.documentType === EDMT_EditorDocumentType.PCB"
                     " ? await eda.pcb_Document.save() : await eda.sch_Document.save();")


def export_netlist(file_name=None):
    return export_generated_file("netlist", file_name or "SenseMind.net")


def export_bom(file_name=None, file_type="xlsx"):
    return export_generated_file("bom", file_name or ("SenseMind_BOM." + file_type), file_type=file_type)


def new_project(friendly_name, slug, description=""):
    if not slug or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in slug):
        raise RuntimeError("Project slug may contain only letters, digits and hyphens")
    return exec_code(
        "const current = await eda.dmt_Project.getCurrentProjectInfo();"
        "if (current && current.uuid) throw new Error('Use a bare dedicated session; a project is already open');"
        "const uuid = await eda.dmt_Project.createProject(%s,%s,undefined,undefined,%s,undefined,EDMT_ProjectFileFormat.EPRJ3);"
        "if (!uuid) throw new Error('Project creation failed');"
        "const opened = await eda.dmt_Project.openProject(uuid);"
        "if (!opened) throw new Error('Project created but open failed: ' + uuid);"
        "return await eda.dmt_Project.getCurrentProjectInfo();"
        % (js_str(friendly_name), js_str(slug), js_str(description))
    )


def create_page(schematic_uuid, name):
    return exec_code(
        "const uuid = await eda.dmt_Schematic.createSchematicPage(%s);"
        "if (!uuid) throw new Error('Schematic page creation failed');"
        "if (!await eda.dmt_Schematic.modifySchematicPageName(uuid,%s)) throw new Error('Page rename failed: ' + uuid);"
        "return {uuid,name:%s,schematicUuid:%s};"
        % (js_str(schematic_uuid), js_str(name), js_str(name), js_str(schematic_uuid))
    )


def open_page(page_uuid):
    return exec_code(
        "const tabId = await eda.dmt_EditorControl.openDocument(%s);"
        "if (!tabId) throw new Error('Document did not open');"
        "return {tabId, document:await eda.dmt_SelectControl.getCurrentDocumentInfo()};"
        % js_str(page_uuid)
    )


def rename_page(page_uuid, name):
    return exec_code("return await eda.dmt_Schematic.modifySchematicPageName(%s,%s);" % (js_str(page_uuid), js_str(name)))


def list_pages():
    return exec_code("return {schematics:await eda.dmt_Schematic.getAllSchematicsInfo(),pages:await eda.dmt_Schematic.getAllSchematicPagesInfo()};")


def create_board(name):
    return exec_code(
        "const boards = await eda.dmt_Board.getAllBoardsInfo();"
        "if ((boards || []).some(b=>b.name === %s)) throw new Error('Board name already exists');"
        "const originalName = await eda.dmt_Board.createBoard();"
        "if (!originalName) throw new Error('Board creation failed');"
        "const renamed = await eda.dmt_Board.modifyBoardName(originalName,%s);"
        "if (!renamed) throw new Error('Board created but rename failed: ' + originalName);"
        "return {originalName,name:%s,boards:await eda.dmt_Board.getAllBoardsInfo()};"
        % (js_str(name), js_str(name), js_str(name))
    )


def export_generated_file(kind, output_path, file_type=None, scope="current"):
    """Export an actual EDA File and preserve its exact bytes on local disk."""
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise RuntimeError("Refusing to overwrite existing export: %s" % target)
    stem = target.stem
    if kind == "netlist":
        expression = "await eda.sch_ManufactureData.getNetlistFile(%s,ESYS_NetlistType.JLCEDA_PRO)" % js_str(stem)
    elif kind == "bom":
        expression = "await eda.sch_ManufactureData.getBomFile(%s,%s)" % (js_str(stem), js_str(file_type or "xlsx"))
    elif kind == "project":
        expression = "await eda.sys_FileManager.getProjectFile(%s,undefined,'epro2')" % js_str(stem)
    elif kind == "pdf":
        obj = {"current": "Current Schematic Page", "schematic": "Current Schematic", "all": "All Schematic"}[scope]
        expression = "await eda.sch_ManufactureData.getExportDocumentFile(%s,ESCH_ExportDocumentFileType.PDF,undefined,%s,{outputMethod:'Merged sheet'})" % (js_str(stem), js_str(obj))
    elif kind == "png":
        expression = "await eda.sch_ManufactureData.getPngFile(%s,{width:2400})" % js_str(stem)
    elif kind == "svg":
        expression = "await eda.sch_ManufactureData.getSvgFile(%s)" % js_str(stem)
    else:
        raise RuntimeError("Unsupported export kind: " + kind)
    file_data = exec_code(
        "const ESYS_NetlistType = {JLCEDA_PRO:'JLCEDA'};"
        "const ESCH_ExportDocumentFileType = {PDF:'PDF'};"
        "const f = %s; if (!f || !f.size) throw new Error('EDA export returned no file');"
        "const b64 = await new Promise((resolve,reject) => {const r = new FileReader();"
        "r.onerror = () => reject(new Error('FileReader failed'));"
        "r.onload = () => resolve(String(r.result).split(',')[1] || '');r.readAsDataURL(f);});"
        "return {name:f.name,size:f.size,type:f.type,b64};" % expression
    )
    contents = base64.b64decode(file_data["b64"], validate=True)
    if len(contents) != file_data["size"]:
        raise RuntimeError("Export byte count mismatch")
    if kind == "pdf" and not contents.startswith(b"%PDF-"):
        raise RuntimeError("EDA did not return a PDF file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as f:
        f.write(contents)
    return {"ok": True, "path": str(target), "edaFileName": file_data.get("name"),
            "size": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def export_document_source(output_path):
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise RuntimeError("Refusing to overwrite existing export: %s" % target)
    source = exec_code("return await eda.sys_FileManager.getDocumentSource();")
    if not isinstance(source, str) or not source:
        raise RuntimeError("EDA returned no document source")
    contents = source.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as f:
        f.write(contents)
    return {"ok": True, "path": str(target), "size": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest()}


def device_info(device_uuid, library_uuid=None):
    return exec_code("return await eda.lib_Device.get(%s,%s);" % (js_str(device_uuid), js_val(library_uuid)))


def api_capabilities():
    return exec_code(
        "return {document:await eda.dmt_SelectControl.getCurrentDocumentInfo(),"
        "schSave:typeof eda.sch_Document.save,pcbSave:typeof eda.pcb_Document.save,"
        "deviceCreate:typeof eda.lib_Device.create,symbolCreate:typeof eda.lib_Symbol.create,"
        "projectExport:typeof eda.sys_FileManager.getProjectFile,sourceExport:typeof eda.sys_FileManager.getDocumentSource,"
        "bomExport:typeof eda.sch_ManufactureData.getBomFile,netlistExport:typeof eda.sch_ManufactureData.getNetlistFile,"
        "pdfExport:typeof eda.sch_ManufactureData.getExportDocumentFile,"
        "fileReader:typeof FileReader,editorDocumentEnum:typeof EDMT_EditorDocumentType,"
        "symbolEnum:typeof ELIB_SymbolType,netlistEnum:typeof ESYS_NetlistType,pdfEnum:typeof ESCH_ExportDocumentFileType};"
    )


# ═══════════════════════════════════════════════════════════════════
# 器件/引脚查询防护函数
# ═══════════════════════════════════════════════════════════════════

def get_component_pins(primitive_id):
    code = '''
        const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId("%s");
        return (pins || []).map(p => ({ num: p.pinNumber, name: p.pinName, x: p.x, y: p.y }));
    ''' % primitive_id
    return exec_code(code)


def find_component_by_designator(designator):
    code = '''
        const ids = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        for (const id of ids) {
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            if (c && c.designator === "%s") return id;
        }
        return null;
    ''' % designator
    return exec_code(code)


def delete_component(component_id=None, designator=None, margin=50,
                     clean_wires=True, clean_labels=True, clean_text=False):
    if not component_id and not designator:
        raise ValueError("delete_component: must provide id or designator")

    target_id = component_id or find_component_by_designator(designator)
    if not target_id:
        return {"componentDeleted": False, "wires": 0, "labels": 0, "text": 0}

    pins = get_component_pins(target_id)
    wires_deleted = labels_deleted = text_deleted = 0

    if pins:
        xs = [p["x"] for p in pins]
        ys = [p["y"] for p in pins]
        region = {
            "minX": min(xs) - margin, "maxX": max(xs) + margin,
            "minY": min(ys) - margin, "maxY": max(ys) + margin,
        }
        if clean_wires:
            r = delete_wires(region=region)
            wires_deleted = r.get("deleted", 0)
        if clean_labels:
            r = delete_net_labels(region=region)
            labels_deleted = r.get("deleted", 0)
        if clean_text:
            code = '''
                const ids = await eda.sch_PrimitiveText.getAllPrimitiveId();
                let count = 0;
                const region = %s;
                for (const id of ids) {
                    const t = (await eda.sch_PrimitiveText.get([id]))[0];
                    if (t.x >= region.minX && t.x <= region.maxX && t.y >= region.minY && t.y <= region.maxY) {
                        await eda.sch_PrimitiveText.delete([id]);
                        count++;
                    }
                }
                return count;
            ''' % json.dumps(region)
            text_deleted = exec_code(code)

    exec_code('await eda.sch_PrimitiveComponent.delete(["%s"]); return true;' % target_id)
    return {"componentDeleted": True, "wires": wires_deleted,
            "labels": labels_deleted, "text": text_deleted}


def add_chip_pin_label(side, pin_x, pin_y, net, label_type, distance=LABEL_WIRE_LENGTH):
    """为芯片引脚绘制延伸导线 (仅导线，信号类型不放置标签；电源/地放 NetFlag)"""
    end_x, end_y = pin_x, pin_y
    if side == "left": end_x = pin_x - distance
    elif side == "right": end_x = pin_x + distance
    elif side == "top": end_y = pin_y - distance
    elif side == "bottom": end_y = pin_y + distance

    wire_id = add_wire([pin_x, pin_y, end_x, end_y], net)

    flag_id = None
    if label_type == "power":
        rotation = LABEL_ROTATION_BY_SIDE[side]
        flag_id = add_net_flag("Power", net, end_x, end_y, rotation)
    elif label_type == "ground":
        rotation = LABEL_ROTATION_BY_SIDE[side]
        flag_id = add_net_flag("Ground", net, end_x, end_y, rotation)

    return {"wireId": wire_id, "flagId": flag_id}


def place_component_with_labels(library_uuid, uuid, x, y, designator=None,
                                 rotation=0, find_space=False, find_space_options=None,
                                 pin_map=None, module_label=None):
    pin_map = pin_map or {}
    find_space_options = find_space_options or {}

    if find_space:
        pos = find_free_space(**find_space_options)
        if not pos:
            raise RuntimeError("No free space found for placement")
        x = x if x is not None else pos["x"]
        y = y if y is not None else pos["y"]

    component_id = place_component(library_uuid, uuid, x, y, designator, rotation)
    pins = get_component_pins(component_id)

    labels = []
    for pin in pins:
        cfg = pin_map.get(pin["num"])
        if not cfg:
            continue
        r = add_chip_pin_label(
            side=cfg["side"], pin_x=pin["x"], pin_y=pin["y"],
            net=cfg["net"], label_type=cfg["type"],
            distance=cfg.get("distance", LABEL_WIRE_LENGTH),
        )
        labels.append({"pin": pin["num"], "net": cfg["net"], **r})

    if module_label:
        add_text(x, y - 30, module_label, font_size=8)

    return {"componentId": component_id, "pins": pins, "labels": labels,
            "position": {"x": x, "y": y}}


def replace_net_ports(extend_length=50):
    code = '''
        const netPortIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("netport", false);
        if (netPortIds.length === 0) return { replaced: 0, details: [], message: "No NetPort found on current page" };

        const details = [];
        for (const id of netPortIds) {
            const ports = await eda.sch_PrimitiveComponent.get([id]);
            const p = ports[0];
            if (!p) continue;

            const net = p.net || "";
            const x = p.x, y = p.y;
            const rotation = p.rotation || 0;

            let extX = x, extY = y;
            if (rotation === 0) extX = x + %d;
            else if (rotation === 180) extX = x - %d;
            else if (rotation === 90) extY = y + %d;
            else if (rotation === 270) extY = y - %d;

            try {
                await eda.sch_PrimitiveWire.create([x, y, extX, extY], net, null, null, null);
            } catch(e) {
                details.push({ id, net, x, y, rotation, status: "wire_failed", error: e.message });
                continue;
            }

            await eda.sch_PrimitiveComponent.delete([id]);
            details.push({ id, net, x, y, rotation, status: "replaced" });
        }

        return {
            replaced: details.filter(d => d.status === "replaced").length,
            failed: details.filter(d => d.status !== "replaced").length,
            details,
        };
    ''' % (extend_length, extend_length, extend_length, extend_length)
    return exec_code(code)


def mark_nc(designator, pin_numbers):
    pin_list = [str(p) for p in pin_numbers]
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("part", false);
        let targetId = null;
        for (const id of compIds) {
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            if (c && c.designator === "%s") { targetId = id; break; }
        }
        if (!targetId) return { error: "Component %s not found" };

        const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(targetId);
        const targetNums = new Set(%s);
        const details = [];

        for (const pin of pins) {
            if (targetNums.has(pin.pinNumber)) {
                pin.setState_NoConnected(true);
                const ap = pin.toAsync();
                ap.done();
                details.push({ pinNumber: pin.pinNumber, pinName: pin.pinName, noConnected: true });
            }
        }

        return {
            marked: details.length,
            details,
            missing: %s.filter(n => !details.find(d => d.pinNumber === n)),
        };
    ''' % (designator, designator, json.dumps(pin_list), json.dumps(pin_list))
    return exec_code(code)


def check_nc_coverage():
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("part", false);
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wires = [];
        for (const wid of wireIds || []) {
            const prim = await eda.sch_Primitive.getPrimitiveByPrimitiveId(wid);
            if (prim) wires.push({ primitiveId: wid, line: prim.line, net: prim.net });
        }
        const allResults = [];

        for (const id of compIds) {
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            if (!c || !c.designator) continue;
            const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
            if (!pins || pins.length === 0) continue;

            for (const p of pins) {
                let hasWire = false;
                for (const w of wires || []) {
                    const line = w.line || [];
                    for (let i = 0; i < line.length; i += 2) {
                        if (Math.abs(line[i] - p.x) < 1 && Math.abs(line[i + 1] - p.y) < 1) {
                            hasWire = true; break;
                        }
                    }
                    if (hasWire) break;
                }

                const nc = p.getState_NoConnected ? p.getState_NoConnected() : false;
                const covered = hasWire || nc;

                allResults.push({
                    designator: c.designator,
                    pinNumber: p.pinNumber,
                    pinName: p.pinName,
                    hasWire,
                    noConnected: nc,
                    covered,
                });
            }
        }

        const uncovered = allResults.filter(r => !r.covered);
        return {
            totalPins: allResults.length,
            covered: allResults.length - uncovered.length,
            uncovered,
            summary: uncovered.length === 0 ? "PASS: all pins have wire or NC" : "WARN: " + uncovered.length + " pin(s) without wire or NC",
        };
    '''
    return exec_code(code)


# ═══════════════════════════════════════════════════════════════════
# 符号编辑器防护函数 (封装 rotation 反转 / Y 轴方向坑)
# ═══════════════════════════════════════════════════════════════════

def create_symbol(name):
    code = '''
        const lib = await eda.lib_LibrariesList.getPersonalLibraryUuid();
        if (!lib) throw new Error("No personal library found");
        const uuid = await eda.lib_Symbol.create(lib, %s);
        if (!uuid) throw new Error("Failed to create symbol");
        return { symbolUuid: uuid, libraryUuid: lib };
    ''' % js_str(name)
    return exec_code(code)


def open_symbol_in_editor(symbol_uuid, library_uuid):
    return exec_code('return await eda.lib_Symbol.openInEditor("%s", "%s");'
                     % (symbol_uuid, library_uuid))


def create_device_from_symbol(name, symbol_uuid, library_uuid, footprint_uuid=None, description=None):
    assoc = '{ symbolType: ELIB_SymbolType.COMPONENT, symbol: { uuid: "%s", libraryUuid: "%s" }' % (symbol_uuid, library_uuid)
    if footprint_uuid:
        assoc += ', footprint: { uuid: "%s", libraryUuid: "%s" }' % (footprint_uuid, library_uuid)
    assoc += ' }'
    desc_str = js_str(description) if description else "undefined"
    code = '''
        const ELIB_SymbolType = {COMPONENT:2};
        const association = %s;
        const uuid = await eda.lib_Device.create("%s", %s, undefined, association, %s);
        if (!uuid) throw new Error("Failed to create device");
        return { deviceUuid: uuid };
    ''' % (assoc, library_uuid, js_str(name), desc_str)
    return exec_code(code)


def create_symbol_pin(side, x, y, number, name, pin_type="BI", length=20):
    """封装 rotation 反转坑: side 自动映射到正确的 rotation"""
    if side not in PIN_ROTATION_BY_SIDE:
        raise ValueError('Invalid side: "%s". Must be one of: left, right, top, bottom' % side)
    rotation = PIN_ROTATION_BY_SIDE[side]
    code = '''
        const p = await eda.sch_PrimitivePin.create(
            %d, %d, "%s", "%s",
            %d, %d, null, "None", "%s"
        );
        return p?.primitiveId || null;
    ''' % (x, y, number, name, rotation, length, pin_type)
    return exec_code(code)


def get_pin(primitive_id):
    code = '''
        const pins = await eda.sch_PrimitivePin.get(["%s"]);
        const p = pins[0];
        if (!p) return null;
        return {
            id: p.getState_PrimitiveId(),
            x: p.getState_X(), y: p.getState_Y(),
            pinNumber: p.getState_PinNumber(),
            pinName: p.getState_PinName(),
            rotation: p.getState_Rotation(),
            pinLength: p.getState_PinLength(),
            pinColor: p.getState_PinColor(),
            pinShape: p.getState_PinShape(),
            pinType: p.getState_PinType(),
        };
    ''' % primitive_id
    return exec_code(code)


def get_all_pins():
    code = '''
        const pins = await eda.sch_PrimitivePin.getAll();
        return (pins || []).map(p => ({
            id: p.getState_PrimitiveId(),
            pinNumber: p.getState_PinNumber(),
            pinName: p.getState_PinName(),
            x: p.getState_X(), y: p.getState_Y(),
            rotation: p.getState_Rotation(),
        }));
    '''
    return exec_code(code)


def delete_pins(primitive_ids):
    ids_arg = primitive_ids[0] if len(primitive_ids) == 1 else primitive_ids
    return exec_code("return await eda.sch_PrimitivePin.delete(%s);" % json.dumps(ids_arg))


def modify_pin(primitive_id, changes):
    setters = []
    if "x" in changes: setters.append("ap.setState_X(%d);" % changes["x"])
    if "y" in changes: setters.append("ap.setState_Y(%d);" % changes["y"])
    if "pinNumber" in changes: setters.append('ap.setState_PinNumber("%s");' % changes["pinNumber"])
    if "pinName" in changes: setters.append("ap.setState_PinName(%s);" % js_str(changes["pinName"]))
    if "rotation" in changes: setters.append("ap.setState_Rotation(%d);" % changes["rotation"])
    if "pinLength" in changes: setters.append("ap.setState_PinLength(%d);" % changes["pinLength"])
    if "pinColor" in changes: setters.append("ap.setState_PinColor(%s);" % js_val(changes["pinColor"]))
    if "pinShape" in changes: setters.append('ap.setState_PinShape("%s");' % changes["pinShape"])
    if "pinType" in changes: setters.append('ap.setState_PinType("%s");' % changes["pinType"])

    code = '''
        const pins = await eda.sch_PrimitivePin.get(["%s"]);
        const p = pins[0];
        if (!p) return null;
        const ap = p.toAsync();
        %s
        await ap.done();
        return { id: "%s" };
    ''' % (primitive_id, " ".join(setters), primitive_id)
    return exec_code(code)


def create_symbol_rect(center_x, center_y, width, height):
    """封装 Y 轴方向坑: topLeftY = center_y + height/2 (Y 轴向上)"""
    top_left_x = center_x - width / 2
    top_left_y = center_y + height / 2
    code = '''
        const r = await eda.sch_PrimitiveRectangle.create(
            %s, %s, %d, %d,
            0, 0, null, null, null, null, null
        );
        return r?.primitiveId || null;
    ''' % (top_left_x, top_left_y, width, height)
    return exec_code(code)


def create_symbol_dot(x, y, radius=5):
    code = '''
        const d = await eda.sch_PrimitiveCircle.create(
            %d, %d, %d, null, null, null, null, null
        );
        return d?.primitiveId || null;
    ''' % (x, y, radius)
    return exec_code(code)


def delete_device(device_uuid, library_uuid):
    """封装参数顺序坑: delete(uuid, libraryUuid) - uuid 在前"""
    return exec_code('return await eda.lib_Device.delete("%s", "%s");'
                     % (device_uuid, library_uuid))


def delete_symbol(symbol_uuid, library_uuid):
    """封装参数顺序坑: delete(uuid, libraryUuid) - uuid 在前"""
    return exec_code('return await eda.lib_Symbol.delete("%s", "%s");'
                     % (symbol_uuid, library_uuid))


def list_all_primitives():
    code = '''
        const allIds = new Set();
        try {
            const pinIds = await eda.sch_PrimitivePin.getAllPrimitiveId() || [];
            pinIds.forEach(id => allIds.add(id));
        } catch(e) {}

        const docInfo = await eda.dmt_SelectControl.getCurrentDocumentInfo();
        const isSymbol = docInfo.documentType === 2;

        if (isSymbol) {
            const results = [];
            for (const id of [...allIds]) {
                try {
                    const type = await eda.sch_Primitive.getPrimitiveTypeByPrimitiveId(id);
                    const obj = await eda.sch_Primitive.getPrimitiveByPrimitiveId(id);
                    if (obj) results.push(obj);
                } catch(e) {}
            }
            return { documentType: 'symbol', primitives: results, pinIds: [...allIds] };
        } else {
            const rects = await eda.sch_PrimitiveRectangle.getAll() || [];
            const pins = await eda.sch_PrimitivePin.getAll() || [];
            const texts = await eda.sch_PrimitiveText.getAll() || [];
            const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId() || [];
            const wires = [];
            for (const wid of wireIds) {
                const prim = await eda.sch_Primitive.getPrimitiveByPrimitiveId(wid);
                if (prim) wires.push(prim);
            }
            const components = await eda.sch_PrimitiveComponent.getAll() || [];
            const circles = await eda.sch_PrimitiveCircle.getAll() || [];
            return { documentType: 'schematic', primitives: { rects, pins, texts, wires, components, circles } };
        }
    '''
    return exec_code(code)


def list_selected_primitives():
    code = '''
        const primitives = await eda.sch_SelectControl.getAllSelectedPrimitives();
        const results = primitives.map(p => ({
            type: p.primitiveType,
            x: p.x, y: p.y,
            topLeftX: p.topLeftX, topLeftY: p.topLeftY,
            width: p.width, height: p.height,
            centerX: p.centerX, centerY: p.centerY,
            radius: p.radius,
            pinNumber: p.pinNumber, pinName: p.pinName,
            rotation: p.rotation, pinLength: p.pinLength,
        }));
        return { count: results.length, items: results };
    '''
    return exec_code(code)


def build_symbol(name, body_width=160, body_height=260, pin_length=20,
                 pin_spacing=20, sides=None, show_pin1_indicator=True, library_uuid=None):
    sides = sides or []
    code = '''
        const ELIB_SymbolType = {COMPONENT:2};
        const personalLib = %s || await eda.lib_LibrariesList.getPersonalLibraryUuid();
        if (!personalLib) throw new Error("No personal library found");

        const symbolUuid = await eda.lib_Symbol.create(personalLib, %s);
        if (!symbolUuid) throw new Error("Failed to create symbol");

        await eda.lib_Symbol.openInEditor(symbolUuid, personalLib);

        const halfW = %d / 2;
        const halfH = %d / 2;

        const rect = await eda.sch_PrimitiveRectangle.create(-halfW, halfH, %d, %d, 0, 0, null, null, null, null, null);
        if (!rect) throw new Error("Failed to create rectangle");

        const showPin1Indicator = %s;
        if (showPin1Indicator) {
            const dotX = -halfW + 10;
            const dotY = halfH - 10;
            await eda.sch_PrimitiveCircle.create(dotX, dotY, 5, null, null, null, null, null);
        }

        const sideConfigs = %s;
        let pinCount = 0;
        const results = [];

        for (const side of sideConfigs) {
            let pinX, pinY, rotation;
            const pinCount = side.pins.length;
            const startY = -(pinCount - 1) * %d / 2;

            for (let i = 0; i < pinCount; i++) {
                const pin = side.pins[i];
                if (side.side === 'left') {
                    pinX = -halfW;
                    pinY = startY + i * %d;
                    rotation = 0;
                } else if (side.side === 'right') {
                    pinX = halfW;
                    pinY = startY + i * %d;
                    rotation = 180;
                } else if (side.side === 'top') {
                    pinX = startY + i * %d;
                    pinY = halfH;
                    rotation = 270;
                } else if (side.side === 'bottom') {
                    pinX = startY + i * %d;
                    pinY = -halfH;
                    rotation = 90;
                }
                const result = await eda.sch_PrimitivePin.create(pinX, pinY, pin.num, pin.name, rotation, %d, null, "None", pin.type);
                results.push({ num: pin.num, name: pin.name, success: !!result });
            }
        }

        await eda.sch_Document.save();
        const deviceUuid = await eda.lib_Device.create(personalLib, %s, undefined, {
            symbolType: ELIB_SymbolType.COMPONENT,
            symbol: { uuid: symbolUuid, libraryUuid: personalLib },
        });

        const allPinIds = await eda.sch_PrimitivePin.getAllPrimitiveId();
        const expectedCount = sideConfigs.reduce((sum, s) => sum + s.pins.length, 0);
        const pinResult = {
            expected: expectedCount,
            actual: allPinIds.length,
            ok: allPinIds.length === expectedCount,
        };

        return {
            symbolUuid,
            libraryUuid: personalLib,
            deviceUuid,
            pins: results,
            validation: pinResult,
            tip: pinResult.ok
                ? '符号构建成功！使用 switch-tab schematic 切回原理图，然后 search 命令搜索并放置。'
                : '引脚数量不匹配！预期 ' + expectedCount + '，实际 ' + allPinIds.length + '。'
        };
    ''' % (
        js_val(library_uuid), js_str(name),
        body_width, body_height, body_width, body_height,
        "true" if show_pin1_indicator else "false",
        json.dumps(sides),
        pin_spacing, pin_spacing, pin_spacing, pin_spacing, pin_spacing,
        pin_length,
        js_str(name),
    )
    return exec_code(code)


def fix_pin_labels(side, offset=5):
    is_horizontal = side in ("left", "right")
    direction = 1 if side in ("left", "top") else -1
    target_rotation = {"left": 0, "right": 180, "top": 270, "bottom": 90}[side]
    expected_align = 2 if side == "left" else (8 if side == "right" else 5)

    code = '''
        const pinIds = await eda.sch_PrimitivePin.getAllPrimitiveId();
        const pins = [];
        for (const id of pinIds) {
            const p = (await eda.sch_PrimitivePin.get([id]))[0];
            pins.push({ id, x: p.x, y: p.y, rotation: p.rotation, pinNumber: p.pinNumber, pinName: p.pinName });
        }

        const attrIds = await eda.sch_PrimitiveAttribute.getAllPrimitiveId();
        const attrs = [];
        for (const id of attrIds) {
            const a = (await eda.sch_PrimitiveAttribute.get([id]))[0];
            attrs.push({ id: a.primitiveId, key: a.key, value: a.value, parentId: a.parentPrimitiveId, x: a.x, y: a.y, align: a.alignMode });
        }

        const fixed = [];
        const targetRotation = %d;

        for (const pin of pins) {
            if (pin.rotation !== targetRotation) continue;

            let expectedX, expectedY, expectedAlign;
            if (%s) {
                expectedX = pin.x + (%d * %d);
                expectedY = -pin.y;
                expectedAlign = %d;
            } else {
                expectedX = pin.x;
                expectedY = -pin.y + (%d * %d);
                expectedAlign = %d;
            }

            const nameAttr = attrs.find(a =>
                a.key === 'Pin Name' &&
                a.parentId === pin.id
            );

            if (!nameAttr) continue;

            const needFixX = Math.abs(nameAttr.x - expectedX) > 5;
            const needFixY = Math.abs(nameAttr.y - expectedY) > 5;
            const needFixAlign = nameAttr.align !== expectedAlign;

            if (needFixX || needFixY || needFixAlign) {
                const attr = await eda.sch_PrimitiveAttribute.get([nameAttr.id]);
                if (attr && attr[0]) {
                    const at = attr[0].toAsync();
                    if (needFixAlign) at.setState_AlignMode(expectedAlign);
                    if (needFixX) at.setState_X(expectedX);
                    if (needFixY) at.setState_Y(expectedY);
                    await at.done();
                    fixed.push({
                        pinNumber: pin.pinNumber,
                        pinName: pin.pinName,
                        oldX: nameAttr.x, newX: expectedX,
                        oldY: nameAttr.y, newY: expectedY,
                    });
                }
            }
        }

        return {
            fixed: fixed.length,
            details: fixed,
            summary: fixed.length > 0
                ? '已修正 ' + fixed.length + ' 个引脚名称位置'
                : '所有引脚名称位置已正确'
        };
    ''' % (
        target_rotation,
        "true" if is_horizontal else "false",
        direction, offset, expected_align,
        direction, offset, expected_align,
    )
    return exec_code(code)


# ═══════════════════════════════════════════════════════════════════
# 检查函数
# ═══════════════════════════════════════════════════════════════════

def run_drc(show_ui=False):
    code = '''
        const errors = await eda.sch_Drc.check(true, %s, true);
        const fatalCount = (errors||[]).find(e => e.type === "fatalError")?.count || 0;
        const warnCount = (errors||[]).find(e => e.type === "warn")?.count || 0;
        return {
            passed: fatalCount === 0,
            fatalErrors: fatalCount,
            warnings: warnCount,
            details: errors || [],
            note: "DRC API only returns summary counts. Run with --show-ui to see detailed errors in EasyEDA panel.",
        };
    ''' % ("true" if show_ui else "false")
    return exec_code(code)


def detect_duplicate_labels():
    code = '''
        const allComps = await eda.sch_PrimitiveComponent.getAll();
        const posMap = new Map();
        for (const c of allComps||[]) {
            if (c.designator && c.designator !== '?') continue;
            const k = c.x + ',' + c.y;
            if (!posMap.has(k)) posMap.set(k, []);
            posMap.get(k).push({
                id: c.primitiveId,
                type: c.net ? 'NetFlag' : 'NetPort',
                net: c.net,
                rotation: c.rotation,
            });
        }
        const duplicates = [];
        for (const [pos, items] of posMap) {
            if (items.length > 1) duplicates.push({ position: pos, items });
        }
        return { count: duplicates.length, duplicates };
    '''
    return exec_code(code)


def cleanup_duplicate_labels():
    code = '''
        const allComps = await eda.sch_PrimitiveComponent.getAll();
        const posMap = new Map();
        for (const c of allComps||[]) {
            if (c.designator && c.designator !== '?') continue;
            const k = c.x + ',' + c.y;
            if (!posMap.has(k)) posMap.set(k, []);
            posMap.get(k).push(c.primitiveId);
        }
        const toDelete = [];
        const details = [];
        for (const [pos, ids] of posMap) {
            if (ids.length > 1) {
                const keep = ids[0];
                const remove = ids.slice(1);
                toDelete.push(...remove);
                details.push({ position: pos, kept: keep, removed: remove });
            }
        }
        if (toDelete.length > 0) await eda.sch_PrimitiveComponent.delete(toDelete);
        return { deleted: toDelete.length, details };
    '''
    return exec_code(code)


def check_wire_nets():
    # ⚠️ sch_PrimitiveWire.getAll() 在某些版本返回空数组，
    # 必须用 getAllPrimitiveId() + getPrimitiveByPrimitiveId() 逐个查询
    code = '''
        const ids = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wiresNoNet = [];
        const allWires = [];
        for (const id of ids||[]) {
            const prim = await eda.sch_Primitive.getPrimitiveByPrimitiveId(id);
            if (prim) {
                allWires.push({ id: id, net: prim.net, line: prim.line });
                if (!prim.net || prim.net === "") {
                    wiresNoNet.push({ id: id, line: prim.line, net: prim.net });
                }
            }
        }
        return { total: allWires.length, noNet: wiresNoNet.length, wiresNoNet };
    '''
    return exec_code(code)


def detect_unconnected_pins():
    """检测未连接引脚。

    改进点:
    1. 4PIN 轻触开关感知: PIN1↔PIN2, PIN3↔PIN4 内部短接，只接一对即可
    2. NC 标记感知: 有 NC 标记的引脚不算未连接
    3. 误差/警告分级: 区分"应连接"和"可能正常"
    """
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("part", false);
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const allComps = await eda.sch_PrimitiveComponent.getAll();

        // 收集所有连接点 (导线端点 + 网络标签位置)
        const connPoints = new Set();
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.line) continue;
            for (let i = 0; i < w.line.length; i += 2) {
                connPoints.add(w.line[i] + "," + w.line[i+1]);
            }
        }
        for (const c of allComps || []) {
            // NetFlag / NetPort / NetLabel 都算连接点
            if (c.net || c.componentType === "netflag" || c.componentType === "netport" || c.componentType === "netlabel") {
                connPoints.add(c.x + "," + c.y);
            }
        }

        // NC 标记位置集合
        const ncPoints = new Set();
        for (const c of allComps || []) {
            if (c.componentType === "netflag" && (c.net === "NC" || c.name === "NC")) {
                ncPoints.add(c.x + "," + c.y);
            }
        }

        const isConn = (x, y) => connPoints.has(x + "," + y) || ncPoints.has(x + "," + y);
        const isNC = (x, y) => ncPoints.has(x + "," + y);

        const errors = [];   // 应连接但未连接
        const warnings = []; // 可能正常 (4PIN开关冗余引脚等)
        let totalPinsChecked = 0;

        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps?.[0];
            if (!c?.designator || c.designator === '?' || c.designator.includes('?')) continue;
            const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
            if (!pins || pins.length === 0) continue;

            // 判断是否为 4PIN 轻触开关 (PIN1↔PIN2, PIN3↔PIN4 内部短接)
            const symName = (c.symbol?.name || c.name || "").toUpperCase();
            const is4pinSwitch = pins.length === 4 && (
                symName.includes("SWITCH") || symName.includes("轻触") ||
                symName.includes("4PIN") || symName.includes("SMD_4")
            );

            if (is4pinSwitch) {
                // 按引脚号排序: [pin0, pin1, pin2, pin3]
                const sortedPins = [...pins].sort((a, b) => (a.number || 0) - (b.number || 0));
                // 组1: PIN1/PIN2, 组2: PIN3/PIN4
                const groups = [[sortedPins[0], sortedPins[1]], [sortedPins[2], sortedPins[3]]];
                for (const grp of groups) {
                    totalPinsChecked += grp.length;
                    const anyConnected = grp.some(p => isConn(p.x, p.y));
                    const anyNC = grp.some(p => isNC(p.x, p.y));
                    if (anyNC) continue; // 有 NC 标记，OK
                    if (!anyConnected) {
                        // 两个都没连，报 error
                        for (const p of grp) {
                            errors.push({ designator: c.designator, pin: p.number, x: p.x, y: p.y,
                                         reason: "4PIN开关引脚对均未连接" });
                        }
                    } else {
                        // 至少一个已连接，另一个未连是正常 (内部短接)
                        for (const p of grp) {
                            if (!isConn(p.x, p.y)) {
                                warnings.push({ designator: c.designator, pin: p.number, x: p.x, y: p.y,
                                               reason: "4PIN开关内部短接，冗余引脚未接 (正常)" });
                            }
                        }
                    }
                }
            } else {
                // 普通器件: 逐引脚检查
                for (const pin of pins) {
                    totalPinsChecked++;
                    if (isConn(pin.x, pin.y)) continue;
                    if (isNC(pin.x, pin.y)) continue;
                    // 原生 NC 标记 (setState_NoConnected)
                    if (pin.getState_NoConnected && pin.getState_NoConnected()) continue;
                    errors.push({ designator: c.designator, pin: pin.number, x: pin.x, y: pin.y,
                                 reason: "引脚未连接且无 NC 标记" });
                }
            }
        }

        return {
            totalPinsChecked,
            errorCount: errors.length,
            warningCount: warnings.length,
            errors,
            warnings,
        };
    '''
    return exec_code(code)


def check_wire_through_component():
    code = '''
        const partIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("part", false);
        const components = [];
        for (const id of partIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps[0];
            if (!c.designator || c.designator === '?' || c.designator.includes('?')) continue;
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            components.push({
                id, designator: c.designator,
                bbox: { minX: bbox.minX, maxX: bbox.maxX, minY: bbox.minY, maxY: bbox.maxY },
            });
        }
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wireSegments = [];
        for (const id of wireIds) {
            const wires = await eda.sch_PrimitiveWire.get([id]);
            const w = wires[0];
            if (!w) continue;
            const line = w.line || [];
            for (let i = 0; i < line.length - 2; i += 2) {
                wireSegments.push({
                    id: id, net: w.net || '',
                    x1: line[i], y1: line[i+1],
                    x2: line[i+2], y2: line[i+3],
                });
            }
        }
        const violations = [];
        for (const seg of wireSegments) {
            for (const comp of components) {
                const b = comp.bbox;
                const margin = 3;
                const inner = { minX: b.minX + margin, maxX: b.maxX - margin, minY: b.minY + margin, maxY: b.maxY - margin };
                const p1Inside = seg.x1 > inner.minX && seg.x1 < inner.maxX && seg.y1 > inner.minY && seg.y1 < inner.maxY;
                const p2Inside = seg.x2 > inner.minX && seg.x2 < inner.maxX && seg.y2 > inner.minY && seg.y2 < inner.maxY;
                if (p1Inside || p2Inside) {
                    violations.push({
                        wireId: seg.id, net: seg.net,
                        line: [seg.x1, seg.y1, seg.x2, seg.y2],
                        component: comp.designator, componentId: comp.id, bbox: b,
                        reason: 'wire endpoint inside component body',
                    });
                    continue;
                }
                if (seg.x1 < b.minX && seg.x2 < b.minX) continue;
                if (seg.x1 > b.maxX && seg.x2 > b.maxX) continue;
                if (seg.y1 < b.minY && seg.y2 < b.minY) continue;
                if (seg.y1 > b.maxY && seg.y2 > b.maxY) continue;
                const dx = seg.x2 - seg.x1, dy = seg.y2 - seg.y1;
                const tMinX = dx !== 0 ? (b.minX - seg.x1) / dx : -Infinity;
                const tMaxX = dx !== 0 ? (b.maxX - seg.x1) / dx : Infinity;
                const tMinY = dy !== 0 ? (b.minY - seg.y1) / dy : -Infinity;
                const tMaxY = dy !== 0 ? (b.maxY - seg.y1) / dy : Infinity;
                const tEnter = Math.max(Math.min(tMinX, tMaxX), Math.min(tMinY, tMaxY));
                const tExit = Math.min(Math.max(tMinX, tMaxX), Math.max(tMinY, tMaxY));
                if (tEnter < tExit && tExit > 0 && tEnter < 1) {
                    const t1 = Math.max(0, tEnter), t2 = Math.min(1, tExit);
                    if (t1 < t2) {
                        const crossLen = Math.sqrt((dx * (t2 - t1)) ** 2 + (dy * (t2 - t1)) ** 2);
                        if (crossLen > 5) {
                            violations.push({
                                wireId: seg.id, net: seg.net,
                                line: [seg.x1, seg.y1, seg.x2, seg.y2],
                                component: comp.designator, componentId: comp.id, bbox: b,
                                crossLength: Math.round(crossLen),
                                reason: 'wire line passes through component body',
                            });
                        }
                    }
                }
            }
        }
        return {
            wireThroughCount: violations.length,
            wiresThroughComponents: violations,
            summary: violations.length === 0
                ? 'PASS: no wire-through-component detected'
                : 'FAIL: ' + violations.length + ' wire(s) pass through component body',
        };
    '''
    return exec_code(code)


def detect_shorts():
    """检测短路: 不同网络名的导线在物理上连接在一起。

    原理:
    1. 收集所有导线端点和网络标签位置，建立"连接点→网络名"映射
    2. 用并查集 (union-find) 合并物理上相连的连接点
    3. 如果同一个连通分量中有 2+ 个不同网络名 → 短路
    """
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const allComps = await eda.sch_PrimitiveComponent.getAll();

        // pointKey -> Set<nets>  (每个物理点关联的网络名)
        const pointNets = new Map();
        // 导线线段: [{key1, key2, net, id}]
        const segments = [];

        const key = (x, y) => x + "," + y;

        // 收集导线段
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.line || w.line.length < 4) continue;
            const net = w.net || "";
            for (let i = 0; i + 3 < w.line.length; i += 2) {
                const k1 = key(w.line[i], w.line[i+1]);
                const k2 = key(w.line[i+2], w.line[i+3]);
                segments.push({ k1, k2, net, id: w.primitiveId });
                if (!pointNets.has(k1)) pointNets.set(k1, new Set());
                if (!pointNets.has(k2)) pointNets.set(k2, new Set());
                if (net) { pointNets.get(k1).add(net); pointNets.get(k2).add(net); }
            }
        }

        // 收集网络标签位置 → 网络名
        for (const c of allComps || []) {
            if (c.net && (c.componentType === "netflag" || c.componentType === "netport" || c.componentType === "netlabel")) {
                const k = key(c.x, c.y);
                if (!pointNets.has(k)) pointNets.set(k, new Set());
                pointNets.get(k).add(c.net);
            }
        }

        // 并查集: 合并物理相连的点
        const parent = new Map();
        const find = (x) => {
            if (!parent.has(x)) parent.set(x, x);
            if (parent.get(x) !== x) parent.set(x, find(parent.get(x)));
            return parent.get(x);
        };
        const union = (a, b) => { parent.set(find(a), find(b)); };

        for (const seg of segments) {
            union(seg.k1, seg.k2);
        }

        // 每个连通分量收集所有网络名
        const groupNets = new Map(); // root -> Set<nets>
        for (const [pt, nets] of pointNets) {
            const root = find(pt);
            if (!groupNets.has(root)) groupNets.set(root, new Set());
            for (const n of nets) groupNets.get(root).add(n);
        }

        // 找出有 2+ 不同网络名的连通分量 = 短路
        const shorts = [];
        for (const [root, nets] of groupNets) {
            if (nets.size >= 2) {
                // 找出这个连通分量中的所有导线
                const involvedWires = new Set();
                const involvedPoints = [];
                for (const [pt, nets2] of pointNets) {
                    if (find(pt) === root) {
                        involvedPoints.push(pt);
                    }
                }
                for (const seg of segments) {
                    if (find(seg.k1) === root) involvedWires.add(seg.id);
                }
                shorts.push({
                    nets: [...nets],
                    points: involvedPoints,
                    wireCount: involvedWires.size,
                    wireIds: [...involvedWires],
                });
            }
        }

        return {
            shortCount: shorts.length,
            shorts,
            passed: shorts.length === 0,
            summary: shorts.length === 0 ? "PASS" : "FAIL: " + shorts.length + " short(s) detected",
        };
    '''
    return exec_code(code)


def detect_redundant_wires():
    """检测冗余导线: 同两个物理点之间有多条导线。

    冗余导线不会引起电气错误，但会让原理图显得凌乱且难以维护。
    """
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        // pairKey -> [{id, net}]
        const pairMap = new Map();

        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.line || w.line.length < 4) continue;
            // 只检查单段导线 (2点)
            if (w.line.length === 4) {
                const x1 = w.line[0], y1 = w.line[1], x2 = w.line[2], y2 = w.line[3];
                // 规范化 key: 较小的点在前 (方向无关)
                const p1 = x1 + "," + y1, p2 = x2 + "," + y2;
                const pairKey = p1 < p2 ? p1 + "|" + p2 : p2 + "|" + p1;
                if (!pairMap.has(pairKey)) pairMap.set(pairKey, []);
                pairMap.get(pairKey).push({ id: w.primitiveId, net: w.net || "" });
            }
        }

        const redundant = [];
        for (const [pairKey, wires] of pairMap) {
            if (wires.length > 1) {
                redundant.push({ endpoints: pairKey, count: wires.length, wires });
            }
        }

        return {
            redundantCount: redundant.length,
            redundant,
            passed: redundant.length === 0,
            summary: redundant.length === 0 ? "PASS" : "FAIL: " + redundant.length + " redundant wire pair(s)",
        };
    '''
    return exec_code(code)


def detect_pin_shorts():
    """检测引脚短路：同一网络上不同功能的引脚被短接。

    检测两种情况：
    1. 同一器件的多个引脚在同一网络上，且这些引脚的 pinName 不同
       (例: pin19=VCC + pin20=GND 都在 net=VCC 上 → 短路)
    2. 单个引脚的 pinName 与所在网络不匹配
       (例: pinName=GND 的引脚在 net=VCC 上 → 短路)

    返回: { pinShortCount, pinShorts: [...], passed }
    """
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const allComps = await eda.sch_PrimitiveComponent.getAll();

        // 建立连接点 -> 网络名 映射
        const pointNet = new Map();
        for (const wid of wireIds) {
            const ws = await eda.sch_PrimitiveWire.get([wid]);
            const w = ws?.[0];
            if (!w?.line || !w.net) continue;
            for (let i = 0; i < w.line.length; i += 2) {
                pointNet.set(w.line[i] + "," + w.line[i+1], w.net);
            }
        }
        for (const c of allComps || []) {
            if (c.net && (c.componentType === "netflag" || c.componentType === "netport" || c.componentType === "netlabel")) {
                pointNet.set(c.x + "," + c.y, c.net);
            }
        }

        const pinShorts = [];

        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps?.[0];
            if (!c?.designator || c.designator === '?' || c.designator.includes('?')) continue;
            const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
            if (!pins || pins.length === 0) continue;

            // net -> [{pinNumber, pinName}]
            const netPins = new Map();
            for (const pin of pins) {
                const k = pin.x + "," + pin.y;
                const net = pointNet.get(k);
                if (!net) continue;
                if (!netPins.has(net)) netPins.set(net, []);
                netPins.get(net).push({
                    pinNumber: pin.pinNumber || "?",
                    pinName: (pin.pinName || "").toUpperCase().replace(/\\s+/g, ""),
                });
            }

            // 检查每个网络上的引脚
            for (const [net, pins] of netPins) {
                if (pins.length < 2) continue;
                // 获取不同的 pinName
                const uniqueNames = [...new Set(pins.map(p => p.pinName))];
                // 如果有 2+ 个不同 pinName 在同一网络上 → 短路
                // (例: VCC 引脚 + GND 引脚都在 net=VCC 上)
                if (uniqueNames.length >= 2) {
                    pinShorts.push({
                        designator: c.designator,
                        net: net,
                        pins: pins.map(p => p.pinNumber),
                        pinNames: pins.map(p => p.pinName),
                        issue: "Different pin types on same net: " + uniqueNames.join(", "),
                    });
                }
                // 即使 pinName 相同，如果 2+ 个非电源引脚在同一信号网络上 → 可能短路
                else if (uniqueNames.length === 1) {
                    const pinName = uniqueNames[0];
                    const powerPins = new Set(["VCC", "VDD", "3V3", "3.3V", "5V", "VBAT", "VBUS", "GND", "VSS", "DGND", "AGND", "EARTH"]);
                    if (!powerPins.has(pinName)) {
                        pinShorts.push({
                            designator: c.designator,
                            net: net,
                            pins: pins.map(p => p.pinNumber),
                            pinNames: uniqueNames,
                            issue: "Multiple signal pins (" + pinName + ") on same net",
                        });
                    }
                }
            }
        }

        return {
            pinShortCount: pinShorts.length,
            pinShorts,
            passed: pinShorts.length === 0,
            summary: pinShorts.length === 0 ? "PASS" : "FAIL: " + pinShorts.length + " pin short(s) detected",
        };
    '''
    return exec_code(code)


def run_full_check():
    """一键全量检查：8 步检查

    1. 重复标签  2. 导线网络名  3. 未连接引脚 (4PIN感知+NC感知)
    4. 短路检测  5. 冗余导线  6. 引脚短路 (同器件多引脚同一网络)
    7. 导线穿器件  8. DRC
    """
    report = {"timestamp": "", "checks": {}}

    # 1. 重复标签
    dup = detect_duplicate_labels()
    report["checks"]["duplicates"] = dup

    # 2. 导线网络名
    wire_nets = check_wire_nets()
    report["checks"]["wireNets"] = wire_nets

    # 3. 未连接引脚 (改进版: 4PIN开关感知 + NC标记感知)
    unconnected = detect_unconnected_pins()
    report["checks"]["unconnected"] = unconnected

    # 4. 短路检测
    shorts = detect_shorts()
    report["checks"]["shorts"] = shorts

    # 5. 冗余导线
    redundant = detect_redundant_wires()
    report["checks"]["redundantWires"] = redundant

    # 6. 引脚短路 (同器件多引脚同一网络)
    pin_shorts = detect_pin_shorts()
    report["checks"]["pinShorts"] = pin_shorts

    # 7. 导线穿器件
    wire_through = check_wire_through_component()
    report["checks"]["wireThrough"] = wire_through

    # 8. DRC
    drc = run_drc()
    report["checks"]["drc"] = drc

    # 汇总
    statuses = []
    for name, check in report["checks"].items():
        status = check.get("passed") if "passed" in check else check.get("status")
        if status is None:
            status = "PASS" if (check.get("errorCount", 1) == 0 and check.get("shortCount", 1) == 0
                                and check.get("redundantCount", 1) == 0) else "FAIL"
        statuses.append("PASS" if status in (True, "PASS", 0) else "FAIL")
    report["overall"] = "PASS" if all(s == "PASS" for s in statuses) else "FAIL"
    return report


def verify_placement():
    """验证器件摆放质量（每次放置模块后执行）

    与 JS draw-utils.js verifyPlacement 完全对齐：5 步检查
      1. 收集所有真实器件信息（用 getPrimitivesBBox 获取真实符号包围盒）
      2. 器件重叠检测
      3. 同类型器件间距检查
      4. 旋转合理性（二极管极性方向）
      5. wire-component 重叠检查（导线穿过器件本体）
    """
    code = '''
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const bboxes = [];
        const components = [];
        const issues = [];

        // 1. 收集所有真实器件信息（用 getPrimitivesBBox 获取真实符号包围盒）
        for (const id of compIds) {
            const comps = await eda.sch_PrimitiveComponent.get([id]);
            const c = comps[0];
            if (!c.designator || c.designator === '?' || c.designator.includes('?')) continue;
            const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
            if (!pins || pins.length === 0) continue;

            const pinCoords = pins.map(p => ({x:p.x, y:p.y}));
            const realBbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            const minX = realBbox?.minX ?? Math.min(...pinCoords.map(p=>p.x));
            const maxX = realBbox?.maxX ?? Math.max(...pinCoords.map(p=>p.x));
            const minY = realBbox?.minY ?? Math.min(...pinCoords.map(p=>p.y));
            const maxY = realBbox?.maxY ?? Math.max(...pinCoords.map(p=>p.y));
            bboxes.push({ id, designator: c.designator, bbox: [minX, minY, maxX, maxY], width: maxX-minX, height: maxY-minY, pinCoords });
            components.push({ id, designator: c.designator, x: c.x, y: c.y, rotation: c.rotation, pinCoords });
        }

        // 2. 重叠检测
        const overlaps = [];
        for (let i=0; i<bboxes.length; i++) {
            for (let j=i+1; j<bboxes.length; j++) {
                const a=bboxes[i].bbox, b=bboxes[j].bbox;
                if (a[0]<b[2] && a[2]>b[0] && a[1]<b[3] && a[3]>b[1]) {
                    overlaps.push({ comp1: bboxes[i].designator, comp2: bboxes[j].designator });
                }
            }
        }

        // 3. 同类型器件间距检查
        const closePairs = [];
        for (let i=0; i<bboxes.length; i++) {
            for (let j=i+1; j<bboxes.length; j++) {
                const prefix1 = bboxes[i].designator.replace(/[0-9]/g,'');
                const prefix2 = bboxes[j].designator.replace(/[0-9]/g,'');
                if (prefix1 !== prefix2) continue;
                const a=bboxes[i].bbox, b=bboxes[j].bbox;
                const distX = Math.min(Math.abs(a[2]-b[0]), Math.abs(b[2]-a[0]));
                const distY = Math.min(Math.abs(a[3]-b[1]), Math.abs(b[3]-a[1]));
                if (distX < 40 && distY < 40) {
                    closePairs.push({ comp1: bboxes[i].designator, comp2: bboxes[j].designator, gapX: distX, gapY: distY });
                }
            }
        }

        // 4. 旋转检查（二极管极性方向）
        for (const c of components) {
            if (c.designator.startsWith('D') && c.rotation === 0) {
                issues.push({ type: 'rotation_suggestion', designator: c.designator, detail: '水平放置的二极管建议旋转 270 度使 A(上)K(下)排列' });
            }
        }

        // 5. wire-component 重叠检查（导线穿过器件本体）
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wireCompsOverlaps = [];
        for (const wid of wireIds||[]) {
            const prim = await eda.sch_Primitive.getPrimitiveByPrimitiveId(wid);
            const line = prim?.line || [];
            if (line.length < 2) continue;
            let wMinX=Infinity, wMaxX=-Infinity, wMinY=Infinity, wMaxY=-Infinity;
            for (let k=0; k<line.length; k+=2) {
                wMinX=Math.min(wMinX,line[k]); wMaxX=Math.max(wMaxX,line[k]);
                wMinY=Math.min(wMinY,line[k+1]); wMaxY=Math.max(wMaxY,line[k+1]);
            }
            for (const b of bboxes) {
                if (wMinX < b.bbox[2] && wMaxX > b.bbox[0] && wMinY < b.bbox[3] && wMaxY > b.bbox[1]) {
                    const ow = Math.min(wMaxX,b.bbox[2]) - Math.max(wMinX,b.bbox[0]);
                    const oh = Math.min(wMaxY,b.bbox[3]) - Math.max(wMinY,b.bbox[1]);
                    if (ow*oh < 5) continue; // 微小接触跳过
                    // 检查导线端点是否在器件引脚上（正常连接）
                    let atPin = false;
                    for (let k=0; k<line.length; k+=2) {
                        const wx=line[k], wy=line[k+1];
                        for (const cp of b.pinCoords || []) {
                            if (Math.abs(wx-cp.x)<3 && Math.abs(wy-cp.y)<3) { atPin=true; break; }
                        }
                        if (atPin) break;
                    }
                    if (atPin) continue;
                    wireCompsOverlaps.push({ wireNet: prim?.net||'(none)', component: b.designator,
                        bbox: [wMinX,wMinY,wMaxX,wMaxY], compBbox: b.bbox });
                }
            }
        }

        return {
            totalComponents: components.length,
            overlaps: { count: overlaps.length, items: overlaps, status: overlaps.length===0?"PASS":"FAIL" },
            closePairs: { count: closePairs.length, items: closePairs, status: closePairs.length===0?"PASS":"WARN" },
            wireCompsOverlaps: { count: wireCompsOverlaps.length, items: wireCompsOverlaps, status: wireCompsOverlaps.length===0?"PASS":"FAIL" },
            issues,
            status: overlaps.length===0 && wireCompsOverlaps.length===0 ? "PASS" : "FAIL"
        };
    '''
    return exec_code(code)


def verify_wiring():
    """验证连线质量（每次连线后执行）

    与 JS draw-utils.js verifyWiring 完全对齐：3 项检查
      1. 导线网络名检查（无网络名的导线）
      2. 标签重复检查（同一坐标多个 NetFlag/NetPort）
      3. 孤立标签检测（没有导线连接且不在 IC 引脚上的标签）

    注：未连接引脚检测由 detect_unconnected_pins / check-nc-coverage 负责，
    本函数不再重复实现，与 JS 行为一致。
    """
    code = '''
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        const wires = [];
        for (const wid of wireIds||[]) {
            const prim = await eda.sch_Primitive.getPrimitiveByPrimitiveId(wid);
            if (prim) wires.push({ primitiveId: wid, net: prim.net, line: prim.line });
        }
        const allComps = await eda.sch_PrimitiveComponent.getAll();
        const issues = [];

        // 1. 导线网络名检查
        const wiresNoNet = [];
        for (const w of wires) {
            if (!w.net || w.net === "") wiresNoNet.push({ id: w.primitiveId, line: w.line });
        }

        // 2. 标签重复检查
        const posMap = new Map();
        for (const c of allComps||[]) {
            // NetFlag/NetPort: designator is null or "?" (not a real component)
            if (c.designator && c.designator !== '?') continue;
            const k = c.x + ',' + c.y;
            if (!posMap.has(k)) posMap.set(k, []);
            posMap.get(k).push({ id: c.primitiveId, net: c.net, type: c.net ? 'NetFlag' : 'NetPort' });
        }
        const duplicates = [];
        for (const [pos, items] of posMap) {
            if (items.length > 1) duplicates.push({ position: pos, items });
        }

        // 3. 孤立标签检测（没有导线连接的标签）
        const compIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId();
        const wireSegments = [];
        for (const w of wires) {
            const line = w.line || [];
            for (let i=0; i<line.length; i+=2) {
                if (i+3 < line.length) wireSegments.push({x1:line[i], y1:line[i+1], x2:line[i+2], y2:line[i+3]});
            }
        }
        const lonelyLabels = [];
        for (const c of allComps||[]) {
            if (c.designator && c.designator !== '?') continue;
            let hasWire = false;
            for (const s of wireSegments) {
                if (Math.abs(s.x1-c.x)<1&&Math.abs(s.y1-c.y)<1 || Math.abs(s.x2-c.x)<1&&Math.abs(s.y2-c.y)<1) {
                    hasWire = true; break;
                }
            }
            // 也检查标签是否在 IC 引脚上
            let onPin = false;
            for (const id of compIds) {
                const comps = await eda.sch_PrimitiveComponent.get([id]);
                const cc = comps[0];
                if (!cc.designator || cc.designator==='?' || cc.designator.includes('?')) continue;
                const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
                if (!pins) continue;
                for (const p of pins) {
                    if (Math.abs(p.x-c.x)<1 && Math.abs(p.y-c.y)<1) { onPin = true; break; }
                }
                if (onPin) break;
            }
            if (!hasWire && !onPin) {
                lonelyLabels.push({ id: c.primitiveId, net: c.net, type: c.net ? 'NetFlag' : 'NetPort', x: c.x, y: c.y });
            }
        }

        return {
            totalWires: (wires||[]).length,
            wiresNoNet: { count: wiresNoNet.length, items: wiresNoNet, status: wiresNoNet.length===0?"PASS":"FAIL" },
            duplicates: { count: duplicates.length, items: duplicates, status: duplicates.length===0?"PASS":"FAIL" },
            lonelyLabels: { count: lonelyLabels.length, items: lonelyLabels, status: lonelyLabels.length===0?"PASS":"WARN" },
            status: wiresNoNet.length===0 && duplicates.length===0 ? "PASS" : "FAIL"
        };
    '''
    return exec_code(code)


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def do_select_primitives(primitive_ids):
    return exec_code("return await eda.sch_SelectControl.select(%s);" % json.dumps(primitive_ids))


def clear_selected():
    return exec_code("return await eda.sch_SelectControl.clearSelected();")


def get_primitives_bbox(primitive_ids):
    return exec_code("return await eda.sch_Primitive.getPrimitivesBBox(%s);" % json.dumps(primitive_ids))


def check_overlaps():
    """全类型重叠检测（器件/端口/标识/标签/文本/属性/导线）+ 6 条误报过滤规则

    与 JS draw-utils.js checkOverlaps 完全对齐：默认所有类型都检测。
    6 条过滤规则避免伪阳性：
      1. wire-component: 导线端点在器件 BBox 边缘=引脚连接，跳过
      2. netflag-wire: NetFlag 中心点在导线端点上=电气连接，跳过
      3. netflag-attribute: NetFlag 与自身文字，跳过
      4. attribute-component: 属性文字在器件内部，跳过
      5. attribute-wire: 引脚名称与自身导线微小接触（面积<5），跳过
      6. attribute-attribute: Pin Name 与 Pin Number 并列，跳过
    """
    code = '''
        const items = [];

        // 1. 器件 (Component)
        const partIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("part", false);
        for (const id of partIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            items.push({ id, bbox, type: "component", designator: c?.designator || "?", net: c?.net || "", x: c?.x, y: c?.y });
        }

        // 2. 网络端口 (NetPort)
        const netPortIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("netport", false);
        for (const id of netPortIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            items.push({ id, bbox, type: "netport", designator: c?.designator || "?", net: c?.net || "", x: c?.x, y: c?.y, direction: c?.direction || "" });
        }

        // 3. 网络标识 (NetFlag) — VCC/GND 等电源符号
        const netFlagIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("netflag", false);
        for (const id of netFlagIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            items.push({ id, bbox, type: "netflag", designator: c?.designator || "?", net: c?.net || "", x: c?.x, y: c?.y });
        }

        // 4. 网络标签 (NetLabel)
        const netLabelIds = await eda.sch_PrimitiveComponent.getAllPrimitiveId("netlabel", false);
        for (const id of netLabelIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const c = (await eda.sch_PrimitiveComponent.get([id]))[0];
            items.push({ id, bbox, type: "netlabel", designator: c?.designator || "?", net: c?.net || "", x: c?.x, y: c?.y });
        }

        // 5. 文本
        const textIds = await eda.sch_PrimitiveText.getAllPrimitiveId();
        for (const id of textIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const t = (await eda.sch_PrimitiveText.get([id]))[0];
            items.push({ id, bbox, type: "text", content: (t?.content || "").slice(0, 30), x: t?.x, y: t?.y });
        }

        // 6. 属性文字 (Pin Name/Number, Designator 等) — 关键：检测引脚名称与导线/标签重叠
        const attrIds = await eda.sch_PrimitiveAttribute.getAllPrimitiveId();
        const compMap = {};
        for (const item of items) {
            if (item.type === "component" && item.designator) compMap[item.id] = item.designator;
        }
        for (const id of attrIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const a = (await eda.sch_PrimitiveAttribute.get([id]))[0];
            if (!a || !a.value) continue;
            items.push({ id, bbox, type: "attribute", key: a.key || "", value: (a.value || "").slice(0, 20), x: a.x, y: a.y, parentDesignator: compMap[a.parentPrimitiveId] || "" });
        }

        // 7. 导线 (通过线段坐标判断)
        const wireIds = await eda.sch_PrimitiveWire.getAllPrimitiveId();
        for (const id of wireIds) {
            const bbox = await eda.sch_Primitive.getPrimitivesBBox([id]);
            if (!bbox) continue;
            const wires = await eda.sch_PrimitiveWire.get([id]);
            const w = wires[0];
            if (!w) continue;
            items.push({ id, bbox, type: "wire", net: w.getState_Net?.() || "", line: w.getState_Line?.() });
        }

        // ─── 检测重叠 ───
        const overlaps = [];
        for (let i = 0; i < items.length; i++) {
            for (let j = i + 1; j < items.length; j++) {
                const a = items[i].bbox, b = items[j].bbox;
                if (!(a.minX < b.maxX && a.maxX > b.minX && a.minY < b.maxY && a.maxY > b.minY)) continue;

                const overlapW = Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX);
                const overlapH = Math.min(a.maxY, b.maxY) - Math.max(a.minY, b.minY);
                const overlapArea = overlapW * overlapH;

                // 1. wire-component: 检查导线端点是否在器件引脚上 → 正常跳过
                const isWireComp = (items[i].type === "wire" && items[j].type === "component")
                                || (items[i].type === "component" && items[j].type === "wire");
                if (isWireComp) {
                    if (overlapArea < 5) continue;
                    const wireItem = items[i].type === "wire" ? items[i] : items[j];
                    const compItem = items[i].type === "component" ? items[i] : items[j];
                    const wl = wireItem.line || [];
                    let atPinEdge = false;
                    for (let k = 0; k < wl.length; k += 2) {
                        const wx = wl[k], wy = wl[k+1];
                        const cb = compItem.bbox;
                        if ((Math.abs(wx - cb.minX) < 5 || Math.abs(wx - cb.maxX) < 5) &&
                            wy > cb.minY - 5 && wy < cb.maxY + 5) { atPinEdge = true; break; }
                        if ((Math.abs(wy - cb.minY) < 5 || Math.abs(wy - cb.maxY) < 5) &&
                            wx > cb.minX - 5 && wx < cb.maxX + 5) { atPinEdge = true; break; }
                    }
                    if (atPinEdge) continue;
                }

                // 2. netflag-wire: NetFlag 中心点在导线端点上 -> 电气连接正确，跳过
                const isFlagWire = (items[i].type === "netflag" && items[j].type === "wire")
                                || (items[i].type === "wire" && items[j].type === "netflag");
                if (isFlagWire) {
                    const flag = items[i].type === "netflag" ? items[i] : items[j];
                    const wire = items[i].type === "wire" ? items[i] : items[j];
                    if (!flag.x || !flag.y) continue;
                    const wireEndpoints = [];
                    const wl = wire.line || wire.getState_Line?.() || [];
                    for (let k = 0; k < wl.length; k += 2) wireEndpoints.push([wl[k], wl[k+1]]);
                    let onEndpoint = false;
                    for (const [ex, ey] of wireEndpoints) {
                        if (Math.abs(flag.x - ex) < 3 && Math.abs(flag.y - ey) < 3) { onEndpoint = true; break; }
                    }
                    if (onEndpoint) continue;
                }

                // 3. netflag-attribute: NetFlag 与自身文字 - 跳过
                if ((items[i].type === "netflag" && items[j].type === "attribute")
                 || (items[i].type === "attribute" && items[j].type === "netflag")) continue;

                // 4. attribute-component: 属性文字在器件内部 -> 正常
                const isAttrComp = (items[i].type === "attribute" && items[j].type === "component")
                                || (items[i].type === "component" && items[j].type === "attribute");
                if (isAttrComp) continue;

                // 5. attribute-wire: 仅引脚名称与自身导线微小接触跳过（面积 < 5）
                const isAttrWire = (items[i].type === "attribute" && items[j].type === "wire")
                                || (items[i].type === "wire" && items[j].type === "attribute");
                if (isAttrWire && overlapArea < 5) continue;

                // 6. attribute-attribute: Pin Name 与 Pin Number 并列 -> 正常
                const isAttrAttr = items[i].type === "attribute" && items[j].type === "attribute";
                if (isAttrAttr) {
                    const ki = items[i].key || "", kj = items[j].key || "";
                    if ((ki === "Pin Name" && kj === "Pin Number") || (ki === "Pin Number" && kj === "Pin Name")) continue;
                }

                overlaps.push({
                    pair: [
                        { type: items[i].type, id: items[i].id, designator: items[i].designator, net: items[i].net, bbox: items[i].bbox },
                        { type: items[j].type, id: items[j].id, designator: items[j].designator, net: items[j].net, bbox: items[j].bbox },
                    ],
                    overlapRegion: {
                        minX: Math.max(a.minX, b.minX),
                        maxX: Math.min(a.maxX, b.maxX),
                        minY: Math.max(a.minY, b.minY),
                        maxY: Math.min(a.maxY, b.maxY),
                    },
                });
            }
        }

        // ─── 统计 ───
        const byType = {};
        for (const item of items) {
            byType[item.type] = (byType[item.type] || 0) + 1;
        }

        return {
            totalItems: items.length,
            byType,
            overlapCount: overlaps.length,
            overlaps,
            summary: overlaps.length === 0 ? "PASS: no overlaps detected" : "WARN: " + overlaps.length + " overlap(s) found",
        };
    '''
    return exec_code(code)


# ═══════════════════════════════════════════════════════════════════
# CLI 命令处理函数
# ═══════════════════════════════════════════════════════════════════

def cmd_clear(args):
    keep_ids = args.keep.split(",") if args.keep else []
    result = clear_page(keep_ids, delete_text=args.all, delete_rects=args.all)
    emit(result, verbose=args.verbose, quiet=args.quiet,
         extra_keys=("components", "wires", "texts", "rectangles"))


def cmd_delete_wires(args):
    region = None
    if args.region:
        vals = [int(x) for x in args.region.split(",")]
        region = {"minX": vals[0], "minY": vals[1], "maxX": vals[2], "maxY": vals[3]}
    nets = args.nets.split(",") if args.nets else None
    exclude_nets = args.exclude_nets.split(",") if args.exclude_nets else None
    result = delete_wires(region=region, nets=nets, exclude_nets=exclude_nets)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted", "total"))


def cmd_delete_labels(args):
    region = None
    if args.region:
        vals = [int(x) for x in args.region.split(",")]
        region = {"minX": vals[0], "minY": vals[1], "maxX": vals[2], "maxY": vals[3]}
    nets = args.nets.split(",") if args.nets else None
    exclude_nets = args.exclude_nets.split(",") if args.exclude_nets else None
    result = delete_net_labels(region=region, nets=nets, exclude_nets=exclude_nets)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_delete_wires_coords(args):
    coord_sets = [[int(x) for x in s.split(",")] for s in args.coords]
    result = delete_wires_by_coords(coord_sets)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_place(args):
    ensure_schematic()
    name = args.name or args.value
    component_id = place_component(
        library_uuid=args.lib_uuid, uuid=args.uuid,
        x=args.x, y=args.y, designator=args.designator,
        rotation=args.rotation, mirror=args.mirror,
        name=name,
    )
    # 查询并返回完整器件信息 (含 name/spec)
    info = get_component(component_id)
    summary = "Placed %s (%s) at (%d,%d)" % (
        args.designator or "component", info.get("name") or name or "unknown", args.x, args.y)
    emit(info, summary=summary, verbose=args.verbose, quiet=args.quiet)


def cmd_text(args):
    text_id = add_text(
        x=args.x, y=args.y, text=args.text,
        font_size=args.font_size, text_color=args.color,
        font_name=args.font, bold=args.bold, italic=args.italic,
        underline=args.underline, align_mode=args.align,
    )
    emit({"id": text_id}, summary="Added text at (%d,%d)" % (args.x, args.y),
         verbose=args.verbose, quiet=args.quiet)


def cmd_get_text(args):
    result = get_text(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_text(args):
    changes = {}
    if args.x is not None: changes["x"] = args.x
    if args.y is not None: changes["y"] = args.y
    if args.content is not None: changes["content"] = args.content
    if args.color is not None: changes["textColor"] = args.color
    if args.font is not None: changes["fontName"] = args.font
    if args.size is not None: changes["fontSize"] = args.size
    if args.align is not None: changes["alignMode"] = args.align
    if args.bold: changes["bold"] = True
    if args.italic: changes["italic"] = True
    if args.underline: changes["underLine"] = True
    if args.no_bold: changes["bold"] = False
    if args.no_italic: changes["italic"] = False
    if args.no_underline: changes["underLine"] = False
    result = modify_text(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_list_texts(args):
    result = get_all_texts()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_texts(args):
    result = delete_texts(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_rect(args):
    rect_id = add_rect(
        x=args.x, y=args.y, width=args.w, height=args.h,
        corner_radius=args.radius, rotation=args.rot,
        color=args.color, fill_color=args.fill,
        line_width=args.width, line_type=_parse_line_type(args),
    )
    emit({"id": rect_id}, summary="Added rect at (%d,%d) %dx%d" % (args.x, args.y, args.w, args.h),
         verbose=args.verbose, quiet=args.quiet)


def cmd_get_rect(args):
    result = get_rect(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_rect(args):
    changes = {}
    if args.x is not None: changes["topLeftX"] = args.x
    if args.y is not None: changes["topLeftY"] = args.y
    if args.w is not None: changes["width"] = args.w
    if args.h is not None: changes["height"] = args.h
    if args.color is not None: changes["color"] = args.color
    if args.fill is not None: changes["fillColor"] = args.fill
    if args.radius is not None: changes["cornerRadius"] = args.radius
    if args.width is not None: changes["lineWidth"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: changes["lineType"] = lt
    if args.solid: changes["lineType"] = 0
    result = modify_rect(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_list_rects(args):
    result = get_all_rects()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_rects(args):
    result = delete_rects(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_netflag(args):
    flag_id = add_net_flag(args.type, args.net, args.x, args.y)
    emit({"id": flag_id}, summary="Added %s %s at (%d,%d)" % (args.type, args.net, args.x, args.y),
         verbose=args.verbose, quiet=args.quiet)


def cmd_netport(args):
    port_id = add_net_port(args.direction, args.net, args.x, args.y)
    emit({"id": port_id}, summary="Added netport %s at (%d,%d)" % (args.net, args.x, args.y),
         verbose=args.verbose, quiet=args.quiet)


def cmd_wire(args):
    points = [int(x) for x in args.points.split(",")]
    opts = {}
    if args.color: opts["color"] = args.color
    if args.width: opts["line_width"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: opts["line_type"] = lt

    if args.safe:
        result = add_wire_safe(points, net=args.net, **opts)
        if "error" in result:
            emit(result, summary="ABORTED: wire conflicts detected",
                 verbose=args.verbose, quiet=args.quiet)
            return
        summary = "Safe-added wire %s%s" % (args.points, " net=%s" % args.net if args.net else "")
        if result.get("warnings"):
            summary += " (warnings: %d)" % len(result["warnings"])
        emit(result, summary=summary, verbose=args.verbose, quiet=args.quiet)
    else:
        wire_id = add_wire(points, net=args.net, **opts)
        if isinstance(wire_id, dict) and wire_id.get("error"):
            emit(wire_id, summary="FAILED: %s" % wire_id["error"],
                 verbose=args.verbose, quiet=args.quiet)
            return
        net_summary = " net=%s" % args.net if args.net else ""
        emit({"id": wire_id}, summary="Added wire %s%s" % (args.points, net_summary),
             verbose=args.verbose, quiet=args.quiet)


def cmd_wire_batch(args):
    """批量创建导线: 从 JSON 文件读取多条导线规格"""
    specs = []
    if args.file:
        with open(args.file) as f:
            data = json.load(f)
            specs = data if isinstance(data, list) else data.get("wires", [])
    elif args.json:
        specs = json.loads(args.json)
    else:
        emit_error("Need --file <path> or --json '<json>'")
        return

    results = add_wire_batch(specs)
    ok_count = sum(1 for r in results["results"] if "id" in r and not isinstance(r.get("id"), dict))
    fail_count = len(results["results"]) - ok_count
    emit(results,
         summary="Batch: %d ok, %d failed" % (ok_count, fail_count),
         verbose=args.verbose, quiet=args.quiet)


def cmd_check_wire_conflicts(args):
    result = detect_wire_conflicts()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_collect_nets(args):
    result = collect_nets()
    emit(result, summary="%d nets, %d points" % (
        result.get("totalNets", 0), result.get("totalPoints", 0)),
         verbose=args.verbose, quiet=args.quiet)


def cmd_net_summary(args):
    text = export_net_summary()
    # 文本格式直接打印，不走 emit
    if isinstance(text, dict):
        emit(text, verbose=args.verbose, quiet=args.quiet)
    else:
        print(text)


def cmd_get_wire(args):
    result = get_wire_info(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_wire(args):
    changes = {}
    if args.net is not None: changes["net"] = args.net
    if args.color is not None: changes["color"] = args.color
    if args.width is not None: changes["lineWidth"] = args.width
    if args.line is not None: changes["line"] = [int(x) for x in args.line.split(",")]
    lt = _parse_line_type(args)
    if lt is not None: changes["lineType"] = lt
    if args.solid: changes["lineType"] = 0
    result = modify_wire(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_bus(args):
    points = [int(x) for x in args.points.split(",")]
    opts = {}
    if args.color: opts["color"] = args.color
    if args.width: opts["line_width"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: opts["line_type"] = lt
    bus_id = add_bus(args.name, points, **opts)
    emit({"id": bus_id}, summary="Added bus %s" % args.name,
         verbose=args.verbose, quiet=args.quiet)


def cmd_list_buses(args):
    result = get_all_buses()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_buses(args):
    result = delete_buses(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_polygon(args):
    points = [int(x) for x in args.points.split(",")]
    opts = {}
    if args.color: opts["color"] = args.color
    if args.fill: opts["fill_color"] = args.fill
    if args.width: opts["line_width"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: opts["line_type"] = lt
    poly_id = add_polygon(points, **opts)
    emit({"id": poly_id}, summary="Added polygon", verbose=args.verbose, quiet=args.quiet)


def cmd_list_polygons(args):
    result = get_all_polygons()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_polygons(args):
    result = delete_polygons(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_get_polygon(args):
    result = get_polygon(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_polygon(args):
    changes = {}
    if args.line is not None: changes["line"] = [int(x) for x in args.line.split(",")]
    if args.color is not None: changes["color"] = args.color
    if args.fill is not None: changes["fillColor"] = args.fill
    if args.width is not None: changes["lineWidth"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: changes["lineType"] = lt
    if args.solid: changes["lineType"] = 0
    result = modify_polygon(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_circle(args):
    opts = {}
    if args.color: opts["color"] = args.color
    if args.fill: opts["fill_color"] = args.fill
    if args.width: opts["line_width"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: opts["line_type"] = lt
    circle_id = add_circle(args.cx, args.cy, args.radius, **opts)
    emit({"id": circle_id}, summary="Added circle at (%d,%d) r=%d" % (args.cx, args.cy, args.radius),
         verbose=args.verbose, quiet=args.quiet)


def cmd_list_circles(args):
    result = get_all_circles()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_circles(args):
    result = delete_circles(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_arc(args):
    opts = {}
    if args.color: opts["color"] = args.color
    if args.width: opts["line_width"] = args.width
    if args.dashed: opts["line_type"] = 1
    arc_id = add_arc(args.sx, args.sy, args.rx, args.ry, args.ex, args.ey, **opts)
    emit({"id": arc_id}, summary="Added arc", verbose=args.verbose, quiet=args.quiet)


def cmd_list_arcs(args):
    result = get_all_arcs()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_arcs(args):
    result = delete_arcs(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_get_bus(args):
    result = get_bus(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_bus(args):
    changes = {}
    if args.name is not None: changes["busName"] = args.name
    if args.color is not None: changes["color"] = args.color
    if args.width is not None: changes["lineWidth"] = args.width
    lt = _parse_line_type(args)
    if lt is not None: changes["lineType"] = lt
    if args.solid: changes["lineType"] = 0
    result = modify_bus(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_search(args):
    # 优先级: --personal > --project > --lib > 系统库
    if args.personal:
        lib_uuid = get_personal_library_uuid()
        if not lib_uuid:
            emit({"ok": False, "summary": "No personal library found"},
                 verbose=args.verbose, quiet=args.quiet)
            return
    elif args.project:
        lib_uuid = get_project_library_uuid()
        if not lib_uuid:
            emit({"ok": False, "summary": "No project library found"},
                 verbose=args.verbose, quiet=args.quiet)
            return
    else:
        lib_uuid = args.lib or SYSTEM_LIBRARY_UUID
    results = search_device(args.keyword, library_uuid=lib_uuid, limit=args.limit)
    emit(results, summary="Found %d device(s) for '%s'" % (len(results), args.keyword),
         verbose=args.verbose, quiet=args.quiet)


def cmd_lib_personal(args):
    uuid = get_personal_library_uuid()
    if uuid:
        emit({"id": uuid, "libraryUuid": uuid},
             summary="Personal library UUID: %s" % uuid,
             verbose=args.verbose, quiet=args.quiet)
    else:
        emit({"ok": False, "summary": "No personal library found"},
             verbose=args.verbose, quiet=args.quiet)


def cmd_lib_project(args):
    uuid = get_project_library_uuid()
    if uuid:
        emit({"id": uuid, "libraryUuid": uuid},
             summary="Project library UUID: %s" % uuid,
             verbose=args.verbose, quiet=args.quiet)
    else:
        emit({"ok": False, "summary": "No project library found"},
             verbose=args.verbose, quiet=args.quiet)


def cmd_lib_list(args):
    libs = list_all_libraries()
    emit(libs, summary="%d librarie(s)" % len(libs),
         verbose=args.verbose, quiet=args.quiet)


def cmd_check_overlap(args):
    result = check_overlaps()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("overlapCount",))


def cmd_find_space(args):
    result = find_free_space(width=args.w, height=args.h,
                             start_x=args.sx, start_y=args.sy,
                             end_x=args.ex, end_y=args.ey)
    if result:
        emit(result, summary="Found free space at (%d,%d)" % (result["x"], result["y"]),
             verbose=args.verbose, quiet=args.quiet)
    else:
        emit({"ok": False, "summary": "No free space found"}, verbose=args.verbose, quiet=args.quiet)


def cmd_get_pins(args):
    if args.designator:
        primitive_id = find_component_by_designator(args.designator)
        if not primitive_id:
            emit_error('Component "%s" not found' % args.designator)
    else:
        primitive_id = args.id
    pins = get_component_pins(primitive_id)
    emit(pins, summary="Got %d pin(s)" % len(pins), verbose=args.verbose, quiet=args.quiet)


def cmd_get_component(args):
    """查询器件完整信息 (含 name/spec/designator/位置)"""
    if args.designator:
        primitive_id = find_component_by_designator(args.designator)
        if not primitive_id:
            emit_error('Component "%s" not found' % args.designator)
    else:
        primitive_id = args.id
    info = get_component(primitive_id)
    emit(info, verbose=args.verbose, quiet=args.quiet)


def cmd_delete_component(args):
    opts = {"margin": args.margin, "clean_wires": not args.no_clean_wires,
            "clean_labels": not args.no_clean_labels, "clean_text": args.clean_text}
    if args.designator:
        opts["designator"] = args.designator
    elif args.id:
        opts["component_id"] = args.id
    else:
        emit_error("Usage: delete-component --designator <D> | --id <id>")
    result = delete_component(**opts)
    emit(result, verbose=args.verbose, quiet=args.quiet,
         extra_keys=("componentDeleted", "wires", "labels", "text"))


def _parse_pin_map(pin_strs):
    """解析引脚映射字符串列表: ['1:net=VCC,type=power,side=right', ...]"""
    pin_map = {}
    for s in pin_strs:
        if s.startswith("--"):
            continue
        if ":" not in s:
            continue
        pin_num, cfg_str = s.split(":", 1)
        cfg = {}
        for kv in cfg_str.split(","):
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            if k == "distance":
                cfg[k] = int(v)
            else:
                cfg[k] = v
        pin_map[pin_num] = cfg
    return pin_map


def cmd_place_with_labels(args):
    ensure_schematic()
    pin_map = _parse_pin_map(args.pins)
    find_space_opts = None
    if args.find_space:
        w, h = [int(x) for x in args.find_space.split(",")]
        find_space_opts = {"width": w, "height": h}
    result = place_component_with_labels(
        library_uuid=args.lib_uuid, uuid=args.uuid,
        x=args.x, y=args.y, designator=args.designator,
        rotation=args.rotation, find_space=bool(find_space_opts),
        find_space_options=find_space_opts or {},
        pin_map=pin_map, module_label=args.label,
    )
    emit(result, summary="Placed %s + %d label(s)" % (args.designator, len(result["labels"])),
         verbose=args.verbose, quiet=args.quiet,
         extra_keys=("componentId", "position"))


def cmd_list_components(args):
    result = get_all_components()
    emit(result, summary="%d component(s)" % len(result),
         verbose=args.verbose, quiet=args.quiet)


def cmd_list_primitives(args):
    result = list_all_primitives()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_selected_primitives(args):
    result = list_selected_primitives()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_zoom_all(args):
    zoom_to_all()
    emit({"ok": True}, summary="Zoomed to all", verbose=args.verbose, quiet=args.quiet)


def cmd_list_tabs(args):
    result = list_tabs()
    emit(result, summary="%d tab(s)" % len(result), verbose=args.verbose, quiet=args.quiet)


def cmd_switch_tab(args):
    doctype_map = {"schematic": 1, "sch": 1, "symbol": 2, "sym": 2, "start": -1}
    doctype = doctype_map.get(args.type)
    if doctype is None:
        emit_error("Usage: switch-tab <schematic|symbol|start>")
    result = switch_tab(doctype)
    emit(result, summary="Switched to %s" % args.type, verbose=args.verbose, quiet=args.quiet)


def cmd_project_info(args):
    result = get_project_info()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_health(args):
    """检查 bridge server 和 EDA 连通性 (无需 EDA 文档打开)"""
    result = check_health()
    emit(result, verbose=args.verbose, quiet=args.quiet,
         extra_keys=("bridge", "port", "edaConnected", "activeWindow"))


def cmd_page_info(args):
    result = get_page_info()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def set_titleblock_raw(data_json):
    """以原始 JSON 写入标题栏字段 (实验/精细控制用)"""
    data = json.loads(data_json)
    code = (
        "const d = %s;"
        "const ok = await eda.dmt_Schematic.modifySchematicPageTitleBlock(true, d);"
        "const a = await eda.dmt_Schematic.getCurrentSchematicPageInfo();"
        "const tb = a && a.titleBlockData ? a.titleBlockData : {};"
        "const out = {};"
        "for (const k of Object.keys(tb)) { out[k] = tb[k] ? tb[k].value : null; }"
        "return { ok: ok, tb: out };"
    ) % json.dumps(data)
    return exec_code(code)


def cmd_titleblock_set(args):
    r = set_titleblock_raw(args.json)
    emit(r, summary="Title block updated", verbose=args.verbose, quiet=args.quiet)


def cmd_set_page_size(args):
    result = set_page_size(args.size)
    if not result or not result.get("ok"):
        raise RuntimeError("设置图纸尺寸失败: %s" % (result,))
    emit(result, summary="Page size set to %s (%sx%s)" % (
        result.get("pageSize"), result.get("width"), result.get("height")),
        verbose=args.verbose, quiet=args.quiet)


def cmd_restore_titleblock(args):
    restore_title_block()
    emit({"ok": True}, summary="Title block restored", verbose=args.verbose, quiet=args.quiet)


def cmd_save(args):
    saved = save_document()
    if saved is not True:
        raise RuntimeError("EDA did not confirm document save: %s" % saved)
    emit({"ok": True, "saved": saved}, summary="Saved", verbose=args.verbose, quiet=args.quiet)


def cmd_create_symbol(args):
    result = create_symbol(args.name)
    emit(result, summary="Created symbol '%s'" % args.name,
         verbose=args.verbose, quiet=args.quiet)


def cmd_open_symbol(args):
    tab_id = open_symbol_in_editor(args.symbol_uuid, args.library_uuid)
    emit({"tabId": tab_id}, summary="Opened symbol in editor",
         verbose=args.verbose, quiet=args.quiet)


def cmd_create_device(args):
    result = create_device_from_symbol(args.name, args.symbol_uuid, args.library_uuid)
    emit(result, summary="Created device '%s'" % args.name,
         verbose=args.verbose, quiet=args.quiet)


def cmd_create_pin(args):
    ensure_symbol_editor()
    pin_id = create_symbol_pin(
        side=args.side, x=args.x, y=args.y,
        number=args.number, name=args.name,
        pin_type=args.type, length=args.length,
    )
    emit({"id": pin_id}, summary="Created pin %s (%s) at (%d,%d) side=%s"
          % (args.number, args.name, args.x, args.y, args.side),
         verbose=args.verbose, quiet=args.quiet)


def cmd_create_sym_rect(args):
    ensure_symbol_editor()
    rect_id = create_symbol_rect(args.cx, args.cy, args.w, args.h)
    emit({"id": rect_id}, summary="Created rect at (%d,%d) %dx%d" % (args.cx, args.cy, args.w, args.h),
         verbose=args.verbose, quiet=args.quiet)


def cmd_create_dot(args):
    ensure_symbol_editor()
    dot_id = create_symbol_dot(args.x, args.y, args.radius)
    emit({"id": dot_id}, summary="Created dot at (%d,%d)" % (args.x, args.y),
         verbose=args.verbose, quiet=args.quiet)


def cmd_delete_device(args):
    result = delete_device(args.device_uuid, args.library_uuid)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_delete_symbol(args):
    result = delete_symbol(args.symbol_uuid, args.library_uuid)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_ensure_symbol_editor(args):
    ensure_symbol_editor()
    emit({"ok": True}, summary="Symbol editor confirmed", verbose=args.verbose, quiet=args.quiet)


def cmd_get_pin(args):
    result = get_pin(args.id)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_list_pins(args):
    result = get_all_pins()
    emit(result, summary="%d pin(s)" % len(result), verbose=args.verbose, quiet=args.quiet)


def cmd_delete_pins(args):
    result = delete_pins(args.ids)
    emit({"deleted": result}, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))


def cmd_modify_pin(args):
    changes = {}
    if args.x is not None: changes["x"] = args.x
    if args.y is not None: changes["y"] = args.y
    if args.number is not None: changes["pinNumber"] = args.number
    if args.name is not None: changes["pinName"] = args.name
    if args.rot is not None: changes["rotation"] = args.rot
    if args.length is not None: changes["pinLength"] = args.length
    if args.type is not None: changes["pinType"] = args.type
    result = modify_pin(args.id, changes)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_modify_component(args):
    changes = {}
    if args.x is not None: changes["x"] = args.x
    if args.y is not None: changes["y"] = args.y
    if args.rot is not None: changes["rotation"] = args.rot
    if args.designator is not None: changes["designator"] = args.designator
    if args.name is not None: changes["name"] = args.name
    if args.manufacturer is not None: changes["manufacturer"] = args.manufacturer
    if args.manufacturer_id is not None: changes["manufacturerId"] = args.manufacturer_id
    if args.supplier is not None: changes["supplier"] = args.supplier
    if args.supplier_id is not None: changes["supplierId"] = args.supplier_id
    if args.mirror: changes["mirror"] = True
    if args.unmirror: changes["mirror"] = False
    if args.no_bom: changes["addIntoBom"] = False
    if args.no_pcb: changes["addIntoPcb"] = False
    result = modify_component(args.id, changes)
    emit({"ok": bool(result)}, summary="Modified %s" % args.id,
         verbose=args.verbose, quiet=args.quiet)


def cmd_build_symbol(args):
    options = {}
    if args.pin_spacing: options["pin_spacing"] = args.pin_spacing
    if args.body_width: options["body_width"] = args.body_width
    if args.body_height: options["body_height"] = args.body_height
    if args.pin_length: options["pin_length"] = args.pin_length
    if args.library_uuid: options["library_uuid"] = args.library_uuid
    if args.sides_json:
        raw = args.sides_json
        if raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8")
        sides = json.loads(raw)
        if not isinstance(sides, list):
            raise RuntimeError("sides-json must be an array of {side,pins}")
        allowed_types = {"BI", "Ground", "HIZ", "IN", "Open Collector", "Open Emitter", "OUT", "Passive", "Power", "Terminator", "Undefined"}
        numbers = set()
        for side in sides:
            if side.get("side") not in PIN_ROTATION_BY_SIDE or not isinstance(side.get("pins"), list):
                raise RuntimeError("Each side requires left/right/top/bottom and a pins array")
            for pin in side["pins"]:
                if not all(k in pin for k in ("num", "name", "type")):
                    raise RuntimeError("Each pin requires explicit num, name and type")
                number = str(pin["num"])
                if not number or number in numbers:
                    raise RuntimeError("Empty or duplicate pin number: " + number)
                if pin["type"] not in allowed_types:
                    raise RuntimeError("Unsupported documented pin type: " + str(pin["type"]))
                pin["num"] = number
                numbers.add(number)
        options["sides"] = sides
    result = build_symbol(args.name, **options)
    emit(result, verbose=args.verbose, quiet=args.quiet,
         extra_keys=("symbolUuid", "deviceUuid"))


def cmd_set_pin_labels_position(args):
    result = fix_pin_labels(side=args.side, offset=args.offset)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("fixed",))


def cmd_drc(args):
    result = run_drc(show_ui=args.show_ui)
    fatal = result.get("fatalErrors", 0)
    warn = result.get("warnings", 0)
    if fatal > 0 and not args.show_ui:
        summary = "FAIL: %d fatal, %d warn | TIP: run 'drc --show-ui' to see detailed errors in panel" % (fatal, warn)
    elif fatal > 0:
        summary = "FAIL: %d fatal, %d warn (UI panel opened)" % (fatal, warn)
    else:
        summary = "PASS: 0 fatal, %d warn" % warn
    emit(result, summary=summary, verbose=args.verbose, quiet=args.quiet)


def cmd_check_duplicates(args):
    if args.clean:
        result = cleanup_duplicate_labels()
        emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("deleted",))
    else:
        result = detect_duplicate_labels()
        emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("count",))


def cmd_check_wire_nets(args):
    result = check_wire_nets()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("total", "noNet"))


def cmd_check_unconnected(args):
    result = detect_unconnected_pins()
    summary = "%d error(s), %d warning(s)" % (result.get("errorCount", 0), result.get("warningCount", 0))
    emit(result, summary=summary, verbose=args.verbose, quiet=args.quiet)


def cmd_check_shorts(args):
    result = detect_shorts()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_check_redundant_wires(args):
    result = detect_redundant_wires()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_check_pin_shorts(args):
    result = detect_pin_shorts()
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_check_wire_through(args):
    result = check_wire_through_component()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("wireThroughCount",))


def cmd_check_all(args):
    result = run_full_check()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("overall",))


def cmd_verify_placement(args):
    result = verify_placement()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("status",))


def cmd_verify_wiring(args):
    result = verify_wiring()
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("overall",))


def cmd_replace_netports(args):
    result = replace_net_ports(extend_length=args.length)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("replaced",))


def cmd_mark_nc(args):
    pins = [int(x.strip()) for x in args.pins.split(",")]
    result = mark_nc(args.designator, pins)
    emit(result, verbose=args.verbose, quiet=args.quiet, extra_keys=("marked",))


def cmd_check_nc_coverage(args):
    result = check_nc_coverage()
    emit(result, verbose=args.verbose, quiet=args.quiet,
         extra_keys=("totalPins", "covered"))


def cmd_select(args):
    result = do_select_primitives(args.ids)
    emit({"selected": result}, verbose=args.verbose, quiet=args.quiet)


def cmd_clear_selected(args):
    result = clear_selected()
    emit({"cleared": result}, verbose=args.verbose, quiet=args.quiet)


def cmd_bbox(args):
    result = get_primitives_bbox(args.ids)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_export_netlist(args):
    result = export_netlist(args.filename)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_export_bom(args):
    file_type = "csv" if args.csv else "xlsx"
    result = export_bom(args.filename, file_type)
    emit(result, verbose=args.verbose, quiet=args.quiet)


def cmd_project_new(args):
    emit(new_project(args.name, args.slug, args.description), verbose=args.verbose, quiet=args.quiet)


def cmd_page_create(args):
    emit(create_page(args.schematic_uuid, args.name), verbose=args.verbose, quiet=args.quiet)


def cmd_page_open(args):
    emit(open_page(args.page_uuid), verbose=args.verbose, quiet=args.quiet)


def cmd_page_rename(args):
    emit(rename_page(args.page_uuid, args.name), verbose=args.verbose, quiet=args.quiet)


def cmd_page_list(args):
    emit(list_pages(), verbose=args.verbose, quiet=args.quiet)


def cmd_board_create(args):
    emit(create_board(args.name), verbose=args.verbose, quiet=args.quiet)


def cmd_export_file(args):
    emit(export_generated_file(args.export_kind, args.filename, scope=getattr(args, "scope", "current")), verbose=args.verbose, quiet=args.quiet)


def cmd_export_source(args):
    emit(export_document_source(args.filename), verbose=args.verbose, quiet=args.quiet)


def cmd_device_info(args):
    emit(device_info(args.device_uuid, args.library_uuid), verbose=args.verbose, quiet=args.quiet)


def cmd_api_capabilities(args):
    emit(api_capabilities(), verbose=args.verbose, quiet=args.quiet)


def _parse_line_type(args):
    if getattr(args, "dashed", False): return 1
    if getattr(args, "dotted", False): return 2
    if getattr(args, "dot_dashed", False): return 3
    return None


# ═══════════════════════════════════════════════════════════════════
# argparse 主入口
# ═══════════════════════════════════════════════════════════════════

def _add_line_type_options(p):
    p.add_argument("--dashed", action="store_true", help="短划线")
    p.add_argument("--dotted", action="store_true", help="点线")
    p.add_argument("--dot-dashed", dest="dot_dashed", action="store_true", help="点划线")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="draw_cli.py",
        description="EasyEDA 原理图绘制 CLI (Python 版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出完整 JSON (调试用)")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出 id (管道友好)")

    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p = sub.add_parser("project-new", help="在独立空白会话创建新EPRJ3工程")
    p.add_argument("name", help="工程显示名称")
    p.add_argument("--slug", required=True, help="字母/数字/连字符内部名称")
    p.add_argument("--description", default="")
    p.set_defaults(func=cmd_project_new)

    p = sub.add_parser("page-create", help="创建并命名原理图页")
    p.add_argument("schematic_uuid")
    p.add_argument("name")
    p.set_defaults(func=cmd_page_create)

    p = sub.add_parser("page-open", help="按UUID打开原理图页")
    p.add_argument("page_uuid")
    p.set_defaults(func=cmd_page_open)

    p = sub.add_parser("page-rename", help="重命名已有原理图页")
    p.add_argument("page_uuid")
    p.add_argument("name")
    p.set_defaults(func=cmd_page_rename)

    p = sub.add_parser("page-list", help="列出当前工程的原理图及页面")
    p.set_defaults(func=cmd_page_list)

    p = sub.add_parser("board-create", help="创建独立板及其原理图/PCB文档")
    p.add_argument("name")
    p.set_defaults(func=cmd_board_create)

    for kind in ("pdf", "project", "png", "svg"):
        p = sub.add_parser("export-" + kind, help="导出EDA生成的%s原文件" % kind.upper())
        p.add_argument("filename", help="本地输出完整路径（拒绝覆盖）")
        if kind == "pdf":
            p.add_argument("--scope", choices=["current", "schematic", "all"], default="current")
        p.set_defaults(func=cmd_export_file, export_kind=kind)

    p = sub.add_parser("export-source", help="导出当前图页/符号的真实EDA文档源码")
    p.add_argument("filename")
    p.set_defaults(func=cmd_export_source)

    p = sub.add_parser("device-info", help="查询器件全部库/封装/采购属性")
    p.add_argument("device_uuid")
    p.add_argument("library_uuid", nargs="?")
    p.set_defaults(func=cmd_device_info)

    p = sub.add_parser("api-capabilities", help="只读检查已连接EDA的绘图/保存/导出API能力")
    p.set_defaults(func=cmd_api_capabilities)

    # ─── schematic: 原理图操作 ───
    p = sub.add_parser("clear", help="清理页面 (默认保留标题块)")
    p.add_argument("--keep", help="保留的器件 ID 列表 (逗号分隔)")
    p.add_argument("--all", action="store_true", help="删除全部 (含文本和矩形)")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("delete-wires", help="精确删除导线")
    p.add_argument("--region", help="区域 minX,minY,maxX,maxY")
    p.add_argument("--nets", help="网络名白名单 (逗号分隔)")
    p.add_argument("--exclude-nets", dest="exclude_nets", help="网络名黑名单")
    p.set_defaults(func=cmd_delete_wires)

    p = sub.add_parser("delete-labels", help="精确删除网络标签")
    p.add_argument("--region", help="区域 minX,minY,maxX,maxY")
    p.add_argument("--nets", help="网络名白名单")
    p.add_argument("--exclude-nets", dest="exclude_nets", help="网络名黑名单")
    p.set_defaults(func=cmd_delete_labels)

    p = sub.add_parser("delete-wires-coords", help="按坐标精确删除导线 (方向无关)")
    p.add_argument("coords", nargs="+", help='坐标 "x1,y1,x2,y2"')
    p.set_defaults(func=cmd_delete_wires_coords)

    p = sub.add_parser("place", help="放置器件")
    p.add_argument("lib_uuid", help="库 UUID")
    p.add_argument("uuid", help="器件 UUID")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("designator", nargs="?", help="位号")
    p.add_argument("rotation", type=int, nargs="?", default=0)
    p.add_argument("mirror", type=lambda x: x.lower() == "true", nargs="?", default=False)
    p.add_argument("--name", help="器件值/规格 (如 10kΩ, 100nF, nRF52840)")
    p.add_argument("--value", dest="value", help="--name 的别名")
    p.set_defaults(func=cmd_place)

    p = sub.add_parser("text", help="添加文本")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("text")
    p.add_argument("font_size", type=int, nargs="?", default=8)
    p.add_argument("--color")
    p.add_argument("--font", dest="font")
    p.add_argument("--align", type=int)
    p.add_argument("--bold", action="store_true")
    p.add_argument("--italic", action="store_true")
    p.add_argument("--underline", action="store_true")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("get-text", help="查看文本详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_text)

    p = sub.add_parser("modify-text", help="修改文本")
    p.add_argument("id")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--content")
    p.add_argument("--color")
    p.add_argument("--font", dest="font")
    p.add_argument("--size", type=int)
    p.add_argument("--align", type=int)
    p.add_argument("--bold", action="store_true")
    p.add_argument("--italic", action="store_true")
    p.add_argument("--underline", action="store_true")
    p.add_argument("--no-bold", dest="no_bold", action="store_true")
    p.add_argument("--no-italic", dest="no_italic", action="store_true")
    p.add_argument("--no-underline", dest="no_underline", action="store_true")
    p.set_defaults(func=cmd_modify_text)

    p = sub.add_parser("list-texts", help="列出所有文本")
    p.set_defaults(func=cmd_list_texts)

    p = sub.add_parser("delete-texts", help="删除文本")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_texts)

    p = sub.add_parser("rect", help="添加矩形")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("w", type=int)
    p.add_argument("h", type=int)
    p.add_argument("--color")
    p.add_argument("--fill")
    p.add_argument("--radius", type=int)
    p.add_argument("--rot", type=int)
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.set_defaults(func=cmd_rect)

    p = sub.add_parser("get-rect", help="查看矩形详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_rect)

    p = sub.add_parser("modify-rect", help="修改矩形")
    p.add_argument("id")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--w", type=int)
    p.add_argument("--h", type=int)
    p.add_argument("--color")
    p.add_argument("--fill")
    p.add_argument("--radius", type=int)
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.add_argument("--solid", action="store_true")
    p.set_defaults(func=cmd_modify_rect)

    p = sub.add_parser("list-rects", help="列出所有矩形")
    p.set_defaults(func=cmd_list_rects)

    p = sub.add_parser("delete-rects", help="删除矩形")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_rects)

    p = sub.add_parser("netflag", help="添加网络标识 (VCC/GND)")
    p.add_argument("type", choices=["Power", "Ground", "AnalogGround", "ProtectGround"])
    p.add_argument("net")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_netflag)

    p = sub.add_parser("netport", help="添加网络端口 (不推荐，信号用 wire 延伸)")
    p.add_argument("direction")
    p.add_argument("net")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_netport)

    p = sub.add_parser("wire", help="绘制导线")
    p.add_argument("points", help='坐标 "x1,y1,x2,y2"')
    p.add_argument("net", nargs="?", help="网络名 (强烈建议指定, 防止自动继承)")
    p.add_argument("--color")
    p.add_argument("--width", type=int)
    p.add_argument("--safe", action="store_true",
                   help="安全模式: 先检查冲突再创建, 防止跨网络合并 (推荐)")
    _add_line_type_options(p)
    p.set_defaults(func=cmd_wire)

    p = sub.add_parser("wire-batch", help="批量创建导线 (安全模式, 逐条检查冲突)")
    p.add_argument("--file", help="JSON 文件路径")
    p.add_argument("--json", help="JSON 字符串")
    p.set_defaults(func=cmd_wire_batch)

    p = sub.add_parser("get-wire", help="查看导线详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_wire)

    p = sub.add_parser("modify-wire", help="修改导线")
    p.add_argument("id")
    p.add_argument("--net")
    p.add_argument("--color")
    p.add_argument("--width", type=int)
    p.add_argument("--line", help='新坐标 "x1,y1,x2,y2"')
    _add_line_type_options(p)
    p.add_argument("--solid", action="store_true")
    p.set_defaults(func=cmd_modify_wire)

    p = sub.add_parser("bus", help="创建总线")
    p.add_argument("name", help='总线名如 "DATA[7:0]"')
    p.add_argument("points")
    p.add_argument("--color")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.set_defaults(func=cmd_bus)

    p = sub.add_parser("list-buses", help="列出所有总线")
    p.set_defaults(func=cmd_list_buses)

    p = sub.add_parser("delete-buses", help="删除总线")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_buses)

    p = sub.add_parser("get-bus", help="查看总线详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_bus)

    p = sub.add_parser("modify-bus", help="修改总线")
    p.add_argument("id")
    p.add_argument("--name")
    p.add_argument("--color")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.add_argument("--solid", action="store_true")
    p.set_defaults(func=cmd_modify_bus)

    p = sub.add_parser("polygon", help="创建多边形 (装饰框)")
    p.add_argument("points")
    p.add_argument("--color")
    p.add_argument("--fill")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.set_defaults(func=cmd_polygon)

    p = sub.add_parser("list-polygons", help="列出所有多边形")
    p.set_defaults(func=cmd_list_polygons)

    p = sub.add_parser("delete-polygons", help="删除多边形")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_polygons)

    p = sub.add_parser("get-polygon", help="查看多边形详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_polygon)

    p = sub.add_parser("modify-polygon", help="修改多边形")
    p.add_argument("id")
    p.add_argument("--line")
    p.add_argument("--color")
    p.add_argument("--fill")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.add_argument("--solid", action="store_true")
    p.set_defaults(func=cmd_modify_polygon)

    p = sub.add_parser("circle", help="创建圆")
    p.add_argument("cx", type=int)
    p.add_argument("cy", type=int)
    p.add_argument("radius", type=int)
    p.add_argument("--color")
    p.add_argument("--fill")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.set_defaults(func=cmd_circle)

    p = sub.add_parser("list-circles", help="列出所有圆")
    p.set_defaults(func=cmd_list_circles)

    p = sub.add_parser("delete-circles", help="删除圆")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_circles)

    p = sub.add_parser("arc", help="创建弧")
    p.add_argument("sx", type=int)
    p.add_argument("sy", type=int)
    p.add_argument("rx", type=int)
    p.add_argument("ry", type=int)
    p.add_argument("ex", type=int)
    p.add_argument("ey", type=int)
    p.add_argument("--color")
    p.add_argument("--width", type=int)
    _add_line_type_options(p)
    p.set_defaults(func=cmd_arc)

    p = sub.add_parser("list-arcs", help="列出所有弧")
    p.set_defaults(func=cmd_list_arcs)

    p = sub.add_parser("delete-arcs", help="删除弧")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_arcs)

    # ─── 查询/搜索 ───
    p = sub.add_parser("search", help="搜索器件")
    p.add_argument("keyword")
    p.add_argument("limit", type=int, nargs="?", default=10)
    p.add_argument("--lib", help="指定库 UUID (默认系统库)")
    p.add_argument("--personal", action="store_true",
                   help="在个人库中搜索 (自动获取 UUID)")
    p.add_argument("--project", action="store_true",
                   help="在工程库中搜索 (自动获取 UUID)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("lib-personal", help="获取个人库 UUID")
    p.set_defaults(func=cmd_lib_personal)

    p = sub.add_parser("lib-project", help="获取工程库 UUID")
    p.set_defaults(func=cmd_lib_project)

    p = sub.add_parser("lib-list", help="列出所有库")
    p.set_defaults(func=cmd_lib_list)

    p = sub.add_parser("check-overlap", help="检查重叠")
    p.set_defaults(func=cmd_check_overlap)

    p = sub.add_parser("find-space", help="寻找空白区域")
    p.add_argument("w", type=int)
    p.add_argument("h", type=int)
    p.add_argument("sx", type=int, nargs="?", default=100)
    p.add_argument("sy", type=int, nargs="?", default=100)
    p.add_argument("ex", type=int, nargs="?", default=1200)
    p.add_argument("ey", type=int, nargs="?", default=900)
    p.set_defaults(func=cmd_find_space)

    p = sub.add_parser("get-pins", help="获取器件引脚实际坐标")
    p.add_argument("id", nargs="?")
    p.add_argument("--designator", help="按位号查找器件")
    p.set_defaults(func=cmd_get_pins)

    p = sub.add_parser("get-component", help="查询器件完整信息 (含 name/spec)")
    p.add_argument("id", nargs="?")
    p.add_argument("--designator", help="按位号查找器件")
    p.set_defaults(func=cmd_get_component)

    p = sub.add_parser("delete-component", help="删除器件 (含周边清理)")
    p.add_argument("--designator")
    p.add_argument("--id")
    p.add_argument("--margin", type=int, default=50)
    p.add_argument("--no-clean-wires", dest="no_clean_wires", action="store_true")
    p.add_argument("--no-clean-labels", dest="no_clean_labels", action="store_true")
    p.add_argument("--clean-text", dest="clean_text", action="store_true")
    p.set_defaults(func=cmd_delete_component)

    p = sub.add_parser("place-with-labels", help="一站式放置器件 + 自动打标签")
    p.add_argument("lib_uuid")
    p.add_argument("uuid")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("designator")
    p.add_argument("rotation", type=int, nargs="?", default=0)
    p.add_argument("--pins", nargs="+", required=True,
                   help='引脚映射 "1:net=VCC,type=power,side=right" (可多个)')
    p.add_argument("--label", help="模块标签文本")
    p.add_argument("--find-space", dest="find_space",
                   help="自动寻找空白区域 (格式: W,H)")
    p.set_defaults(func=cmd_place_with_labels)

    p = sub.add_parser("list-components", help="列出所有器件")
    p.set_defaults(func=cmd_list_components)

    p = sub.add_parser("collect-nets", help="收集所有网络标签/导线网络 (按网络名分组)")
    p.set_defaults(func=cmd_collect_nets)

    p = sub.add_parser("net-summary", help="生成网络摘要文本 (供子 Agent 使用)")
    p.set_defaults(func=cmd_net_summary)

    p = sub.add_parser("list-primitives", help="列出所有图元")
    p.set_defaults(func=cmd_list_primitives)

    p = sub.add_parser("selected-primitives", help="列出已选中的图元 (符号编辑器专用)")
    p.set_defaults(func=cmd_selected_primitives)

    p = sub.add_parser("zoom-all", help="缩放到所有图元")
    p.set_defaults(func=cmd_zoom_all)

    p = sub.add_parser("list-tabs", help="列出所有打开的标签页")
    p.set_defaults(func=cmd_list_tabs)

    p = sub.add_parser("switch-tab", help="切换标签页")
    p.add_argument("type", choices=["schematic", "sch", "symbol", "sym", "start"])
    p.set_defaults(func=cmd_switch_tab)

    p = sub.add_parser("project-info", help="查看项目信息")
    p.set_defaults(func=cmd_project_info)

    p = sub.add_parser("health", help="检查 bridge server 和 EDA 连通性")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("page-info", help="查看当前页面信息")
    p.set_defaults(func=cmd_page_info)

    p = sub.add_parser("titleblock-set", help="以原始 JSON 写入标题栏字段")
    p.add_argument("json", help="JSON 字符串")
    p.set_defaults(func=cmd_titleblock_set)

    p = sub.add_parser("set-page-size", help="修改原理图图纸尺寸 (A4/A3/A2/A1)")
    p.add_argument("size", help="图纸尺寸: A4 / A3 / A2 / A1")
    p.set_defaults(func=cmd_set_page_size)

    p = sub.add_parser("restore-titleblock", help="恢复标题块")
    p.set_defaults(func=cmd_restore_titleblock)

    p = sub.add_parser("save", help="保存当前文档")
    p.set_defaults(func=cmd_save)

    # ─── 符号编辑 ───
    p = sub.add_parser("create-symbol", help="创建空符号到个人库")
    p.add_argument("name")
    p.set_defaults(func=cmd_create_symbol)

    p = sub.add_parser("open-symbol", help="在编辑器中打开符号")
    p.add_argument("symbol_uuid")
    p.add_argument("library_uuid")
    p.set_defaults(func=cmd_open_symbol)

    p = sub.add_parser("create-device", help="从符号创建器件")
    p.add_argument("name")
    p.add_argument("symbol_uuid")
    p.add_argument("library_uuid")
    p.set_defaults(func=cmd_create_device)

    p = sub.add_parser("create-pin", help="创建符号引脚 (自动处理 rotation 反转)")
    p.add_argument("side", choices=["left", "right", "top", "bottom"])
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("number")
    p.add_argument("name")
    p.add_argument("type", nargs="?", default="BI")
    p.add_argument("length", type=int, nargs="?", default=20)
    p.set_defaults(func=cmd_create_pin)

    p = sub.add_parser("create-sym-rect", help="创建符号矩形 (自动处理 Y 轴方向)")
    p.add_argument("cx", type=int)
    p.add_argument("cy", type=int)
    p.add_argument("w", type=int)
    p.add_argument("h", type=int)
    p.set_defaults(func=cmd_create_sym_rect)

    p = sub.add_parser("create-dot", help="创建方向指示圆点")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("radius", type=int, nargs="?", default=5)
    p.set_defaults(func=cmd_create_dot)

    p = sub.add_parser("delete-device", help="从库删除器件 (参数顺序已修正)")
    p.add_argument("device_uuid")
    p.add_argument("library_uuid")
    p.set_defaults(func=cmd_delete_device)

    p = sub.add_parser("delete-symbol", help="从库删除符号 (参数顺序已修正)")
    p.add_argument("symbol_uuid")
    p.add_argument("library_uuid")
    p.set_defaults(func=cmd_delete_symbol)

    p = sub.add_parser("ensure-symbol-editor", help="确认当前在符号编辑器")
    p.set_defaults(func=cmd_ensure_symbol_editor)

    p = sub.add_parser("get-pin", help="查看引脚详细信息")
    p.add_argument("id")
    p.set_defaults(func=cmd_get_pin)

    p = sub.add_parser("list-pins", help="列出所有引脚")
    p.set_defaults(func=cmd_list_pins)

    p = sub.add_parser("delete-pins", help="删除引脚")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_delete_pins)

    p = sub.add_parser("modify-pin", help="修改引脚")
    p.add_argument("id")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--number")
    p.add_argument("--name")
    p.add_argument("--rot", type=int)
    p.add_argument("--length", type=int)
    p.add_argument("--type")
    p.set_defaults(func=cmd_modify_pin)

    p = sub.add_parser("modify-component", help="修改器件属性")
    p.add_argument("id")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--rot", type=int)
    p.add_argument("--designator")
    p.add_argument("--name")
    p.add_argument("--manufacturer")
    p.add_argument("--manufacturer-id", dest="manufacturer_id")
    p.add_argument("--supplier")
    p.add_argument("--supplier-id", dest="supplier_id")
    p.add_argument("--mirror", action="store_true")
    p.add_argument("--unmirror", action="store_true")
    p.add_argument("--no-bom", dest="no_bom", action="store_true")
    p.add_argument("--no-pcb", dest="no_pcb", action="store_true")
    p.set_defaults(func=cmd_modify_component)

    p = sub.add_parser("build-symbol", help="一键构建符号骨架")
    p.add_argument("name")
    p.add_argument("--pin-spacing", type=int, dest="pin_spacing")
    p.add_argument("--body-width", type=int, dest="body_width")
    p.add_argument("--body-height", type=int, dest="body_height")
    p.add_argument("--pin-length", type=int, dest="pin_length")
    p.add_argument("--sides-json", help='JSON数组或@文件: [{"side":"left","pins":[{"num":"1","name":"GND","type":"Ground"}]}]')
    p.add_argument("--library-uuid", help="指定目标库UUID；默认个人库")
    p.set_defaults(func=cmd_build_symbol)

    p = sub.add_parser("set-pin-labels-position", help="修正引脚标签位置")
    p.add_argument("--side", choices=["left", "right", "top", "bottom"], required=True)
    p.add_argument("--offset", type=int, default=5)
    p.set_defaults(func=cmd_set_pin_labels_position)

    # ─── 检查/验证 ───
    p = sub.add_parser("drc", help="DRC 检查")
    p.add_argument("--show-ui", dest="show_ui", action="store_true", help="打开 DRC 面板")
    p.set_defaults(func=cmd_drc)

    p = sub.add_parser("check-duplicates", help="检测重复标签")
    p.add_argument("--clean", action="store_true", help="自动清理")
    p.set_defaults(func=cmd_check_duplicates)

    p = sub.add_parser("check-wire-nets", help="检查无网络名的导线")
    p.set_defaults(func=cmd_check_wire_nets)

    p = sub.add_parser("check-wire-conflicts", help="检测导线网络冲突 (触碰不同网络的导线)")
    p.set_defaults(func=cmd_check_wire_conflicts)

    p = sub.add_parser("check-unconnected", help="检测未连接引脚 (4PIN开关感知+NC感知)")
    p.set_defaults(func=cmd_check_unconnected)

    p = sub.add_parser("check-shorts", help="检测短路 (不同网络名的导线连接在一起)")
    p.set_defaults(func=cmd_check_shorts)

    p = sub.add_parser("check-redundant-wires", help="检测冗余导线 (同两点间多条导线)")
    p.set_defaults(func=cmd_check_redundant_wires)

    p = sub.add_parser("check-pin-shorts", help="检测引脚短路 (同器件多引脚连到同一网络, 电源/地除外)")
    p.set_defaults(func=cmd_check_pin_shorts)

    p = sub.add_parser("check-wire-through", help="检测导线穿过元器件本体")
    p.set_defaults(func=cmd_check_wire_through)

    p = sub.add_parser("check-all", help="一键全量检查")
    p.set_defaults(func=cmd_check_all)

    p = sub.add_parser("verify-placement", help="验证摆放质量")
    p.set_defaults(func=cmd_verify_placement)

    p = sub.add_parser("verify-wiring", help="验证连线质量")
    p.set_defaults(func=cmd_verify_wiring)

    p = sub.add_parser("replace-netports", help="将 NetPort 替换为延伸导线")
    p.add_argument("--length", type=int, default=80)
    p.set_defaults(func=cmd_replace_netports)

    p = sub.add_parser("mark-nc", help="标记未连接引脚 (使用原生 API，非文本)")
    p.add_argument("designator")
    p.add_argument("pins", help="引脚号列表 (逗号分隔, 如 14,16)")
    p.set_defaults(func=cmd_mark_nc)

    p = sub.add_parser("check-nc-coverage", help="检查 NC 标记覆盖率")
    p.set_defaults(func=cmd_check_nc_coverage)

    # ─── 选择/导出 ───
    p = sub.add_parser("select", help="选中图元")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_select)

    p = sub.add_parser("clear-selected", help="清除选择")
    p.set_defaults(func=cmd_clear_selected)

    p = sub.add_parser("bbox", help="获取图元包围盒")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_bbox)

    p = sub.add_parser("export-netlist", help="导出网络表")
    p.add_argument("filename", nargs="?")
    p.set_defaults(func=cmd_export_netlist)

    p = sub.add_parser("export-bom", help="导出 BOM")
    p.add_argument("filename", nargs="?")
    p.add_argument("--csv", action="store_true", help="导出为 CSV (默认 XLSX)")
    p.set_defaults(func=cmd_export_bom)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        args.func(args)
    except RuntimeError as e:
        sys.stderr.write("Error: %s\n" % e)
        return 1
    except Exception as e:
        sys.stderr.write("Unexpected error: %s\n" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
