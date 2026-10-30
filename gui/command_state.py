"""Cheap command availability, shared by toolbars, shortcuts and context menus.

FreeCAD polls IsActive repeatedly, including while a large imported model is
selected, so never walk a model's faces, its Mesh or face-lock matching here.
The one exception is a small selection (at most CLASSIFY_LIMIT subelements on
shapes of at most CLASSIFY_FACES faces): its faces, edges and vertices are
classified once as flat or curved, cached until that object's Shape changes,
so flat-only tools grey out on curved faces.
Operation-specific geometry validation still runs when a command is invoked.
"""
from dataclasses import dataclass, field
import sys
import time


DRAW = frozenset(('Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere'))
PICK = frozenset(('PushPull', 'Offset', 'Elongate', 'VertexMove', 'Measure'))
SMART = frozenset(('SmartSelect', 'SelectHole', 'SelectLoop', 'SelectFlat', 'SelectSmooth'))
SURFACE = frozenset(('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'FillHole', 'Unwrap'))
ALWAYS = DRAW | {'Select', 'Tape', 'Settings', 'MCP'}
CLASSIFY_LIMIT = 16  # larger selections stay unclassified; invoke-time checks still apply
CLASSIFY_FACES = 2000

NOT_FLAT = frozenset(('cylinder', 'curved'))
FLAT_ONLY = {
    'PushPull': '推拉 (Push/Pull) 需要平面。曲面请使用【曲面偏移 (OffsetFace)】进行推拉。',
    'Subdivide': '细分面需要平面。曲面暂不支持细分。',
}
FLAT_OR_ROUND = {
    'Offset': '偏移支持平面、圆柱面、直线边和圆弧，不支持自由曲线边或自由曲面。',
    'Elongate': '拉长支持平面、圆柱面和圆形轮廓，不支持自由曲面或自由曲线边。',
    'Draft': '拔模支持平面和圆柱面，不支持自由曲面。',
}

REQUIREMENTS = {
    **{key: '无需预先选择；直接在 3D 视图中点击即可开始绘制。' for key in DRAW},
    'Select': '在视图中点击几何体，或拖动拉出框选矩形。',
    'Measure': '打开 CAD 模型，然后在视图中点击几何体进行测量；无需预选。',
    'Tape': '无需预选；在视图中点击点、边或参考线以引出辅助虚线。',
    'PushPull': '启动后在视图中点击一个平面，或预先选中一个平面。',
    'Offset': '启动后点击一个平面或一条边，或预先选中一个。',
    'Elongate': '启动后点击一个面或孔口边框，或预先选中一个。',
    'VertexMove': '启动后点击一个 CAD 顶点，或预先选中一个。',
    'Move': '选择 CAD 对象，或启动后在视图中点击要移动的 CAD 对象。',
    'Copy': '选择 CAD 对象，或启动后在视图中点击要复制的 CAD 对象。',
    'ConvertMesh': '请选择一个 STL 网格对象，或者只保留一个可见网格且不要多选。',
    'MeshSplit': '请选择一个 STL 网格对象，或者只保留一个可见网格且不要多选。',
    'MeshStretch': '请先选择一个 STL 网格对象。',
    'MeshRegion': '请先选择一个 STL 网格对象，然后在视图中点击面片进行局部编辑。',
    'Analytic': '请选择圆弧边、圆柱面或一个分面 CAD 对象。原始网格请先转为可编辑 CAD。',
    'Round': '请先选择 CAD 边、面或实体对象。',
    'Subdivide': '请先选择一个平整的 CAD 面，或单面对象。',
    'Slice': '请先选择 CAD 对象。若选择 STL 网格将打开网格分割。',
    'Intersect': '请选择相交的 CAD 面或对象；所选内容必须包含面或完整对象。',
    'Union': '请选择要合并求并集的 CAD 对象。复合体内部的多个实体也可合并。',
    'Rotate': '请先选择 CAD 对象、面或边。',
    'Deform': '请先在单个 CAD 对象上选择一个区域或选择整个对象。',
    'Scale': '请先选择要缩放的 CAD 对象。',
    'Loft': '请按顺序依次选择至少两个 CAD 面或线框截面轮廓。',
    'Sweep': '请先选择 CAD 面/线框截面轮廓，然后选择其相连的边或路径。',
    'Mirror': '请先选择要镜像的 CAD 对象。',
    'Pattern': '请选择要重复阵列的完整 CAD 对象；可选选中另一个对象的边缘作为路径。',
    'Imprint': '请选择要绘制的目标 CAD 面（须位于同一对象上）；点击位置将作为绘图中心。',
    'OffsetFace': '请选择要偏移的 CAD 面（须位于同一个封闭实体上）。',
    'Shell': '请选择一个 CAD 实体，或要留空的开口面；亦可选择曲面对象进行加厚。',
    'Draft': '请选择要倾斜拔模的平整或圆柱侧壁（须位于同一个封闭实体上）。',
    'HealFaces': '请选择要从封闭 CAD 实体中移除并自动缝合的面。',
    'RemoveRounds': '请选择一个封闭 CAD 实体，或选择其部分面以仅在其中搜索圆角。',
    'FillHole': '请选择开敞的 CAD 曲面对象，或要修补封闭的孔洞边框。',
    'Unwrap': '请选择一个要展平的 CAD 曲面。',
    'Curvature': '打开 CAD 模型；选中的对象或所有可见对象将显示曲率色彩。再次点击隐藏。',
    'Delete': '请选择 CAD 边、面、完整对象或辅助线。单个独立顶点无法单独删除。',
    **{key: '请先选择 CAD 面或边；原始 STL 三角网格需先转换。' for key in SMART},
    'Isolate': '请选择要隔离的对象。再次点击可恢复可见性（无需选中任何对象）。',
    'Appearance': '请先选择 CAD 面或完整 CAD 对象。',
    'Cleanup': '请选择 CAD 对象，或取消选择以清理所有可见的 CAD 对象。',
    'Heal': '请先选择要按公差修复对齐的 CAD 对象。',
    'Settings': '配置 SimpleCAD 界面显示、绘图吸附捕捉与建模精度。',
    'MCP': '启动或停止 AI 客户端连接；无需打开模型或选择对象。',
}


@dataclass(frozen=True)
class Target:
    kind: str
    names: tuple = ()
    locked: bool = False
    surfaces: frozenset = frozenset()
    face_count: int = field(init=False)
    edge_count: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'face_count', sum(n.startswith('Face') for n in self.names))
        object.__setattr__(self, 'edge_count', sum(n.startswith('Edge') for n in self.names))


@dataclass(frozen=True)
class Context:
    document: bool = False
    selected: tuple = ()
    visible_cad: bool = False
    visible_meshes: int = 0
    isolated: bool = False
    curvature: bool = False


def kind(obj):
    if obj.isDerivedFrom('Mesh::Feature'):
        return 'mesh'
    properties = obj.PropertiesList
    if 'SC_Guide' in properties or 'SC_Guides' in properties:
        return 'guide'
    return 'cad' if 'Shape' in properties else 'other'


def classify(shape, name):
    import Part
    try:
        element = shape.getElement(name)
    except Exception:
        return None
    if name.startswith('Face'):
        surface = element.Surface
        if isinstance(surface, Part.Plane):
            return 'flat'
        return 'cylinder' if isinstance(surface, Part.Cylinder) else 'curved'
    if name.startswith('Edge'):
        curve = None if element.Degenerated else element.Curve
        if isinstance(curve, (Part.Line, Part.LineSegment)):
            return 'straight'
        return 'circular' if isinstance(curve, Part.Circle) else 'freeform'
    if name.startswith('Vertex'):
        edges = shape.ancestorsOfType(element, Part.Edge)
        faces = shape.ancestorsOfType(element, Part.Face)
        straight = all(not e.Degenerated and isinstance(e.Curve, (Part.Line, Part.LineSegment)) for e in edges)
        flat = all(isinstance(f.Surface, Part.Plane) for f in faces)
        return 'corner' if straight and flat else 'curved-corner'
    return None


_kinds = {}


def surface_kinds(doc, obj, names):
    shape = obj.Shape
    key = (doc.Name, obj.Name)
    cached = _kinds.get(key)
    if cached is None or not cached[0].isSame(shape):
        cached = _kinds[key] = (shape, {} if shape.countElement('Face') <= CLASSIFY_FACES else None)
        for old in list(_kinds)[:-8]:
            del _kinds[old]
    kinds = cached[1]
    if kinds is None:
        return frozenset()
    for name in names:
        if name not in kinds:
            kinds[name] = classify(shape, name)
    return frozenset(kinds[name] for name in names) - {None}


def capture():
    import FreeCAD as App
    import FreeCADGui as Gui
    doc = App.ActiveDocument
    if doc is None:
        return Context()
    picked, owners = {}, {}
    for item in Gui.Selection.getSelectionEx():
        obj = item.Object
        if obj is None or obj.Document != doc:
            continue
        names = tuple(item.SubElementNames)
        prior = picked.get(obj.Name)
        if prior is not None:
            names = tuple(dict.fromkeys(prior.names + names)) if prior.names and names else ()
        picked[obj.Name] = Target(kind(obj), names, bool(getattr(obj, 'SC_Locked', False)))
        owners[obj.Name] = obj
    if sum(len(t.names) for t in picked.values()) <= CLASSIFY_LIMIT:
        for name, target in picked.items():
            if target.kind == 'cad' and target.names:
                try:
                    kinds = surface_kinds(doc, owners[name], target.names)
                except Exception:
                    continue
                picked[name] = Target(target.kind, target.names, target.locked, kinds)
    cad, meshes = False, 0
    for obj in doc.Objects:
        if obj.ViewObject is None or not obj.ViewObject.Visibility:
            continue
        obj_kind = kind(obj)
        cad |= obj_kind == 'cad'
        meshes += obj_kind == 'mesh'
    module = sys.modules.get('simplecad.gui.tools.smart_select')
    isolated = module is not None and doc.Name in module._isolated
    module = sys.modules.get('simplecad.gui.tools.curvature')
    curvature = module is not None and doc.Name in module._shown
    return Context(True, tuple(picked.values()), cad, meshes, isolated, curvature)


_cached = None
_expires = 0


def current(fresh=False):
    global _cached, _expires
    now = time.monotonic()
    if fresh or _cached is None or now >= _expires:
        try:
            _cached = capture()
        except (ReferenceError, RuntimeError):
            _cached = Context()
        _expires = now + .1
    return _cached


def surface_reason(key, selected):
    kinds = frozenset().union(*(t.surfaces for t in selected))
    if not kinds:
        return ''
    if key in FLAT_ONLY and kinds & NOT_FLAT:
        return FLAT_ONLY[key]
    if key in FLAT_OR_ROUND and kinds & {'curved', 'freeform'}:
        return FLAT_OR_ROUND[key]
    if key == 'VertexMove' and 'curved-corner' in kinds:
        return '移动顶点需要由平面和直边相交形成的角点，不支持曲面角点。'
    if key == 'SelectHole' and 'curved' in kinds:
        return '选择整孔需要圆柱面、分面孔壁或边缘，不支持自由曲面。'
    if key == 'SelectFlat' and kinds <= NOT_FLAT:
        return '选择平整区需要平面或直线边；弯曲表面请使用【选择相切光滑面】。'
    return ''


def reason(key, context=None):
    if key in ALWAYS:
        return ''
    c = current() if context is None else context
    if not c.document:
        return '请先打开一个模型。'
    selected = c.selected
    if key == 'Delete' and any(t.kind == 'guide' for t in selected):
        selected = tuple(t for t in selected if t.kind != 'guide')
        if not selected:
            return ''
    cad = bool(selected) and all(t.kind == 'cad' for t in selected)
    curved = surface_reason(key, selected) if cad else ''
    if curved:
        return curved
    if key == 'Isolate':
        return '' if selected or c.isolated else '请先选择要隔离的对象。'
    if key == 'Curvature':
        return '' if c.curvature or cad or not selected and c.visible_cad else REQUIREMENTS[key]
    if key in PICK:
        return '' if c.visible_cad or cad else '此工具需要 CAD 实体几何体。如果是原始 STL，请先使用【转为可编辑网格】。'
    if key in ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion'):
        valid = len(selected) == 1 and selected[0].kind == 'mesh'
        if key not in ('MeshStretch','MeshRegion') and not selected:
            valid = c.visible_meshes == 1
        if not valid:
            return REQUIREMENTS[key]
        if key != 'ConvertMesh' and any(t.locked for t in selected):
            return '编辑前请先解锁网格。'
        return ''
    if key == 'Slice' and len(selected) == 1 and selected[0].kind == 'mesh':
        return reason('MeshSplit', c)
    if key in ('Move', 'Copy') and not selected:
        return '' if c.visible_cad else '请先打开 CAD 模型，然后选择或点击对象。'
    if key == 'Cleanup' and not selected:
        return '' if c.visible_cad else '请先打开包含可编辑 CAD 对象的模型。'
    if not cad:
        return REQUIREMENTS.get(key, '请先选择 CAD 几何体。')
    count = sum(len(t.names) for t in selected)
    faces = sum(t.face_count for t in selected)
    edges = sum(t.edge_count for t in selected)
    faces_edges = count == faces + edges
    if key in SMART:
        return '' if count and faces_edges else REQUIREMENTS[key]
    if key == 'Appearance':
        return '' if count == faces else REQUIREMENTS[key]
    if key == 'Pattern':
        whole = [t for t in selected if not t.names]
        return '' if whole and all(t.edge_count == len(t.names) for t in selected) else REQUIREMENTS[key]
    if key not in ('Copy', 'Mirror', 'Analytic', 'Loft', 'Sweep', 'Unwrap') and any(t.locked for t in selected):
        return '编辑前请先解锁所选对象。'
    if key == 'Subdivide' and (len(selected) != 1 or count and (count != 1 or faces != 1)):
        return REQUIREMENTS[key]
    if key in ('Deform', 'Analytic') and len(selected) != 1:
        return REQUIREMENTS[key]
    if key in SURFACE:
        one = len(selected) == 1
        valid = {'Imprint': one and count and count == faces, 'HealFaces': one and count and count == faces,
                 'OffsetFace': one and count and count == faces, 'Draft': one and count and count == faces,
                 'Shell': one and count == faces,
                 'RemoveRounds': one and count == faces, 'FillHole': one and count == edges,
                 'Unwrap': one and count == faces == 1}[key]
        return '' if valid else REQUIREMENTS[key]
    if key in ('Delete', 'Round', 'Analytic') and not faces_edges:
        return REQUIREMENTS[key]
    if key == 'Intersect' and count != faces:
        return REQUIREMENTS[key]
    if key in ('Loft', 'Sweep'):
        profiles = sum(t.face_count or 1 for t in selected)
        mixed = any(t.face_count and t.edge_count for t in selected)
        if not faces_edges or mixed or not (2 <= profiles <= 32 if key == 'Loft' else profiles == 2):
            return REQUIREMENTS[key]
    return '' if key in REQUIREMENTS else '未知的 SimpleCAD 命令。'


def context_groups(context=None):
    c = current(fresh=True) if context is None else context
    if not c.selected:
        return [('绘制', ('Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere')),
                ('检查与测量', ('Select', 'Measure', 'Tape', 'Curvature', 'Isolate'))]
    if all(t.kind == 'guide' for t in c.selected):
        return [('修改', ('Delete',)), ('检查与测量', ('Tape', 'Isolate'))]
    if all(t.kind == 'mesh' for t in c.selected):
        return [('网格', ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion')),
                ('检查与测量', ('Isolate',))]
    if not all(t.kind == 'cad' for t in c.selected):
        return [('检查与测量', ('Isolate',))]
    names = [name for target in c.selected for name in target.names]
    modify = ['Move', 'Rotate', 'Copy', 'Pattern', 'Mirror', 'Scale']
    inspect = ['Measure', 'Tape', 'Curvature', 'Isolate']
    surface = ['Shell', 'RemoveRounds', 'FillHole']
    if names and all(n.startswith('Vertex') for n in names):
        modify = ['VertexMove', 'Deform'] + modify
        surface = []
    else:
        if any(n.startswith('Face') for n in names):
            modify = ['PushPull', 'Offset', 'Elongate', 'Subdivide', 'Deform'] + modify
            surface = ['Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'Unwrap', 'FillHole']
        elif names:
            modify = ['Offset', 'Elongate'] + modify
            surface = ['FillHole']
        modify += ['Analytic', 'Round', 'Slice', 'Intersect', 'Union', 'Loft', 'Sweep', 'Appearance', 'Delete']
        if names:
            inspect = ['SelectHole', 'SelectLoop', 'SelectFlat', 'SelectSmooth'] + inspect
    return [('修改', tuple(modify))] + ([('曲面', tuple(surface))] if surface else []) + [('检查与测量', tuple(inspect))]