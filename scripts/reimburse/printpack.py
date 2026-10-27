import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

A4 = (595, 842)
RED = (0.85, 0.1, 0.1)
_font = None


def _cjk():
    global _font
    if _font is None:
        _font = pymupdf.Font("cjk")
    return _font


def _text(page, xy, s, size=10, color=(0, 0, 0)):
    tw = pymupdf.TextWriter(page.rect)
    tw.append(xy, s, font=_cjk(), fontsize=size)
    tw.write_text(page, color=color)


def _badge(page, cx, cy, seq, r=9):
    page.draw_circle((cx, cy), r, color=RED, fill=RED)
    s = str(seq)
    size = 9 if len(s) < 3 else 7
    w = pymupdf.get_text_length(s, fontname="hebo", fontsize=size)
    page.insert_text((cx - w / 2, cy + size * 0.36), s, fontname="hebo", fontsize=size, color=(1, 1, 1))
    return [cx - r, cy - r, cx + r, cy + r]


def _image_bytes(path):
    if Path(path).suffix.lower() in (".heic", ".heif"):
        from pillow_heif import register_heif_opener

        register_heif_opener()
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(img.size) > 1600:
        img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def build_print_pack(month, persons, records, out_path):
    """persons: [{name, base, report}]；records: 汇总后的记录（含 seq、person、evidence）。返回徽标位置列表。"""
    y, m = month[:4], int(month[5:])
    doc = pymupdf.open()
    badges = []
    cover = doc.new_page(width=A4[0], height=A4[1])
    _text(cover, (60, 80), f"{y}年{m}月 打车报销打印材料", 20)
    _text(cover, (60, 108), "出租车：支付记录截图（每页 6 张，红色圆圈为汇总表序号）；网约车：电子行程单（序号标在对应行左侧）", 9, (0.3, 0.3, 0.3))
    yy = 150
    _text(cover, (60, yy), "乘坐人", 11)
    _text(cover, (170, yy), "汇总表序号", 11)
    _text(cover, (290, yy), "笔数", 11)
    _text(cover, (350, yy), "金额（元）", 11)
    _text(cover, (450, yy), "起始页", 11)
    cover_rows = []
    total = 0
    by_person = {}
    for r in records:
        by_person.setdefault(r["person"], []).append(r)
    base_of = {p["name"]: Path(p["base"]) for p in persons}
    for name, recs in by_person.items():
        start_page = doc.page_count + 1
        base = base_of[name]
        taxi = [r for r in recs if r["type"] == "出租车" and "payment" in r["evidence"]]
        cells = []
        for r in taxi:
            cells.append((r, r["evidence"]["payment"]["file"], False))
            for s in r["evidence"].get("supplements", []):
                cells.append((r, s, True))
        for k in range(0, len(cells), 6):
            page = doc.new_page(width=A4[0], height=A4[1])
            chunk = cells[k:k + 6]
            seqs = [c[0]["seq"] for c in chunk]
            _text(page, (28, 30), f"{name}  出租车支付记录  汇总表第 {min(seqs)}–{max(seqs)} 条", 11)
            cw, ch = (A4[0] - 56) / 3, (A4[1] - 70) / 2
            for i, (r, f, supp) in enumerate(chunk):
                x0 = 28 + (i % 3) * cw
                y0 = 46 + (i // 3) * ch
                cap = f"{r['date'][5:]}  {r['amount']:.2f}元" + ("  补充" if supp else "")
                _text(page, (x0 + 24, y0 + 14), cap, 9)
                badges.append({"seq": r["seq"], "page": page.number, "rect": _badge(page, x0 + 11, y0 + 10, r["seq"]), "file": f})
                rect = pymupdf.Rect(x0 + 4, y0 + 22, x0 + cw - 4, y0 + ch - 6)
                page.insert_image(rect, stream=_image_bytes(base / f), keep_proportion=True)
                page.draw_rect(rect, color=(0.8, 0.8, 0.8), width=0.5)
        # 网约车：按行程单文件分组
        groups = []
        for r in recs:
            if r["type"] == "网约车" and "itinerary" in r["evidence"]:
                f = r["evidence"]["itinerary"]["file"]
                if not groups or groups[-1][0] != f:
                    groups.append((f, []))
                groups[-1][1].append(r)
        for f, rs in groups:
            src = pymupdf.open(base / f)
            first = doc.page_count
            doc.insert_pdf(src)
            src.close()
            seqs = [r["seq"] for r in rs]
            for r in rs:
                ev = r["evidence"]["itinerary"]
                page = doc[first + ev["page"]]
                cx = max(12, ev["x"] - 14)
                badges.append({"seq": r["seq"], "page": page.number, "rect": _badge(page, cx, ev["y"], r["seq"]), "file": f})
            for pn in range(first, doc.page_count):
                pg = doc[pn]
                _text(pg, (28, pg.rect.height - 18), f"{name}  网约车行程单  汇总表第 {min(seqs)}–{max(seqs)} 条  合计 {sum(r['amount'] for r in rs):.2f} 元", 9, (0.2, 0.2, 0.2))
        amt = round(sum(r["amount"] for r in recs), 2)
        total += amt
        cover_rows.append((name, f"{recs[0]['seq']}–{recs[-1]['seq']}", len(recs), amt, start_page if doc.page_count >= start_page else "-"))
    cover = doc[0]
    for name, rng, n, amt, sp in cover_rows:
        yy += 22
        _text(cover, (60, yy), name, 11)
        _text(cover, (170, yy), rng, 11)
        _text(cover, (290, yy), str(n), 11)
        _text(cover, (350, yy), f"{amt:.2f}", 11)
        _text(cover, (450, yy), str(sp), 11)
    yy += 30
    _text(cover, (60, yy), f"合计 {len(records)} 笔，{total:.2f} 元", 12)
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return badges


def build_taxi_pack(month, persons, records, out_path):
    """只含出租车支付记录：按人、再按出租车发票顺序（乘车时间）排列，供对照纸质发票人工核对。返回页数。"""
    y, m = month[:4], int(month[5:])
    doc = pymupdf.open()
    cover = doc.new_page(width=A4[0], height=A4[1])
    _text(cover, (60, 80), f"{y}年{m}月 出租车支付记录汇总（核对纸质发票用）", 18)
    _text(cover, (60, 106), "顺序：按乘坐人，再按出租车发票编号（乘车时间先后）；红圈为汇总表序号，补充截图紧跟在对应支付记录之后", 9, (0.3, 0.3, 0.3))
    base_of = {p["name"]: Path(p["base"]) for p in persons}
    by_person = {}
    for r in records:
        if r["type"] == "出租车" and "payment" in r["evidence"]:
            by_person.setdefault(r["person"], []).append(r)
    rows = []
    for name, recs in by_person.items():
        recs.sort(key=lambda r: r.get("label") or "")
        start = doc.page_count + 1
        cells = []
        for r in recs:
            cells.append((r, r["evidence"]["payment"]["file"], False))
            cells += [(r, s, True) for s in r["evidence"].get("supplements", [])]
        for k in range(0, len(cells), 6):
            page = doc.new_page(width=A4[0], height=A4[1])
            chunk = cells[k:k + 6]
            labels = [c[0].get("label", "") for c in chunk]
            _text(page, (28, 30), f"{name}  出租车支付记录  {labels[0]} – {labels[-1]}（共 {len(recs)} 张发票）", 11)
            _text(page, (A4[0] - 120, 30), f"第 {page.number + 1} 页", 9, (0.4, 0.4, 0.4))
            cw, ch = (A4[0] - 56) / 3, (A4[1] - 70) / 2
            for i, (r, f, supp) in enumerate(chunk):
                x0 = 28 + (i % 3) * cw
                y0 = 46 + (i // 3) * ch
                p = r["evidence"]["payment"]
                when = (p.get("ride_at") or p.get("paid_at") or r["date"])[5:16]
                cap = f"{r.get('label', '')}  {when}  {r['amount']:.2f}元" + ("  补充截图" if supp else "")
                _text(page, (x0 + 24, y0 + 14), cap, 8)
                _badge(page, x0 + 11, y0 + 10, r["seq"])
                rect = pymupdf.Rect(x0 + 4, y0 + 22, x0 + cw - 4, y0 + ch - 6)
                page.insert_image(rect, stream=_image_bytes(base_of[name] / f), keep_proportion=True)
                page.draw_rect(rect, color=(0.8, 0.8, 0.8), width=0.5)
        rows.append((name, len(recs), round(sum(r["amount"] for r in recs), 2), start))
    cover = doc[0]
    yy = 150
    for i, h in enumerate(["乘坐人", "发票张数", "金额（元）", "起始页"]):
        _text(cover, (60 + i * 110, yy), h, 11)
    for name, n, amt, sp in rows:
        yy += 22
        for i, v in enumerate([name, str(n), f"{amt:.2f}", str(sp)]):
            _text(cover, (60 + i * 110, yy), v, 11)
    yy += 30
    _text(cover, (60, yy), f"合计 {sum(r[1] for r in rows)} 张，{sum(r[2] for r in rows):.2f} 元", 12)
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)
    n = doc.page_count
    doc.close()
    return n


def build_invoice_pack(persons, records, out_path):
    doc = pymupdf.open()
    base_of = {p["name"]: Path(p["base"]) for p in persons}
    seen = []
    for r in records:
        inv = r["evidence"].get("invoice") if r["type"] == "网约车" else None
        if not inv:
            continue
        key = (r["person"], inv["file"])
        if seen and seen[-1]["key"] == key:
            seen[-1]["seqs"].append(r["seq"])
        elif key not in [s["key"] for s in seen]:
            seen.append({"key": key, "inv": inv, "seqs": [r["seq"]]})
        else:
            next(s for s in seen if s["key"] == key)["seqs"].append(r["seq"])
    for s in seen:
        name, f = s["key"]
        src = pymupdf.open(base_of[name] / f)
        first = doc.page_count
        doc.insert_pdf(src)
        src.close()
        for pn in range(first, doc.page_count):
            pg = doc[pn]
            _text(pg, (28, pg.rect.height - 12), f"{name} · 汇总表第 {min(s['seqs'])}–{max(s['seqs'])} 条 · 发票 {s['inv']['number']} · {s['inv']['total']:.2f} 元", 8, (0.75, 0.1, 0.1))
    if doc.page_count == 0:
        doc.new_page(width=A4[0], height=A4[1])
        _text(doc[0], (60, 80), "本月没有网约车电子发票", 14)
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return [{"person": s["key"][0], "file": s["key"][1], "number": s["inv"]["number"], "total": s["inv"]["total"], "seqs": s["seqs"]} for s in seen]
