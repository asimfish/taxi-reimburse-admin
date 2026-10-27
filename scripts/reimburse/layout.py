from openpyxl.styles import Alignment, Border, Side
from openpyxl.worksheet.properties import PageSetupProperties

THIN = Side(style="thin", color="FF8C99A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MAIN_WIDTHS = {"A": 6, "B": 11.5, "C": 44, "D": 30, "E": 8, "F": 10, "G": 34}


def _weight(s):
    return sum(2 if ord(ch) > 255 else 1.1 for ch in str(s or ""))


def apply_main_layout(ws, header_row=3):
    for col, w in MAIN_WIDTHS.items():
        ws.column_dimensions[col].width = w
    last = ws.max_row
    for r in range(header_row, last + 1):
        lines = 1
        for col, w in MAIN_WIDTHS.items():
            c = ws[f"{col}{r}"]
            c.border = BORDER
            c.alignment = Alignment(horizontal=c.alignment.horizontal, vertical="center", wrap_text=True)
            lines = max(lines, -(-int(_weight(c.value)) // int(w * 1.9)))
        ws.row_dimensions[r].height = max(18, 15 * lines + 4)
    apply_page_setup(ws, f"A1:G{last}", f"{header_row}:{header_row}")


def apply_page_setup(ws, area=None, title_rows=None):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.page_margins.header = ws.page_margins.footer = 0.25
    ws.print_options.horizontalCentered = True
    ws.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    if title_rows:
        ws.print_title_rows = title_rows
    if area:
        ws.print_area = area
