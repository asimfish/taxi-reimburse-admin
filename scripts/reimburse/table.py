import csv
import datetime as dt
import re
from collections import Counter

import openpyxl

HEADER_KEYS = {
    "seq": ["序号", "编号"],
    "date": ["日期", "乘车日期", "时间"],
    "type": ["类型", "类别", "交通方式", "方式"],
    "start": ["起点", "出发地", "出发"],
    "end": ["终点", "目的地", "到达"],
    "route": ["起止地", "起止地点", "行程", "路线", "起讫"],
    "reason": ["公务事由", "事由", "用途", "原因"],
    "person": ["乘坐人", "乘车人", "姓名", "报销人"],
    "amount": ["金额", "费用", "车费"],
    "remark": ["备注", "说明", "票据"],
}
ROUTE_SPLIT = re.compile(r"\s*(?:\||｜|→|->|—>|－>|⇒| 至 |至| - | — |—|–)\s*")


def split_route(text):
    text = str(text or "").strip()
    parts = [p.strip() for p in ROUTE_SPLIT.split(text) if p.strip()]
    # “A | 途经 | B” 取首尾
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return text, ""


def _is_money_text(c):
    return isinstance(c, str) and re.fullmatch(r"\s*[¥￥]?\s*\d+(?:\.\d{1,2})?\s*元?\s*", c) is not None


def parse_date(v, month):
    """month: 'YYYY-MM'。返回 'YYYY-MM-DD' 或 None。"""
    year, mon = int(month[:4]), int(month[5:7])
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 30000 < v < 60000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = str(v or "").strip()
    if not s:
        return None
    m = re.search(r"(20\d\d)\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", s)
        if not m:
            m2 = re.fullmatch(r"(\d{1,2})日?", s)
            if not m2:
                return None
            y, mo, d = year, mon, int(m2.group(1))
        else:
            y, (mo, d) = year, map(int, m.groups())
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_amount(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(v or "").replace(",", ""))
    return round(float(m.group(1)), 2) if m else None


def normalize_type(v):
    s = str(v or "")
    if "出租" in s or "的士" in s:
        return "出租车"
    if any(k in s for k in ("网约", "滴滴", "高德", "快车", "专车", "平台", "打车", "曹操", "火箭", "T3", "首汽约车", "花小猪", "美团")):
        return "网约车"
    return None


def _context_type(s, exact_dache=False):
    s = str(s or "")
    if "出租" in s:
        return "出租车"
    if any(k in s for k in ("网约", "滴滴", "高德")) or (exact_dache and s.strip() == "打车"):
        return "网约车"
    return None


def _match_header(cell):
    s = re.sub(r"\s+", "", str(cell or ""))
    if not s or len(s) > 12:
        return None
    for key, words in HEADER_KEYS.items():
        if any(s == w or s.startswith(w) for w in words):
            return key
    return None


def _sheet_rows(path):
    p = str(path).lower()
    if p.endswith(".csv"):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            yield "CSV", list(csv.reader(f))
        return
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def read_table_file(path, month):
    """返回 (rows, notes)。每个 row: date, type, start, end, reason, amount, person, remark, source。"""
    sheets = []
    for title, data in _sheet_rows(path):
        hdr_idx, cols = None, {}
        for i, row in enumerate(data[:20]):
            found = {}
            for j, cell in enumerate(row):
                k = _match_header(cell)
                if k and k not in found:
                    found[k] = j
            if "date" in found and "amount" in found and len(found) >= 3:
                hdr_idx, cols = i, found
                break
        rows = []
        if hdr_idx is not None:
            body = data[hdr_idx + 1:]
            for k, row in enumerate(body):
                get = lambda key: row[cols[key]] if key in cols and cols[key] < len(row) else None
                joined = "".join(str(c) for c in row if c is not None)
                if "合计" in joined or "总计" in joined:
                    break
                date = parse_date(get("date"), month)
                amount = parse_amount(get("amount"))
                if date is None and amount is None:
                    continue
                start, end = (str(get("start") or "").strip(), str(get("end") or "").strip())
                if not end and "route" in cols:
                    start, end = split_route(get("route"))
                rows.append({
                    "date": date, "amount": amount, "start": start, "end": end,
                    "reason": str(get("reason") or "").strip(),
                    "person": str(get("person") or "").strip(),
                    "type": normalize_type(get("type")) or normalize_type(get("remark")),
                    "remark": str(get("remark") or "").strip(),
                    "source": f"{path.name}/{title} 第{hdr_idx + k + 2}行",
                })
        else:
            # 无表头：按内容推断（日期、起止地、事由、金额、备注）
            for k, row in enumerate(data):
                cells = [c for c in row]
                di = next((j for j, c in enumerate(cells) if parse_date(c, month) and (isinstance(c, (dt.date, dt.datetime)) or re.search(r"\d+[-/.月]\d+", str(c or "")))), None)
                if di is None:
                    continue
                texts = [(j, str(c).strip()) for j, c in enumerate(cells) if j > di and isinstance(c, str) and c.strip() and not _is_money_text(c)]
                nums = [(j, parse_amount(c)) for j, c in enumerate(cells) if j > di and ((isinstance(c, (int, float)) and not isinstance(c, bool)) or _is_money_text(c))]
                if not nums or not texts:
                    continue
                start, end = split_route(texts[0][1])
                rest = [t for j, t in texts[1:] if j < nums[-1][0]]
                after = [t for j, t in texts[1:] if j > nums[-1][0]]
                rows.append({
                    "date": parse_date(cells[di], month), "amount": round(float(nums[-1][1]), 2), "start": start, "end": end,
                    "reason": rest[0] if rest else "", "person": rest[1] if len(rest) > 1 else "",
                    "type": normalize_type(" ".join(after)), "remark": " ".join(after),
                    "source": f"{path.name}/{title} 第{k + 1}行",
                })
        if rows:
            ctx = _context_type(title, exact_dache=True) or _context_type(path.parent.name) or _context_type(path.stem)
            if ctx:
                for r in rows:
                    r["type"] = r["type"] or ctx
            sheets.append((title, rows))
    return sheets


def row_key(r):
    return (r["date"], r["amount"], r["start"], r["end"])


def read_tables(paths, month):
    """合并多个表格文件，去掉整张重复的工作表。"""
    all_rows, notes = [], []
    union = Counter()
    for path in paths:
        try:
            sheets = read_table_file(path, month)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{path.name} 无法读取：{e}")
            continue
        # 先放行数多的表（如“行程汇总”），子表重复时跳过
        for title, rows in sorted(sheets, key=lambda s: -len(s[1])):
            c = Counter(row_key(r) for r in rows)
            if all(union[k] >= v for k, v in c.items()):
                notes.append(f"{path.name}/{title} 与已读取内容重复，已忽略")
                continue
            for r in rows:
                if not r["type"]:
                    r["type"] = None
            all_rows.extend(rows)
            union.update(c)
    return all_rows, notes
