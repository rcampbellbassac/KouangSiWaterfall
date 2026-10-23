"""Offline font tooling (no FontLab needed): inspect, shape, render and compare fonts.

Everything here works on built font files (.ttf/.otf/.ttc/.woff2) or on UFO
sources, which are compiled to a temporary TTF first.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

import uharfbuzz as hb
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFont

REFERENCE_ROOT = Path(os.environ.get("FONTLAB_MCP_REFERENCES", "~/Fonts/reference")).expanduser()
WORK_ROOT = Path(os.environ.get("FONTLAB_MCP_WORK", "~/Fonts/work")).expanduser()
CACHE = Path("~/.cache/fontlab-mcp").expanduser()
LABEL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Lao block (U+0E80-U+0EFF). "core" = modern Lao orthography; "extended" adds
# Pali/Sanskrit (Unicode 12/13) and Khmu letters.
LAO_CORE = (
    [0x0E81, 0x0E82, 0x0E84, 0x0E87, 0x0E88, 0x0E8A, 0x0E8D]
    + list(range(0x0E94, 0x0E98)) + list(range(0x0E99, 0x0EA0)) + [0x0EA1, 0x0EA2, 0x0EA3, 0x0EA5, 0x0EA7, 0x0EAA, 0x0EAB]
    + list(range(0x0EAD, 0x0EBA)) + [0x0EBB, 0x0EBC, 0x0EBD]
    + list(range(0x0EC0, 0x0EC5)) + [0x0EC6] + list(range(0x0EC8, 0x0ECE))
    + list(range(0x0ED0, 0x0EDA)) + [0x0EDC, 0x0EDD]
)
LAO_EXTENDED = sorted(set(LAO_CORE) | {0x0E86, 0x0E89, 0x0E8C, 0x0E8E, 0x0E8F, 0x0E90, 0x0E91, 0x0E92,
                                        0x0E93, 0x0E98, 0x0EA0, 0x0EA8, 0x0EA9, 0x0EAC, 0x0EBA,
                                        0x0ECE, 0x0EDE, 0x0EDF})
LAO_MARKS = [0x0EB1, 0x0EB4, 0x0EB5, 0x0EB6, 0x0EB7, 0x0EB8, 0x0EB9, 0x0EBA, 0x0EBB, 0x0EBC,
             0x0EC8, 0x0EC9, 0x0ECA, 0x0ECB, 0x0ECC, 0x0ECD, 0x0ECE]

SAMPLES = {
    "pangram": "ສະບາຍດີ ພາສາລາວ ຂ້ອຍຮັກເຈົ້າ ໜັງສືພິມ ຫຼວງພະບາງ",
    "display": "ນ້ຳຕົກຕາດກວາງຊີ",
    "consonants": "ກ ຂ ຄ ງ ຈ ສ ຊ ຍ ດ ຕ ຖ ທ ນ ບ ປ ຜ ຝ ພ ຟ ມ ຢ ຣ ລ ວ ຫ ອ ຮ ໜ ໝ ຫຼ",
    "vowels": "ກະ ກາ ກິ ກີ ກຶ ກື ກຸ ກູ ເກ ແກ ໂກ ເກາະ ກໍ ເກີ ເກຍ ເກືອ ກົວ ໄກ ໃກ ກຳ ເກົາ",
    "stacking": "ກິ່ ກີ້ ກຶ໊ ກື໋ ກຸ່ ກູ້ ກົ່ ກັ້ ກໍ່ ປີ່ ຝັ້ ຟື້ ຢູ່ ຍຸ ຽ ກ່ຳ ນ້ຳ ຂົ້ວ ເຂົ້າ ປິ່ນ ຟ້າ",
    "digits": "໐໑໒໓໔໕໖໗໘໙ 0123456789",
    "latin": "Hamburgefonstiv 0123456789",
}


# ---------------------------------------------------------------- font loading

def _ufo_to_ttf(ufo: Path) -> Path:
    """Compile a UFO to a cached TTF (keyed on source mtimes) so it can be rendered."""
    stamp = hashlib.sha1()
    for p in sorted(ufo.rglob("*")):
        if p.is_file():
            stamp.update(f"{p.relative_to(ufo)}:{p.stat().st_mtime_ns}".encode())
    out = CACHE / "ufo-builds" / f"{ufo.stem}-{stamp.hexdigest()[:12]}.ttf"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        import ufo2ft
        import ufoLib2
        font = ufoLib2.Font.open(ufo)
        ttf = ufo2ft.compileTTF(font, removeOverlaps=True)
        ttf.save(out)
    return out


def font_path(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.suffix.lower() == ".ufo" and p.is_dir():
        return _ufo_to_ttf(p)
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def open_ttfont(path: str | Path, index: int = 0) -> TTFont:
    p = font_path(path)
    if p.suffix.lower() in (".ttc", ".otc"):
        return TTCollection(p).fonts[index]
    return TTFont(p, fontNumber=index if p.suffix.lower() in (".ttc", ".otc") else -1)


def _name(font: TTFont, *ids: int) -> str | None:
    for i in ids:
        rec = font["name"].getDebugName(i)
        if rec:
            return rec
    return None


# ---------------------------------------------------------------- inspection

def font_info(path: str | Path, index: int = 0) -> dict:
    f = open_ttfont(path, index)
    cmap = f.getBestCmap() or {}
    os2 = f["OS/2"] if "OS/2" in f else None
    head, hhea = f["head"], f["hhea"]
    gsub = sorted({fr.FeatureTag for fr in f["GSUB"].table.FeatureList.FeatureRecord}) if "GSUB" in f and f["GSUB"].table.FeatureList else []
    gpos = sorted({fr.FeatureTag for fr in f["GPOS"].table.FeatureList.FeatureRecord}) if "GPOS" in f and f["GPOS"].table.FeatureList else []
    scripts = set()
    for tag in ("GSUB", "GPOS"):
        if tag in f and f[tag].table.ScriptList:
            scripts |= {sr.ScriptTag for sr in f[tag].table.ScriptList.ScriptRecord}
    info = {
        "path": str(path),
        "family": _name(f, 16, 1),
        "style": _name(f, 17, 2),
        "full_name": _name(f, 4),
        "version": _name(f, 5),
        "designer": _name(f, 9),
        "manufacturer": _name(f, 8),
        "license": (_name(f, 13) or "")[:300] or None,
        "license_url": _name(f, 14),
        "units_per_em": head.unitsPerEm,
        "glyph_count": len(f.getGlyphOrder()),
        "outline_format": "CFF" if "CFF " in f or "CFF2" in f else "TrueType",
        "variable_axes": [
            {"tag": a.axisTag, "min": a.minValue, "default": a.defaultValue, "max": a.maxValue}
            for a in f["fvar"].axes] if "fvar" in f else [],
        "metrics": {
            "ascender": hhea.ascent, "descender": hhea.descent, "line_gap": hhea.lineGap,
            "x_height": getattr(os2, "sxHeight", None) if os2 else None,
            "cap_height": getattr(os2, "sCapHeight", None) if os2 else None,
            "win_ascent": getattr(os2, "usWinAscent", None) if os2 else None,
            "win_descent": getattr(os2, "usWinDescent", None) if os2 else None,
            "weight_class": getattr(os2, "usWeightClass", None) if os2 else None,
            "width_class": getattr(os2, "usWidthClass", None) if os2 else None,
        },
        "opentype": {"scripts": sorted(scripts), "gsub_features": gsub, "gpos_features": gpos},
        "lao": lao_coverage_from_cmap(cmap),
        "codepoints": len(cmap),
    }
    return info


def lao_coverage_from_cmap(cmap: dict) -> dict:
    have = set(cmap)
    core_missing = [c for c in LAO_CORE if c not in have]
    ext_missing = [c for c in LAO_EXTENDED if c not in have]
    return {
        "core_total": len(LAO_CORE),
        "core_present": len(LAO_CORE) - len(core_missing),
        "core_missing": [f"U+{c:04X} {chr(c)}" for c in core_missing],
        "extended_total": len(LAO_EXTENDED),
        "extended_present": len(LAO_EXTENDED) - len(ext_missing),
        "extended_missing": [f"U+{c:04X} {chr(c)}" for c in ext_missing],
    }


def shape(path: str | Path, text: str, features: dict | None = None, variations: dict | None = None,
          index: int = 0) -> dict:
    """Shape text with HarfBuzz; returns glyph names, clusters, advances and offsets (font units)."""
    p = font_path(path)
    blob = hb.Blob.from_file_path(str(p))
    face = hb.Face(blob, index)
    font = hb.Font(face)
    if variations:
        font.set_variations(variations)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, features or {})
    tt = open_ttfont(p, index)
    order = tt.getGlyphOrder()
    glyphs = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        glyphs.append({
            "glyph": order[info.codepoint] if info.codepoint < len(order) else info.codepoint,
            "cluster": info.cluster,
            "x_advance": pos.x_advance, "y_advance": pos.y_advance,
            "x_offset": pos.x_offset, "y_offset": pos.y_offset,
        })
    notdef = sum(1 for g in glyphs if g["glyph"] == ".notdef")
    return {"script": buf.script, "direction": buf.direction, "glyphs": glyphs, "missing_glyphs": notdef,
            "total_advance": sum(g["x_advance"] for g in glyphs)}


def mark_collisions(path: str | Path, text: str | None = None, index: int = 0) -> dict:
    """Heuristic check of Lao above/below mark placement.

    For each cluster with stacked marks, compares the bounding boxes of the base
    and its marks after shaping and flags overlaps or marks that sit unusually
    far from the base. A starting point for review, not a verdict.
    """
    from fontTools.pens.boundsPen import BoundsPen
    text = text or SAMPLES["stacking"]
    shaped = shape(path, text, index=index)
    tt = open_ttfont(path, index)
    gs = tt.getGlyphSet()
    upm = tt["head"].unitsPerEm
    boxes, x = [], 0
    for g in shaped["glyphs"]:
        pen = BoundsPen(gs)
        try:
            gs[g["glyph"]].draw(pen)
        except KeyError:
            pen.bounds = None
        b = pen.bounds
        if b:
            ox, oy = x + g["x_offset"], g["y_offset"]
            boxes.append((g, (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy)))
        else:
            boxes.append((g, None))
        x += g["x_advance"]
    issues = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            gi, bi = boxes[i]
            gj, bj = boxes[j]
            if not bi or not bj or gi["cluster"] != gj["cluster"]:
                continue
            ox = min(bi[2], bj[2]) - max(bi[0], bj[0])
            oy = min(bi[3], bj[3]) - max(bi[1], bj[1])
            if ox > upm * 0.02 and oy > upm * 0.02:
                issues.append({"cluster": gi["cluster"], "text": _cluster_text(text, gi["cluster"]),
                               "a": gi["glyph"], "b": gj["glyph"], "overlap_units": [round(ox), round(oy)]})
    return {"checked_glyphs": len(boxes), "overlaps": issues}


def _cluster_text(text: str, cluster: int) -> str:
    end = cluster + 1
    while end < len(text) and 0x0EB0 <= ord(text[end]) <= 0x0ECE and text[end] not in "ະາຳ":
        end += 1
    return text[cluster:end]


# ---------------------------------------------------------------- rendering

def _pil_font(path: str | Path, size: int, index: int = 0, variations: dict | None = None):
    f = ImageFont.truetype(str(font_path(path)), size=size, index=index, layout_engine=ImageFont.Layout.RAQM)
    if variations:
        try:
            f.set_variation_by_axes([variations.get(a["tag"], a["default"]) for a in _axes(path, index)])
        except Exception:
            pass
    return f


def _axes(path, index=0):
    tt = open_ttfont(path, index)
    return [{"tag": a.axisTag, "default": a.defaultValue} for a in tt["fvar"].axes] if "fvar" in tt else []


def render_text(path: str | Path, text: str, size: int = 96, width: int | None = None, index: int = 0,
                variations: dict | None = None, guides: bool = True, padding: int = 24,
                fg=(20, 20, 20), bg=(255, 255, 255)) -> Image.Image:
    """Render (multi-line) text with full Lao shaping. Optional metric guide lines."""
    font = _pil_font(path, size, index, variations)
    lines = text.split("\n")
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + size // 4
    widths = [font.getbbox(l or " ", language="lo")[2] for l in lines]
    w = width or max(widths) + padding * 2
    h = line_h * len(lines) + padding * 2
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    tt = open_ttfont(path, index)
    upm = tt["head"].unitsPerEm
    os2 = tt["OS/2"] if "OS/2" in tt else None
    for n, line in enumerate(lines):
        base = padding + n * line_h + ascent
        if guides:
            d.line([(0, base), (w, base)], fill=(120, 170, 255), width=1)
            for val, col in ((getattr(os2, "sxHeight", 0), (255, 180, 120)), (getattr(os2, "sCapHeight", 0), (200, 200, 200))):
                if val:
                    y = base - val * size / upm
                    d.line([(0, y), (w, y)], fill=col, width=1)
        d.text((padding, base), line, font=font, fill=fg, anchor="ls", language="lo")
    return img


def _label_font(size=14):
    try:
        return ImageFont.truetype(LABEL_FONT, size)
    except OSError:
        return ImageFont.load_default()


def specimen(paths: Iterable[str | Path], text: str, size: int = 72, width: int = 1600,
             labels: Iterable[str] | None = None, variations: dict | None = None) -> Image.Image:
    """Stack the same text rendered in several fonts, labelled, for side-by-side comparison."""
    paths = list(paths)
    labels = list(labels) if labels else [None] * len(paths)
    rows = []
    for p, label in zip(paths, labels):
        try:
            info = font_info(p)
            label = label or f"{info['family']} {info['style'] or ''}".strip()
            row = render_text(p, text, size=size, width=width, variations=variations, guides=False)
        except Exception as e:  # keep going; show the failure in the sheet
            row = Image.new("RGB", (width, size), (255, 235, 235))
            ImageDraw.Draw(row).text((10, 10), f"{p}: {e}", fill=(160, 0, 0), font=_label_font())
            label = label or str(p)
        rows.append((label, row))
    lf = _label_font(15)
    total_h = sum(r.height + 26 for _, r in rows)
    sheet = Image.new("RGB", (width, total_h), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    y = 0
    for label, row in rows:
        d.text((12, y + 5), label, fill=(90, 90, 90), font=lf)
        sheet.paste(row, (0, y + 24))
        y += row.height + 26
        d.line([(0, y - 1), (width, y - 1)], fill=(225, 225, 225))
    return sheet


def glyph_grid(path: str | Path, codepoints: Iterable[int] | None = None, cell: int = 110, cols: int = 12,
               index: int = 0) -> Image.Image:
    """Grid of individual characters (default: Lao core set) with codepoint labels; missing = red cell."""
    cps = list(codepoints or LAO_CORE)
    tt = open_ttfont(path, index)
    cmap = tt.getBestCmap() or {}
    font = _pil_font(path, int(cell * 0.5), index)
    lf = _label_font(11)
    rows = (len(cps) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, cp in enumerate(cps):
        x, y = (i % cols) * cell, (i // cols) * cell
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(220, 220, 220),
                    fill=(255, 255, 255) if cp in cmap else (255, 225, 225))
        ch = chr(cp)
        s = ("◌" + ch) if cp in LAO_MARKS else ch  # show marks on a dotted circle
        if cp in cmap:
            d.text((x + cell / 2, y + cell * 0.62), s, font=font, fill=(20, 20, 20), anchor="ms", language="lo")
        d.text((x + 4, y + cell - 15), f"{cp:04X}", fill=(130, 130, 130), font=lf)
    return img


def png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- reference library

def reference_fonts(query: str | None = None, script: str | None = "lao") -> list[dict]:
    """Catalog of reference fonts under ~/Fonts/reference (cached by mtime)."""
    idx_file = CACHE / "reference-index.json"
    files = sorted(p for p in REFERENCE_ROOT.rglob("*")
                   if p.suffix.lower() in (".ttf", ".otf", ".ttc") and "_replaced" not in p.parts)
    sig = hashlib.sha1("".join(f"{p}:{p.stat().st_mtime_ns}" for p in files).encode()).hexdigest()
    index = None
    if idx_file.exists():
        cached = json.loads(idx_file.read_text())
        if cached.get("sig") == sig:
            index = cached["fonts"]
    if index is None:
        index = []
        for p in files:
            try:
                n = len(TTCollection(p).fonts) if p.suffix.lower() == ".ttc" else 1
                for i in range(n):
                    info = font_info(p, i)
                    index.append({
                        "path": str(p), "index": i, "family": info["family"], "style": info["style"],
                        "source": p.relative_to(REFERENCE_ROOT).parts[1] if len(p.relative_to(REFERENCE_ROOT).parts) > 2 else None,
                        "designer": info["designer"], "license_url": info["license_url"],
                        "variable_axes": [a["tag"] for a in info["variable_axes"]],
                        "lao_core": f"{info['lao']['core_present']}/{info['lao']['core_total']}",
                        "weight_class": info["metrics"]["weight_class"], "width_class": info["metrics"]["width_class"],
                    })
            except Exception as e:
                index.append({"path": str(p), "error": str(e)})
        idx_file.parent.mkdir(parents=True, exist_ok=True)
        idx_file.write_text(json.dumps({"sig": sig, "fonts": index}))
    out = index
    if script == "lao":
        out = [f for f in out if "lao" in f.get("path", "").lower() or f.get("lao_core", "0/").split("/")[0] not in ("0", "")]
    if query:
        q = query.lower()
        out = [f for f in out if q in json.dumps(f).lower()]
    return out


# ---------------------------------------------------------------- Google Fonts

GF_METADATA = "https://fonts.google.com/metadata/fonts"


def google_fonts_catalog(refresh: bool = False) -> list[dict]:
    import urllib.request
    cache = CACHE / "google-fonts-metadata.json"
    if refresh or not cache.exists() or (cache.stat().st_mtime < __import__("time").time() - 7 * 86400):
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(GF_METADATA, timeout=60) as r:
            cache.write_bytes(r.read())
    data = json.loads(cache.read_text())
    return data["familyMetadataList"]


def google_fonts_search(query: str | None = None, category: str | None = None, subset: str | None = None,
                        limit: int = 30) -> list[dict]:
    """Search Google Fonts metadata; results sorted by popularity (1 = most popular)."""
    out = []
    for f in google_fonts_catalog():
        if category and (f.get("category") or "").lower() != category.lower():
            continue
        if subset and subset not in f.get("subsets", []):
            continue
        if query:
            hay = " ".join([f.get("family", ""), f.get("category", ""), " ".join(f.get("designers", [])),
                            " ".join((f.get("classifications") or [])), " ".join(f.get("stroke") or [] if isinstance(f.get("stroke"), list) else [str(f.get("stroke") or "")])]).lower()
            if query.lower() not in hay:
                continue
        out.append({
            "family": f["family"], "category": f.get("category"), "popularity": f.get("popularity"),
            "trending": f.get("trending"), "designers": f.get("designers"), "subsets": f.get("subsets"),
            "axes": [a.get("tag") for a in f.get("axes", [])], "styles": list(f.get("fonts", {}).keys()),
            "classifications": f.get("classifications"), "date_added": f.get("dateAdded"),
        })
    out.sort(key=lambda f: f["popularity"] or 1e9)
    return out[:limit]


def google_fonts_fetch(family: str, dest: str | Path | None = None) -> dict:
    """Download a Google Fonts family (font files + license) from github.com/google/fonts."""
    import urllib.parse
    import urllib.request
    slug = family.lower().replace(" ", "")
    dest = Path(dest).expanduser() if dest else REFERENCE_ROOT / "google" / slug
    for lic in ("ofl", "apache", "ufl"):
        api = f"https://api.github.com/repos/google/fonts/contents/{lic}/{slug}"
        try:
            with urllib.request.urlopen(api, timeout=60) as r:
                listing = json.loads(r.read())
            break
        except Exception:
            listing = None
    if not listing:
        raise FileNotFoundError(f"{family!r} not found in google/fonts (tried ofl/apache/ufl/{slug})")
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for item in listing:
        if item.get("type") != "file":
            continue
        name = urllib.parse.unquote(item["name"])
        with urllib.request.urlopen(item["download_url"], timeout=120) as r:
            (dest / name).write_bytes(r.read())
        got.append(name)
    return {"family": family, "license_dir": lic, "dest": str(dest), "files": got}


# ---------------------------------------------------------------- building & extracting

def compile_ufo(ufo: str | Path, out: str | Path, fmt: str = "ttf") -> dict:
    """Compile a UFO with ufo2ft (kern + mark/mkmk features are generated from groups and anchors)."""
    import ufo2ft
    import ufoLib2
    font = ufoLib2.Font.open(Path(ufo).expanduser())
    warnings = []
    # Open contours don't render in a filled font and break overlap removal: drop them
    # from this in-memory copy only, and report them so they get fixed in the source.
    for glyph in font:
        open_idx = [i for i, c in enumerate(glyph) if c.open]
        for i in reversed(open_idx):
            warnings.append(f"{glyph.name}: dropped open contour #{i} ({len(glyph.contours[i])} points)")
            del glyph.contours[i]
        if glyph.width < 0:  # mark glyphs drawn left of origin should be width 0, never negative
            warnings.append(f"{glyph.name}: negative advance {glyph.width} set to 0")
            glyph.width = 0
    compile_fn = ufo2ft.compileOTF if fmt == "otf" else ufo2ft.compileTTF
    try:
        built = compile_fn(font, removeOverlaps=True)
    except Exception as e:
        warnings.append(f"overlap removal failed ({type(e).__name__}: {e}); built without it")
        built = compile_fn(font, removeOverlaps=False)
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    built.save(out)
    return {"path": str(out), "format": fmt, "glyphs": len(built.getGlyphOrder()), "warnings": warnings}


from fontTools.pens.basePen import BasePen  # noqa: E402


class _UFOPointCollector(BasePen):
    """Segment pen -> UFO-style point contours, converting quadratic curves to cubic exactly."""

    def __init__(self, glyphset, scale: float = 1.0):
        super().__init__(glyphset)
        self.scale = scale
        self.contours: list[list[dict]] = []
        self._cur: list[dict] | None = None

    def _p(self, pt, kind):
        return {"x": round(pt[0] * self.scale, 2), "y": round(pt[1] * self.scale, 2), "type": kind}

    def _moveTo(self, pt):
        self._cur = [self._p(pt, "move")]

    def _lineTo(self, pt):
        self._cur.append(self._p(pt, "line"))

    def _curveToOne(self, p1, p2, p3):
        self._cur += [self._p(p1, "offcurve"), self._p(p2, "offcurve"), self._p(p3, "curve")]

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
        self._curveToOne(c1, c2, p2)

    def _closePath(self):
        pts = self._cur
        if len(pts) > 1 and (pts[-1]["x"], pts[-1]["y"]) == (pts[0]["x"], pts[0]["y"]):
            last = pts.pop()
            pts[0]["type"] = last["type"]
        else:
            pts[0]["type"] = "line"
        self.contours.append(pts)
        self._cur = None

    def _endPath(self):
        if self._cur:
            self.contours.append(self._cur)
        self._cur = None


def extract_glyph(path: str | Path, glyph: str, target_upm: int | None = None, index: int = 0) -> dict:
    """Outline of one glyph (by name, character or U+XXXX) as cubic UFO points, scaled to target_upm."""
    tt = open_ttfont(path, index)
    cmap = tt.getBestCmap() or {}
    name = glyph
    cp = None
    if len(glyph) == 1:
        cp = ord(glyph)
    elif glyph.upper().startswith("U+"):
        cp = int(glyph[2:], 16)
    elif glyph.startswith("uni") and len(glyph) == 7:
        try:
            cp = int(glyph[3:], 16)
        except ValueError:
            pass
    if cp is not None and cp in cmap:
        name = cmap[cp]
    gs = tt.getGlyphSet()
    if name not in gs:
        raise KeyError(f"{glyph!r} not in {path}")
    upm = tt["head"].unitsPerEm
    scale = (target_upm / upm) if target_upm else 1.0
    pen = _UFOPointCollector(gs, scale)
    gs[name].draw(pen)
    return {"source_name": name, "codepoint": f"{cp:04X}" if cp is not None else None,
            "advance": round(gs[name].width * scale), "contours": pen.contours, "scale": scale}
