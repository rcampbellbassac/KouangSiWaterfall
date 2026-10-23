"""Outline stylization filters for deriving display styles from existing fonts.

octilinearize(): rebuild contours from straight edges at multiples of 45 degrees
(the Black Ops One / stencil-signage look: curves become chamfers, bowls become octagons).
stencil_cut(): subtract bridge gaps (rectangles or slanted bars) from a glyph.
All functions work on UFO-style point contours: [[{"x","y","type"}, ...], ...].
"""
from __future__ import annotations

import math
from typing import Iterable

Point = tuple[float, float]


# ---------------------------------------------------------------- flattening

def _cubic(p0, p1, p2, p3, t):
    mt = 1 - t
    return (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])


def flatten(points: list[dict], step: float = 4.0) -> list[Point]:
    """UFO closed contour (cubic / line) -> polygon vertices."""
    pts = list(points)
    first_on = next(i for i, p in enumerate(pts) if p["type"] != "offcurve")
    pts = pts[first_on + 1:] + pts[:first_on + 1]  # end on an on-curve point; start segment after it
    poly: list[Point] = []
    cur = (pts[-1]["x"], pts[-1]["y"])
    offs: list[Point] = []
    for p in pts:
        xy = (p["x"], p["y"])
        if p["type"] == "offcurve":
            offs.append(xy)
            continue
        if p["type"] == "curve" and len(offs) == 2:
            approx = math.dist(cur, offs[0]) + math.dist(offs[0], offs[1]) + math.dist(offs[1], xy)
            n = max(2, int(approx / step))
            poly += [_cubic(cur, offs[0], offs[1], xy, i / n) for i in range(1, n + 1)]
        elif p["type"] in ("qcurve",) or (p["type"] == "curve" and len(offs) != 2):
            raise ValueError("only cubic curves / lines supported")
        else:
            poly.append(xy)
        offs = []
        cur = xy
    return poly


# ---------------------------------------------------------------- simplification

def _rdp(pts: list[Point], eps: float) -> list[Point]:
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy) or 1e-9
    idx, dmax = 0, -1.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + b[0] * a[1] - b[1] * a[0]) / norm
        if d > dmax:
            idx, dmax = i, d
    if dmax > eps:
        return _rdp(pts[:idx + 1], eps)[:-1] + _rdp(pts[idx:], eps)
    return [a, b]


def simplify_closed(poly: list[Point], eps: float) -> list[Point]:
    """RDP on a closed polygon, split at the two mutually farthest-apart vertices for stability."""
    if len(poly) < 4:
        return poly
    i0 = 0
    i1 = max(range(len(poly)), key=lambda i: math.dist(poly[i0], poly[i]))
    i0 = max(range(len(poly)), key=lambda i: math.dist(poly[i1], poly[i]))
    i1 = max(range(len(poly)), key=lambda i: math.dist(poly[i0], poly[i]))
    a, b = sorted((i0, i1))
    first = poly[a:b + 1]
    second = poly[b:] + poly[:a + 1]
    return _rdp(first, eps)[:-1] + _rdp(second, eps)[:-1]


# ---------------------------------------------------------------- octilinear snapping

def _snap_dir(dx, dy, step_deg=45.0):
    ang = math.atan2(dy, dx)
    k = round(ang / math.radians(step_deg))
    a = k * math.radians(step_deg)
    return (round(math.cos(a), 12), round(math.sin(a), 12)), k % int(360 / step_deg)


def _intersect(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def octilinear_polygon(poly: list[Point], min_edge: float = 6.0, step_deg: float = 45.0) -> list[Point]:
    """Snap every edge to a multiple of step_deg and rebuild vertices as edge-line intersections."""
    n_dirs = int(360 / step_deg)
    for _ in range(6):
        n = len(poly)
        if n < 3:
            return poly
        lines = []  # (anchor point, direction, dir index, length)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            if a == b:
                continue
            d, k = _snap_dir(b[0] - a[0], b[1] - a[1], step_deg)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            lines.append([mid, d, k, math.dist(a, b)])
        # merge consecutive parallel lines (length-weighted offset)
        merged = []
        for ln in lines:
            if merged and merged[-1][2] == ln[2]:
                m = merged[-1]
                w = m[3] + ln[3]
                m[0] = ((m[0][0] * m[3] + ln[0][0] * ln[3]) / w, (m[0][1] * m[3] + ln[0][1] * ln[3]) / w)
                m[3] = w
            else:
                merged.append(ln)
        if len(merged) > 1 and merged[0][2] == merged[-1][2]:
            m, ln = merged[0], merged.pop()
            w = m[3] + ln[3]
            m[0] = ((m[0][0] * m[3] + ln[0][0] * ln[3]) / w, (m[0][1] * m[3] + ln[0][1] * ln[3]) / w)
            m[3] = w
        # insert a perpendicular connector between anti-parallel neighbours
        fixed = []
        for i, ln in enumerate(merged):
            fixed.append(ln)
            nx = merged[(i + 1) % len(merged)]
            if (nx[2] - ln[2]) % n_dirs == n_dirs // 2:
                k = (ln[2] + n_dirs // 4) % n_dirs
                a = math.radians(k * step_deg)
                d = (round(math.cos(a), 12), round(math.sin(a), 12))
                fixed.append([((ln[0][0] + nx[0][0]) / 2, (ln[0][1] + nx[0][1]) / 2), d, k, 0.0])
        lines = fixed
        verts = []
        for i in range(len(lines)):
            p = _intersect(lines[i - 1][0], lines[i - 1][1], lines[i][0], lines[i][1])
            if p is not None:
                verts.append(p)
        # drop vertices that create tiny edges, then iterate to re-snap
        clean = []
        for v in verts:
            if clean and math.dist(clean[-1], v) < min_edge:
                continue
            clean.append(v)
        if len(clean) > 2 and math.dist(clean[0], clean[-1]) < min_edge:
            clean.pop()
        if clean == poly:
            break
        poly = clean
    return poly


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def octilinearize(contours: list[list[dict]], eps: float = 14.0, min_edge: float = 8.0,
                  min_area: float = 150.0, grid: float = 1.0) -> list[list[dict]]:
    """Rebuild contours with only 0/45/90-degree edges. Keeps contour direction; drops slivers."""
    out = []
    for c in contours:
        poly = flatten(c)
        if len(poly) < 3:
            continue
        sign = 1 if _area(poly) > 0 else -1
        simp = simplify_closed(poly, eps)
        octo = octilinear_polygon(simp, min_edge=min_edge)
        if len(octo) < 3 or abs(_area(octo)) < min_area:
            continue
        if (1 if _area(octo) > 0 else -1) != sign:
            octo = octo[::-1]
        out.append([{"x": round(x / grid) * grid, "y": round(y / grid) * grid, "type": "line"} for x, y in octo])
    return clean_overlaps(out)


# ---------------------------------------------------------------- boolean helpers

def _draw(contours, pen):
    for c in contours:
        pen.beginPath()
        for p in c:
            pen.addPoint((p["x"], p["y"]), segmentType=None if p["type"] == "offcurve" else p["type"])
        pen.endPath()


class _Collect:
    """Minimal point pen that records closed contours as UFO point dicts."""

    def __init__(self):
        self.contours, self._cur = [], None

    def beginPath(self, identifier=None, **kw):
        self._cur = []

    def addPoint(self, pt, segmentType=None, smooth=False, name=None, identifier=None, **kw):
        self._cur.append({"x": round(pt[0], 2), "y": round(pt[1], 2), "type": segmentType or "offcurve"})

    def endPath(self):
        if self._cur:
            self.contours.append(self._cur)
        self._cur = None

    def addComponent(self, *a, **k):
        pass


def clean_overlaps(contours):
    from booleanOperations import BooleanOperationManager
    pen = _Collect()
    mgr = BooleanOperationManager()
    mgr.union(_PathList(contours), pen)
    return pen.contours


class _PathList(list):
    """booleanOperations wants objects with drawPoints(); wrap point lists."""

    def __init__(self, contours):
        super().__init__(_Path(c) for c in contours)


class _Path:
    def __init__(self, pts):
        self.pts = pts

    def drawPoints(self, pen):
        _draw([self.pts], pen)

    def __len__(self):
        return len(self.pts)


def stencil_cut(contours, cuts: Iterable[dict]):
    """Subtract stencil gaps. Each cut: {"x0","y0","x1","y1"} rectangle, optionally "slant": dx shift of the top edge."""
    from booleanOperations import BooleanOperationManager
    shapes = []
    for c in cuts:
        x0, y0, x1, y1 = c["x0"], c["y0"], c["x1"], c["y1"]
        s = c.get("slant", 0)
        shapes.append([{"x": x0, "y": y0, "type": "line"}, {"x": x1, "y": y0, "type": "line"},
                       {"x": x1 + s, "y": y1, "type": "line"}, {"x": x0 + s, "y": y1, "type": "line"}])
    pen = _Collect()
    BooleanOperationManager().difference(_PathList(contours), _PathList(shapes), pen)
    return pen.contours


# ---------------------------------------------------------------- automatic stencil bridges

def _poly(c):
    return [(p["x"], p["y"]) for p in c if p["type"] != "offcurve"]


def _hits_vertical(polys, x):
    ys = []
    for poly in polys:
        n = len(poly)
        for i in range(n):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
            if (x0 <= x < x1) or (x1 <= x < x0):
                ys.append(y0 + (x - x0) * (y1 - y0) / (x1 - x0))
    return sorted(ys)


def _hits_horizontal(polys, y):
    xs = []
    for poly in polys:
        n = len(poly)
        for i in range(n):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return sorted(xs)


def auto_stencil_cuts(contours, gap: float = 22.0, inset: float = None, max_wall: float = 260.0,
                      prefer: str = "vertical", per_hole: int = 1) -> list[dict]:
    """Suggest stencil gaps: for every enclosed counter, slit its thinnest wall.

    Candidates are vertical slits through the wall above/below the counter, placed near the
    counter's left/right edge (where a bowl meets a stem, as in Black Ops One), and horizontal
    slits through the side walls at mid-height. Returns rectangles for stencil_cut().
    """
    polys = [_poly(c) for c in contours]
    if not polys:
        return []
    areas = [_area(p) for p in polys]
    outer_sign = 1 if areas[max(range(len(areas)), key=lambda i: abs(areas[i]))] > 0 else -1
    inset = gap * 1.2 if inset is None else inset
    cuts = []
    for poly, a in zip(polys, areas):
        if (1 if a > 0 else -1) == outer_sign or abs(a) < gap * gap * 2:
            continue  # outer contour, or a counter too small to bother
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        hx0, hx1, hy0, hy1 = min(xs), max(xs), min(ys), max(ys)
        cands = []
        if hx1 - hx0 > 2 * inset:
            for x in (hx0 + inset, hx1 - inset, (hx0 + hx1) / 2):
                hits = _hits_vertical(polys, x)
                top_in = max((y for y in _hits_vertical([poly], x)), default=None)
                bot_in = min((y for y in _hits_vertical([poly], x)), default=None)
                if top_in is not None:
                    above = [y for y in hits if y > top_in + 0.5]
                    if above:
                        w = above[0] - top_in
                        cands.append((w, "v", {"x0": x - gap / 2, "x1": x + gap / 2, "y0": top_in - 2, "y1": above[0] + 2}))
                if bot_in is not None:
                    below = [y for y in hits if y < bot_in - 0.5]
                    if below:
                        w = bot_in - below[-1]
                        cands.append((w, "v", {"x0": x - gap / 2, "x1": x + gap / 2, "y0": below[-1] - 2, "y1": bot_in + 2}))
        if hy1 - hy0 > 2 * inset:
            y = (hy0 + hy1) / 2
            hits = _hits_horizontal(polys, y)
            own = _hits_horizontal([poly], y)
            if own:
                left = [x for x in hits if x < min(own) - 0.5]
                right = [x for x in hits if x > max(own) + 0.5]
                if left:
                    cands.append((min(own) - left[-1], "h", {"x0": left[-1] - 2, "x1": min(own) + 2, "y0": y - gap / 2, "y1": y + gap / 2}))
                if right:
                    cands.append((right[0] - max(own), "h", {"x0": max(own) - 2, "x1": right[0] + 2, "y0": y - gap / 2, "y1": y + gap / 2}))
        cands = [c for c in cands if c[0] <= max_wall]
        if not cands:
            continue
        # thinnest wall wins; preferred direction breaks near-ties (within 15%)
        best = min(c[0] for c in cands)
        near = [c for c in cands if c[0] <= best * 1.15]
        near.sort(key=lambda c: (0 if c[1] == prefer[0] else 1, c[0]))
        cuts += [c[2] for c in near[:per_hole]]
    return cuts


def _ray_exit(polys, origin, d, skip=0.5):
    """Distance along unit axis direction d from origin to the first edge crossing beyond `skip`."""
    best = None
    ox, oy = origin
    for poly in polys:
        n = len(poly)
        for i in range(n):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
            if d[0] != 0:  # horizontal ray: crosses edges spanning oy
                if (y0 <= oy < y1) or (y1 <= oy < y0):
                    x = x0 + (oy - y0) * (x1 - x0) / (y1 - y0)
                    t = (x - ox) * d[0]
            else:
                if (x0 <= ox < x1) or (x1 <= ox < x0):
                    y = y0 + (ox - x0) * (y1 - y0) / (x1 - x0)
                    t = (y - oy) * d[1]
                else:
                    continue
            if d[0] != 0 and not ((y0 <= oy < y1) or (y1 <= oy < y0)):
                continue
            if t > skip and (best is None or t < best):
                best = t
    return best


def auto_junction_cuts(contours, gap: float = 22.0, min_wall: float = 40.0, max_wall: float = 170.0,
                       max_cuts: int = 2, min_height: float = 250.0, spacing: float = 80.0,
                       prefer_vertical: float = 0.85, min_piece: float = 12000.0) -> list[dict]:
    """Black Ops-style junction gaps: at inside right-angle corners, slit the joining stroke
    along the stem's edge (e.g. detach an L's foot from its stem). Returns stencil_cut() rectangles."""
    polys = [_poly(c) for c in contours]
    if not polys:
        return []
    ys = [p[1] for poly in polys for p in poly]
    if max(ys) - min(ys) < min_height:
        return []  # marks and small signs stay solid
    areas = [_area(p) for p in polys]
    outer_sign = 1 if areas[max(range(len(areas)), key=lambda i: abs(areas[i]))] > 0 else -1
    cands = []
    for poly, a in zip(polys, areas):
        n = len(poly)
        sign = 1 if a > 0 else -1
        for i in range(n):
            p0, v, p1 = poly[i - 1], poly[i], poly[(i + 1) % n]
            e1 = (v[0] - p0[0], v[1] - p0[1])
            e2 = (p1[0] - v[0], p1[1] - v[1])
            if not ((e1[0] == 0) ^ (e1[1] == 0)) or not ((e2[0] == 0) ^ (e2[1] == 0)):
                continue  # both edges must be axis-aligned
            cross = e1[0] * e2[1] - e1[1] * e2[0]
            if cross == 0 or (1 if cross > 0 else -1) == sign:
                continue  # convex corner
            u1 = (int(math.copysign(1, e1[0])) if e1[0] else 0, int(math.copysign(1, e1[1])) if e1[1] else 0)
            u2 = (int(math.copysign(1, e2[0])) if e2[0] else 0, int(math.copysign(1, e2[1])) if e2[1] else 0)
            # A: continue e1 through the material, band offset toward e2
            # B: continue -e2 through the material, band offset toward -e1
            for d, off in ((u1, u2), ((-u2[0], -u2[1]), (-u1[0], -u1[1]))):
                t = _ray_exit(polys, v, d)
                if t is None or not (min_wall <= t <= max_wall):
                    continue
                end = (v[0] + d[0] * (t + 2), v[1] + d[1] * (t + 2))
                start = (v[0] - d[0] * 2, v[1] - d[1] * 2)
                o2 = (v[0] + off[0] * gap, v[1] + off[1] * gap)
                xs = [start[0], end[0], o2[0] if d[0] == 0 else start[0]]
                yy = [start[1], end[1], o2[1] if d[1] == 0 else start[1]]
                rect = {"x0": min(xs), "x1": max(xs), "y0": min(yy), "y1": max(yy)}
                vertical = d[0] == 0
                score = t * (prefer_vertical if vertical else 1.0)
                cands.append((score, v, rect))
    cands.sort(key=lambda c: c[0])
    chosen = []
    for score, v, rect in cands:
        if len(chosen) >= max_cuts:
            break
        if any(math.dist(v, cv) < spacing for cv, _ in chosen):
            continue
        before = stencil_cut(contours, [r for _, r in chosen]) if chosen else contours
        test = stencil_cut(contours, [r for _, r in chosen] + [rect])
        # reject cuts that would leave a tiny floating piece
        if any(abs(_area(_poly(c))) < min_piece for c in test if len(c) > 2 and _area(_poly(c)) * _area(_poly(contours[0])) > 0):
            continue
        # a real stencil gap changes topology (splits a piece or opens a counter); a nick doesn't
        if _topology(before) == _topology(test):
            continue
        chosen.append((v, rect))
    return [r for _, r in chosen]


def _topology(contours):
    """(pieces, holes) of a glyph, by contour orientation relative to the largest contour."""
    polys = [_poly(c) for c in contours if len(c) > 2]
    if not polys:
        return (0, 0)
    areas = [_area(p) for p in polys]
    outer = 1 if areas[max(range(len(areas)), key=lambda i: abs(areas[i]))] > 0 else -1
    pieces = sum(1 for a in areas if (1 if a > 0 else -1) == outer)
    return (pieces, len(areas) - pieces)


# ---------------------------------------------------------------- weight

def embolden_x(contours, d: float, stretch: float = 64.0, precision: int = 16, keep_counters: bool = True):
    """Thicken stems horizontally by d per side, leaving horizontal bars' thickness unchanged.

    Anisotropic offset: stretch y by `stretch`, mitre-offset by d, squash back. Vertical edges move
    d, horizontal edges move only d/stretch, 45-degree edges stay at 45 degrees. Counters narrow by 2d
    (tiny counters can close: check proofs). Returns UFO-style line contours.
    keep_counters: grow only the outer contours and keep enclosed counters at their original size,
    so small Lao loops (in letters such as ຄ ຍ ອ) stay open.
    """
    import pyclipper
    if not contours or d == 0:
        return contours
    holes = []
    if keep_counters:
        polys = [_poly(c) for c in contours]
        areas = [_area(q) for q in polys]
        outer = 1 if areas[max(range(len(areas)), key=lambda i: abs(areas[i]))] > 0 else -1
        holes = [c for c, a in zip(contours, areas) if (1 if a > 0 else -1) != outer]
        contours = [c for c, a in zip(contours, areas) if (1 if a > 0 else -1) == outer]
    sx, sy = precision, precision * stretch
    paths = [[(int(round(p["x"] * sx)), int(round(p["y"] * sy))) for p in c if p["type"] != "offcurve"]
             for c in contours]
    co = pyclipper.PyclipperOffset(miter_limit=8.0)
    co.AddPaths(paths, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    out = co.Execute(d * sx)
    res = []
    for path in out:
        pts = []
        for x, y in path:
            p = (round(x / sx, 1), round(y / sy))
            if not pts or pts[-1] != p:
                pts.append(p)
        if len(pts) > 2 and pts[0] == pts[-1]:
            pts.pop()
        # drop collinear vertices introduced by rounding
        clean = []
        for i, p in enumerate(pts):
            a, b = pts[i - 1], pts[(i + 1) % len(pts)]
            if (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0]) != 0:
                clean.append(p)
        if len(clean) > 2:
            res.append([{"x": x, "y": y, "type": "line"} for x, y in clean])
    grown = clean_overlaps(res)
    if not holes:
        return grown
    # cut the original counters back out (as filled shapes, whatever their stored direction)
    filled = [c if _area(_poly(c)) * _area(_poly(grown[0])) > 0 else c[::-1] for c in holes]
    return clean_overlaps(stencil_cut_shapes(grown, filled))


def stencil_cut_shapes(contours, shapes):
    """Subtract arbitrary closed shapes from contours."""
    from booleanOperations import BooleanOperationManager
    pen = _Collect()
    BooleanOperationManager().difference(_PathList(contours), _PathList(shapes), pen)
    return pen.contours


def translate(contours, dx: float = 0, dy: float = 0):
    return [[{**p, "x": p["x"] + dx, "y": p["y"] + dy} for p in c] for c in contours]
