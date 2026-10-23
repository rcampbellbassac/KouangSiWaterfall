"""Build a multi-script display family (Lao + Thai + Khmer + Latin) from a pen recipe.

A family spec (JSON):
  {"name": "Champa Script", "slug": "ChampaScript", "version": "0.100",
   "bases": {"lao": "lao-looped", "thai": "thai-looped", "khmer": "khmer", "latin": "latin"},
   "wght": 100, "recipe": [...pen steps...], "per_script": {"khmer": {"wght": 150}}}
Each script part keeps Noto's OpenType layout; outlines come from pen.apply_recipe; anchors move
with the outlines. Parts are merged with fontTools.merge.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.merge import Merger
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from . import offline, pen

REF = Path.home() / "Fonts/reference"
BASES = {
    "lao": REF / "lao/google/notosanslao/NotoSansLao[wdth,wght].ttf",
    "lao-looped": REF / "lao/google/notosanslaolooped/NotoSansLaoLooped[wdth,wght].ttf",
    "lao-serif": REF / "lao/google/notoseriflao/NotoSerifLao[wdth,wght].ttf",
    "thai": REF / "google-base/notosansthai/NotoSansThai[wdth,wght].ttf",
    "thai-looped": REF / "google-base/notosansthailooped/NotoSansThaiLooped[wdth,wght].ttf",
    "thai-serif": REF / "google-base/notoserifthai/NotoSerifThai[wdth,wght].ttf",
    "khmer": REF / "google-base/notosanskhmer/NotoSansKhmer[wdth,wght].ttf",
    "khmer-serif": REF / "google-base/notoserifkhmer/NotoSerifKhmer[wdth,wght].ttf",
    "latin": REF / "google-base/notosans/NotoSans[wdth,wght].ttf",
    "math": REF / "google-base/notosansmath/NotoSansMath-Regular.ttf",
    "symbols2": REF / "google-base/notosanssymbols2/NotoSansSymbols2-Regular.ttf",
}
UNICODES = {
    "lao": list(range(0x0E80, 0x0F00)) + [0x25CC, 0x200B, 0x200C, 0x200D],
    "thai": list(range(0x0E01, 0x0E5C)) + [0x25CC, 0x200B, 0x200C, 0x200D],
    "khmer": list(range(0x1780, 0x1800)) + list(range(0x19E0, 0x1A00)) + [0x25CC, 0x200B, 0x200C, 0x200D],
    # Latin, combining marks, punctuation, spaces, super/subscripts, currencies, letterlike, number forms
    "latin": (list(range(0x20, 0x7F)) + list(range(0xA0, 0x250)) + [0x02BC, 0x02C6, 0x02C7, 0x02D8, 0x02D9, 0x02DA, 0x02DB, 0x02DC, 0x02DD]
              + list(range(0x0300, 0x0370)) + list(range(0x1E00, 0x1F00)) + list(range(0x2000, 0x2070))
              + list(range(0x2070, 0x20A0)) + list(range(0x20A0, 0x20C1)) + list(range(0x2100, 0x2190)) + [0x0394, 0x03A9, 0x03BC, 0x03C0, 0xFEFF, 0xFFFD]),
    # practical math, arrows and geometric symbols (from Noto Sans Math, thinned to match the pen)
    "symbols": list(range(0x2190, 0x2200)) + list(range(0x2200, 0x2300)) + list(range(0x2300, 0x2310))
               + list(range(0x25A0, 0x2600)) + [0x2605, 0x2606, 0x2713, 0x2717],
    "dingbats": [0x2605, 0x2606, 0x2713, 0x2717, 0x25CF],
}
ORDER = ["latin", "symbols", "dingbats", "lao", "thai", "khmer"]  # first font wins cmap conflicts
PART_BASE = {"symbols": "math", "dingbats": "symbols2"}
PRE_THIN = {"math": -25.0, "symbols2": -25.0}  # static Regular fonts: thin strokes before the pen


def _instance(path: Path, wght: float, wdth: float = 100) -> TTFont:
    vf = TTFont(path)
    if "fvar" not in vf:
        return vf
    axes = {a.axisTag: a for a in vf["fvar"].axes}
    loc = {"wght": max(axes["wght"].minValue, min(axes["wght"].maxValue, wght))}
    if "wdth" in axes:
        loc["wdth"] = max(axes["wdth"].minValue, min(axes["wdth"].maxValue, wdth))
    return instancer.instantiateVariableFont(vf, loc)


def _subset(tt: TTFont, unicodes, text=None):
    o = subset.Options()
    o.layout_features = ["*"]
    o.name_IDs = ["*"]
    o.glyph_names = True
    o.notdef_outline = True
    o.hinting = False
    o.drop_tables += ["DSIG", "gasp", "STAT", "fvar", "gvar", "avar", "HVAR", "MVAR", "cvar", "meta", "MATH", "vhea", "vmtx", "VORG"]
    s = subset.Subsetter(o)
    if text:
        s.populate(text=text)
    else:
        s.populate(unicodes=unicodes)
    s.subset(tt)
    return tt


def _tt_glyph(polys):
    p = TTGlyphPen(None)
    for poly in polys:
        if len(poly) < 3:
            continue
        p.moveTo(poly[0])
        for pt in poly[1:]:
            p.lineTo(pt)
        p.closePath()
    return p.glyph()


MID_Y = 265  # anchors above this attach marks above the letter, below it marks underneath


def transform_anchors(tt: TTFont, xf: dict):
    """xf[glyph] = (dx, k, gy). Attachment anchors on bases, ligatures and mark-bearing marks move
    away from the body by 2*gy (the pen thickened both the letter and the mark by gy), then
    x' = x + dx + k*y. Anchors on the attaching mark itself only get the shift and slant."""
    if "GPOS" not in tt:
        return

    def mv(a, g, attach_point=False):
        if a is None or g not in xf:
            return
        dx, k, gy = xf[g]
        y = a.YCoordinate
        if attach_point and gy:
            y = y + 2 * gy if y > MID_Y else y - 2 * gy
            a.YCoordinate = int(round(y))
        a.XCoordinate = int(round(a.XCoordinate + dx + k * y))

    for lookup in tt["GPOS"].table.LookupList.Lookup:
        for st in lookup.SubTable:
            t = lookup.LookupType
            if t == 9:
                t, st = st.ExtensionLookupType, st.ExtSubTable
            if t in (4, 5):
                for g, rec in zip(st.MarkCoverage.glyphs, st.MarkArray.MarkRecord):
                    mv(rec.MarkAnchor, g)
            if t == 4:
                for g, rec in zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord):
                    for a in rec.BaseAnchor:
                        mv(a, g, True)
            elif t == 5:
                for g, att in zip(st.LigatureCoverage.glyphs, st.LigatureArray.LigatureAttach):
                    for comp in att.ComponentRecord:
                        for a in comp.LigatureAnchor:
                            mv(a, g, True)
            elif t == 6:
                for g, rec in zip(st.Mark1Coverage.glyphs, st.Mark1Array.MarkRecord):
                    mv(rec.MarkAnchor, g)
                for g, rec in zip(st.Mark2Coverage.glyphs, st.Mark2Array.Mark2Record):
                    for a in rec.Mark2Anchor:
                        mv(a, g, True)
            elif t == 1:  # single adjustment: contextual mark nudges (e.g. Lao tone mark over nikhahit)
                glyphs = st.Coverage.glyphs
                values = [st.Value] * len(glyphs) if st.Format == 1 else st.Value
                done = set()
                for g, v in zip(glyphs, values):
                    if v is None or id(v) in done or g not in xf:
                        continue
                    done.add(id(v))
                    dx, k, gy = xf[g]
                    yp = getattr(v, "YPlacement", 0) or 0
                    if yp and gy:
                        v.YPlacement = int(round(yp + (2 * gy if yp > 0 else -2 * gy)))
                        if k and hasattr(v, "XPlacement"):
                            v.XPlacement = int(round((v.XPlacement or 0) + k * (v.YPlacement - yp)))
            elif t == 3:
                for g, rec in zip(st.Coverage.glyphs, st.EntryExitRecord):
                    mv(rec.EntryAnchor, g)
                    mv(rec.ExitAnchor, g)


def build_part(script: str, spec: dict, text: str | None = None) -> TTFont:
    ps = {**spec, **spec.get("per_script", {}).get(script, {})}
    base_key = PART_BASE.get(script) or spec["bases"][script]
    tt = _instance(BASES[base_key], ps.get("wght", 100), ps.get("wdth", 100))
    _subset(tt, UNICODES[script], text)
    glyf, hmtx = tt["glyf"], tt["hmtx"]
    gs = tt.getGlyphSet()
    xf = {}
    recipe = ps["recipe"]
    if base_key in PRE_THIN:
        recipe = [{"op": "offset", "d": PRE_THIN[base_key], "join": "miter"}] + recipe
    # read every original outline first: composites (e.g. Lao nikhahit + tone ligatures) must be
    # drawn from untouched components, not from components the pen already thickened
    sources = {}
    for name in tt.getGlyphOrder():
        if name == ".notdef":
            continue
        pc = offline._UFOPointCollector(gs)
        gs[name].draw(pc)
        sources[name] = pc.contours
    for name, contours in sources.items():
        adv = hmtx[name][0]
        if not contours:
            continue
        polys = pen.from_ufo_points(contours)
        if adv == 0:  # marks: keep stacked pieces (nikhahit + tone ligatures) apart
            polys, info = pen.apply_recipe_stacked(polys, recipe, seed=f"{spec['slug']}/{name}")
        else:
            polys, info = pen.apply_recipe(polys, recipe, seed=f"{spec['slug']}/{name}")
        dx = 0.0
        if adv > 0:
            dx = info["grow_left"]
            polys = [[(x + dx, y) for x, y in p] for p in polys]
            adv = int(round(adv + info["grow_left"] + info["grow_right"] + ps.get("tracking", 0)))
        g = _tt_glyph(polys)
        glyf[name] = g
        g.recalcBounds(glyf)
        hmtx[name] = (adv, getattr(g, "xMin", 0))
        xf[name] = (dx, info["shear"], info["grow_y"])
    # empty spacing glyphs (space etc.) widen with the pen too
    grow = None
    for name in tt.getGlyphOrder():
        if name not in xf and hmtx[name][0] > 0:
            if grow is None:
                _, grow = pen.apply_recipe([[(0, 0), (10, 0), (10, 10), (0, 10)]], recipe, seed="space")
            hmtx[name] = (int(round(hmtx[name][0] + (grow["grow_left"] + grow["grow_right"]) / 2)), 0)
    transform_anchors(tt, xf)
    _normalize_for_merge(tt)
    if ps.get("scale") and ps["scale"] != 1:
        _uniform_scale(tt, ps["scale"])
    return tt


def _uniform_scale(tt: TTFont, s: float):
    """Scale every coordinate (outlines, metrics, GPOS) by s, keeping unitsPerEm."""
    from fontTools.ttLib.scaleUpem import scale_upem
    upm = tt["head"].unitsPerEm
    scale_upem(tt, int(round(upm * s)))
    tt["head"].unitsPerEm = upm


def _normalize_for_merge(tt: TTFont):
    """Make parts merge-compatible: OS/2 version 4 (drop v5 optical size fields), post format 2."""
    os2 = tt["OS/2"]
    if os2.version > 4:
        os2.version = 4
        for attr in ("usLowerOpticalPointSize", "usUpperOpticalPointSize"):
            if hasattr(os2, attr):
                delattr(os2, attr)
    tt["post"].formatType = 2.0


def add_missing_spaces(tt: TTFont):
    """Map standard spaces and zero-width controls the parts didn't provide (empty glyphs)."""
    upm = tt["head"].unitsPerEm
    widths = {0x2000: upm // 2, 0x2001: upm, 0x2002: upm // 2, 0x2003: upm, 0x2004: upm // 3, 0x2005: upm // 4,
              0x2006: upm // 6, 0x2008: upm // 4, 0x2009: upm // 5, 0x200A: upm // 10, 0x202F: upm // 5, 0x205F: (upm * 4) // 18}
    zero = [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF]
    cmap_tables = [t for t in tt["cmap"].tables if t.isUnicode()]
    have = tt.getBestCmap()
    if 0x2007 not in have and 0x30 in have:
        widths[0x2007] = tt["hmtx"][have[0x30]][0]
    order = tt.getGlyphOrder()
    added = []
    for cp, w in [(c, widths[c]) for c in widths] + [(c, 0) for c in zero]:
        if cp in have:
            continue
        name = f"uni{cp:04X}"
        if name not in tt["glyf"]:
            tt["glyf"][name] = TTGlyphPen(None).glyph()
            tt["hmtx"][name] = (w, 0)
            order.append(name)
        for t in cmap_tables:
            if t.format in (4, 12) or cp < 0x10000:
                t.cmap[cp] = name
        added.append(cp)
    tt.setGlyphOrder(order)
    if "post" in tt and hasattr(tt["post"], "extraNames"):
        pass
    return added


def build_family(spec: dict, out_dir: Path, text: str | None = None, scripts=None) -> Path:
    scripts = scripts or ORDER
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for sc in [s for s in ORDER if s in scripts]:
            part = build_part(sc, spec, text)
            p = Path(d) / f"{sc}.ttf"
            part.save(p)
            paths.append(str(p))
        merged = Merger().merge(paths) if len(paths) > 1 else TTFont(paths[0])
    add_missing_spaces(merged)
    finish(merged, spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{spec['slug']}-Regular.ttf"
    merged.save(out)
    return out


def finish(tt: TTFont, spec: dict):
    name, slug, version = spec["name"], spec["slug"], spec.get("version", "0.100")
    nt = tt["name"]
    nt.names = []
    copyright_ = spec.get("copyright") or (
        "Copyright 2026 Robert Martin Campbell. Derived from Noto Sans Lao Looped, Noto Sans Thai Looped, "
        "Noto Sans Khmer and Noto Sans (Copyright 2022 The Noto Project Authors).")
    for nid, val in {0: copyright_, 1: name, 2: "Regular", 3: f"{version};NONE;{slug}-Regular",
                     4: f"{name} Regular", 5: f"Version {version}", 6: f"{slug}-Regular",
                     9: "Robert Martin Campbell",
                     13: "This Font Software is licensed under the SIL Open Font License, Version 1.1.",
                     14: "https://openfontlicense.org"}.items():
        nt.setName(val, nid, 3, 1, 0x409)
    tt["head"].fontRevision = float(version)
    glyf = tt["glyf"]
    ymax = max(getattr(glyf[g], "yMax", 0) for g in tt.getGlyphOrder())
    ymin = min(getattr(glyf[g], "yMin", 0) for g in tt.getGlyphOrder())
    os2, hhea = tt["OS/2"], tt["hhea"]
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 1069, -400, 0
    os2.usWinAscent, os2.usWinDescent = max(ymax, 1069), max(-ymin, 400)
    hhea.ascent, hhea.descent, hhea.lineGap = os2.usWinAscent, -os2.usWinDescent, 0
    os2.fsSelection |= 1 << 7
    os2.achVendID = "NONE"
    tt["post"].formatType = 2.0


if __name__ == "__main__":
    import sys
    spec = json.loads(Path(sys.argv[1]).read_text())
    print(build_family(spec, Path(sys.argv[2])))
