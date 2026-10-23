"""Pen / brush / effect generators for deriving display families from thin "skeleton" fonts.

All operations take and return polygon contours: lists of (x, y) tuples, outer contours and
holes as produced by a nonzero union. Curves are flattened first; output is dense polylines,
simplified with RDP. Designed for Noto Thin instances (Lao Looped, Thai Looped, Khmer, Latin),
whose outlines are close to a centre-line, so a Minkowski sum with a nib reads as a pen stroke.

Recipes are lists of steps, e.g.
  [{"op": "wobble", "amp": 6, "wave": 260}, {"op": "nib", "shape": "line", "w": 90, "angle": 30},
   {"op": "shear", "deg": 12}]
apply_recipe() also returns the horizontal shift and the shear factor so callers can move
OpenType anchors and widen the advance in step with the outlines.
"""
from __future__ import annotations

import hashlib
import math
import random

import pyclipper

S = 8  # fixed-point scale for pyclipper (1/8 unit precision)


def _to_c(polys):
    return [[(int(round(x * S)), int(round(y * S))) for x, y in p] for p in polys if len(p) > 2]


def _from_c(paths):
    return [[(x / S, y / S) for x, y in p] for p in paths if len(p) > 2]


def _add(pc, polys, kind):
    try:
        pc.AddPaths(_to_c(polys), kind, True)
        return True
    except pyclipper.ClipperException:  # every path degenerate (zero area)
        return False


def union(polys):
    if not polys:
        return []
    pc = pyclipper.Pyclipper()
    if not _add(pc, polys, pyclipper.PT_SUBJECT):
        return []
    return _from_c(pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO))


def difference(a, b):
    if not a:
        return []
    if not b:
        return a
    pc = pyclipper.Pyclipper()
    if not _add(pc, a, pyclipper.PT_SUBJECT):
        return []
    if not _add(pc, b, pyclipper.PT_CLIP):
        return union(a)
    return _from_c(pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO))


def offset(polys, d, join="round"):
    if not polys or d == 0:
        return polys
    jt = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}[join]
    co = pyclipper.PyclipperOffset(miter_limit=4.0, arc_tolerance=0.25 * S)
    co.AddPaths(_to_c(polys), jt, pyclipper.ET_CLOSEDPOLYGON)
    return _from_c(co.Execute(d * S))


# ---------------------------------------------------------------- input

def from_ufo_points(contours, step=3.0):
    """UFO point contours (lines/cubics) -> dense polygons."""
    from .stylize import flatten
    out = []
    for c in contours:
        try:
            out.append(flatten(c, step=step))
        except StopIteration:
            continue
    return union(out)


def resample(poly, step):
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.dist(a, b)
        k = max(1, int(L / step))
        out += [(a[0] + (b[0] - a[0]) * t / k, a[1] + (b[1] - a[1]) * t / k) for t in range(k)]
    return out


# ---------------------------------------------------------------- pens

def nib_polygon(shape="round", w=60.0, h=None, angle=0.0, sides=24):
    """Pen tip as a polygon centred on the origin.
    round: circle of diameter w. line: broad nib w long, h thick (default w/7), rotated by angle.
    ellipse: w x h ellipse rotated by angle (a flat sign-painter's brush with soft corners)."""
    a = math.radians(angle)
    if shape == "round":
        r = w / 2
        pts = [(r * math.cos(2 * math.pi * i / sides), r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    elif shape == "line":
        h = h or max(4.0, w / 7)
        pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    elif shape == "ellipse":
        h = h or w / 3
        pts = [(w / 2 * math.cos(2 * math.pi * i / sides), h / 2 * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    else:
        raise ValueError(shape)
    return [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in pts]


def nib(polys, nib_pts, min_hole=300.0):
    """Minkowski sum of a filled shape with a pen tip: drag the nib along every edge.
    Specks smaller than min_hole (slivers left between the two edges of a thin stroke) are dropped."""
    if not polys:
        return polys
    pat = [(int(round(x * S)), int(round(y * S))) for x, y in nib_pts]
    pieces = list(polys)
    for p in _to_c(polys):
        pieces += _from_c(pyclipper.MinkowskiSum(pat, p, True))
    return drop_specks(union(pieces), min_hole)


def _area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def drop_specks(polys, min_area=300.0):
    return [p for p in polys if abs(_area(p)) >= min_area]


# ---------------------------------------------------------------- distortions

def _rng(seed):
    return random.Random(int(hashlib.sha1(str(seed).encode()).hexdigest()[:8], 16))


def wobble(polys, amp=6.0, wave=240.0, seed="g"):
    """Smooth hand tremor: displace points with a low-frequency field (sum of sines), per glyph seed."""
    r = _rng(seed)
    waves = [(r.uniform(0.6, 1.4) / wave, r.uniform(0.6, 1.4) / wave, r.uniform(0, 6.3), r.uniform(0, 6.3))
             for _ in range(3)]

    def f(x, y):
        dx = sum(math.sin(2 * math.pi * (x * a + y * b) + p) for a, b, p, _ in waves) / 3
        dy = sum(math.sin(2 * math.pi * (x * b - y * a) + q) for a, b, _, q in waves) / 3
        return x + amp * dx, y + amp * dy
    return union([[f(x, y) for x, y in resample(p, 8)] for p in polys])


def rough(polys, amp=4.0, step=10.0, seed="g"):
    """Dry-brush / chalk edge: jitter the outline at short intervals."""
    r = _rng(seed)
    out = []
    for p in polys:
        q = resample(p, step)
        out.append([(x + r.uniform(-amp, amp), y + r.uniform(-amp, amp)) for x, y in q])
    return union(out)


def shear(polys, deg):
    k = math.tan(math.radians(deg))
    return [[(x + k * y, y) for x, y in p] for p in polys]


# ---------------------------------------------------------------- display effects

def inline(polys, inset=None, line=None):
    """Cut a thin line inside the strokes (fancy / sign 'inline'). Thin strokes are left alone."""
    inset = inset or 18.0
    line = line or 10.0
    inner = offset(polys, -inset)
    ring = difference(inner, offset(inner, -line))
    return difference(polys, ring)


def outline(polys, w=18.0):
    return difference(polys, offset(polys, -w))


def outline_shadow(polys, w=14.0, dx=30.0, dy=-30.0, gap=8.0):
    """Hollow letter with a solid drop shadow (fairground / 3D lettering)."""
    moved = [[(x + dx, y + dy) for x, y in p] for p in polys]
    shadow = difference(moved, offset(polys, gap))
    return union(outline(polys, w) + shadow)


def halo(polys, gap=12.0, w=8.0):
    """Neon-style halo: a thin ring following the letter at a distance."""
    ring = difference(offset(polys, gap + w), offset(polys, gap))
    return union(polys + ring)


def stripes(polys, width=12.0, period=48.0, angle=45.0):
    """Cut diagonal stripes through the letter (candy stripe). Pieces too small to print are dropped."""
    if not polys:
        return polys
    xs = [x for p in polys for x, _ in p]; ys = [y for p in polys for _, y in p]
    x0, x1, y0, y1 = min(xs) - 50, max(xs) + 50, min(ys) - 50, max(ys) + 50
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)      # stripe direction
    nx, ny = -uy, ux                        # stripe normal
    L = (x1 - x0) + (y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bands = []
    k = -int(L / period) - 1
    while k * period < L:
        o = k * period
        px, py = cx + nx * o, cy + ny * o
        hw = width / 2
        bands.append([(px - ux * L + nx * -hw, py - uy * L + ny * -hw), (px + ux * L + nx * -hw, py + uy * L + ny * -hw),
                      (px + ux * L + nx * hw, py + uy * L + ny * hw), (px - ux * L + nx * hw, py - uy * L + ny * hw)])
        k += 1
    return drop_specks(difference(polys, bands), 250.0)


def block_shadow(polys, dx=34.0, dy=-34.0, gap=10.0):
    """Sign-painter's drop shadow: an offset solid copy separated from the letter by a thin gap."""
    moved = [[(x + dx, y + dy) for x, y in p] for p in polys]
    shadow = difference(moved, offset(polys, gap))
    return union(polys + shadow)


def simplify(polys, eps=0.6):
    """Drop near-collinear points from closed polygons (RDP split at the farthest-apart vertices)."""
    from .stylize import simplify_closed
    out = []
    for p in polys:
        q = p if len(p) < 8 else simplify_closed(p, eps)
        if len(q) > 2:
            out.append(q)
    return out


# ---------------------------------------------------------------- recipes

def apply_recipe(polys, recipe, seed="g"):
    """Run steps; returns (polys, info) where info = {"grow": extra half-width, "shear": k, "shift_x": dx}
    so the caller can widen advances and transform anchors (x' = x + shift_x + shear * y)."""
    info = {"grow_left": 0.0, "grow_right": 0.0, "grow_y": 0.0, "shear": 0.0}
    for st in recipe:
        op = st["op"]
        if op == "nib":
            pts = nib_polygon(st.get("shape", "round"), st.get("w", 60), st.get("h"), st.get("angle", 0))
            polys = nib(polys, pts, st.get("min_hole", 300.0))
            half = max(abs(x) for x, _ in pts)
            info["grow_left"] += half
            info["grow_right"] += half
            info["grow_y"] += max(abs(y) for _, y in pts)
        elif op == "offset":
            polys = offset(polys, st["d"], st.get("join", "round"))
            info["grow_left"] += st["d"]
            info["grow_right"] += st["d"]
            info["grow_y"] += max(0.0, st["d"])
        elif op == "wobble":
            polys = wobble(polys, st.get("amp", 6), st.get("wave", 240), seed)
        elif op == "rough":
            polys = rough(polys, st.get("amp", 4), st.get("step", 10), seed)
        elif op == "shear":
            polys = shear(polys, st["deg"])
            info["shear"] += math.tan(math.radians(st["deg"]))
        elif op == "inline":
            polys = inline(polys, st.get("inset"), st.get("line"))
        elif op == "outline":
            polys = outline(polys, st.get("w", 18))
        elif op == "halo":
            polys = halo(polys, st.get("gap", 12), st.get("w", 8))
            g = st.get("gap", 12) + st.get("w", 8)
            info["grow_left"] += g; info["grow_right"] += g; info["grow_y"] += g
        elif op == "stripes":
            polys = stripes(polys, st.get("width", 12), st.get("period", 48), st.get("angle", 45))
        elif op == "outline_shadow":
            polys = outline_shadow(polys, st.get("w", 14), st.get("dx", 30), st.get("dy", -30), st.get("gap", 8))
            info["grow_right"] += max(0.0, st.get("dx", 30))
        elif op == "shadow":
            polys = block_shadow(polys, st.get("dx", 34), st.get("dy", -34), st.get("gap", 10))
            info["grow_right"] += max(0.0, st.get("dx", 34))
        else:
            raise ValueError(f"unknown op {op}")
    return simplify(polys, 0.6), info


def components(polys):
    """Group polygons into connected pieces: each outer contour with the holes inside it."""
    outers = [p for p in polys if _area(p) > 0]
    holes = [p for p in polys if _area(p) <= 0]
    groups = [[o] for o in outers]

    def inside(pt, poly):
        x, y = pt
        c = False
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[i - 1]
            if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
                c = not c
        return c
    for h in holes:
        for g in groups:
            if inside(h[0], g[0]):
                g.append(h)
                break
    return groups


def apply_recipe_stacked(polys, recipe, seed="g"):
    """For mark ligatures (e.g. Lao nikhahit + tone in one glyph): pen each vertically stacked
    piece separately and lift upper pieces by 2*grow_y per level so they don't fuse."""
    groups = components(polys)
    if len(groups) < 2:
        return apply_recipe(polys, recipe, seed)
    groups.sort(key=lambda g: min(y for _, y in g[0]))
    levels, last_top = [], None
    for g in groups:
        lo = min(y for _, y in g[0]); hi = max(y for _, y in g[0])
        if last_top is None or lo > last_top - 5:
            levels.append([g]); last_top = hi
        else:
            levels[-1].append(g); last_top = max(last_top, hi)
    out, info = [], None
    for i, lvl in enumerate(levels):
        pts = [p for g in lvl for p in g]
        res, info = apply_recipe(pts, recipe, seed=f"{seed}/{i}")
        lift = 2 * info["grow_y"] * i
        out += [[(x, y + lift) for x, y in p] for p in res]
    return union(out), info
