"""Build the downloadable Excel audit report."""
import io
from datetime import datetime

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .matcher import FLAG_STATUSES, STATUS_COLORS, STATUS_ORDER

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=10)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def build_excel(res: pd.DataFrame, bookings_out: pd.DataFrame, summary: dict, info: dict) -> bytes:
    flagged = res[res["Status"].isin(FLAG_STATUSES)] if not res.empty else res
    unmatched = bookings_out[(bookings_out["In Block?"] == "Yes") & (bookings_out["On Attendee List?"] == "No")]
    booking_cols = [c for c in ["first", "last", "group_code", "created", "confirmation", "arrival", "departure",
                                "In Block?", "On Attendee List?", "matched_attendee", "source", "pdf_line"]
                    if c in bookings_out.columns]
    rename = {"first": "First", "last": "Last", "group_code": "Group Code", "created": "Created", "confirmation": "Confirmation",
              "arrival": "Arrival", "departure": "Departure", "matched_attendee": "Matched Attendee",
              "source": "Source", "pdf_line": "PDF Line"}

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _summary_sheet(xw, summary, info)
        _write(xw, res, "Attendee Audit", status_col="Status")
        _write(xw, flagged, "Flagged - Outside Block", status_col="Status")
        _write(xw, unmatched[booking_cols].rename(columns=rename), "In-Block Not On List")
        _write(xw, bookings_out[booking_cols].rename(columns=rename), "All Bookings Read")
    return buf.getvalue()


def _summary_sheet(xw, summary: dict, info: dict):
    ws = xw.book.create_sheet("Summary", 0)
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws["A1"] = "Group Block Audit"
    ws["A1"].font = Font(name="Arial", bold=True, size=16, color="1F3864")
    meta = [("Group", info.get("group", "")), ("Hotel", info.get("hotel", "")),
            ("Valid group codes", ", ".join(info.get("codes", [])) or "(any code)"),
            ("Attendee file", info.get("attendee_file", "")), ("Bookings file(s)", info.get("booking_files", "")),
            ("Run on", datetime.now().strftime("%m/%d/%Y %I:%M %p"))]
    for r, (k, v) in enumerate(meta, start=3):
        ws.cell(row=r, column=1, value=k).font = Font(name="Arial", bold=True)
        ws.cell(row=r, column=2, value=v).font = BODY_FONT

    start = 3 + len(meta) + 1
    for c, h in enumerate(["Attendee Status", "Count", "% of Attendees"], start=1):
        cell = ws.cell(row=start, column=c, value=h)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BOX
    total = summary["total_attendees"]
    r = start
    for r, s in enumerate(STATUS_ORDER, start=start + 1):
        n = summary["counts"][s]
        ws.cell(row=r, column=1, value=s).fill = PatternFill("solid", fgColor=STATUS_COLORS[s].lstrip("#"))
        ws.cell(row=r, column=2, value=n)
        pct = ws.cell(row=r, column=3, value=(n / total) if total else 0)
        pct.number_format = "0.0%"
    tr = r + 1
    ws.cell(row=tr, column=1, value="Total attendees")
    ws.cell(row=tr, column=2, value=f"=SUM(B{start + 1}:B{r})")
    for row in ws.iter_rows(min_row=start + 1, max_row=tr, max_col=3):
        for cell in row:
            cell.border = BOX
            cell.font = Font(name="Arial", size=10, bold=(cell.row == tr))

    br = tr + 2
    ws.cell(row=br, column=1, value="Bookings").font = Font(name="Arial", bold=True, size=12, color="1F3864")
    for i, (k, v) in enumerate([("Bookings read from file(s)", summary["total_bookings"]),
                                ("Bookings with a valid group code", summary["in_block_bookings"]),
                                ("In-block bookings NOT on attendee list", summary["unmatched_in_block"])], start=br + 1):
        ws.cell(row=i, column=1, value=k).font = BODY_FONT
        ws.cell(row=i, column=2, value=v).font = BODY_FONT
        ws.cell(row=i, column=1).border = ws.cell(row=i, column=2).border = BOX


def _write(xw, df: pd.DataFrame, sheet: str, status_col: str | None = None):
    df = df.copy()
    if df.empty:
        df = pd.DataFrame({"Info": ["No rows"]})
    df.to_excel(xw, sheet_name=sheet, index=False)
    ws = xw.sheets[sheet]
    for c in range(1, df.shape[1] + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BOX
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        values = [str(v) for v in df.iloc[:, c - 1].head(500)] + [str(df.columns[c - 1])]
        ws.column_dimensions[get_column_letter(c)].width = min(max(len(v) for v in values) + 2, 50)
    status_idx = list(df.columns).index(status_col) + 1 if status_col in df.columns else None
    for r in range(2, len(df) + 2):
        fill = None
        if status_idx:
            color = STATUS_COLORS.get(ws.cell(row=r, column=status_idx).value)
            fill = PatternFill("solid", fgColor=color.lstrip("#")) if color else None
        for c in range(1, df.shape[1] + 1):
            cell = ws.cell(row=r, column=c)
            cell.font, cell.border = BODY_FONT, BOX
            if fill:
                cell.fill = fill
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
