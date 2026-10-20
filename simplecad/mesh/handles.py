"""Geometry for mesh plane handles; no FreeCAD, Qt or scene-graph dependencies."""
import math
import numpy as np
from .transform import vector


def rotations(angles):
    """World X, then Y, then Z (degrees), and their current Euler handle axes."""
    values = vector(angles, 'Plane rotation')
    if np.any(np.abs(values) > 180):
        raise ValueError('Plane rotations must be between -180 and 180 degrees.')
    x, y, z = np.radians(values)
    cx, cy, cz = np.cos((x, y, z)); sx, sy, sz = np.sin((x, y, z))
    rx = np.array(((1,0,0),(0,cx,-sx),(0,sx,cx)))
    ry = np.array(((cy,0,sy),(0,1,0),(-sy,0,cy)))
    rz = np.array(((cz,-sz,0),(sz,cz,0),(0,0,1)))
    return rz @ ry @ rx, (rz @ ry @ (1,0,0), rz @ (0,1,0), np.array((0.,0.,1.)))


def basis(normal):
    normal = np.asarray(normal, dtype=float)
    normal = normal / np.linalg.norm(normal)
    u = np.cross(normal, np.eye(3)[np.argmin(np.abs(normal))])
    u /= np.linalg.norm(u)
    return u, np.cross(normal, u)


def ring(center, normal, radius, segments=72):
    u, v = basis(normal)
    angles = np.linspace(0, 2*math.pi, segments+1)
    return np.asarray(center) + radius * (np.cos(angles)[:, None]*u + np.sin(angles)[:, None]*v)


def nearest_segment(pos, line):
    """Pixel distance and fractional segment index, including collapsed views."""
    line = np.asarray(line, dtype=float)
    a, delta = line[:-1], np.diff(line, axis=0)
    lengths = np.einsum('ij,ij->i', delta, delta)
    t = np.clip(np.einsum('ij,ij->i', np.asarray(pos)-a, delta) / np.maximum(lengths, 1e-12), 0, 1)
    distances = np.linalg.norm(a + t[:,None]*delta - pos, axis=1)
    index = int(np.argmin(distances))
    return float(distances[index]), index + float(t[index])


def plane_angle(origin, direction, center, normal):
    """Cursor-ray angle in a ring's plane, or None for an edge-on/central hit."""
    direction, normal = np.asarray(direction), np.asarray(normal)
    denominator = float(direction @ normal)
    if abs(denominator) < np.linalg.norm(direction)*.15:
        return None
    origin, center = np.asarray(origin), np.asarray(center)
    point = origin + direction * float((center-origin) @ normal) / denominator - center
    u, v = basis(normal)
    x, y = float(point @ u), float(point @ v)
    return math.atan2(y, x) if math.hypot(x, y) > 1e-9 else None


def tangent_rotation(down, pos, tangent):
    """Edge-on fallback: mouse travel along the projected ring tangent."""
    tangent = np.asarray(tangent)
    return float((np.asarray(pos)-down) @ tangent) / max(float(tangent @ tangent), 1e-9)


def angle_step(previous, current):
    return (current - previous + math.pi) % (2*math.pi) - math.pi


def drag_level(value, lower, upper, which, limits):
    """Clamp to the mesh and keep planes ordered on the four-decimal UI grid."""
    minimum = math.ceil(limits[0]*10000)/10000
    maximum = math.floor(limits[1]*10000)/10000
    if which == 0:
        maximum = min(maximum, round(upper-.0001, 4))
    else:
        minimum = max(minimum, round(lower+.0001, 4))
    if maximum < minimum:
        return lower if which == 0 else upper
    return min(maximum, max(minimum, round(value, 4)))
