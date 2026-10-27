import json
from collections import defaultdict
from pathlib import Path

import openpyxl
import pymupdf

from .config import load_config
from .pdfdocs import classify_pdf, parse_invoice


def verify_month(out_dir, cfg=None):
    """独立核对：汇总表 ↔ 记录 ↔ 原始凭证 ↔ 打印材料。"""
    cfg = cfg or load_config()
    out_dir = Path(out_dir)
    data = json.loads((out_dir / "汇总数据.json").read_text(encoding="utf-8"))
    st, recs = data["stats"], data["records"]
    bases = {k: Path(v) for k, v in data["bases"].items()}
    problems = []

    wb = openpyxl.load_workbook(out_dir / st["files"]["xlsx"])
    ws = wb["行程汇总"]
    rows = [r for r in ws.iter_rows(min_row=4, values_only=True) if isinstance(r[0], int)]
    if [r[0] for r in rows] != list(range(1, len(recs) + 1)):
        problems.append("汇总表序号不连续或与记录数不一致")
    for x, r in zip(rows, recs):
        if x[4] != r["person"] or abs((x[5] or 0) - (r["amount"] or 0)) > 0.005:
            problems.append(f"汇总表第{x[0]}条与记录不一致")
    if abs(sum(x[5] or 0 for x in rows) - st["total"]) > 0.005:
        problems.append("汇总表逐笔合计与统计合计不一致")

    by_inv = defaultdict(list)
    for r in recs:
        ev = r["evidence"]
        if r["type"] == "出租车":
            pay = ev.get("payment")
            if not pay:
                problems.append(f"第{r['seq']}条出租车缺支付记录")
            elif not (bases[r["person"]] / pay["file"]).is_file():
                problems.append(f"第{r['seq']}条支付截图文件不存在")
            elif abs(pay["amount"] - r["amount"]) > 0.005 and abs(pay["amount"] - (ev.get("toll") or 0) - r["amount"]) > 0.005:
                problems.append(f"第{r['seq']}条申报 {r['amount']} 与支付 {pay['amount']} 不符且无路桥费说明")
        elif r["type"] == "网约车":
            it, inv = ev.get("itinerary"), ev.get("invoice")
            if not it or abs(it["amount"] - r["amount"]) > 0.005:
                problems.append(f"第{r['seq']}条网约车与行程单金额不符")
            if not inv:
                problems.append(f"第{r['seq']}条网约车缺电子发票")
            else:
                by_inv[(r["person"], inv["file"])].append(r)
        else:
            problems.append(f"第{r['seq']}条类型未确定")
    for (person, f), rs in by_inv.items():
        p = bases[person] / f
        kind, text = classify_pdf(p)
        inv = parse_invoice(p, text, cfg) if kind == "invoice" else None
        s = round(sum(r["amount"] for r in rs), 2)
        if not inv or inv["total"] is None or abs(inv["total"] - s) > 0.005:
            problems.append(f"{person} 发票 {f} 金额 {inv and inv['total']} 与对应行程合计 {s} 不一致")
        elif not inv["buyer_ok"]:
            problems.append(f"{person} 发票 {f} 抬头/税号不符")

    doc = pymupdf.open(out_dir / st["files"]["print"])
    found = []
    for b in data["badges"]:
        txt = doc[b["page"]].get_text("text", clip=pymupdf.Rect(b["rect"])).strip()
        if txt != str(b["seq"]):
            problems.append(f"打印材料第{b['page'] + 1}页序号 {b['seq']} 未找到（读到“{txt}”）")
        found.append((b["page"], b["seq"]))
    order = [s for _, s in sorted(found, key=lambda x: x[0])]
    dedup = [s for i, s in enumerate(order) if i == 0 or s != order[i - 1]]
    expected = [r["seq"] for r in recs if (r["type"] == "出租车" and r["evidence"].get("payment")) or (r["type"] == "网约车" and r["evidence"].get("itinerary"))]
    if sorted(set(dedup)) != expected:
        problems.append("打印材料中的序号集合与汇总表不一致")
    if dedup != sorted(dedup):
        problems.append("打印材料中的序号顺序与汇总表不一致")
    doc.close()
    return {"ok": not problems, "count": len(recs), "total": st["total"], "problems": problems}
