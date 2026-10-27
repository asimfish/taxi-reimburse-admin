import re

from .ocr import group_rows, ocr_boxes

DT_RE = re.compile(r"(20\d\d)\s*[-年./]\s*(\d{1,2})\s*[-月./]\s*(\d{1,2})\s*日?\s*(?:(\d{1,2})\s*[:：]\s*(\d{2})(?:\s*[:：]\s*(\d{2}))?)?")
NEG_AMOUNT_RE = re.compile(r"^[-－−—–]\s*[¥￥]?\s*(\d{1,5}(?:[.,]\d{1,2})?)\s*元?$")
YUAN_AMOUNT_RE = re.compile(r"[¥￥]?\s*(\d{1,5}\.\d{1,2})\s*元")
PLAIN_MONEY_RE = re.compile(r"(\d{1,5}\.\d{2})")
ORDER_RE = re.compile(r"[0-9A-Za-z_]{16,}")
TAXI_INVOICE_HINTS = ["出租汽车", "出租车发票", "发票联", "发票代码", "监督电话", "车号", "单价", "等候", "里程", "计程", "通用机打", "taxi", "invoice", "distance", "priceperkm", "certificate"]
TOLL_WORDS = ("路桥", "过路", "高速", "过桥", "通行费", "停车费")
COUPON_WORDS = ("优惠", "抵扣", "立减", "红包", "折扣", "券", "减免")


def _dt(text):
    m = DT_RE.search(text)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    try:
        date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
            return None
    except ValueError:
        return None
    if hh is not None and int(hh) < 24:
        return f"{date} {int(hh):02d}:{mm}:{ss or '00'}"
    return date


def _num(s):
    return round(float(s.replace(",", ".")), 2)


def _row_value(rows, labels):
    for r in rows:
        for lb in labels:
            if lb in r["text"]:
                return r
    return None


def _amount_in(text):
    m = YUAN_AMOUNT_RE.search(text) or PLAIN_MONEY_RE.search(text)
    return _num(m.group(1)) if m else None


def parse_image(path, cache_dir=None):
    ocr = ocr_boxes(path, cache_dir)
    rows = group_rows(ocr["boxes"])
    full = "\n".join(r["text"] for r in rows)
    info = {"kind": "unknown", "text": full[:4000]}

    neg = []
    for r in rows:
        # 支付金额在截图中独占一行；费用明细里的“优惠券抵扣 -1.00元”不算
        if len(r["parts"]) != 1:
            continue
        m = NEG_AMOUNT_RE.match(r["parts"][0]["text"].replace(" ", ""))
        if m and _num(m.group(1)) > 0:
            neg.append((r["y"], _num(m.group(1))))
    pay_page = bool(re.search(r"账单详情|支付时间|付款时间|支付成功|交易单号|扣款成功|全部账单", full))
    photo_hits = sum(h.lower() in full.lower() for h in TAXI_INVOICE_HINTS)
    if photo_hits >= 2 and not pay_page:
        info["kind"] = "taxi_invoice_photo"
        return info
    m = re.search(r"原价\s*[¥￥]?\s*(\d{1,5}\.\d{2})", full)
    info["original_price"] = _num(m.group(1)) if m else None

    toll = coupon = fare = pay_amount = None
    for i, r in enumerate(rows):
        t = r["text"]
        if any(w in t for w in TOLL_WORDS):
            a = _amount_in(t)
            if a is not None:
                toll = round((toll or 0) + a, 2)
        elif any(w in t for w in COUPON_WORDS) and any(s in t for s in ("-", "－", "元", "¥", "￥")):
            a = _amount_in(t)
            if a is not None:
                coupon = round((coupon or 0) + a, 2)
        elif re.match(r"^(车费|行程费|里程费|起步价|总价|订单金额)", t):
            fare = _amount_in(t) if fare is None else fare
        if ("支付金额" in t or "实付" in t) and pay_amount is None:
            pay_amount = _amount_in(t)
            if pay_amount is None:
                near = [x for x in rows[max(0, i - 1): i + 2] if x is not r]
                for x in near:
                    if re.fullmatch(r"\s*[¥￥]?\s*\d{1,5}\.\d{2}\s*元?\s*", x["text"]):
                        pay_amount = _amount_in(x["text"])
                        break

    def labeled_dt(labels):
        r = _row_value(rows, labels)
        return _dt(r["text"]) if r else None

    paid_at = labeled_dt(["支付时间", "付款时间", "交易时间", "创建时间", "扣款时间"])
    ride_at = labeled_dt(["乘车时间", "上车时间", "行程时间", "用车时间"])
    m = re.search(r"(\d{1,2})月(\d{1,2})日行程", full)
    ride_hint = (int(m.group(1)), int(m.group(2))) if m else None
    orders = sorted({o for r in rows if re.search(r"单号|订单号|交易号|流水号", r["text"]) for o in ORDER_RE.findall(r["text"].replace(" ", "")) if sum(ch.isdigit() for ch in o) >= 12})
    product = _row_value(rows, ["商品说明", "商品", "商户全称"])
    merchant = ""
    for kw in ["滴滴出行", "高德打车", "曹操出行", "T3出行", "美团打车", "花小猪", "首汽约车", "如祺出行", "享道出行", "出租车", "微信支付"]:
        if kw in full:
            merchant = kw
            break
    info.update({"paid_at": paid_at, "ride_at": ride_at, "ride_hint": ride_hint, "orders": orders, "product": product["text"] if product else "", "merchant": merchant, "toll": toll, "coupon": coupon, "fare": fare})

    if neg:
        entries = []
        if len(neg) == 1:
            entries.append({"amount": neg[0][1], "paid_at": paid_at, "ride_at": ride_at})
        else:
            # 账单列表：每个金额配最近的日期
            dts = [(r["y"], _dt(r["text"])) for r in rows if _dt(r["text"])]
            for y, a in neg:
                near = min(dts, key=lambda d: abs(d[0] - y)) if dts else (0, None)
                entries.append({"amount": a, "paid_at": near[1], "ride_at": None})
        info.update({"kind": "payment", "entries": entries, "discount": coupon})
        return info

    if fare is not None or toll is not None or "车费明细" in full or "费用明细" in full or (pay_amount is not None and re.search(r"订单详情|行程详情|账单详情", full)):
        date = None
        for r in rows:
            d = _dt(r["text"])
            if d and not any(k in r["text"] for k in ("支付时间", "付款时间")):
                date = d
                break
        info.update({"kind": "detail", "pay_amount": pay_amount, "date": date or paid_at})
        return info

    if photo_hits >= 2 or (len(re.findall(r"\d{1,2}:\d{2}\s*[-－]\s*\d{1,2}:\d{2}", full)) >= 1 and "￥" in full and not pay_page):
        info["kind"] = "taxi_invoice_photo"
        return info

    # 没有负号但带金额的支付成功页
    if re.search(r"支付成功|付款成功|交易成功|已支付", full):
        for r in rows:
            m2 = re.fullmatch(r"\s*[-－]?\s*[¥￥]\s*(\d{1,5}\.\d{2})\s*", r["text"])
            if m2:
                info.update({"kind": "payment", "entries": [{"amount": _num(m2.group(1)), "paid_at": paid_at, "ride_at": ride_at}], "discount": coupon})
                return info
    return info
