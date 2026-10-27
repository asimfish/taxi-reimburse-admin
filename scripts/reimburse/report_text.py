LEVEL_NAME = {"error": "必须修改", "warning": "需要确认", "tip": "提示"}


def report_to_text(rep):
    lines = []
    t = rep["totals"]
    status = "通过" if rep["passed"] else "未通过"
    lines.append(f"【{rep['name'] or '未填姓名'} {rep['month']} 打车报销自查：{status}】")
    lines.append(f"共 {t['count']} 笔，出租车 {t['taxi']:.2f} 元，网约车 {t['platform']:.2f} 元，合计 {t['all']:.2f} 元")
    c = rep["counts"]
    lines.append(f"必须修改 {c['error']} 项，需要确认 {c['warning']} 项，提示 {c['tip']} 项")
    ai = rep.get("ai") or {}
    if ai.get("status") == "ok" and ai.get("summary"):
        lines.append(f"模型复核：{ai['summary']}")
    for level in ("error", "warning", "tip"):
        items = [x for x in rep["issues"] if x["level"] == level]
        if not items:
            continue
        lines.append("")
        lines.append(f"== {LEVEL_NAME[level]} ==")
        for k, x in enumerate(items, 1):
            lines.append(f"{k}. {x['message']}")
            if x["suggestion"]:
                lines.append(f"   修改建议：{x['suggestion']}")
    lines.append("")
    lines.append("== 逐笔核对 ==")
    for r in rep["rows"]:
        ev = r["evidence"]
        if "itinerary" in ev:
            src = f"行程单{ev['itinerary']['file']}第{ev['itinerary']['no']}笔"
        elif "payment" in ev:
            src = f"支付{ev['payment']['file']}"
        else:
            src = "未找到凭证"
        amt = f"{r['amount']:.2f}" if r["amount"] is not None else "?"
        note = ("；" + "；".join(r["notes"])) if r["notes"] else ""
        lines.append(f"{r['idx']:>3}. {r['date']} {r['type'] or '?'} {r['start']} → {r['end']} {amt}元 [{r.get('label', '')}] {src}{note}")
    return "\n".join(lines)
