"""曲率热力图：根据曲面弯曲的紧绷程度为其着色。

通过在 3D 视图上叠加临时 Coin 图层进行显示，绝不修改文档几何内容。
再次运行该命令可隐藏热力图；若有选中对象则仅针对所选对象绘制，未选择任何对象时则针对所有可见 CAD 对象绘制。
"""
import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from ...document import operations as ops
from ...surfaces import edit as se

_shown = {}  # 文档名称 -> (view, overlay root)


def shown(doc):
    return doc is not None and doc.Name in _shown


def hide(doc):
    view, root = _shown.pop(doc.Name, (None, None))
    if view is not None:
        try:
            view.getSceneGraph().removeChild(root)
            view.redraw()
        except (RuntimeError, ReferenceError):
            pass


def drawn_mesh(obj):
    """获取 3D 视图为该对象绘制的 (顶点列表, 各面的三角形索引)（位于对象自身坐标系中）；
    若视图当前未显示着色面（如线框模式 Wireframe、点云模式 Points）或以其他方式绘制，则返回 None。"""
    face_set = coin.SoType.fromName('SoBrepFaceSet')
    if face_set.isBad() or getattr(obj, 'ViewObject', None) is None:
        return None
    found = []
    for kind in (coin.SoCoordinate3.getClassTypeId(), face_set):
        search = coin.SoSearchAction()
        search.setType(kind)
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(obj.ViewObject.RootNode)
        paths = search.getPaths()
        found.append([paths[i].getTail() for i in range(paths.getLength())])
    coords, faces = found
    if len(coords) != 1 or len(faces) != 1:
        return None
    points = [tuple(p) for p in coords[0].point.getValues()]
    index = faces[0].getField('coordIndex').getValues()
    parts = faces[0].getField('partIndex').getValues()
    if (len(parts) != len(obj.Shape.Faces) or 4 * sum(parts) != len(index)
            or any(i != -1 for i in index[3::4]) or any(i >= len(points) for i in index)):
        return None
    triangles, start = [], 0
    for count in parts:
        triangles.append([tuple(index[k:k + 3]) for k in range(start, start + 4 * count, 4)])
        start += 4 * count
    return points, triangles


def overlay(objects):
    """返回对象的 (Coin 根节点, 急弯紧绷半径, 平缓平坦半径, 着色面数量)。"""
    shapes = []
    for obj in objects:
        # 视图在对象自身坐标系中绘制各形状，并根据对象的 Placement 进行平移变换，因此热力图也采用同样处理。
        shape = obj.Shape.copy(False)
        shape.Placement = App.Placement()
        try:
            place = obj.getGlobalPlacement()
        except (AttributeError, RuntimeError):
            place = obj.Shape.Placement
        shapes.append((obj, shape, place))
    size = App.BoundBox()
    for obj, _, _ in shapes:
        size.add(obj.Shape.BoundBox)
    tight, gentle = se.curvature_range(size.DiagonalLength)
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    # 热力图与视图着色的三角形完全重合，因此向摄像机方向轻微拉近偏移，
    # 无论缩放到何种程度都能在深度测试中置顶显示。
    offset = coin.SoPolygonOffset()
    offset.factor = -1.0
    offset.units = -1.0
    root.addChild(offset)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    root.addChild(hints)
    faces = 0
    for obj, shape, place in shapes:
        drawn = drawn_mesh(obj)
        box = shape.BoundBox
        box.enlarge(1e-3 + box.DiagonalLength * 1e-3)
        if drawn and not all(box.isInside(App.Vector(*p)) for p in drawn[0][::max(1, len(drawn[0]) // 50)]):
            drawn = None  # 未在形状自身坐标系中绘制；重新剖分网格
        points, triangles, radii = se.curvature_mesh(shape, drawn=drawn)
        if not triangles:
            continue
        faces += sum(1 for f in shape.Faces if type(f.Surface).__name__ != 'Plane')
        group = coin.SoSeparator()
        move = coin.SoTransform()
        move.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
        move.rotation.setValue(*place.Rotation.Q)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), [tuple(p) for p in points])
        material = coin.SoMaterial()
        material.diffuseColor.setValues(0, len(radii), [se.curvature_color(r, tight, gentle) for r in radii])
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
        mesh = coin.SoIndexedFaceSet()
        indices = [i for triangle in triangles for i in (*triangle, -1)]
        mesh.coordIndex.setValues(0, len(indices), indices)
        mesh.materialIndex.setValues(0, len(indices), indices)
        for node in (move, coords, material, binding, mesh):
            group.addChild(node)
        root.addChild(group)
    return root, tight, gentle, faces


def toggle(controller):
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError('请先打开一个模型。')
    if shown(doc):
        hide(doc)
        controller.message('已隐藏曲率热力图')
        return False
    objects = controller.selected() or ops.visible_shapes(doc)
    objects = [obj for obj in objects if hasattr(obj, 'Shape') and not obj.Shape.isNull()]
    if not objects:
        raise ValueError('请先选择 CAD 对象，或显示部分 CAD 对象以绘制曲率。')
    root, tight, gentle, faces = overlay(objects)
    if not faces:
        raise ValueError('所选对象仅包含平面，没有可分析着色的曲面。')
    view = Gui.activeDocument().activeView()
    view.getSceneGraph().addChild(root)
    view.redraw()
    _shown[doc.Name] = (view, root)
    controller.message('已显示 %d 个曲面的曲率热力图 · 红色：半径 ≤ %.3g mm（急弯紧绷）· 黄色、绿色 · '
                       '蓝色：半径 ≥ %.3g mm（平缓平坦）· 平面保持原色 · 再次点击隐藏'
                       % (faces, tight, gentle))
    return True


def forget_document(name):
    _shown.pop(name, None)