import datetime as dt
import hashlib
import re
from collections import Counter
from pathlib import Path

from . import __version__
from .config import load_config, tax_hint
from .images import parse_image
from .pdfdocs import classify_pdf, parse_invoice, parse_itinerary
from .rules import check_row_text, place_group
from .table import read_tables

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".bmp"}
TABLE_EXT = {".xlsx", ".xlsm", ".csv"}
SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
EPS = 0.005


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _day(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def _eq(a, b):
    return a is not None and b is not None and abs(a - b) < EPS


def _fmt(a):
    return f"{a:.2f}" if isinstance(a, (int, float)) else "?"


def is_skipped(p):
    n = p.name
    return n.lower() in SKIP_NAMES or n.startswith(".") or n.startswith("~$") or n.startswith("修改说明") or "__MACOSX" in p.parts


def collect_files(root):
    root = Path(root)
    return sorted(p for p in root.rglob("*") if p.is_file() and not is_skipped(p.relative_to(root)))


def check_submission(root, name, month, cfg=None, cache_dir=None, progress=None, files=None, image_hook=None):
    """检查一个人一个月的报销材料。root 为材料目录。返回报告 dict。

    image_hook(path, info) -> info|None：OCR 规则识别不了的图片交给它（例如视觉模型）重新识别。
    """
    cfg = cfg or load_config()
    root = Path(root)
    files = files if files is not None else collect_files(root)
    issues = []

    def issue(level, code, message, suggestion="", row=None, file=None):
        issues.append({"level": level, "code": code, "message": message, "suggestion": suggestion, "row": row, "file": file})

    year = month[:4]
    inventory, tables, invoices, itins, images = [], [], [], [], []
    seen = {}
    for i, p in enumerate(files):
        rel = str(p.relative_to(root))
        if progress:
            progress(i, len(files), rel)
        digest = sha256_file(p)
        entry = {"path": rel, "sha256": digest, "size": p.stat().st_size, "kind": "other"}
        if digest in seen:
            entry["kind"] = "duplicate"
            entry["duplicate_of"] = seen[digest]
            inventory.append(entry)
            issue("tip", "file_duplicate", f"{rel} 与 {seen[digest]} 内容完全相同，已忽略", "无需重复上传同一文件", file=rel)
            continue
        seen[digest] = rel
        ext = p.suffix.lower()
        try:
            if ext in TABLE_EXT:
                entry["kind"] = "table"
                tables.append(p)
            elif ext == ".xls":
                issue("error", "table_xls", f"{rel} 是旧版 .xls 格式，无法读取", "请用 Excel/WPS 另存为 .xlsx 后重新上传", file=rel)
            elif ext == ".pdf":
                kind, text = classify_pdf(p)
                entry["kind"] = kind
                if kind == "invoice":
                    inv = parse_invoice(p, text, cfg)
                    inv.update({"file": rel, "sha256": digest})
                    invoices.append(inv)
                elif kind == "itinerary":
                    it = parse_itinerary(p, text, year)
                    it.update({"file": rel, "sha256": digest})
                    itins.append(it)
                elif kind == "scanned":
                    issue("warning", "pdf_scanned", f"{rel} 是图片型 PDF，无法读取文字", "电子发票、行程单请上传平台下载的原始 PDF；支付截图请直接上传图片", file=rel)
                else:
                    issue("warning", "pdf_unknown", f"{rel} 不是电子发票或行程单", "请确认是否传错文件", file=rel)
            elif ext in IMAGE_EXT:
                info = parse_image(p, cache_dir)
                if image_hook and (info["kind"] == "unknown" or (info["kind"] == "payment" and not info.get("entries"))):
                    info = image_hook(p, info) or info
                info.update({"file": rel, "sha256": digest})
                entry["kind"] = info["kind"]
                images.append(info)
            else:
                issue("warning", "file_ignored", f"{rel} 的格式无法处理，已忽略", "只接受 xlsx/csv 汇总表、PDF 电子发票与行程单、png/jpg 截图", file=rel)
        except Exception as e:  # noqa: BLE001
            entry["kind"] = "broken"
            issue("error", "file_broken", f"{rel} 无法打开或解析：{e}", "请确认文件未损坏，重新导出后上传", file=rel)
        inventory.append(entry)

    # 电子发票
    num_count = Counter(inv["number"] for inv in invoices if inv["number"])
    for inv in invoices:
        if not inv["buyer_ok"]:
            issue("error", "invoice_buyer", f"{inv['file']} 抬头或税号不符", f"请重新开具：抬头“{cfg['buyer_name']}”{tax_hint(cfg)}", file=inv["file"])
        if inv["total"] is None:
            issue("error", "invoice_total", f"{inv['file']} 读不到价税合计金额", "请上传平台下载的原始电子发票 PDF", file=inv["file"])
        if num_count[inv["number"]] > 1:
            issue("error", "invoice_dup", f"发票号码 {inv['number']} 出现了 {num_count[inv['number']]} 次", "同一张发票只能报销一次，请删除重复文件", file=inv["file"])

    # 行程单与发票配对
    for it in itins:
        for prob in it["problems"]:
            issue("warning", "itinerary_parse", f"{it['file']}：{prob}", "管理员将人工核对该行程单", file=it["file"])
    used_inv = set()
    for it in [x for x in itins if not x["is_taxi"]]:
        total = it["declared_total"] if it["declared_total"] is not None else round(sum(r["amount"] for r in it["rows"]), 2)
        cands = [k for k, inv in enumerate(invoices) if k not in used_inv and _eq(inv["total"], total)]
        if cands:
            stem = re.sub(r"(电子发票|电子行程单|行程报销单|行程单|发票).*$", "", Path(it["file"]).name)
            cands.sort(key=lambda k: (invoices[k]["platform"] != it["platform"], not Path(invoices[k]["file"]).name.startswith(stem) if stem else True, invoices[k]["file"]))
            used_inv.add(cands[0])
            it["invoice"] = cands[0]
        else:
            it["invoice"] = None
            issue("error", "itinerary_no_invoice", f"行程单 {it['file']}（合计 {_fmt(total)} 元）没有金额相同的电子发票", "请上传与该行程单配套的电子发票 PDF（发票价税合计应等于行程单合计）", file=it["file"])
    for k, inv in enumerate(invoices):
        if k not in used_inv:
            issue("error", "invoice_no_itinerary", f"电子发票 {inv['file']}（{_fmt(inv['total'])} 元）没有对应的行程单", "请上传与该发票同时开具的电子行程单 PDF", file=inv["file"])

    # 汇总表
    rows, notes = read_tables(tables, month) if tables else ([], [])
    for n in notes:
        issue("tip", "table_note", n)
    if not tables:
        issue("error", "table_missing", "没有找到个人打车汇总表（xlsx）", "请下载模板，按“日期、类型、起点、终点、公务事由、金额”逐笔填写后一起上传")
    elif not rows:
        issue("error", "table_empty", "汇总表中没有读到任何行程", "请使用模板，表头需包含“日期”“金额”等列")
    for i, r in enumerate(rows, 1):
        r["idx"] = i
        r["evidence"] = {}
        r["notes"] = []
        if not r["date"]:
            issue("error", "row_date", f"第{i}行日期无法识别（{r['source']}）", "日期请写成 2026-07-14 这样的格式", row=i)
        elif not r["date"].startswith(month):
            issue("error", "row_month", f"第{i}行日期 {r['date']} 不属于 {month}", "请把该行程放到对应月份提交", row=i)
        if r["amount"] is None or r["amount"] <= 0:
            issue("error", "row_amount", f"第{i}行金额无法识别", "金额请填数字，例如 45 或 45.50", row=i)
        if r["person"] and name and r["person"] != name:
            issue("warning", "row_person", f"第{i}行乘坐人“{r['person']}”与提交人“{name}”不一致", "每人只提交本人的行程", row=i)
        for level, code, msg, sug in check_row_text(r, cfg):
            issue(level, code, f"第{i}行：{msg}", sug, row=i)

    def desc(r):
        return f"第{r['idx']}行（{r['date']} {r['start']}→{r['end']} {_fmt(r['amount'])}元）"

    # 网约车：汇总表行 ↔ 行程单行
    evs = []
    for ii, it in enumerate(itins):
        if it["is_taxi"]:
            continue
        for tr in it["rows"]:
            evs.append({"it": ii, **tr, "used": False})
    pairs = []
    for r in rows:
        if r["type"] == "出租车" or not r["date"] or r["amount"] is None:
            continue
        for k, ev in enumerate(evs):
            if _eq(ev["amount"], r["amount"]):
                diff = abs((_day(ev["date"]) - _day(r["date"])).days)
                if diff <= 1:
                    pairs.append((diff, r["idx"], k))
    taken_rows = set()
    for diff, ridx, k in sorted(pairs):
        if ridx in taken_rows or evs[k]["used"]:
            continue
        r = rows[ridx - 1]
        ev = evs[k]
        ev["used"] = True
        taken_rows.add(ridx)
        it = itins[ev["it"]]
        inv = invoices[it["invoice"]] if it.get("invoice") is not None else None
        r["type"] = "网约车"
        r["evidence"]["itinerary"] = {k2: ev[k2] for k2 in ("no", "date", "time", "start", "end", "provider", "amount", "page", "y", "x")} | {"file": it["file"]}
        r["evidence"]["invoice"] = {"file": inv["file"], "number": inv["number"], "total": inv["total"]} if inv else None
        r["provider"] = ev["provider"] or it["provider"]
        if diff:
            r["notes"].append(f"行程单日期 {ev['date']}")
        sg_it, eg_it = place_group(ev["start"], cfg), place_group(ev["end"], cfg)
        sg, eg = place_group(r["start"], cfg), place_group(r["end"], cfg)
        if sg_it and eg_it and sg_it != eg_it and sg == eg_it and eg == sg_it:
            issue("error", "direction_vs_itinerary", f"第{ridx}行起止地与行程单方向相反（行程单：{ev['start']} → {ev['end']}）", f"请改为“{r['end']} | {r['start']}”，并核对公务事由", row=ridx)
        if not (sg == eg_it and eg == sg_it):
            for x in issues:
                if x["row"] == ridx and x["code"] == "direction_reversed" and sg_it and eg_it:
                    x["suggestion"] = f"行程单显示实际行程为“{ev['start']} → {ev['end']}”，起止地无误，请把公务事由改成与该方向一致的描述（例如返程写“从……返回学院”）"
    for r in rows:
        if r["type"] == "网约车" and r["idx"] not in taken_rows:
            issue("error", "platform_unmatched", f"{desc(r)} 在行程单中找不到", "请核对日期和金额是否与行程单一致；若缺少该笔的电子发票和行程单，请补充上传", row=r["idx"])
    for ev in evs:
        if not ev["used"]:
            it = itins[ev["it"]]
            issue("error", "itinerary_row_unclaimed", f"行程单 {it['file']} 第{ev['no']}笔（{ev['date']} {ev['time']} {ev['start']}→{ev['end']} {_fmt(ev['amount'])}元）没有填进汇总表", "请在汇总表补填该行程及公务事由；若不是公务行程，需重新开具不含该行程的发票和行程单", file=it["file"])

    # 支付记录
    pays = []
    for im in images:
        if im["kind"] != "payment":
            continue
        for e in im["entries"]:
            ride = e.get("ride_at") or ""
            if not ride and im.get("ride_hint") and len(im["entries"]) == 1:
                mo, d = im["ride_hint"]
                ride = f"{year}-{mo:02d}-{d:02d}"
            pays.append({"file": im["file"], "amount": e["amount"], "paid_at": e.get("paid_at") or "", "ride_at": ride, "orders": im["orders"] if len(im["entries"]) == 1 else [], "discount": im.get("discount"), "product": im.get("product", ""), "used": False})
    details = [dict(im, used=False) for im in images if im["kind"] == "detail"]

    def pay_score(p, r, amount):
        if not _eq(p["amount"], amount):
            return None
        if p["ride_at"]:
            diff = (_day(p["ride_at"]) - _day(r["date"])).days
            return 0 if diff == 0 else (1 if abs(diff) == 1 else None)
        if not p["paid_at"]:
            return 5
        diff = (_day(p["paid_at"]) - _day(r["date"])).days
        return 0 if diff == 0 else (1 if 1 <= diff <= 3 else (2 if diff == -1 else None))

    # 网约车可选的支付截图（金额一致）
    for r in rows:
        if r["type"] != "网约车" or "itinerary" not in r["evidence"]:
            continue
        best = min(((s, k) for k, p in enumerate(pays) if not p["used"] and (s := pay_score(p, r, r["amount"])) is not None and s < 5), default=None)
        if best:
            pays[best[1]]["used"] = True
            r["evidence"]["payment"] = {k: pays[best[1]][k] for k in ("file", "amount", "paid_at", "ride_at", "orders")}

    # 出租车：必须有支付记录
    taxi_rows = [r for r in rows if r["type"] in ("出租车", None) and r["date"] and r["amount"] is not None]
    pairs = []
    for r in taxi_rows:
        for k, p in enumerate(pays):
            if p["used"]:
                continue
            s = pay_score(p, r, r["amount"])
            if s is not None:
                pairs.append((s, r["idx"], k, None))
            elif p["amount"] > r["amount"] + EPS:
                # 支付含路桥费：需要车费明细截图证明差额
                for d in details:
                    if _eq(d.get("toll"), round(p["amount"] - r["amount"], 2)) and (not d.get("date") or abs((_day(d["date"]) - _day(r["date"])).days) <= 1):
                        s2 = pay_score(p, r, p["amount"])
                        if s2 is not None:
                            pairs.append((3 + s2, r["idx"], k, d["file"]))
    taken = set()
    for s, ridx, k, dfile in sorted(pairs, key=lambda x: (x[0], x[1], x[2])):
        if ridx in taken or pays[k]["used"]:
            continue
        r = rows[ridx - 1]
        p = pays[k]
        p["used"] = True
        taken.add(ridx)
        r["type"] = "出租车"
        r["evidence"]["payment"] = {kk: p[kk] for kk in ("file", "amount", "paid_at", "ride_at", "orders")}
        supp = []
        if dfile:
            d = next(d for d in details if d["file"] == dfile)
            d["used"] = True
            supp.append(dfile)
            r["evidence"]["toll"] = d["toll"]
            r["notes"].append(f"支付{_fmt(p['amount'])}元，扣除路桥费{_fmt(d['toll'])}元")
        if p.get("discount"):
            r["notes"].append(f"优惠券抵扣{_fmt(p['discount'])}元，按实付填写")
            r["evidence"]["coupon"] = p["discount"]
        # 同一笔的补充截图（同日、实付金额一致）
        for d in details:
            if d["used"]:
                continue
            same_day = d.get("date") and abs((_day(d["date"]) - _day(r["date"])).days) <= 1
            stem_link = Path(d["file"]).stem.replace("补充", "").strip() == Path(p["file"]).stem
            if stem_link or (same_day and (_eq(d.get("pay_amount"), p["amount"]) or _eq(d.get("fare"), r["amount"]))):
                d["used"] = True
                supp.append(d["file"])
                if d.get("coupon") and "coupon" not in r["evidence"]:
                    r["evidence"]["coupon"] = d["coupon"]
                    r["notes"].append(f"优惠券抵扣{_fmt(d['coupon'])}元，按实付填写")
                if d.get("toll") and "toll" not in r["evidence"] and _eq(round(p["amount"] - d["toll"], 2), r["amount"]):
                    r["evidence"]["toll"] = d["toll"]
        if supp:
            r["evidence"]["supplements"] = supp
    for r in taxi_rows:
        if r["idx"] in taken:
            continue
        near = [p for p in pays if not p["used"] and (_day(p["ride_at"] or p["paid_at"]) if (p["ride_at"] or p["paid_at"]) else None) and 0 <= ((_day(p["ride_at"] or p["paid_at"]) - _day(r["date"])).days) <= (1 if p["ride_at"] else 3)]
        hint = "（汇总表未注明类型，按出租车核对）" if r["type"] is None else ""
        r["type"] = "出租车"
        if near:
            p = min(near, key=lambda p: abs(p["amount"] - r["amount"]))
            p["used"] = True
            r["evidence"]["near_payment"] = {k: p[k] for k in ("file", "amount", "paid_at", "ride_at")}
            for d in details:
                if not d["used"] and (Path(d["file"]).stem.replace("补充", "").strip() == Path(p["file"]).stem):
                    d["used"] = True
            if p["amount"] > r["amount"]:
                issue("error", "taxi_less_than_paid", f"{desc(r)} 与同日支付记录 {p['file']}（{_fmt(p['amount'])}元）金额不一致{hint}", f"若差额 {_fmt(p['amount'] - r['amount'])} 元是路桥费/高速费，请上传显示该费用的车费明细截图（文件名可写“{Path(p['file']).stem}补充”）；否则请按实际支付金额填写", row=r["idx"])
            else:
                cd = next((d for d in details if d.get("coupon") and (_eq(d.get("fare"), r["amount"]) or _eq(d.get("pay_amount"), p["amount"]))), None)
                if cd:
                    sug = f"车费明细 {cd['file']} 显示优惠券抵扣 {_fmt(cd['coupon'])} 元，请把金额改为实付 {_fmt(p['amount'])} 元"
                else:
                    sug = f"如使用了优惠券，报销金额必须填写优惠后的实付金额 {_fmt(p['amount'])} 元，并上传显示优惠券抵扣的截图"
                issue("error", "taxi_more_than_paid", f"{desc(r)} 大于同日实际支付 {_fmt(p['amount'])} 元（{p['file']}）{hint}", sug, row=r["idx"])
        else:
            issue("error", "taxi_no_payment", f"{desc(r)} 缺少支付记录截图{hint}", "出租车每一笔都需要支付记录截图（显示金额与支付/乘车时间）；网约车请上传电子发票和行程单", row=r["idx"])

    # 网约车支付金额与行程单不一致
    for r in rows:
        if r["type"] != "网约车" or "payment" in r["evidence"] or "itinerary" not in r["evidence"]:
            continue
        it_date = r["evidence"]["itinerary"]["date"]
        for p in pays:
            if p["used"]:
                continue
            if p["ride_at"]:
                if p["ride_at"][:10] != it_date:
                    continue
                t = r["evidence"]["itinerary"].get("time")
                if t and p["ride_at"][11:16] and abs(int(t[:2]) * 60 + int(t[3:5]) - int(p["ride_at"][11:13]) * 60 - int(p["ride_at"][14:16])) > 30:
                    continue
            elif not p["paid_at"] or not 0 <= (_day(p["paid_at"]) - _day(it_date)).days <= 1 or abs(p["amount"] - r["amount"]) > max(5, r["amount"] * 0.2):
                continue
            p["used"] = True
            r["evidence"]["payment"] = {k: p[k] for k in ("file", "amount", "paid_at", "ride_at", "orders")}
            linked = [d for d in details if not d["used"] and d.get("date") and d["date"][:10] == r["date"]]
            if p.get("discount") and _eq(round(p["amount"] + p["discount"], 2), r["amount"]):
                r["notes"].append(f"实付{_fmt(p['amount'])}元，支付截图显示优惠{_fmt(p['discount'])}元，按电子发票金额填写")
            elif linked:
                for d in linked:
                    d["used"] = True
                r["evidence"]["supplements"] = [d["file"] for d in linked]
                r["notes"].append(f"实付{_fmt(p['amount'])}元，行程单{_fmt(r['amount'])}元，已附说明截图")
            else:
                issue("warning", "platform_paid_diff", f"{desc(r)} 实际支付 {_fmt(p['amount'])} 元，与行程单金额不一致（{p['file']}）", "请补充显示优惠券/费用明细的截图；汇总按电子发票与行程单金额填写", row=r["idx"])
            break

    for p in pays:
        if not p["used"]:
            when = p["ride_at"] or p["paid_at"] or "日期未识别"
            issue("warning", "payment_unused", f"支付记录 {p['file']}（{when} {_fmt(p['amount'])}元）没有对应汇总表中的行程", "请确认是否漏填该行程、日期金额写错，或误传了其他截图", file=p["file"])
    for d in details:
        if not d["used"]:
            issue("tip", "detail_unused", f"补充截图 {d['file']} 未能自动对应到某一笔", "管理员会人工查看；建议把补充截图命名为“支付截图文件名+补充”", file=d["file"])
    for im in images:
        if im["kind"] == "unknown":
            issue("warning", "image_unknown", f"图片 {im['file']} 无法识别为支付记录", "请上传完整的支付详情截图（需显示金额、支付时间），不要裁剪", file=im["file"])
    has_taxi = any(r["type"] == "出租车" for r in rows)
    if has_taxi and not any(im["kind"] == "taxi_invoice_photo" for im in images):
        issue("tip", "taxi_photo", "未发现出租车纸质发票照片", "建议把出租车纸质发票按汇总表顺序贴在 A4 纸上拍照一起上传（非必须，纸质发票原件仍需交给管理员）")

    # 出租车行程单（高德出租车）作为辅助凭证
    for it in [x for x in itins if x["is_taxi"]]:
        for tr in it["rows"]:
            r = next((r for r in rows if r["type"] == "出租车" and r["date"] == tr["date"] and _eq(r["amount"], tr["amount"]) and "taxi_itinerary" not in r["evidence"]), None)
            if r:
                r["evidence"]["taxi_itinerary"] = {"file": it["file"], "no": tr["no"], "page": tr["page"], "y": tr["y"], "start": tr["start"], "end": tr["end"]}

    # 备注标签
    def ride_time(r):
        p = r["evidence"].get("payment") or {}
        return (p.get("ride_at") or p.get("paid_at") or "")[11:]

    taxi_sorted = sorted([r for r in rows if r["type"] == "出租车"], key=lambda r: (r["date"] or "", ride_time(r), r["idx"]))
    for n, r in enumerate(taxi_sorted, 1):
        r["label"] = f"出租车发票{n:02d}"
    prov_inv = Counter()
    for it in itins:
        if not it["is_taxi"] and it.get("invoice") is not None:
            prov_inv[it["provider"]] += 1
    for r in rows:
        if r["type"] == "网约车" and "invoice" in r["evidence"]:
            prov = r.get("provider") or "网约车"
            inv = r["evidence"]["invoice"]
            r["label"] = f"{prov}（{_fmt(inv['total'])}）" if inv and prov_inv[prov] > 1 else prov
        r.setdefault("label", r["type"] or "")

    for r in rows:
        r["issues"] = [k for k, x in enumerate(issues) if x["row"] == r["idx"]]

    counts = Counter(x["level"] for x in issues)
    taxi_total = round(sum(r["amount"] or 0 for r in rows if r["type"] == "出租车"), 2)
    plat_total = round(sum(r["amount"] or 0 for r in rows if r["type"] == "网约车"), 2)
    trips = []
    for r in rows:
        ev = r["evidence"]
        if "itinerary" in ev:
            trips.append(f"{ev['itinerary']['provider']}|{ev['itinerary']['date']} {ev['itinerary']['time']}|{_fmt(ev['itinerary']['amount'])}")
        if "payment" in ev and ev["payment"]["paid_at"]:
            trips.append(f"pay|{ev['payment']['paid_at']}|{_fmt(ev['payment']['amount'])}")
    return {
        "tool_version": __version__,
        "name": name,
        "month": month,
        "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passed": counts["error"] == 0,
        "counts": {"error": counts["error"], "warning": counts["warning"], "tip": counts["tip"]},
        "totals": {"count": len(rows), "taxi": taxi_total, "platform": plat_total, "all": round(taxi_total + plat_total, 2)},
        "rows": rows,
        "issues": issues,
        "files": inventory,
        "invoices": invoices,
        "itineraries": [{k: v for k, v in it.items()} for it in itins],
        "images": [{k: (v[:1500] if k == "text" else v) for k, v in im.items() if k != "text" or im["kind"] == "unknown"} for im in images],
        "fingerprints": {
            "files": sorted(e["sha256"] for e in inventory if e["kind"] not in ("duplicate", "table", "other")),
            "invoices": sorted(inv["number"] for inv in invoices if inv["number"]),
            "orders": sorted({o for p in pays for o in p["orders"]}),
            "trips": sorted(set(trips)),
        },
    }
