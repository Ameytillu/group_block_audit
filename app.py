"""Group Block Audit - find group attendees who booked outside the room block.

Run locally:   streamlit run app.py
"""
import re
from datetime import date

import pandas as pd
import streamlit as st

from core import matcher, pdf_reader, report, tables
from core.tables import NONE

st.set_page_config(page_title="Group Block Audit", page_icon="🏨", layout="wide")
pd.set_option("styler.render.max_elements", 5_000_000)


# ----------------------------------------------------------------------------
# Cached helpers (so re-runs don't re-read the same files)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def read_sheet_file(data: bytes, name: str):
    return tables.read_spreadsheet(data, name)


@st.cache_data(show_spinner=False)
def pdf_info(data: bytes):
    return pdf_reader.pdf_page_count(data), pdf_reader.pdf_has_text(data)


@st.cache_data(show_spinner="Reading PDF text…")
def pdf_lines(data: bytes, codes: tuple, source: str):
    return pdf_reader.extract_by_text_lines(data, list(codes), source)


@st.cache_data(show_spinner="Reading reservation blocks…")
def pdf_blocks(data: bytes, source: str):
    return pdf_reader.extract_name_blocks(data, source)


@st.cache_data(show_spinner=False)
def pdf_is_block_report(data: bytes):
    return pdf_reader.looks_like_name_block_report(data)


@st.cache_data(show_spinner="Reading PDF tables…")
def pdf_tables(data: bytes, strategy: str):
    return pdf_reader.extract_tables(data, strategy)


@st.cache_data(show_spinner="Matching attendees to bookings…")
def audit(att: pd.DataFrame, bk: pd.DataFrame, codes: tuple, threshold: int, nick: bool, fuzzy: bool, initials: bool):
    settings = matcher.AuditSettings(list(codes), threshold, nick, fuzzy, initials)
    res, bk_out = matcher.run_audit(att, bk, settings)
    return res, bk_out, matcher.summarize(res, bk_out)


def parse_codes(text: str) -> list[str]:
    return sorted({c.strip().upper() for c in re.split(r"[,;\n\t ]+", text or "") if c.strip()})


def index_of(options: list[str], value: str) -> int:
    return options.index(value) if value in options else 0


def column_mapper(df: pd.DataFrame, prefix: str, extra: bool = False) -> dict:
    """Let the user say which columns hold the name / group code."""
    cols = list(df.columns)
    options = [NONE] + cols
    g_first = tables.guess_column(cols, "first")
    g_last = tables.guess_column(cols, "last", exclude=(g_first,))
    g_full = tables.guess_column(cols, "full", exclude=(g_first, g_last))
    has_split = g_first != NONE and g_last != NONE

    mode_label = st.radio(
        "How are names laid out?",
        ["Separate First / Last columns", "One full-name column"],
        index=0 if has_split or g_full == NONE else 1,
        horizontal=True,
        key=f"{prefix}_mode",
    )
    mapping = {"mode": "separate" if mode_label.startswith("Separate") else "full"}

    c = st.columns(4)
    if mapping["mode"] == "separate":
        mapping["first"] = c[0].selectbox("First name column", options, index_of(options, g_first), key=f"{prefix}_first")
        mapping["last"] = c[1].selectbox("Last name column", options, index_of(options, g_last), key=f"{prefix}_last")
    else:
        mapping["full"] = c[0].selectbox("Full name column", options, index_of(options, g_full if g_full != NONE else g_first),
                                         key=f"{prefix}_full", help="Handles 'SMITH, JOHN' and 'John Smith'.")
    used = {mapping.get("first"), mapping.get("last"), mapping.get("full")}
    g_code = tables.guess_column(cols, "group_code", exclude=tuple(u for u in used if u))
    mapping["group_code"] = c[2].selectbox("Group code column (optional)", options, index_of(options, g_code), key=f"{prefix}_code")

    if extra:
        e = st.columns(4)
        mapping["confirmation"] = e[0].selectbox("Confirmation # (optional)", options,
                                                 index_of(options, tables.guess_column(cols, "confirmation")), key=f"{prefix}_conf")
        mapping["arrival"] = e[1].selectbox("Arrival (optional)", options,
                                            index_of(options, tables.guess_column(cols, "arrival")), key=f"{prefix}_arr")
        mapping["departure"] = e[2].selectbox("Departure (optional)", options,
                                              index_of(options, tables.guess_column(cols, "departure")), key=f"{prefix}_dep")
    return mapping


def color_rows(df: pd.DataFrame):
    if df.empty or "Status" not in df.columns:
        return df
    return df.style.apply(
        lambda r: [f"background-color: {matcher.STATUS_COLORS.get(r['Status'], '')}; color: #000"] * len(r), axis=1
    )


# ----------------------------------------------------------------------------
# Sidebar - settings
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Audit settings")
    group_name = st.text_input("Group name", placeholder="e.g. ACME Sales Conference 2026")
    hotel_name = st.text_input("Hotel", placeholder="e.g. Downtown Marriott")
    codes_text = st.text_area(
        "Valid group code(s)",
        placeholder="e.g. ACME26\nACME26S",
        help="Codes that count as IN the block. One per line or comma-separated. "
             "Leave blank to use the codes from the attendee file's group code column.",
    )
    st.divider()
    st.subheader("Name matching")
    threshold = st.slider("Similar-spelling strictness", 75, 100, 88,
                          help="Higher = stricter. 88 catches typos like Jonhson/Johnson without false matches.")
    use_nick = st.toggle("Match nicknames (Bob = Robert)", value=True)
    use_fuzzy = st.toggle("Match similar spellings / typos", value=True)
    use_init = st.toggle("Match last name + first initial", value=True,
                         help="Shows up as 'Review' - useful for nicknames not in the built-in list.")
    st.divider()
    st.caption("🔒 Files are processed in memory for this session only and are not saved by the app.")

# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------
st.title("🏨 Group Block Audit")
st.write("Upload the **group attendee list** and the **hotel's booked reservations**. "
         "The app flags attendees who have a reservation but **not under the group code**.")

# ----------------------------------------------------------------------------
# Step 1 - Upload
# ----------------------------------------------------------------------------
st.subheader("1 · Upload files")
u1, u2 = st.columns(2)
att_file = u1.file_uploader("Group attendee list (Excel or CSV)", type=["xlsx", "csv"])
bk_files = u2.file_uploader("Booked reservations (PDF, Excel or CSV)", type=["pdf", "xlsx", "csv"],
                            accept_multiple_files=True)

if not att_file or not bk_files:
    st.info("⬆️ Upload both files to start.")
    st.stop()

# ----------------------------------------------------------------------------
# Step 2 - Attendee list
# ----------------------------------------------------------------------------
st.subheader("2 · Attendee list")
att_sheets = read_sheet_file(att_file.getvalue(), att_file.name)
att_sheet = st.selectbox("Sheet", list(att_sheets), key="att_sheet") if len(att_sheets) > 1 else next(iter(att_sheets))
att_raw = att_sheets[att_sheet]
with st.container(border=True):
    att_map = column_mapper(att_raw, "att")
attendees = tables.to_guest_list(att_raw, att_map, att_file.name)

# Valid codes: typed in the sidebar, otherwise taken from the attendee file
typed_codes = parse_codes(codes_text)
file_codes = sorted({c for c in attendees["group_code"] if c})
valid_codes = typed_codes or file_codes
if typed_codes:
    st.caption(f"Valid group codes (from sidebar): **{', '.join(valid_codes)}**")
elif file_codes:
    st.caption(f"Valid group codes (from attendee file): **{', '.join(valid_codes)}** — override in the sidebar if needed.")
else:
    st.info("No group codes entered — any reservation with a filled-in group code will count as in block. "
            "To audit one group only, enter its code(s) in the sidebar.")

with st.expander(f"Preview attendees read ({len(attendees)})"):
    st.dataframe(attendees[["first", "last", "group_code", "source"]], hide_index=True)

# ----------------------------------------------------------------------------
# Step 3 - Bookings
# ----------------------------------------------------------------------------
st.subheader("3 · Booked reservations")
METHODS = {
    "blocks": "Reservation report — 'Name:' blocks with Group- and Crtd (name, group code, created date only)",
    "lines": "Text lines — names written 'LAST, FIRST' (most hotel system reports)",
    "table_lines": "Table with cell borders",
    "table_text": "Table without borders (spaced columns)",
}
booking_frames = []
for n, f in enumerate(bk_files):
    data = f.getvalue()
    with st.expander(f"📄 {f.name}", expanded=True):
        if f.name.lower().endswith(".pdf"):
            pages, has_text = pdf_info(data)
            if not has_text:
                st.error("This PDF has no selectable text (it is probably a scan). "
                         "Export it from the hotel system again, or run it through OCR first — see README.")
                continue
            if pdf_is_block_report(data):
                default = "blocks"
            else:
                default = "lines" if len(pdf_lines(data, tuple(valid_codes), f.name)) else "table_lines"
            method = st.radio("How should this PDF be read?", list(METHODS), format_func=METHODS.get,
                              index=list(METHODS).index(default), key=f"method_{n}")
            if method == "blocks":
                bk = pdf_blocks(data, f.name)
                no_code = int((bk["group_code"] == "").sum())
                st.caption(f"{pages} page(s) · {len(bk)} reservations found · "
                           f"{len(bk) - no_code} with a group code · {no_code} with a blank Group- field.")
            elif method == "lines":
                bk = pdf_lines(data, tuple(valid_codes), f.name)
                st.caption(f"{pages} page(s) · {len(bk)} names found. "
                           "Group code is detected when one of the valid codes appears on the same line.")
            else:
                raw = pdf_tables(data, "lines" if method == "table_lines" else "text")
                if raw.empty:
                    st.warning("No table found with this method. Try another option above.")
                    continue
                st.caption(f"Table preview ({len(raw)} rows) — pick the columns below.")
                st.dataframe(raw.head(15), hide_index=True)
                bk = tables.to_guest_list(raw, column_mapper(raw, f"bk{n}", extra=True), f.name)
        else:
            sheets = read_sheet_file(data, f.name)
            sh = st.selectbox("Sheet", list(sheets), key=f"bk_sheet_{n}") if len(sheets) > 1 else next(iter(sheets))
            raw = sheets[sh]
            bk = tables.to_guest_list(raw, column_mapper(raw, f"bk{n}", extra=True), f.name)
        booking_frames.append(bk)

if not booking_frames or all(b.empty for b in booking_frames):
    st.warning("No reservations could be read yet. Adjust the options above.")
    st.stop()

bookings = pd.concat(booking_frames, ignore_index=True).fillna("")
# Show only the columns the report actually provided
optional = ["created", "confirmation", "arrival", "departure", "pdf_line"]
bookings = bookings.drop(columns=[c for c in optional if c in bookings.columns
                                  and (bookings[c].astype(str).str.strip() == "").all()])
st.markdown("**Check the reservations that were read.** Fix any misread names or codes directly in the table "
            "(you can also add or delete rows). Edits reset if you change files or settings above.")
bookings = st.data_editor(
    bookings,
    num_rows="dynamic",
    hide_index=True,
    key="bookings_editor",
    column_config={
        "first": "First", "last": "Last", "group_code": "Group Code", "created": "Created", "confirmation": "Confirmation",
        "arrival": "Arrival", "departure": "Departure", "source": "Source",
        "pdf_line": st.column_config.TextColumn("PDF Line (for checking)", disabled=True),
    },
)

# ----------------------------------------------------------------------------
# Step 4 - Results
# ----------------------------------------------------------------------------
st.subheader("4 · Results")
if attendees.empty:
    st.warning("No attendee names were read — check the column choices in step 2.")
    st.stop()

res, bk_out, summary = audit(attendees, bookings, tuple(valid_codes), threshold, use_nick, use_fuzzy, use_init)
counts = summary["counts"]

m = st.columns(6)
m[0].metric("Attendees", summary["total_attendees"])
m[1].metric("🟢 In block", counts[matcher.IN_BLOCK])
m[2].metric("🔴 Outside block", counts[matcher.OUTSIDE], help="Exact name match, booking has no valid group code")
m[3].metric("🟠 Review – maybe outside", counts[matcher.REVIEW_OUTSIDE])
m[4].metric("🟡 Review – maybe in block", counts[matcher.REVIEW_IN])
m[5].metric("⚪ No booking found", counts[matcher.NOT_FOUND])
st.caption(f"**{summary['pct_outside']:.1%}** of attendees booked outside the block · "
           f"{summary['total_bookings']} reservations read · {summary['in_block_bookings']} with a valid group code · "
           f"{summary['unmatched_in_block']} in-block reservations are not on the attendee list.")

f1, f2 = st.columns([2, 1])
status_filter = f1.multiselect("Show statuses", matcher.STATUS_ORDER, default=matcher.STATUS_ORDER)
search = f2.text_input("Search name", placeholder="Type a name…")

view = res[res["Status"].isin(status_filter)] if not res.empty else res
if search and not view.empty:
    s = search.lower()
    view = view[(view["Attendee First"] + " " + view["Attendee Last"] + " " + view["Booked As"]).str.lower().str.contains(s, regex=False)]

flagged = res[res["Status"].isin(matcher.FLAG_STATUSES)] if not res.empty else res
unmatched = bk_out[(bk_out["In Block?"] == "Yes") & (bk_out["On Attendee List?"] == "No")]

t1, t2, t3, t4 = st.tabs([f"All attendees ({len(view)})", f"🚩 Flagged ({len(flagged)})",
                          f"In-block, not on list ({len(unmatched)})", f"All reservations ({len(bk_out)})"])
with t1:
    st.dataframe(color_rows(view), hide_index=True)
with t2:
    st.caption("Attendees booked outside the block (exact match) plus near-matches whose booking has no valid group code.")
    st.dataframe(color_rows(flagged), hide_index=True)
with t3:
    st.caption("Reservations under the group code whose name isn't on the attendee list — may be non-attendees using block rooms, or a name spelled differently.")
    st.dataframe(unmatched, hide_index=True)
with t4:
    st.dataframe(bk_out, hide_index=True)

# ----------------------------------------------------------------------------
# Step 5 - Export
# ----------------------------------------------------------------------------
st.subheader("5 · Download report")
xlsx = report.build_excel(res, bk_out, summary, {
    "group": group_name, "hotel": hotel_name, "codes": valid_codes,
    "attendee_file": att_file.name, "booking_files": ", ".join(f.name for f in bk_files),
})
safe = re.sub(r"[^A-Za-z0-9]+", "_", group_name).strip("_") or "Group"
st.download_button("⬇️ Download Excel report", data=xlsx, type="primary",
                   file_name=f"Block_Audit_{safe}_{date.today():%Y-%m-%d}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
