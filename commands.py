import FreeCAD as App
import FreeCADGui as Gui
import Part
from .. import ROOT
from . import command_state

TOOLS = [
    ("ConvertMesh", "转为可编辑网格…", "将导入的 STL 网格转换为可编辑的 CAD 曲面；保留原始网格作为备份"),
    ("Analytic", "拟合圆 / 圆柱面", "将选中的分面圆弧边或圆柱面转换为原生解析几何体，或用标准圆柱体替换实体内的分面孔"),
    ("Select", "选择模式", "S / Esc: 选择模式；从右往左拉框接触即选中，从左往右拉框完全包含才选中"),
    ("Measure", "测量", "Z: 点击顶点、边、面或孔进行测量；点击第二个元素测量距离、间距和夹角。放置标注可将其保留在视图中"),
    ("Tape", "测量卷尺与参考线", "T: 从边或参考线引出平行虚线辅助线，或从点引出参考点；绘图会自动吸附到辅助线。按 Tab 键输入精确距离"),
    ("Rectangle", "矩形", "R: 点击两个对角点；选择【绘制: 平面】或【绘制: 曲面】；按 Tab 键输入局部绘图坐标系下的宽度与高度"),
    ("Circle", "圆", "O: 点击指定圆心，然后指定半径；选择【绘制: 平面】或【绘制: 曲面】；按 Tab 键输入精确半径"),
    ("Arc", "圆弧", "A: 在【绘制: 平面】或【绘制: 曲面】中依次指定圆心、起点与终点；按 Tab 键输入局部半径和扫掠角度"),
    ("Arc2Point", "两点圆弧", "H: 依次指定第一端点、第二端点和拱高；选择【绘制: 平面】或【绘制: 曲面】；按 Tab 键输入端点距离与拱高数值"),
    ("Sphere", "球体", "B: 点击球心然后确定半径以创建球体；按 Tab 键输入精确半径"),
    ("Polygon", "正多边形", "G: 设置边数，点击中心然后指定顶点；选择【绘制: 平面】或【绘制: 曲面】；按 Tab 键输入精确局部外接圆半径"),
    ("Line", "直线 / 多段线", "L: 连续绘制直线；【绘制: 平面】生成直线段；【绘制: 曲面】可跨越相连表面贴合并分割闭合区域；按 X/Y/Z 可锁定坐标轴；按 Esc 完成"),
    ("Offset", "偏移", "E: 选中面或边，向内/向外或向两侧偏移；按 Tab 键输入精确距离"),
    ("Elongate", "拉长 / 椭圆化", "X: 选中面或孔边缘，拖动沿任意方向拉伸为椭圆；按 Tab 键输入精确距离和角度"),
    ("PushPull", "推拉 (Push/Pull)", "P: 拖动平面拉伸；吸附到对立面可贯通成孔；拖过对立面可继续向外延伸"),
    ("Round", "倒圆角 / 倒斜角", "F: 对选中的边倒圆角或倒斜角；外拉倒圆角 (Fillet)，内推倒斜角 (Chamfer)；实时预览"),
    ("Subdivide", "细分面", "D: 将平面细分为三角形、中心放射网格或均匀分布的行与列"),
    ("MeshSplit", "分割网格…", "沿 X/Y/Z 轴或主轴/局部轴切分 STL 网格；保留三角面细节，可选封闭切割断面"),
    ("MeshStretch", "拉伸网格 / 移动区域…", "固定一端并移动另一端；仅在两平面之间拉伸网格，生成新网格并保留原网格备份"),
    ("MeshRegion", "网格局部编辑 · 移动/旋转/挤出…", "选中相连的平整或光滑网格面片，实时预览移动、旋转或挤出效果，并保留原网格备份"),
    ("Slice", "切片 / 分离", "U: 沿 X/Y/Z 或主轴进行切片分割；可添加用于 3D 打印的定位销/孔并将切片零件散开"),
    ("Intersect", "相交切分曲面", "I: 选择交叉的面或实体；分割两侧表面并保留区域以便删除"),
    ("Union", "合并实体 (并集)", "J: 将选中的多个实体合并为一个闭合实体；自动消除内部面与多余的分隔边；撤销可恢复各部分"),
    ("VertexMove", "移动顶点", "V: 拖动顶点形变相邻的平面；按 X/Y/Z 锁定单轴；按 Tab 键输入 dx, dy, dz"),
    ("Move", "移动", "M: 选择对象，点击基准点，再点击目标位置"),
    ("Rotate", "旋转", "Q: 围绕中心或轴线旋转整个对象或选中的线/弧；应用前可实时预览"),
    ("Deform", "弯曲 / 柔性变形", "N: 在一个对象上选择区域；平滑衰减变形或沿轴线弯曲；应用前可预览"),
    ("Scale", "缩放 / 拉伸", "K: 等比缩放整个对象，或沿世界/局部坐标系的 X/Y/Z 轴独立拉伸变形"),
    ("Loft", "放样", "Shift+Q: 按顺序依次选择截面轮廓或线框，然后生成平滑或直纹的实体/曲面"),
    ("Sweep", "扫掠", "W: 先选择轮廓截面，再选择相连的边或导轨路径；使轮廓沿路径扫掠成型"),
    ("Copy", "复制", "C: 放置所选对象的独立副本"),
    ("Pattern", "阵列…", "按矩形网格、环形旋转或沿选定边缘路径重复阵列对象；应用前可预览"),
    ("Mirror", "镜像", "沿 X、Y 或 Z 轴翻转对象；默认创建镜像副本，也可选择直接镜像原对象"),
    ("Delete", "删除", "Delete / Backspace: 擦除选中的边、面或整个对象；共面表面将自动合并"),
]


SURFACE = [
    ("Imprint", "表面绘制 / 压印…", "在平整或弯曲表面上投影或包裹矩形、圆、多边形或文字：分割为独立可选中区域，或按指定深度凹凸成型"),
    ("OffsetFace", "曲面偏移…", "沿面法线方向移动面（无论是平面还是曲面）：向外增加实体材料，向内切削挖槽。曲面版的推拉；侧壁沿法线垂直拉伸"),
    ("Shell", "抽壳 / 加厚…", "将实体掏空为指定壁厚的壳体，保留所选面为开口；或将曲面对象加厚为具有壁厚的实体"),
    ("Draft", "拔模斜度…", "使平整或圆柱侧壁绕铰链基准面倾斜指定角度，以便于模具注塑或铸件脱模"),
    ("HealFaces", "删除并缝合面", "从实体中移除选中的面，并延伸相邻的面直到实体重新封闭（例如消除凸台、凹槽或圆角）"),
    ("RemoveRounds", "消除圆角…", "查找指定半径内的圆角（内凹或外凸），将其移除以恢复尖锐棱角；应用前可预览"),
    ("FillHole", "修补孔洞…", "使用与相邻曲面平滑过渡的面片封闭曲面开口；完全闭合的曲面将自动转化为实体"),
    ("Unwrap", "展开曲面", "将曲面展平成相同面积的二维平面轮廓，放置在零件旁，用于钣金展开、模板和下料切割"),
    ("Curvature", "曲率热力图", "根据弯曲曲率程度给曲面着色：红色紧绷急弯，蓝色平缓平坦。再次点击隐藏。测量工具可显示点击点的具体曲率半径"),
]


SMART = [
    ("SelectHole", "选择整孔", "从选中的面或孔边沿自动扩展选择整个孔壁或圆柱面（支持解析曲面与三角网格面）"),
    ("SelectLoop", "选择边缘环", "从选中的边自动扩展为闭合的边缘循环回路（如孔的边框环）"),
    ("SelectFlat", "选择共面平整区", "从选中的面自动扩展为同平面上所有相连的面（例如网格转换后的平坦区域）"),
    ("SelectSmooth", "选择相切光滑面", "跨越平缓折痕自动扩展选择所有光滑过渡的相邻面（如圆角、过渡曲面墙等）"),
]


GROUPS = (
    ('绘制 (Draw)', ('Select', 'Line', 'Rectangle', 'Circle', 'Arc', 'Arc2Point', 'Polygon', 'Sphere')),
    ('修改 (Modify)', ('PushPull', 'Offset', 'Elongate', 'Analytic', 'Round', 'Subdivide', 'Slice', 'Intersect',
                'Union', 'VertexMove', 'Move', 'Rotate', 'Deform', 'Scale', 'Loft', 'Sweep',
                'Copy', 'Pattern', 'Mirror', 'Delete')),
    ('曲面 (Surface)', ('Imprint', 'OffsetFace', 'Shell', 'Draft', 'HealFaces', 'RemoveRounds', 'FillHole', 'Unwrap')),
    ('检查 (Inspect)', ('SmartSelect', 'Measure', 'Tape', 'Curvature', 'Isolate')),
    ('网格 (Mesh)', ('ConvertMesh', 'MeshSplit', 'MeshStretch', 'MeshRegion')),
)
MENU_EXTRAS = {'Modify': ('Separator', 'Appearance', 'Cleanup', 'Heal')}
EXTRAS = [
    ('Isolate', '隔离选中对象', '隐藏除了所选对象之外的所有内容；再次点击隔离可恢复显示。模型几何不受影响'),
    ('Cleanup', '合并重合几何', '消除重叠的共面与重复线；一步撤销即可缝合接触的开敞曲面'),
    ('Heal', '按精度修复对齐', '将模型公差范围内近似平行、近轴对齐或近共面的表面和孔精确对齐；支持一步撤销'),
    ('Settings', '设置…', '显示或隐藏曲面接缝线，配置绘图捕捉与吸附精度'),
    ('MCP', 'AI 助手连接 (MCP)…', '开启或停止用于 AI 客户端检查与修改模型的本地 MCP 协议通信接口'),
    ('Appearance', '颜色与透明度…', '设置选中面或整个对象的表面颜色和不透明度；支持实时预览、应用或取消'),
]
DEFINITIONS = {key: (title, hint) for key, title, hint in TOOLS + SURFACE + SMART + EXTRAS}


def names(keys):
    return [key if key == 'Separator' else 'SimpleCAD_' + key for key in keys]


class SmartSelectGroup:
    def GetCommands(self):
        return tuple("SimpleCAD_" + key for key, _, _ in SMART)

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"MenuText": "智能选择 (Smart select)", "ToolTip": "智能将选择扩展到整孔、边缘环、共面平整区或相切平滑曲面。双击面或边自动智能识别"}

    def IsActive(self):
        return not command_state.reason('SmartSelect')


class Command:
    def __init__(self, key, title, hint):
        self.key, self.title, self.hint = key, title, hint

    def GetResources(self):
        icon = "workbench" if self.key in ("Cleanup", "Heal", "Settings", "MCP", "Appearance") else self.key.lower()
        return {"Pixmap": str(ROOT / "Resources" / "icons" / (icon + ".svg")),
                "MenuText": self.title,
                "ToolTip": self.hint + '\n\n' + command_state.REQUIREMENTS[self.key]}

    def Activated(self):
        if self.key == 'MCP':
            from .tools.mcp import show
            show()
            return
        from .controller import instance
        instance().start(self.key)

    def IsActive(self):
        return not command_state.reason(self.key)


def register():
    for key, (title, hint) in DEFINITIONS.items():
        Gui.addCommand('SimpleCAD_' + key, Command(key, title, hint))
    Gui.addCommand('SimpleCAD_SmartSelect', SmartSelectGroup())
    return names(key for _, keys in GROUPS for key in keys)


def populate_context_menu(menu):
    from .qt import QtGui
    context = command_state.current(fresh=True)
    menu.setToolTipsVisible(True)
    for group, keys in command_state.context_groups(context):
        submenu = menu.addMenu(group)
        submenu.setToolTipsVisible(True)
        for key in keys:
            command = Command(key, *DEFINITIONS[key])
            resources = command.GetResources()
            action = submenu.addAction(QtGui.QIcon(resources['Pixmap']), resources['MenuText'])
            missing = command_state.reason(key, context)
            action.setEnabled(not missing)
            action.setToolTip((missing + '\n\n' if missing else '') + resources['ToolTip'])
            action.setStatusTip(missing or command_state.REQUIREMENTS[key])
            action.triggered.connect(lambda checked=False, command=command: command.Activated())


# =========================================================================
# Shapr3D 风格智能自动触发器：
# 1. 点击平面 -> 自动启动推拉 (PushPull)
# 2. 点击边线 -> 自动启动圆角/倒角 (Round)
# 安全原则：只呼出工具，绝不在后台私自修改/消除模型几何！
# =========================================================================
class AutoCADToolObserver:
    def __init__(self):
        self._busy = False

    def addSelection(self, *args):
        if self._busy or len(args) < 3:
            return

        sub_name = str(args[2])
        is_face = sub_name.startswith('Face')
        is_edge = sub_name.startswith('Edge')

        if not (is_face or is_edge):
            return

        doc_name = str(args[0])
        obj_name = str(args[1])

        def trigger():
            try:
                from .controller import instance
                c = instance()
                if c is None or (c.tool is not None and c.tool not in ('', 'Select', 'PushPull', 'Round')):
                    return

                sel = Gui.Selection.getSelectionEx()
                if len(sel) != 1 or len(sel[0].SubElementNames) < 1:
                    return

                doc = App.getDocument(doc_name)
                obj = doc.getObject(obj_name) if doc else None
                if not obj or not hasattr(obj, 'Shape'):
                    return

                if is_face:
                    face = obj.Shape.getElement(sub_name)
                    # 只有平面才自动触发推拉，曲面不误触
                    if isinstance(face.Surface, Part.Plane):
                        if c.tool == 'Round':
                            c.cancel(quiet=True)
                        Gui.runCommand('SimpleCAD_PushPull', 0)
                        return

                elif is_edge:
                    # 选中棱边 -> 触发圆角/倒角工具
                    if c.tool == 'Round':
                        c.cancel(quiet=True)
                    Gui.runCommand('SimpleCAD_Round', 0)

            except Exception:
                pass
            finally:
                self._busy = False

        self._busy = True
        from .qt import QtCore
        QtCore.QTimer.singleShot(20, trigger)


_auto_tool_observer = AutoCADToolObserver()
if hasattr(Gui, 'Selection'):
    try:
        if '_auto_push_pull_observer' in globals():
            Gui.Selection.removeObserver(_auto_push_pull_observer)
        Gui.Selection.removeObserver(_auto_tool_observer)
    except Exception:
        pass
    Gui.Selection.addObserver(_auto_tool_observer)