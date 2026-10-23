"""Build Kouang Si Waterfall with Thai, Khmer and Latin added, following modern font practice.

  python scripts/build_multiscript.py

Lao: Robert's hand-drawn glyphs from OpenType-TT/KouangSiWaterfall-Regular.ttf (FontLab export, kept as
drawn; hinting dropped). Thai, Khmer, Latin, symbols, and the Lao letters the original does not have yet are
generated with a soft-brush recipe matched to the Lao stroke (scripts/recipe.json) on the thin Noto designs.
Everything is merged into one font with consistent vertical metrics, names and OS/2 data.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fontlab_mcp import family  # noqa: E402  (vendored)
from fontTools import subset  # noqa: E402
from fontTools.merge import Merger  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

ROOT = HERE.parents[0]
SRC = ROOT / "KouangSiWaterfall/OpenType-TT/KouangSiWaterfall-Regular.ttf"
OUT_TTF = ROOT / "fonts/KouangSiWaterfall-Regular.ttf"
VERSION = "0.100"
LAO = list(range(0x0E80, 0x0F00)) + [0x25CC]


def lao_original(tmp: Path) -> tuple[Path, set]:
    tt = TTFont(SRC)
    o = subset.Options(); o.layout_features = ["*"]; o.name_IDs = ["*"]; o.glyph_names = True
    o.notdef_outline = True; o.hinting = False; o.drop_tables += ["DSIG", "gasp", "vhea", "vmtx"]
    s = subset.Subsetter(o); s.populate(unicodes=LAO + [0x20, 0xA0, 0x200B]); s.subset(tt)
    family._normalize_for_merge(tt)
    have = set(tt.getBestCmap())
    p = tmp / "lao-original.ttf"; tt.save(p)
    return p, have


def generated(tmp: Path, spec: dict, script: str, only=None) -> Path:
    if only is not None:
        keep = family.UNICODES[script]
        family.UNICODES[script] = [c for c in keep if c in only]
    part = family.build_part(script, spec)
    p = tmp / f"{script}{'-extra' if only else ''}.ttf"
    part.save(p)
    return p


def finish(tt: TTFont):
    nt = tt["name"]; nt.names = []
    fam = "Kouang Si Waterfall"
    vals = {0: "Copyright 2019-2026 Robert Martin Campbell. Thai, Khmer, Latin and added Lao letters derived from "
               "Noto Sans Lao Looped, Noto Sans Thai Looped, Noto Sans Khmer, Noto Sans and Noto Sans Math "
               "(Copyright 2022 The Noto Project Authors).",
            1: fam, 2: "Regular", 3: f"{VERSION};NONE;KouangSiWaterfall-Regular", 4: f"{fam} Regular",
            5: f"Version {VERSION}", 6: "KouangSiWaterfall-Regular", 8: "Southeast Asia SDA Media Library",
            9: "Robert Martin Campbell", 11: "https://sea-sda.org", 12: "https://sea-sda.org",
            13: "This Font Software is licensed under the SIL Open Font License, Version 1.1.",
            14: "https://openfontlicense.org", 19: "ນ້ຳຕົກຕາດກວາງຊີ  น้ำตก  ទឹកធ្លាក់  Kouang Si"}
    for nid, v in vals.items():
        nt.setName(v, nid, 3, 1, 0x409)
    tt["head"].fontRevision = float(VERSION)
    glyf, cmap = tt["glyf"], tt.getBestCmap()
    ymax = max(getattr(glyf[g], "yMax", 0) for g in tt.getGlyphOrder())
    ymin = min(getattr(glyf[g], "yMin", 0) for g in tt.getGlyphOrder())
    def top(ch):
        return getattr(glyf[cmap[ord(ch)]], "yMax", 0)
    os2, hhea = tt["OS/2"], tt["hhea"]
    os2.sxHeight, os2.sCapHeight = top("x"), top("H")
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 1100, -400, 0   # room for stacked Lao/Thai marks
    os2.usWinAscent, os2.usWinDescent = max(ymax, 1100), max(-ymin, 400)       # no clipping on Windows
    hhea.ascent, hhea.descent, hhea.lineGap = os2.usWinAscent, -os2.usWinDescent, 0
    os2.fsSelection = (os2.fsSelection | (1 << 7) | (1 << 6)) & ~((1 << 0) | (1 << 5))  # USE_TYPO_METRICS, REGULAR
    os2.fsType = 0                       # installable embedding
    os2.usWeightClass, os2.usWidthClass = 700, 5
    os2.achVendID = "NONE"
    os2.recalcUnicodeRanges(tt)
    os2.recalcCodePageRanges(tt)
    tt["post"].formatType = 2.0
    tt["post"].italicAngle, tt["post"].isFixedPitch = 0, 0
    tt["head"].flags |= 1 << 3           # integer ppem


def build():
    spec = json.loads((HERE / "recipe.json").read_text())
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        lao, have = lao_original(d)
        missing_lao = [c for c in LAO if c not in have and 0x0E80 <= c <= 0x0EFF]
        parts = [generated(d, spec, "latin"), lao]
        if missing_lao:
            parts.append(generated(d, spec, "lao", only=set(missing_lao)))
        parts += [generated(d, spec, s) for s in ("thai", "khmer", "symbols", "dingbats")]
        merged = Merger().merge([str(p) for p in parts])
    family.add_missing_spaces(merged)
    finish(merged)
    OUT_TTF.parent.mkdir(exist_ok=True)
    merged.save(OUT_TTF)
    for flavor in ("woff2", "woff"):
        w = TTFont(OUT_TTF); w.flavor = flavor; w.save(OUT_TTF.with_suffix("." + flavor))
    print(json.dumps({"ttf": str(OUT_TTF), "glyphs": len(merged.getGlyphOrder()), "added_lao": [f"{c:04X}" for c in missing_lao]}))


if __name__ == "__main__":
    build()
