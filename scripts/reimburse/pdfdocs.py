import re

import pymupdf

MONEY = re.compile(r"^[¥￥]?(\d{1,6}\.\d{2})元?$")
TAXI_PROVIDER_HINTS = ("出租", "的士", "金银建", "渔阳", "北汽", "新月", "首汽出租", "银建", "祥龙")


def pdf_text(path):
    with pymupdf.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)


def classify_pdf(path):
    text = pdf_text(path)
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return "scanned", text
    if "发票号码" in compact and ("价税合计" in compact or "电子发票" in compact or "普通发票" in compact):
        return "invoice", text
    if "行程单" in compact or "ITINERARY" in compact.upper() or "TRIPTABLE" in compact.upper() or "行程报销单" in compact:
        return "itinerary", text
    return "unknown", text


def parse_invoice(path, text, cfg):
    compact = re.sub(r"\s+", "", text)
    num = re.search(r"发票号码[：:]?(\d{8,24})", compact)
    date = re.search(r"开票日期[：:]?(\d{4})年(\d{1,2})月(\d{1,2})日", compact)
    total = None
    with pymupdf.open(path) as doc:
        for page in doc:
            words = page.get_text("words")
            for w in words:
                if "小写" in w[4]:
                    ymid = (w[1] + w[3]) / 2
                    cands = [x for x in words if x[0] > w[0] and abs((x[1] + x[3]) / 2 - ymid) < 8 and MONEY.match(x[4].replace(",", ""))]
                    if cands:
                        total = float(MONEY.match(min(cands, key=lambda x: x[0])[4].replace(",", "")).group(1))
                        break
            if total is not None:
                break
    if total is None:
        m = re.search(r"小写[）)]?[¥￥]?(\d+\.\d{2})", compact) or re.search(r"[（(]小写[）)].*?(\d+\.\d{2})", compact)
        total = float(m.group(1)) if m else None
    sellers = re.findall(r"名称[：:]([^\n名统]+)", compact)
    seller = next((s for s in sellers if cfg["buyer_name"] not in s), "")
    return {
        "number": num.group(1) if num else "",
        "date": f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else "",
        "total": total,
        "buyer_ok": cfg["buyer_name"] in compact and (not cfg.get("buyer_tax_id") or cfg["buyer_tax_id"] in compact),
        "buyer_name_ok": cfg["buyer_name"] in compact,
        "seller": seller,
        "platform": "滴滴" if "滴滴" in compact else ("高德" if "高德" in compact or "AMAP" in compact.upper() else ""),
    }


def _center(w):
    return (w[0] + w[2]) / 2


def parse_itinerary(path, text, year_hint):
    compact = re.sub(r"\s+", "", text)
    platform = "高德" if ("高德" in compact or "AMAP" in compact.upper()) else ("滴滴" if "滴滴" in compact else "")
    cnt = re.search(r"共(?:计)?(\d+)[单笔]行程", compact)
    tot = re.search(r"合计(\d+(?:\.\d{1,2})?)元", compact)
    rows, problems = [], []
    heads = None
    with pymupdf.open(path) as doc:
        for pi, page in enumerate(doc):
            words = page.get_text("words")
            hdr = next((w for w in words if w[4].startswith("序号")), None)
            if hdr:
                hy = (hdr[1] + hdr[3]) / 2
                heads = {w[4]: w for w in words if abs((w[1] + w[3]) / 2 - hy) < 4}
                head_y = hdr[3]
            elif heads is None:
                continue
            else:
                head_y = 0
            names = sorted(heads.values(), key=lambda w: w[0])
            centers = [(w[4], _center(w)) for w in names]

            def col_of(x):
                best = None
                for i, (name, c) in enumerate(centers):
                    left = (centers[i - 1][1] + c) / 2 if i else -1e9
                    right = (c + centers[i + 1][1]) / 2 if i + 1 < len(centers) else 1e9
                    if left <= x < right:
                        best = name
                return best

            seq_x = next(w for k, w in heads.items() if k.startswith("序号"))[0]
            bottom_limit = page.rect.height - 40
            nums = [w for w in words if w[4].isdigit() and abs(w[0] - seq_x) < 14 and w[1] > head_y + 2 and w[1] < bottom_limit]
            nums.sort(key=lambda w: w[1])
            for i, n in enumerate(nums):
                top = (nums[i - 1][1] + n[1]) / 2 if i else head_y + 1
                bot = (n[1] + nums[i + 1][1]) / 2 if i + 1 < len(nums) else n[3] + 26
                body = [w for w in words if top <= (w[1] + w[3]) / 2 < bot and w is not n]
                cells = {}
                for w in sorted(body, key=lambda w: (round(w[1] / 3), w[0])):
                    cells.setdefault(col_of(_center(w)), []).append(w[4])
                joined = {k: "".join(v) for k, v in cells.items() if k}
                alltext = " ".join(w[4] for w in body)
                dm = re.search(r"(20\d\d)-(\d\d)-(\d\d)", alltext) or re.search(r"(?<!\d)(\d\d)-(\d\d)(?!\d)", alltext)
                tm = re.search(r"(?<!\d)(\d\d):(\d\d)(?!\d)", alltext)
                amount_col = next((k for k in joined if k.startswith("金额")), None)
                amounts = [float(MONEY.match(w[4]).group(1)) for w in body if MONEY.match(w[4]) and (amount_col is None or col_of(_center(w)) == amount_col)]
                if not dm or not amounts:
                    problems.append(f"第{pi + 1}页第{n[4]}行无法读取日期或金额")
                    continue
                if len(dm.groups()) == 3:
                    date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
                else:
                    date = f"{year_hint}-{dm.group(1)}-{dm.group(2)}"
                rows.append({
                    "no": int(n[4]),
                    "date": date,
                    "time": f"{tm.group(1)}:{tm.group(2)}" if tm else "",
                    "start": joined.get("起点", ""),
                    "end": joined.get("终点", ""),
                    "provider": joined.get("服务商", "") or ("滴滴出行" if platform == "滴滴" else ""),
                    "amount": amounts[-1],
                    "page": pi,
                    "y": round((n[1] + n[3]) / 2, 1),
                    "x": round(n[0], 1),
                })
    declared_count = int(cnt.group(1)) if cnt else None
    declared_total = float(tot.group(1)) if tot else None
    if declared_count is not None and declared_count != len(rows):
        problems.append(f"行程单声明{declared_count}笔，实际读取{len(rows)}笔")
    if declared_total is not None and abs(sum(r["amount"] for r in rows) - declared_total) > 0.005:
        problems.append(f"行程单合计{declared_total:.2f}元与逐笔合计{sum(r['amount'] for r in rows):.2f}元不一致")
    providers = [r["provider"] for r in rows if r["provider"]]
    is_taxi = "出租车" in path.name or (providers and all(any(h in p for h in TAXI_PROVIDER_HINTS) for p in providers) and platform == "高德")
    return {
        "platform": platform,
        "declared_count": declared_count,
        "declared_total": declared_total,
        "rows": rows,
        "problems": problems,
        "provider": providers[0] if providers else ("滴滴出行" if platform == "滴滴" else platform),
        "is_taxi": bool(is_taxi),
    }
