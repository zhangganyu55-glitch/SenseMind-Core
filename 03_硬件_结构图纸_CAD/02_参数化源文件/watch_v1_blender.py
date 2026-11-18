"""SenseMind H3-05 V1.1 · Blender/Cycles 产品渲染脚本.

用法:
  Blender -b -P watch_v1_blender.py -- --shot hero --out out.png

几何来自 STL (装配坐标, 单位 mm), 导入后整体缩放 0.001 变成米。
渲染只负责材质/灯光/构图, 不改任何 CAD 尺寸。
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
STL_DIR = HERE / "打印文件_STL" if (HERE / "打印文件_STL").exists() else HERE / "out"
# 可选：屏幕 UI 贴图。默认找同目录 ui_tex/ui_health_live.png，
# 也可用环境变量 SENSEMIND_UI_TEX 指定；都没有时退回纯色发光材质。
UI_TEX = Path(os.environ.get("SENSEMIND_UI_TEX", str(HERE / "ui_tex" / "ui_health_live.png"))).expanduser()
if not UI_TEX.exists():
    UI_TEX = None

MATERIALS = {
    # name: (base color hex, roughness, metallic)
    "body":          ("#3E4248", 0.54, 0.0),
    "bezel":         ("#0F1013", 0.80, 0.0, None, 0.03),
    "back_cover":    ("#33373C", 0.62, 0.0),
    "sensor_carrier": ("#1E4D33", 0.65, 0.0),
    "battery_bay":   ("#8A8F96", 0.38, 0.85),
    "usbc_end_cap":  ("#1A1C1F", 0.45, 0.0),
    "button_caps":   ("#2B2D31", 0.28, 0.90),
}


def hex_rgb(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # sRGB -> linear
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name, color_hex, rough, metal, emit_tex=None, spec=0.22):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*hex_rgb(color_hex), 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if emit_tex and emit_tex.exists():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(emit_tex))
        tex.interpolation = "Cubic"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.6
        bsdf.inputs["Base Color"].default_value = (0.01, 0.012, 0.014, 1)
        bsdf.inputs["Roughness"].default_value = 0.12
    return mat


def import_parts(scale=0.001):
    objs = {}
    for name in MATERIALS:
        f = STL_DIR / f"watch_v1_{name}.stl"
        if not f.exists():
            print("missing", f)
            continue
        before = set(bpy.data.objects)
        bpy.ops.wm.stl_import(filepath=str(f))
        new = [o for o in bpy.data.objects if o not in before]
        if not new:
            print("import failed:", f)
            continue
        ob = new[0]
        ob.name = name
        ob.scale = (scale, scale, scale)
        mat = make_material(name, *MATERIALS[name])
        ob.data.materials.clear()
        ob.data.materials.append(mat)
        # STL 导入会带 OBJECT 级材质槽, 会盖住 DATA 级; 统一改回 DATA
        for slot in ob.material_slots:
            slot.link = "DATA"
        bc = tuple(round(c, 3) for c in mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)
        slots = [m.name if m else None for m in ob.data.materials]
        dims = tuple(round(v, 4) for v in ob.dimensions)
        print(f"  OBJ {ob.name:16s} slots={slots} base={bc} dim={dims}")
        objs[name] = ob
    return objs


def add_display(width=0.0282, height=0.0282, z=-0.0004):
    """屏幕玻璃 (仅渲染用假体: 真实是 ST7789V 模块)"""
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.object
    ob.name = "display_glass"
    ob.scale = (width, height, 1)
    ob.location = (0, 0.0012, z)
    mat = make_material("display", "#05070A", 0.1, 0.0, emit_tex=UI_TEX)
    ob.data.materials.append(mat)
    return ob


def add_floor(size=0.6, z=-0.0222):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, z))
    ob = bpy.context.object
    ob.name = "floor"
    mat = make_material("floor", "#0B0C0E", 0.45, 0.0)
    ob.data.materials.append(mat)
    return ob


def add_lights():
    def area(name, loc, rot, size, energy, color=(1, 1, 1), shape="RECTANGLE", size_y=None):
        d = bpy.data.lights.new(name, type="AREA")
        d.energy = energy
        d.color = color
        d.shape = shape
        d.size = size
        if size_y:
            d.size_y = size_y
        ob = bpy.data.objects.new(name, d)
        ob.location = loc
        ob.rotation_euler = rot
        bpy.context.scene.collection.objects.link(ob)
        return ob

    # 主光: 左上前方大柔光箱
    area("key", (-0.22, -0.26, 0.30), (math.radians(52), 0, math.radians(-40)),
         0.30, 2.6, (1.0, 0.97, 0.93))
    # 轮廓光: 右后侧条形灯
    area("rim", (0.28, 0.24, 0.16), (math.radians(75), 0, math.radians(140)),
         0.42, 2.2, (0.82, 0.90, 1.0), size_y=0.10)
    # 轮廓光: 左后低角度条灯, 勾出顶面倒角
    area("rim2", (-0.26, 0.22, 0.07), (math.radians(88), 0, math.radians(-140)),
         0.40, 1.6, (0.90, 0.94, 1.0), size_y=0.06)
    # 补光: 右前弱光
    area("fill", (0.26, -0.22, 0.10), (math.radians(80), 0, math.radians(45)),
         0.35, 0.5, (0.95, 0.97, 1.0))


def add_world():
    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.012, 0.013, 0.016, 1)
    bg.inputs["Strength"].default_value = 1.0


def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def add_camera(az_deg, el_deg, dist, target=(0, 0, -0.0105), lens=85):
    d = bpy.data.cameras.new("Cam")
    d.lens = lens
    d.clip_start = 0.004
    d.clip_end = 20.0
    cam = bpy.data.objects.new("Cam", d)
    bpy.context.scene.collection.objects.link(cam)
    az, el = math.radians(az_deg), math.radians(el_deg)
    cam.location = (
        dist * math.sin(az) * math.cos(el),
        -dist * math.cos(az) * math.cos(el),
        target[2] + dist * math.sin(el),
    )
    look_at(cam, target)
    bpy.context.scene.camera = cam
    return cam


def setup_render(res=(2000, 1500), samples=128, gpu=False):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.exposure = -0.4
    try:
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    if gpu:
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            prefs.compute_device_type = "METAL"
            prefs.get_devices()
            for dev in prefs.devices:
                dev.use = True
            sc.cycles.device = "GPU"
        except Exception as exc:
            print("GPU 不可用, 用 CPU:", exc)
            sc.cycles.device = "CPU"


def setup_render_gpu():
    sc = bpy.context.scene
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = True
        sc.cycles.device = "GPU"
        print("GPU enabled")
    except Exception as exc:
        print("GPU 启用失败, 保持 CPU:", exc)


def flip_back_up(objs, h=0.0219):
    """整体翻 180°, 让皮肤侧朝上 (背面展示)"""
    for ob in objs.values():
        ob.rotation_euler = (math.pi, 0, 0)
    for ob in objs.values():
        ob.location.z -= h


def explode(objs):
    offsets = {
        "back_cover": -0.052, "battery_bay": -0.034, "sensor_carrier": -0.017,
        "body": 0.0, "bezel": 0.028, "usbc_end_cap": 0.0, "button_caps": 0.0,
    }
    for k, ob in objs.items():
        ob.location.z += offsets.get(k, 0.0)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    shot = "hero"
    out = str(HERE / "render.png")
    samples = None
    res = None
    gpu = False
    for i, a in enumerate(argv):
        if a == "--shot":
            shot = argv[i + 1]
        elif a == "--out":
            out = argv[i + 1]
        elif a == "--samples":
            samples = int(argv[i + 1])
        elif a == "--res":
            res = tuple(int(x) for x in argv[i + 1].split("x"))
        elif a == "--gpu":
            gpu = True

    clear()
    add_world()
    objs = import_parts()
    add_floor()
    add_display()
    add_lights()

    if shot == "hero":
        add_camera(az_deg=-32, el_deg=17, dist=0.180)
        setup_render(res=(2200, 1650), samples=140)
    elif shot == "side":
        add_camera(az_deg=42, el_deg=8, dist=0.155)
        setup_render(res=(2200, 1650), samples=140)
    elif shot == "top":
        add_camera(az_deg=-8, el_deg=62, dist=0.15)
        setup_render(res=(1800, 1350), samples=120)
    elif shot == "detail":
        add_camera(az_deg=-52, el_deg=14, dist=0.125, target=(0.019, -0.002, -0.012))
        setup_render(res=(1800, 1350), samples=160)
    elif shot == "back":
        flip_back_up(objs)
        g = bpy.data.objects.get("display_glass")
        if g:
            g.hide_render = True
        add_camera(az_deg=-28, el_deg=34, dist=0.170, target=(0, 0, -0.011))
        setup_render(res=(2200, 1650), samples=140)
    elif shot == "exploded":
        g = bpy.data.objects.get("display_glass")
        if g:
            g.hide_render = True
        fl = bpy.data.objects.get("floor")
        if fl:
            fl.hide_render = True
        explode(objs)
        add_camera(az_deg=-30, el_deg=16, dist=0.30, target=(0, 0, -0.016), lens=50)
        setup_render(res=(2200, 1650), samples=160)
    else:
        raise SystemExit(f"unknown shot {shot}")

    if gpu:
        setup_render_gpu()
    if samples:
        bpy.context.scene.cycles.samples = samples
    if res:
        bpy.context.scene.render.resolution_x = res[0]
        bpy.context.scene.render.resolution_y = res[1]
    bpy.context.scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("rendered", out)


if __name__ == "__main__":
    main()
