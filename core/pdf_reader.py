"""Pull guest names (and group codes) out of hotel reservation PDFs.

Two methods, because hotel system reports come in two shapes:

1. TEXT LINES - for reports where each reservation is a line of text with the
   name written "LAST, FIRST" (Opera, OnQ, Maestro and most PMS arrival /
   reservation reports). Group code is found by looking for any of your valid
   group codes on the same line.

2. TABLES - for PDFs that contain a real table (column borders or clean
   column spacing). Returns the raw table so the user can map the columns.

This only works on PDFs that contain selectable text. A scanned image PDF
needs OCR first (see README).
"""
import io
import re

import pandas as pd
import pdfplumber

from .names import PARTICLES, TITLES, clean, split_full_name
from .tables import make_unique

# A name written "LAST, FIRST" - last name can contain hyphens / apostrophes
NAME_RE = re.compile(
    r"(?P<before>(?:[A-Za-z][A-Za-z'’\-\.]*\s+){0,3})"       # up to 3 words before the comma (particles / junk)
    r"(?P<last>[A-Za-z][A-Za-z'’\-\.]*)\s*,\s*"                 # last name word right before the comma
    r"(?P<first>(?:(?:MR|MRS|MS|MISS|DR|PROF)\.?\s+)?[A-Za-z][A-Za-z'’\-]*)",  # optional title + first name
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b|\b\d{1,2}-[A-Za-z]{3}-\d{2,4}\b")
CONF_RE = re.compile(r"\b\d{6,12}\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")

# Lines that are report furniture, not reservations
SKIP_RE = re.compile(r"(?i)\b(page \d+|printed|report|run date|total[s]?\b|grand total|property:|sorted by)")
# Words that often appear as "City, ST" or "Inc, LLC" - not people
NOT_A_FIRST_NAME = {"inc", "llc", "ltd", "corp", "co", "usa", "us"}


# ---------------------------------------------------------------------------
# Block-style reservation report ("Name:  LAST, FIRST ... Group-XXXX ... Crtd - mm/dd/yyyy")
# Each reservation starts with a "Name:" line; everything else in the block is ignored.
# ---------------------------------------------------------------------------
REC_NAME_RE = re.compile(r"^\s*Name:\s*(?P<name>.+?)(?=\s+Res\s*Stat|\s{3,}|$)", re.IGNORECASE)
REC_GROUP_RE = re.compile(r"Group-\s*(?P<code>.*?)\s*(?=Accommodation-|Accom|$)", re.IGNORECASE)
REC_CREATED_RE = re.compile(r"Crtd\s*-\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)


def looks_like_name_block_report(pdf_bytes: bytes) -> bool:
    """True if the PDF uses the 'Name: / Group- / Crtd -' reservation block layout."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    return bool(re.search(r"(?im)^\s*Name:", text)) and "Crtd" in text and "Group-" in text


def extract_name_blocks(pdf_bytes: bytes, source: str = "PDF") -> pd.DataFrame:
    """Read a block-style reservation report. Keeps only guest name, group code and created date."""
    records, cur = [], None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").splitlines():
                m = REC_NAME_RE.search(line)
                if m:
                    first, last = split_full_name(m.group("name").strip())
                    cur = {"first": first, "last": last, "group_code": "", "created": "",
                           "source": f"{source} p{page_no}", "_group_seen": False}
                    records.append(cur)
                if cur is None:
                    continue
                if not cur["_group_seen"]:
                    g = REC_GROUP_RE.search(line)
                    if g:
                        cur["group_code"] = g.group("code").strip().upper()
                        cur["_group_seen"] = True
                if not cur["created"]:
                    c = REC_CREATED_RE.search(line)
                    if c:
                        cur["created"] = c.group("date")
    df = pd.DataFrame(records, columns=["first", "last", "group_code", "created", "source", "_group_seen"])
    return df.drop(columns="_group_seen")


def pdf_page_count(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def pdf_has_text(pdf_bytes: bytes) -> bool:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:3]:
            if (page.extract_text() or "").strip():
                return True
    return False


def extract_by_text_lines(pdf_bytes: bytes, valid_codes: list[str], source: str = "PDF") -> pd.DataFrame:
    """Find every 'LAST, FIRST' name in the PDF, one reservation per line."""
    codes = {c.strip().upper() for c in valid_codes if c and c.strip()}
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=False) or ""
            for line in text.splitlines():
                line = line.strip()
                if not line or SKIP_RE.search(line):
                    continue
                m = NAME_RE.search(line)
                if not m:
                    continue
                first, last = _name_from_match(m)
                if not first or not last or clean(first) in NOT_A_FIRST_NAME:
                    continue
                tokens = {t.upper() for t in TOKEN_RE.findall(line)}
                found_codes = sorted(tokens & codes)
                dates = DATE_RE.findall(line)
                conf = CONF_RE.findall(line)
                rows.append({
                    "first": first,
                    "last": last,
                    "group_code": ", ".join(found_codes),
                    "confirmation": conf[0] if conf else "",
                    "arrival": dates[0] if len(dates) > 0 else "",
                    "departure": dates[1] if len(dates) > 1 else "",
                    "source": f"{source} p{page_no}",
                    "pdf_line": line,
                })
    return pd.DataFrame(rows, columns=["first", "last", "group_code", "confirmation", "arrival", "departure", "source", "pdf_line"])


def _name_from_match(m: re.Match) -> tuple[str, str]:
    last = m.group("last")
    # Pull in particles that sit right before the last name: "DE LA CRUZ, JUAN"
    before = m.group("before").split()
    while before and clean(before[-1]) in PARTICLES:
        last = f"{before.pop()} {last}"
    first_words = m.group("first").split()
    if len(first_words) > 1 and clean(first_words[0]) in TITLES:
        first_words = first_words[1:]
    first = first_words[-1] if first_words else ""
    return first.strip(" .-"), last.strip(" .-")


def extract_tables(pdf_bytes: bytes, strategy: str = "lines") -> pd.DataFrame:
    """Return every table row in the PDF as one raw DataFrame.

    strategy='lines' uses drawn cell borders; 'text' uses column spacing
    (for reports without borders).
    """
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    if strategy == "text":
        settings = {"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 3, "join_tolerance": 3}
    all_rows: list[list[str]] = []
    page_of_row: list[int] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables(table_settings=settings) or []:
                for row in table:
                    cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]
                    if any(cells):
                        all_rows.append(cells)
                        page_of_row.append(page_no)
    if not all_rows:
        return pd.DataFrame()

    width = max(len(r) for r in all_rows)
    all_rows = [r + [""] * (width - len(r)) for r in all_rows]

    header_idx = _find_header_row(all_rows)
    if header_idx is not None:
        header = [h or f"Column {i + 1}" for i, h in enumerate(all_rows[header_idx])]
        header_set = [h.lower() for h in all_rows[header_idx]]
        body = [(r, p) for r, p in zip(all_rows, page_of_row) if [c.lower() for c in r] != header_set]
    else:
        header = [f"Column {i + 1}" for i in range(width)]
        body = list(zip(all_rows, page_of_row))

    df = pd.DataFrame([r for r, _ in body], columns=make_unique(header))
    df.insert(0, "PDF Page", [p for _, p in body])
    # Drop columns that are completely empty
    df = df.loc[:, (df != "").any(axis=0)]
    return df.reset_index(drop=True)


def _find_header_row(rows: list[list[str]]) -> int | None:
    """First of the top rows that looks like a header (contains 'name')."""
    for i, r in enumerate(rows[:15]):
        joined = " ".join(r).lower()
        if "name" in joined or ("first" in joined and "last" in joined):
            return i
    return None
