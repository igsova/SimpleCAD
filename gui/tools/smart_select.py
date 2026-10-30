"""智能选择与隔离命令；两者均不修改模型几何内容。"""
import FreeCAD as App
import FreeCADGui as Gui

from ...inspection import smart_select
from ...mesh.conversion import is_mesh
from .selection import visible_names

KIND_TEXT = {'hole': '整孔 / 圆柱壁', 'loop': '边缘环', 'flat': '共面平整区', 'smooth': '相切光滑面'}
_isolated = {}  # 文档名称 -> 被“隔离”功能隐藏的对象名称列表


def expand_selection(controller, mode):
    """将选中的每个面或边按指定模式扩展，并选中扩展结果。"""
    doc = App.ActiveDocument
    picked = [(item.Object, name) for item in Gui.Selection.getSelectionEx()
              if doc is not None and item.Object.Document == doc and hasattr(item.Object, 'Shape')
              for name in item.SubElementNames if name.startswith(('Face', 'Edge'))]
    if not picked:
        raise ValueError('请先选择一个面或一条边，或在视图中双击面/边。')
    view = Gui.activeDocument().activeView()
    grown, kinds = {}, set()
    for obj, name in picked:
        names, kind = smart_select.expand(obj.Shape, name, mode, view.getViewDirection())
        grown.setdefault(obj, set()).update(visible_names(obj, names))
        kinds.add(kind)
    hits = [(obj, name) for obj, names in grown.items() for name in sorted(names, key=natural)]
    hits = controller.selection.filtered(hits)
    controller.selection.apply(hits, 0)
    controller.message('已选中 %s · 共 %d 个元素 · 按 Delete 键可删除；测量工具可读取孔信息' % (
        '、'.join(KIND_TEXT[kind] for kind in sorted(kinds)), len(hits)))


def natural(name):
    kind = name.rstrip('0123456789')
    return kind, int(name[len(kind):] or 0)


def isolate(controller):
    """隐藏除所选对象以外的所有形状；再次调用时恢复其可见性。"""
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError('请先打开一个模型。')
    hidden = _isolated.pop(doc.Name, None)
    if hidden is not None:
        for name in hidden:
            obj = doc.getObject(name)
            if obj is not None and obj.ViewObject is not None:
                obj.ViewObject.Visibility = True
        controller.message('已恢复所有对象的可见性')
        return False
    keep = {item.Object.Name for item in Gui.Selection.getSelectionEx() if item.Object.Document == doc}
    if not keep:
        raise ValueError('请先选择要隔离的对象。')
    hidden = [obj.Name for obj in doc.Objects
              if obj.Name not in keep and obj.ViewObject is not None and obj.ViewObject.Visibility
              and (hasattr(obj, 'Shape') or is_mesh(obj))]
    for name in hidden:
        doc.getObject(name).ViewObject.Visibility = False
    _isolated[doc.Name] = hidden
    controller.message('已隔离 %d 个对象 · 再次点击“隔离”可恢复显示全部 · 模型几何不受影响' % len(keep))
    return True


def forget_document(name):
    _isolated.pop(name, None)