"""SimpleCAD-only preferences; never change FreeCAD's picking defaults."""
from dataclasses import dataclass, fields
import re

import FreeCAD as App

PARAMETER_PATH = "User parameter:BaseApp/Preferences/Mod/SimpleCAD"
RANGES = {
    "endpoint_radius": (4, 80),
    "midpoint_radius": (4, 80),
    "edge_radius": (4, 80),
    "center_radius": (4, 120),
    "axis_radius": (2, 40),
    "pull_radius": (2, 40),
    "precision": (0.001, 1.0),
}


@dataclass(frozen=True)
class Settings:
    show_seams: bool = False
    # Dark viewport with ground grid, axes and camera lights while SimpleCAD is active.
    viewport_style: bool = True
    # Display color of faces without a color of their own, while the style is on.
    face_color: str = "#E3E3EC"
    endpoints: bool = True
    midpoints: bool = True
    edges: bool = True
    centers: bool = True
    axes: bool = True
    pull_faces: bool = True
    endpoint_radius: int = 24
    midpoint_radius: int = 24
    edge_radius: int = 16
    center_radius: int = 40
    axis_radius: int = 12
    pull_radius: int = 24
    # Modeling precision in mm. Mesh conversion flattens and aligns surfaces
    # within it, and edits treat anything smaller as noise, not geometry.
    precision: float = 0.1


def color_text(value, default=Settings.face_color):
    """`value` as an upper-case #RRGGBB string, or `default` if it is not one."""
    value = str(value).strip()
    return value.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else default


def color(text):
    """RGB in 0..1 of a #RRGGBB string."""
    return tuple(int(text[i:i+2], 16) / 255 for i in (1, 3, 5))


def load():
    params = App.ParamGet(PARAMETER_PATH)
    values = {}
    for field in fields(Settings):
        if field.type is bool:
            values[field.name] = params.GetBool(field.name, field.default)
        elif field.type is str:
            values[field.name] = color_text(params.GetString(field.name, field.default), field.default)
        elif field.type is float:
            low, high = RANGES[field.name]
            values[field.name] = max(low, min(high, params.GetFloat(field.name, field.default)))
        else:
            low, high = RANGES[field.name]
            values[field.name] = max(low, min(high, params.GetInt(field.name, field.default)))
    return Settings(**values)


def save(settings):
    params = App.ParamGet(PARAMETER_PATH)
    if any(color_text(getattr(settings, field.name), None) is None for field in fields(Settings) if field.type is str):
        raise ValueError("A color must be written #RRGGBB.")
    for field in fields(Settings):
        value = getattr(settings, field.name)
        if field.type is bool:
            params.SetBool(field.name, bool(value))
        elif field.type is str:
            params.SetString(field.name, color_text(value))
        elif field.type is float:
            low, high = RANGES[field.name]
            params.SetFloat(field.name, max(low, min(high, float(value))))
        else:
            low, high = RANGES[field.name]
            params.SetInt(field.name, max(low, min(high, int(value))))


def precision():
    """The modeling precision in mm, readable without a GUI."""
    return load().precision


def smooth_surfaces():
    """Whether Make mesh editable fits smooth surfaces, as last chosen there."""
    return App.ParamGet(PARAMETER_PATH).GetBool('smooth_surfaces', True)


VIEW_PATH = "User parameter:BaseApp/Preferences/View"
LONG_PRESS = "EnableLongPressClarifySelection"


def suspend_long_press_menu():
    """Keep a slow click while drawing from opening FreeCAD's Clarify Selection menu.

    FreeCAD reads this setting on every press. A marker records that
    SimpleCAD turned it off, so a crash mid-tool is undone on the next start.
    """
    view, own = App.ParamGet(VIEW_PATH), App.ParamGet(PARAMETER_PATH)
    if view.GetBool(LONG_PRESS, True) and not own.GetBool("SuspendedLongPressMenu", False):
        own.SetBool("SuspendedLongPressMenu", True)
        view.SetBool(LONG_PRESS, False)


def restore_long_press_menu():
    own = App.ParamGet(PARAMETER_PATH)
    if own.GetBool("SuspendedLongPressMenu", False):
        App.ParamGet(VIEW_PATH).SetBool(LONG_PRESS, True)
        own.RemBool("SuspendedLongPressMenu")
