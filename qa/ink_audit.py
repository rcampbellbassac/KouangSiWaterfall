"""Run: python qa/ink_audit.py fonts/KouangSiWaterfall-Regular.ttf  (needs uharfbuzz, pillow, fonttools).
Ink audit: every Latin letter + every combining mark, shaped by HarfBuzz, rasterised (even-odd, 1/4 scale).
Flags: mark ink touching base ink (above/below marks only; ccc 202 attached marks are meant to touch),
mark centred off the letter, or mark too far away (> 400 units from the letter's ink)."""
import sys, unicodedata, json
from pathlib import Path
from collections import Counter
import uharfbuzz as hb
from PIL import Image, ImageDraw, ImageChops
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen

S = 0.25; OX, OY = 400, 1400  # raster origin offsets (font units)

class Poly(BasePen):
    def __init__(self, gs):
        super().__init__(gs); self.contours = []; self.cur = []
    def _moveTo(self, p): self.cur = [p]
    def _lineTo(self, p): self.cur.append(p)
    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, 9):
            t = i / 8; mt = 1 - t
            self.cur.append((mt**3*p0[0]+3*mt*mt*t*p1[0]+3*mt*t*t*p2[0]+t**3*p3[0], mt**3*p0[1]+3*mt*mt*t*p1[1]+3*mt*t*t*p2[1]+t**3*p3[1]))
    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for i in range(1, 7):
            t = i / 6; mt = 1 - t
            self.cur.append((mt*mt*p0[0]+2*mt*t*p1[0]+t*t*p2[0], mt*mt*p0[1]+2*mt*t*p1[1]+t*t*p2[1]))
    def _closePath(self):
        if len(self.cur) > 2: self.contours.append(self.cur)
        self.cur = []
    _endPath = _closePath

def raster(gs, g, dx, dy, size=(800, 700)):
    pen = Poly(gs); gs[g].draw(pen)
    img = Image.new("1", size, 0)
    for c in pen.contours:
        m = Image.new("1", size, 0)
        ImageDraw.Draw(m).polygon([((x + dx + OX) * S, (OY - (y + dy)) * S) for x, y in c], fill=1)
        img = ImageChops.logical_xor(img, m)
    return img

def main(path, show=40):
    tt = TTFont(path); gs = tt.getGlyphSet(); cmap = tt.getBestCmap()
    font = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
    bc = {}
    def box(g):
        if g not in bc:
            p = BoundsPen(gs); gs[g].draw(p); bc[g] = p.bounds
        return bc[g]
    newer = {0xA7CB: "Lu"}
    letters = [c for c in cmap if (newer.get(c) or unicodedata.category(chr(c))) in ("Lu", "Ll", "Lt", "Lo")
               and ("LATIN" in unicodedata.name(chr(c), "") or c in newer) and box(cmap[c])]
    marks = [c for c in cmap if 0x300 <= c <= 0x36F and unicodedata.combining(chr(c)) in (230, 220, 202)]
    rcache = {}
    bad = []
    for L in letters:
        for M in marks:
            b = hb.Buffer(); b.add_str(chr(L) + chr(M)); b.guess_segment_properties(); hb.shape(font, b)
            gi, gp = b.glyph_infos, b.glyph_positions
            if len(gi) != 2:
                continue
            base, mk = font.glyph_to_string(gi[0].codepoint), font.glyph_to_string(gi[1].codepoint)
            mb, bb = box(mk), box(base)
            if not mb:
                continue
            ox, oy = gp[0].x_advance + gp[1].x_offset, gp[1].y_offset
            ccc = unicodedata.combining(chr(M))
            why = []
            cx = (mb[0] + mb[2]) / 2 + ox
            if not (bb[0] - 60 <= cx <= bb[2] + 60):
                why.append("off the letter")
            gapx = max(bb[0] - (mb[2] + ox), (mb[0] + ox) - bb[2], 0)
            gapy = max(bb[1] - (mb[3] + oy), (mb[1] + oy) - bb[3], 0)
            if max(gapx, gapy) > 400:
                why.append("far away")
            if ccc != 202 and not why:
                if base not in rcache:
                    rcache[base] = raster(gs, base, 0, 0)
                mr = raster(gs, mk, ox, oy)
                if ImageChops.logical_and(rcache[base], mr).getbbox():
                    why.append("touches the letter")
            if why:
                bad.append((chr(L), f"U+{M:04X}", ", ".join(why)))
    print(json.dumps({"letters": len(letters), "marks": len(marks), "pairs_flagged": len(bad)}))
    print("by reason:", Counter(w for *_, w in bad).most_common())
    print("by letter:", " ".join(f"{k}:{v}" for k, v in Counter(b[0] for b in bad).most_common(show)))
    print("by mark:", " ".join(f"{k}:{v}" for k, v in Counter(b[1] for b in bad).most_common(20)))
    out = Path(__file__).resolve().parent / "latin-mark-ink-audit.json"
    out.write_text(json.dumps({"font": Path(path).name, "pairs_flagged": len(bad), "flagged": bad}, ensure_ascii=False, indent=1) + "\n")

if __name__ == "__main__":
    main(sys.argv[1])
