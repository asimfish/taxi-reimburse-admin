import re

FROM_RE = re.compile(r"(?:从|由|自)(.+?)(返回|回到|回|前往|去往|去|到达|到|至|赴)")
TO_RE = re.compile(r"(?:返回|回到|返|回|前往|去往|去|到达|到|至|赴)(.+)$")


def place_group(text, cfg):
    t = str(text or "").lower().replace(" ", "")
    if not t:
        return None
    # 取匹配到的最长关键词，避免“合作单位”被“单位”归到学院
    best, size = None, 0
    for group, words in cfg["place_groups"].items():
        for w in words:
            w = w.lower().replace(" ", "")
            if w in t and len(w) > size:
                best, size = group, len(w)
    return best


def reason_direction(reason, cfg):
    """从公务事由推断 (出发类别, 目的类别)。"""
    r = str(reason or "")
    src = dst = None
    m = FROM_RE.search(r)
    if m:
        src = place_group(m.group(1), cfg)
        rest = r[m.start(2):]
    else:
        rest = r
    m2 = TO_RE.search(rest)
    if m2:
        dst = place_group(m2.group(1), cfg)
    elif re.search(r"返校|回校|返院|回院|返回$", r):
        dst = "学院"
    return src, dst


def check_row_text(row, cfg):
    """返回 [(level, code, message, suggestion)]。"""
    out = []
    reason = (row.get("reason") or "").strip()
    start, end = (row.get("start") or "").strip(), (row.get("end") or "").strip()
    if not start or not end:
        out.append(("error", "route_missing", "起止地不完整", "请分别填写起点和终点（或在“起止地”写成“起点 | 终点”）"))
    if not reason:
        out.append(("error", "reason_missing", "未填写公务事由", "请写明公务事由，例如“前往真机实验场地”“从实验场地返回学院”"))
    elif reason in cfg["vague_reasons"] or len(reason) < 3:
        out.append(("error", "reason_vague", f"公务事由“{reason}”不明确", "请写清楚去做什么，例如“前往深势科技开会”"))
    places = f"{start} {end}".lower()
    for kw in cfg["forbidden_place_keywords"]:
        if kw.lower() in places:
            out.append(("error", "place_forbidden", f"起止地含“{kw}”，与公务出行无法对应", "该行程不属于公务出行，请删除；如确属公务，请改写为实际公务地点并说明"))
            break
    else:
        for kw in cfg["suspicious_place_keywords"]:
            if kw.lower() in places:
                out.append(("warning", "place_suspicious", f"起止地含“{kw}”，需说明公务原因", "请在公务事由中写明该地点的公务用途，否则管理员可能删除该行程"))
                break
    if start and end and reason:
        sg, eg = place_group(start, cfg), place_group(end, cfg)
        rs, rd = reason_direction(reason, cfg)
        if rd and sg and eg and sg != eg:
            if sg == rd and (rs is None or eg == rs):
                out.append(("error", "direction_reversed", f"方向与事由相反：起止地是“{start} → {end}”，事由是“{reason}”", f"请改为“{end} | {start}”，或修改公务事由"))
            elif eg != rd:
                out.append(("warning", "direction_mismatch", f"终点“{end}”与事由“{reason}”的目的地不一致", "请确认起止地或公务事由"))
        elif rs and sg and eg and sg != eg and eg == rs and sg != rs:
            out.append(("error", "direction_reversed", f"方向与事由相反：起止地是“{start} → {end}”，事由是“{reason}”", f"请改为“{end} | {start}”，或修改公务事由"))
    return out
