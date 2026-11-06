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
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fontlab_mcp import family  # noqa: E402  (vendored)
from fontTools import subset  # noqa: E402
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString  # noqa: E402
from fontTools.merge import Merger  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import ttProgram  # noqa: E402

ROOT = HERE.parents[0]
SRC = ROOT / "KouangSiWaterfall/OpenType-TT/KouangSiWaterfall-Regular.ttf"
VFJ = ROOT / "KouangSiWaterfall-Regular.vfj"   # anchors + kern/mark/mkmk feature code (source of truth)
OUT_TTF = ROOT / "fonts/KouangSiWaterfall-Regular.ttf"
VERSION = "0.240"
LAO = list(range(0x0E80, 0x0F00)) + [0x25CC]
# Google Fonts GF_Latin_African (Robert, 2026-11-04: complete it). These 80 come from the Noto Sans fill (Ⓐ ⓐ from Noto
# Sans Symbols); Ɤ (U+A7CB) exists in no reference font yet. Ʀ Ⱥ Ⱦ are not African Latin and would lack lowercase
# (FontBakery case_mapping), so they stay out.
AFRICAN = {0x0189, 0x018F, 0x0193, 0x0194, 0x0196, 0x0197, 0x019C, 0x019F, 0x01A9, 0x01AE, 0x01B1, 0x01B2, 0x01B7, 0x0244, 0x0245, 0x0250, 0x0251, 0x0256, 0x0259, 0x0260, 0x0263, 0x0264, 0x0265, 0x0266, 0x0268, 0x0269, 0x026A, 0x026F, 0x0275, 0x027D, 0x0283, 0x0288, 0x0289, 0x028A, 0x028B, 0x028C, 0x0292, 0x0294, 0x0295, 0x0298, 0x029D, 0x02B7, 0x02C0, 0x02C8, 0x02D7, 0x02EE, 0x1D43, 0x1D49, 0x1D4B, 0x1D52, 0x1D53, 0x1D58, 0x1D7D, 0x1DA4, 0x1DB6, 0x1DC4, 0x1DC5, 0x1DC6, 0x1DC7, 0x24B6, 0x24D0, 0x2C63, 0x2C64, 0x2C6D, 0x2C6F, 0x2C72, 0x2C73, 0xA789, 0xA78A, 0xA78B, 0xA78C, 0xA78D, 0xA7AA, 0xA7AE, 0xA7B2, 0xA7B4, 0xA7B5, 0xA7B6, 0xA7B7, 0xA7C7, 0xA7C8, 0xA7CB}
AFRICAN |= {0x0253, 0x0254, 0x0257, 0x025B, 0x0272}  # Latin Core lowercase partners of Ɓ Ɔ Ɗ Ɛ Ɲ
AFRICAN |= {0x02BB, 0x02B8, 0x02C1}  # ʻ (Gbari), ʸ ˁ (Zenaga): FontBakery shape_languages
NOT_IN_FONT = {0x01A6, 0x023A, 0x023E}
CIRCLED = [0x24B6, 0x24D0]



def source_features(tt: TTFont) -> None:
    """Rebuild the Lao GPOS (kern, mark, mkmk) from the feature code in the FontLab source (.vfj), so anchor and
    kerning fixes made there reach the font without re-exporting from FontLab. Class members the exported TTF does
    not contain (CR, uni000A) are dropped; the export has no GSUB."""
    of = json.loads(VFJ.read_text())["font"]["openTypeFeatures"]
    fea = "\n".join(x["feature"] for x in of)
    names = set(tt.getGlyphOrder())
    fea = re.sub(r"(@\w+\s*=\s*)\[([^\]]*)\];",
                 lambda m: f"{m.group(1)}[{' '.join(t for t in m.group(2).split() if t in names)}];", fea)
    for tag in ("GPOS", "GSUB", "GDEF"):
        if tag in tt:
            del tt[tag]
    addOpenTypeFeaturesFromString(tt, fea)


def lao_original(tmp: Path) -> tuple[Path, set]:
    tt = TTFont(SRC)
    source_features(tt)
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


def add_rams_horn_capital(tt: TTFont):
    """U+A7CB Ɤ (Dan, Goo) exists in no reference font yet. Build it from this font's hand-drawn capital Ɣ, which has
    the right stroke weight and an open loop: scaled vertically so the loop rests on the baseline (round overshoot, as
    on o) and the arms reach cap height (H). Ɣ itself descends in this font, so the two stay distinct. (0.230 scaled
    the lowercase ɤ instead, whose loop is filled; that came out heavy.)"""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    cmap, gs = tt.getBestCmap(), tt.getGlyphSet()
    if 0xA7CB in cmap or 0x0194 not in cmap:
        return

    def box(g):
        p = BoundsPen(gs); gs[g].draw(p); return p.bounds

    src = cmap[0x0194]
    _, y0, _, y1 = box(src)
    base, cap = box(cmap[ord("o")])[1], box(cmap[ord("H")])[3]
    k = (cap - base) / (y1 - y0)
    pen = TTGlyphPen(gs)
    gs[src].draw(TransformPen(pen, (1, 0, 0, k, 0, base - y0 * k)))
    name = "uniA7CB"
    order = tt.getGlyphOrder() + [name]
    tt.setGlyphOrder(order)
    tt["glyf"].glyphOrder = order  # glyf keeps its own copy of the order
    tt["glyf"][name] = pen.glyph()
    g = tt["glyf"][name]; g.recalcBounds(tt["glyf"])
    tt["hmtx"][name] = (tt["hmtx"][src][0], g.xMin)
    for sub in tt["cmap"].tables:
        if sub.isUnicode():
            sub.cmap[0xA7CB] = name
    if "GDEF" in tt and tt["GDEF"].table.GlyphClassDef:
        tt["GDEF"].table.GlyphClassDef.classDefs[name] = 1


def rare_lao_anchors(tt: TTFont, added: list[int]):
    """Give the Lao letters filled in from Noto (Pali letters, Khmu ໞ ໟ) a place in the hand-drawn Lao mark rules,
    so vowels and tones attach to them too. Anchors follow the medians of Robert's own consonants: top centred and
    33 units below the letter's top; bottom centred, 2 units above its lowest point, or at -100 beside a descender
    (as on ຊ and ຖ)."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib.tables import otTables
    cmap, gs, order = tt.getBestCmap(), tt.getGlyphSet(), tt.getGlyphOrder()
    bases = [cmap[c] for c in added if c in cmap and unicodedata.category(chr(c)) == "Lo"]
    st = None
    for lk in tt["GPOS"].table.LookupList.Lookup:
        for s in lk.SubTable:
            s = getattr(s, "ExtSubTable", s)
            if lk.LookupType in (4, 9) and getattr(s, "BaseCoverage", None) and "uni0E84" in s.BaseCoverage.glyphs \
                    and "uni0EB4" in s.MarkCoverage.glyphs:
                st = s
    if st is None:
        raise RuntimeError("Lao mark-to-base lookup not found")
    ref = st.BaseArray.BaseRecord[st.BaseCoverage.glyphs.index("uni0E84")].BaseAnchor
    top_i = max(range(len(ref)), key=lambda i: ref[i].YCoordinate if ref[i] else -9999)
    records = dict(zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord, strict=True))
    for g in bases:
        if g in records:
            continue
        p = BoundsPen(gs); gs[g].draw(p); x0, y0, x1, y1 = p.bounds
        cx = round((x0 + x1) / 2)
        rec = otTables.BaseRecord(); rec.BaseAnchor = []
        for i in range(len(ref)):
            a = otTables.Anchor(); a.Format = 1
            a.XCoordinate, a.YCoordinate = (cx, round(y1 - 33)) if i == top_i else (cx, round(y0 + 2) if y0 > -60 else -100)
            rec.BaseAnchor.append(a)
        records[g] = rec
    glyphs = sorted(records, key=order.index)
    st.BaseCoverage.glyphs = glyphs
    st.BaseArray.BaseRecord = [records[g] for g in glyphs]
    st.BaseArray.BaseCount = len(glyphs)


def _subtables(lookup):
    for s in lookup.SubTable:
        yield getattr(s, "ExtSubTable", s)


def dotted_circle_bases(tt: TTFont):
    """Let every mark that attaches to a letter attach to the dotted circle U+25CC too (FontBakery dotted_circle), so
    a mark typed alone shows correctly. In each mark-to-base subtable that lacks ◌, its anchors copy a reference letter
    of that subtable (o for Latin): same horizontal offset from the centre, same gap above the top or below the bottom."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib.tables import otTables
    cmap, gs, order = tt.getBestCmap(), tt.getGlyphSet(), tt.getGlyphOrder()
    dc = cmap.get(0x25CC)
    if not dc:
        return

    def box(g):
        p = BoundsPen(gs); gs[g].draw(p); return p.bounds

    dx0, dy0, dx1, dy1 = box(dc)
    lookups = [lk for lk in tt["GPOS"].table.LookupList.Lookup if lk.LookupType in (4, 9)]
    attached = {m for lk in lookups for st in _subtables(lk)
                if hasattr(st, "BaseCoverage") and dc in st.BaseCoverage.glyphs for m in st.MarkCoverage.glyphs}
    for lk in lookups:
        for st in _subtables(lk):
            if not hasattr(st, "BaseCoverage") or dc in st.BaseCoverage.glyphs:
                continue
            if attached & set(st.MarkCoverage.glyphs):
                continue  # these marks already attach to ◌ in their own rules (e.g. Robert's Lao): don't shadow them
            records = dict(zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord, strict=True))
            ref = next((g for g in ("o", "uni0E01", "uni1780", "uni0E81", "a") if g in records and box(g)),
                       next((g for g in records if box(g)), None))
            if ref is None:
                continue
            rx0, ry0, rx1, ry1 = box(ref)
            rec = otTables.BaseRecord(); rec.BaseAnchor = []
            for a in records[ref].BaseAnchor:
                if a is None:
                    rec.BaseAnchor.append(None); continue
                n = otTables.Anchor(); n.Format = 1
                n.XCoordinate = round((dx0 + dx1) / 2 + a.XCoordinate - (rx0 + rx1) / 2)
                above = a.YCoordinate >= (ry0 + ry1) / 2
                n.YCoordinate = round(dy1 + a.YCoordinate - ry1) if above else round(dy0 + a.YCoordinate - ry0)
                rec.BaseAnchor.append(n)
            records[dc] = rec
            attached |= set(st.MarkCoverage.glyphs)
            glyphs = sorted(records, key=order.index)
            st.BaseCoverage.glyphs = glyphs
            st.BaseArray.BaseRecord = [records[g] for g in glyphs]
            st.BaseArray.BaseCount = len(glyphs)


def latin_accents_everywhere(tt: TTFont):
    """Every Latin letter joins every Latin mark-to-base rule set it is missing from, so any combining accent attaches
    to any letter (the merged parts each only knew their own letters and marks). Anchors are copied from the letter's
    base (ȩ from e) or a look-alike (ɛ from e, ɔ from o, ...), else o / O: same offset from the centre, same gap above
    the top or below the bottom."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib.tables import otTables
    cmap, gs, order = tt.getBestCmap(), tt.getGlyphSet(), tt.getGlyphOrder()
    rev = {g: c for c, g in cmap.items()}
    look = {"ɓ": "b", "Ɓ": "B", "ɗ": "d", "Ɗ": "D", "ɖ": "d", "Ɖ": "D", "ɛ": "e", "Ɛ": "E", "ə": "e", "Ə": "E",
            "ɔ": "o", "Ɔ": "O", "ɲ": "n", "Ɲ": "N", "ɨ": "i", "Ɨ": "I", "ʉ": "u", "Ʉ": "U", "ʊ": "u", "Ʊ": "U",
            "ʋ": "v", "Ʋ": "V", "ɣ": "y", "Ɣ": "Y", "ɩ": "i", "Ɩ": "I", "ʌ": "v", "Ʌ": "V", "ɑ": "a", "Ɑ": "A"}
    boxes = {}

    def box(g):
        if g not in boxes:
            p = BoundsPen(gs); gs[g].draw(p); boxes[g] = p.bounds
        return boxes[g]

    # Letters newer than the running Python's Unicode data (Ɤ U+A7CB is Unicode 16, Python 3.13+).
    newer = {0xA7CB: ("Lu", "LATIN CAPITAL LETTER RAMS HORN")}

    def cat(ch):
        return newer.get(ord(ch), (unicodedata.category(ch),))[0]

    def is_upper(ch):
        return cat(ch) in ("Lu", "Lt")

    def latin_letter(g):
        c = rev.get(g)
        if c is None:
            return False
        ch = chr(c)
        name = newer.get(c, (None, unicodedata.name(ch, "")))[1]
        # Lo covers uncased Latin letters such as ʔ
        return cat(ch) in ("Lu", "Ll", "Lt", "Lo") and "LATIN" in name and bool(box(g))

    letters = [g for g in order if latin_letter(g)]

    def latin_mark(g):
        c = rev.get(g)
        return c is not None and (0x0300 <= c <= 0x036F or 0x1AB0 <= c <= 0x1AFF or 0x1DC0 <= c <= 0x1DFF)

    def reference(g, records):
        ch = chr(rev[g])
        d = unicodedata.decomposition(ch).split()
        cands = []
        if d and not d[0].startswith("<"):
            cands.append(cmap.get(int(d[0], 16)))
        if ch in look:
            cands.append(cmap.get(ord(look[ch])))
        cands.append("O" if is_upper(ch) else "o")
        hit = next((r for r in cands if r and r in records and box(r)), None)
        if hit:
            return hit
        same_case = [r for r in records if r in rev and is_upper(chr(rev[r])) == is_upper(ch) and box(r)]
        return same_case[0] if same_case else None

    for lk in tt["GPOS"].table.LookupList.Lookup:
        if lk.LookupType not in (4, 9):
            continue
        for st in _subtables(lk):
            if not hasattr(st, "BaseCoverage"):
                continue
            records = dict(zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord, strict=True))
            if not any(latin_mark(m) for m in st.MarkCoverage.glyphs):
                continue  # not a Latin rule set
            changed = False
            for g in letters:
                if g in records:
                    continue
                ref = reference(g, records)
                if ref is None:
                    continue
                (gx0, gy0, gx1, gy1), (rx0, ry0, rx1, ry1) = box(g), box(ref)
                rec = otTables.BaseRecord(); rec.BaseAnchor = []
                for a in records[ref].BaseAnchor:
                    if a is None:
                        rec.BaseAnchor.append(None); continue
                    n = otTables.Anchor(); n.Format = 1
                    n.XCoordinate = round((gx0 + gx1) / 2 + a.XCoordinate - (rx0 + rx1) / 2)
                    above = a.YCoordinate >= (ry0 + ry1) / 2
                    n.YCoordinate = round(gy1 + a.YCoordinate - ry1) if above else round(gy0 + a.YCoordinate - ry0)
                    rec.BaseAnchor.append(n)
                records[g] = rec; changed = True
            if changed:
                glyphs = sorted(records, key=order.index)
                st.BaseCoverage.glyphs = glyphs
                st.BaseArray.BaseRecord = [records[x] for x in glyphs]
                st.BaseArray.BaseCount = len(glyphs)


def repair_latin_mark_positions(tt: TTFont):
    """Check where each Latin accent's ink actually lands on each Latin letter, and move the anchors that put it off
    the letter or into it. The borrowed Latin part had bad anchors for some letters (accents on ɨ ị ȋ ĳ at the
    bottom left, on b ɓ through the ascender, on ɩ ţ far off the glyph). Rules, per letter and accent class:
    - the accent's centre must lie over the letter's ink (else it is centred on the letter);
    - an above accent must clear the letter's outline under it by the gap it has on o (40-120 units), and not
      float more than 120 units beyond that (a below accent likewise).
    Anchors that already pass are left exactly as they are. Lao, Thai and Khmer rules are not touched."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib.tables import otTables
    cmap, gs = tt.getBestCmap(), tt.getGlyphSet()
    rev = {g: c for c, g in cmap.items()}
    newer = {0xA7CB: ("Lu", "LATIN CAPITAL LETTER RAMS HORN")}
    boxes, pts = {}, {}

    def box(g):
        if g not in boxes:
            p = BoundsPen(gs); gs[g].draw(p); boxes[g] = p.bounds
        return boxes[g]

    def points(g):
        if g not in pts:
            rp = DecomposingRecordingPen(gs); gs[g].draw(rp)
            pts[g] = [pt for _, args in rp.value for pt in args if pt is not None]
        return pts[g]

    def latin_letter(g):
        c = rev.get(g)
        if c is None or not box(g):
            return False
        cat, name = newer.get(c, (unicodedata.category(chr(c)), unicodedata.name(chr(c), "")))
        return cat in ("Lu", "Ll", "Lt", "Lo") and "LATIN" in name

    def latin_mark(g):
        c = rev.get(g)
        return c is not None and (0x0300 <= c <= 0x036F or 0x1AB0 <= c <= 0x1AFF or 0x1DC0 <= c <= 0x1DFF)

    def extent(g, x0, x1, top):
        """Highest (top=True) or lowest point of g's outline between x0 and x1, else of the whole glyph."""
        ys = [y for x, y in points(g) if x0 <= x <= x1]
        b = box(g)
        return (max(ys) if top else min(ys)) if ys else (b[3] if top else b[1])

    def side(m):
        """Unicode's combining class says where a mark goes: 230 above, 220 below; 202/216 (cedilla, ogonek, horn)
        are attached to the letter and only checked for centring."""
        ccc = unicodedata.combining(chr(rev[m]))
        return "above" if ccc == 230 else "below" if ccc == 220 else "attached"

    prefer = ["acutecomb", "gravecomb", "uni0302", "uni0303", "uni0308", "dotbelowcomb", "uni0331", "uni0327"]
    fixed = 0
    for lk in tt["GPOS"].table.LookupList.Lookup:
        if lk.LookupType not in (4, 9):
            continue
        for st in _subtables(lk):
            if not hasattr(st, "BaseCoverage") or not any(latin_mark(m) for m in st.MarkCoverage.glyphs):
                continue
            rep = {}  # class -> (mark glyph, mark anchor, kind)
            members = {}  # class -> every Latin mark in it: (mark glyph, mark record)
            for m, rec in zip(st.MarkCoverage.glyphs, st.MarkArray.MarkRecord, strict=True):
                if not latin_mark(m) or not box(m):
                    continue
                members.setdefault(rec.Class, []).append((m, rec))
                cur = rep.get(rec.Class)
                if cur is None or (m in prefer and (cur[0] not in prefer or prefer.index(m) < prefer.index(cur[0]))):
                    rep[rec.Class] = (m, rec.MarkAnchor, side(m))
            bases = st.BaseCoverage.glyphs

            def o_gap(m, ma, a, kind):
                """How far mark m (anchor ma) clears o when o's anchor is a."""
                mb = box(m); dx, dy = a.XCoordinate - ma.XCoordinate, a.YCoordinate - ma.YCoordinate
                if kind == "above":
                    return mb[1] + dy - extent("o", mb[0] + dx - 30, mb[2] + dx + 30, True)
                return extent("o", mb[0] + dx - 30, mb[2] + dx + 30, False) - (mb[3] + dy)

            # the gap each above/below class keeps on o (the reference shape), at least 40 units
            gap = {}
            if "o" in bases:
                orec = st.BaseArray.BaseRecord[bases.index("o")]
                for k, (m, ma, kind) in rep.items():
                    a = orec.BaseAnchor[k]
                    if a is not None and kind != "attached":
                        gap[k] = min(max(o_gap(m, ma, a, kind), 40), 120)
                # marks sharing a class but sitting closer to o than the class's main mark (̔ ̥ ̳ ͇ touched the
                # letters) get their own anchor moved so they clear o by the same gap
                for m, rec in zip(st.MarkCoverage.glyphs, st.MarkArray.MarkRecord, strict=True):
                    k = rec.Class
                    if not latin_mark(m) or not box(m) or k not in gap or orec.BaseAnchor[k] is None:
                        continue
                    ma, kind = rec.MarkAnchor, side(m)
                    if kind != rep[k][2]:
                        continue
                    short = gap[k] - o_gap(m, ma, orec.BaseAnchor[k], kind)
                    if short > 25:
                        n = otTables.Anchor(); n.Format = 1; n.XCoordinate = ma.XCoordinate
                        n.YCoordinate = round(ma.YCoordinate - short if kind == "above" else ma.YCoordinate + short)
                        rec.MarkAnchor = n; fixed += 1
            for g, brec in zip(bases, st.BaseArray.BaseRecord, strict=True):
                if not latin_letter(g):
                    continue
                bx0, _, bx1, _ = box(g)
                for k, (m, ma, kind) in rep.items():
                    a = brec.BaseAnchor[k]
                    if a is None:
                        continue
                    mb = box(m)
                    nx, ny = a.XCoordinate, a.YCoordinate
                    cx = (mb[0] + mb[2]) / 2 + nx - ma.XCoordinate
                    if not (bx0 - 40 <= cx <= bx1 + 40):
                        nx = round(nx + (bx0 + bx1) / 2 - cx)
                    dx, dy = nx - ma.XCoordinate, ny - ma.YCoordinate
                    if kind == "above":
                        want = extent(g, mb[0] + dx - 30, mb[2] + dx + 30, True) + gap.get(k, 40)
                        ceiling = max(want, box(g)[3] + gap.get(k, 40)) + 120  # too high above the whole letter
                        if mb[1] + dy < want - 25:
                            ny = round(ny + want - (mb[1] + dy))
                        elif mb[1] + dy > ceiling:
                            ny = round(ny - (mb[1] + dy - ceiling + 120))
                    elif kind == "below":
                        want = extent(g, mb[0] + dx - 30, mb[2] + dx + 30, False) - gap.get(k, 40)
                        floor = min(want, box(g)[1] - gap.get(k, 40)) - 120  # too far below the whole letter
                        if mb[3] + dy > want + 25:
                            ny = round(ny - (mb[3] + dy - want))
                        elif mb[3] + dy < floor:
                            ny = round(ny + (floor + 120 - (mb[3] + dy)))
                    if kind in ("above", "below"):
                        # taller marks in the same class (fermata, combining small letters) must clear by 40 too
                        need = 0
                        for mm, rec in members.get(k, []):
                            if side(mm) != kind:
                                continue
                            b2, ma2 = box(mm), rec.MarkAnchor
                            ddx, ddy = nx - ma2.XCoordinate, ny - ma2.YCoordinate
                            if kind == "above":
                                need = max(need, extent(g, b2[0] + ddx - 30, b2[2] + ddx + 30, True) + 40 - (b2[1] + ddy))
                            else:
                                need = max(need, (b2[3] + ddy) - (extent(g, b2[0] + ddx - 30, b2[2] + ddx + 30, False) - 40))
                        if need > 0:
                            ny = round(ny + need if kind == "above" else ny - need)
                    if (nx, ny) != (a.XCoordinate, a.YCoordinate):
                        n = otTables.Anchor(); n.Format = 1; n.XCoordinate, n.YCoordinate = nx, ny
                        brec.BaseAnchor[k] = n; fixed += 1
    return fixed


def smcp_before_liga(tt: TTFont):
    """Move the small-caps lookups to just before the first ligature lookup (FontBakery smallcaps_before_ligatures),
    so small caps apply before ligatures form. All lookup references (features, contextual rules) are renumbered."""
    gsub = tt["GSUB"].table
    feats = gsub.FeatureList.FeatureRecord
    smcp = sorted({i for f in feats if f.FeatureTag == "smcp" for i in f.Feature.LookupListIndex})
    liga = [i for f in feats if f.FeatureTag == "liga" for i in f.Feature.LookupListIndex]
    if not smcp or not liga or min(smcp) < min(liga):
        return
    first = min(liga)
    n = len(gsub.LookupList.Lookup)
    new_order = [i for i in range(first) if i not in smcp] + smcp + [i for i in range(first, n) if i not in smcp]
    remap = {old: new for new, old in enumerate(new_order)}
    gsub.LookupList.Lookup = [gsub.LookupList.Lookup[i] for i in new_order]
    for f in feats:
        f.Feature.LookupListIndex = [remap[i] for i in f.Feature.LookupListIndex]

    def walk(obj, seen):
        if id(obj) in seen or not hasattr(obj, "__dict__"):
            return
        seen.add(id(obj))
        if type(obj).__name__ in ("SubstLookupRecord", "LookupRecord") and hasattr(obj, "LookupListIndex"):
            obj.LookupListIndex = remap[obj.LookupListIndex]
            return
        for v in vars(obj).values():
            for x in (v if isinstance(v, list) else [v]):
                if hasattr(x, "__dict__"):
                    walk(x, seen)
    seen = set()
    for lk in gsub.LookupList.Lookup:
        for st in lk.SubTable:
            walk(st, seen)


def widen_zero_width_bases(tt: TTFont):
    """Spacing characters that came out with zero advance (e.g. U+02C8 ˈ) get their ink width plus 60-unit sidebearings
    (FontBakery base_has_width). Marks (GDEF class 3) keep zero width."""
    gdef = tt["GDEF"].table.GlyphClassDef.classDefs if "GDEF" in tt and tt["GDEF"].table.GlyphClassDef else {}
    glyf, hmtx = tt["glyf"], tt["hmtx"]
    for c, g in tt.getBestCmap().items():
        if hmtx[g][0] != 0 or gdef.get(g) == 3 or unicodedata.category(chr(c)).startswith("M"):
            continue
        gl = glyf[g]
        if not gl.numberOfContours:
            continue
        gl.recalcBounds(glyf)
        dx = 60 - gl.xMin
        if gl.isComposite():
            continue
        coords = gl.coordinates
        coords.translate((dx, 0))
        gl.recalcBounds(glyf)
        hmtx[g] = (gl.xMax + 60, gl.xMin)


def finish(tt: TTFont):
    nt = tt["name"]; nt.names = []
    fam = "Kouang Si Waterfall"
    vals = {0: "Copyright 2019-2026 The Kouang Si Waterfall Project Authors (https://github.com/rcampbellbassac/KouangSiWaterfall). "
               "Thai and Latin derived from Mali (Copyright 2018 The Mali Project Authors), Khmer from Fasthand (Copyright 2020 "
               "The Fasthand Project Authors), other characters and added Lao letters from the Noto fonts (Copyright 2022 The Noto "
               "Project Authors).",
            1: fam, 2: "Regular", 3: f"{VERSION};NONE;KouangSiWaterfall-Regular", 4: f"{fam} Regular",
            5: f"Version {VERSION}", 6: "KouangSiWaterfall-Regular", 8: "Southeast Asia SDA Media Library",
            9: "Robert Martin Campbell", 11: "https://sea-sda.org", 12: "https://sea-sda.org",
            13: "This Font Software is licensed under the SIL Open Font License, Version 1.1.",
            14: "https://openfontlicense.org", 19: "ນ້ຳຕົກຕາດກວາງຊີ  น้ำตก  ទឹកធ្លាក់  Kouang Si"}
    # ss02 (UINameID 257) merges Noto Lao Looped "Alternate lla" and Noto Math "Straight integrals";
    # the label must survive the name-table reset (FontBakery ttx_roundtrip).
    vals[257] = "Alternate lla and straight integrals"
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
    # One line height everywhere (1.70 em, Robert's choice 2026-11-01): typo == hhea so Mac/iOS match Windows,
    # Android and the web; win covers the tallest stacked Thai/Lao marks so nothing clips on Windows.
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 1250, -450, 0
    os2.usWinAscent, os2.usWinDescent = max(ymax, 1250), max(-ymin, 450)
    hhea.ascent, hhea.descent, hhea.lineGap = os2.sTypoAscender, os2.sTypoDescender, 0
    os2.fsSelection = (os2.fsSelection | (1 << 7) | (1 << 6)) & ~((1 << 0) | (1 << 5))  # USE_TYPO_METRICS, REGULAR
    os2.fsType = 0                       # installable embedding
    os2.usWeightClass, os2.usWidthClass = 400, 5  # the style is named Regular, so 400 (was 700)
    os2.achVendID = "NONE"
    os2.recalcUnicodeRanges(tt)
    os2.recalcCodePageRanges(tt)
    tt["post"].formatType = 2.0
    tt["post"].italicAngle, tt["post"].isFixedPitch = 0, 0
    tt["head"].flags |= 1 << 3           # integer ppem
    # Unhinted font: smart dropout control + gasp "smooth everything" (what gftools fix-nonhinting does).
    prep = newTable("prep")
    prep.program = ttProgram.Program()
    prep.program.fromAssembly(["PUSHW[]", "511", "SCANCTRL[]", "PUSHB[]", "4", "SCANTYPE[]"])
    tt["prep"] = prep
    gasp = newTable("gasp")
    gasp.gaspRange = {0xFFFF: 0x000F}
    tt["gasp"] = gasp
    tt["maxp"].maxStackElements = max(tt["maxp"].maxStackElements, 2)


def build():
    spec = json.loads((HERE / "recipe.json").read_text())
    latin = (set(family.UNICODES["latin"]) | AFRICAN) - NOT_IN_FONT - set(CIRCLED)
    family.UNICODES["latin"] = sorted(latin)
    family.BASES["symbols1"] = family.REF / "google-base/notosanssymbols/NotoSansSymbols[wght].ttf"
    family.PART_BASE["circled"] = "symbols1"
    family.UNICODES["circled"] = CIRCLED
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        lao, have = lao_original(d)
        missing_lao = [c for c in LAO if c not in have and 0x0E80 <= c <= 0x0EFF]
        parts = styled_with_fill(d, spec, "latin") + [lao]
        if missing_lao:
            parts.append(generated(d, spec, "lao", only=set(missing_lao)))
        parts += styled_with_fill(d, spec, "thai") + styled_with_fill(d, spec, "khmer")
        parts += [generated(d, spec, s) for s in ("symbols", "dingbats", "circled")]
        merged = Merger().merge([str(p) for p in parts])
    family.add_missing_spaces(merged)
    add_rams_horn_capital(merged)
    add_khmer_shifter_rule(merged)
    declare_khmer_gpos(merged)
    rare_lao_anchors(merged, missing_lao)
    dotted_circle_bases(merged)
    latin_accents_everywhere(merged)
    repair_latin_mark_positions(merged)
    smcp_before_liga(merged)
    widen_zero_width_bases(merged)
    finish(merged)
    OUT_TTF.parent.mkdir(exist_ok=True)
    merged.save(OUT_TTF)
    for flavor in ("woff2", "woff"):
        w = TTFont(OUT_TTF); w.flavor = flavor; w.save(OUT_TTF.with_suffix("." + flavor))
    print(json.dumps({"ttf": str(OUT_TTF), "glyphs": len(merged.getGlyphOrder()), "added_lao": [f"{c:04X}" for c in missing_lao]}))


if __name__ == "__main__":
    build()
