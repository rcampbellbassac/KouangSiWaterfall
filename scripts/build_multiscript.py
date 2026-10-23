"""Build Kouang Si Waterfall with Thai, Khmer and Latin added, following modern font practice.

  python scripts/build_multiscript.py

Lao: Robert's hand-drawn glyphs from OpenType-TT/KouangSiWaterfall-Regular.ttf (FontLab export, kept as
drawn; hinting dropped). Thai and Latin (letters, digits, punctuation) are built on Mali, and Khmer on Fasthand:
hand-lettered OFL skeletons whose round loop heads and casual rhythm match the Lao, given the Lao's stroke weight
and proportions by a measured brush (scripts/recipe.json). Characters those skeletons lack (rare Latin, Khmer
lunar-date signs, math and symbols) and the Lao letters the original does not have yet come from Noto with the
same brush. Everything is merged into one font with consistent vertical metrics, names and OS/2 data.
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
VERSION = "0.200"
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


def generated(tmp: Path, spec: dict, script: str, only=None, tag="") -> Path:
    keep = family.UNICODES[script]
    if only is not None:
        family.UNICODES[script] = [c for c in keep if c in only]
    try:
        part = family.build_part(script, spec)
    finally:
        family.UNICODES[script] = keep
    p = tmp / f"{script}{tag or ('-extra' if only else '')}.ttf"
    part.save(p)
    return p


def styled_with_fill(tmp: Path, spec: dict, script: str) -> list[Path]:
    """The hand-lettered skeleton for everything it covers, Noto (spec["fill"][script]) for the rest."""
    base = family.BASES[spec["bases"][script]]
    has = set(family._instance(base, 400).getBestCmap())
    want = set(family.UNICODES[script])
    parts = [generated(tmp, spec, script, only=want & has, tag="-hand")]
    rest = want - has - {0x20, 0xA0}
    if rest and script in spec.get("fill", {}):
        fill = {**spec, "per_script": {script: spec["fill"][script]}}
        parts.append(generated(tmp, fill, script, only=rest, tag="-fill"))
    return parts


KHMER_SHIFTER_FEA = """
lookup shifter_below { sub uni17C9 by uni17BB; sub uni17CA by uni17BB; sub uni17C9.r by uni17BB; } shifter_below;
feature abvs { script khmr; sub [uni17C9 uni17CA uni17C9.r]' lookup shifter_below
  [uni17B7 uni17B8 uni17B9 uni17BA uni17BE uni17D0 uni17DD uni17B7_17CD uni17B7.a uni17B8.a uni17B9.a uni17BA.a uni17D0.a
   uni17B7.r uni17B8.r uni17B9.r uni17BA.r]; } abvs;
"""
FEATURES_FOR_SHIFTER = ("abvs", "clig")   # Fasthand picks some vowel variants in clig, after abvs: catch both


def add_khmer_shifter_rule(tt: TTFont):
    """Khmer: a register shifter (៉ ៊) followed by an above vowel is written below the consonant (as the u-shape),
    so the two never stack. Fasthand lacks this rule; add it to the merged GSUB without disturbing other lookups."""
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.ttLib.tables import otTables as ot
    tmp = TTFont()
    tmp.setGlyphOrder(tt.getGlyphOrder())
    addOpenTypeFeaturesFromString(tmp, KHMER_SHIFTER_FEA, tables=["GSUB"])
    G, N = tt["GSUB"].table, tmp["GSUB"].table
    base = len(G.LookupList.Lookup)
    for lk in N.LookupList.Lookup:
        for st in lk.SubTable:
            for rec in getattr(st, "SubstLookupRecord", []) or []:
                rec.LookupListIndex += base
        G.LookupList.Lookup.append(lk)
    G.LookupList.LookupCount = len(G.LookupList.Lookup)
    mine = [base + i for i, lk in enumerate(N.LookupList.Lookup) if lk.LookupType == 6]
    # shapers use only the first feature record of a tag per language system, so extend Fasthand's own records
    for sr in G.ScriptList.ScriptRecord:
        if sr.ScriptTag != "khmr":
            continue
        for ls in [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]:
            if ls is None:
                continue
            for tag in FEATURES_FOR_SHIFTER:
                idx = [i for i in ls.FeatureIndex if G.FeatureList.FeatureRecord[i].FeatureTag == tag]
                if idx:
                    f = G.FeatureList.FeatureRecord[idx[0]].Feature
                    f.LookupListIndex = sorted(set(f.LookupListIndex) | set(mine)); f.LookupCount = len(f.LookupListIndex)
                else:
                    fr = ot.FeatureRecord(); fr.FeatureTag = tag; fr.Feature = ot.Feature()
                    fr.Feature.FeatureParams = None; fr.Feature.LookupListIndex = list(mine); fr.Feature.LookupCount = len(mine)
                    G.FeatureList.FeatureRecord.append(fr); G.FeatureList.FeatureCount = len(G.FeatureList.FeatureRecord)
                    ls.FeatureIndex.append(len(G.FeatureList.FeatureRecord) - 1); ls.FeatureCount = len(ls.FeatureIndex)


def declare_khmer_gpos(tt: TTFont):
    """Fasthand places Khmer marks by glyph design (no anchors), so GPOS has no 'khmr' script and shapers fall back
    to DFLT. Declare 'khmr' with exactly DFLT's features: same rendering, explicit Khmer support (kerning etc.)."""
    import copy
    from fontTools.ttLib.tables import otTables as ot
    S = tt["GPOS"].table.ScriptList
    if any(r.ScriptTag == "khmr" for r in S.ScriptRecord):
        return
    dflt = next(r for r in S.ScriptRecord if r.ScriptTag == "DFLT")
    rec = ot.ScriptRecord(); rec.ScriptTag = "khmr"; rec.Script = ot.Script()
    rec.Script.DefaultLangSys = copy.deepcopy(dflt.Script.DefaultLangSys)
    rec.Script.LangSysRecord = []; rec.Script.LangSysCount = 0
    S.ScriptRecord.append(rec); S.ScriptRecord.sort(key=lambda r: r.ScriptTag); S.ScriptCount = len(S.ScriptRecord)


def finish(tt: TTFont):
    nt = tt["name"]; nt.names = []
    fam = "Kouang Si Waterfall"
    vals = {0: "Copyright 2019-2026 Robert Martin Campbell. Thai and Latin derived from Mali (Copyright 2018 The Mali "
               "Project Authors), Khmer from Fasthand (Copyright 2020 The Fasthand Project Authors), other characters and added Lao letters "
               "from the Noto fonts (Copyright 2022 The Noto Project Authors).",
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
        parts = styled_with_fill(d, spec, "latin") + [lao]
        if missing_lao:
            parts.append(generated(d, spec, "lao", only=set(missing_lao)))
        parts += styled_with_fill(d, spec, "thai") + styled_with_fill(d, spec, "khmer")
        parts += [generated(d, spec, s) for s in ("symbols", "dingbats")]
        merged = Merger().merge([str(p) for p in parts])
    family.add_missing_spaces(merged)
    add_khmer_shifter_rule(merged)
    declare_khmer_gpos(merged)
    finish(merged)
    OUT_TTF.parent.mkdir(exist_ok=True)
    merged.save(OUT_TTF)
    for flavor in ("woff2", "woff"):
        w = TTFont(OUT_TTF); w.flavor = flavor; w.save(OUT_TTF.with_suffix("." + flavor))
    print(json.dumps({"ttf": str(OUT_TTF), "glyphs": len(merged.getGlyphOrder()), "added_lao": [f"{c:04X}" for c in missing_lao]}))


if __name__ == "__main__":
    build()
