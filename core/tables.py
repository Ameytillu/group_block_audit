"""Read Excel/CSV files and turn any table into a standard guest list.

Standard guest list columns:
    first, last, group_code, confirmation, arrival, departure, source
"""
import io
import re

import pandas as pd

from .names import split_full_name

STANDARD_COLUMNS = ["first", "last", "group_code", "created", "confirmation", "arrival", "departure", "source"]

# Header keywords used to pre-select columns in the UI
GUESS_KEYWORDS = {
    "first": ["first name", "firstname", "first", "given", "fname"],
    "last": ["last name", "lastname", "last", "surname", "family", "lname"],
    "full": ["guest name", "full name", "name", "guest", "attendee"],
    "group_code": ["group code", "block code", "group id", "groupcode", "block", "group", "code", "rate code", "rate plan"],
    "confirmation": ["confirmation", "conf", "reservation", "res #", "res no", "booking"],
    "arrival": ["arrival", "arrive", "check in", "checkin", "arr"],
    "created": ["created", "date created", "crtd", "booked on", "booking date", "made on"],
    "departure": ["departure", "depart", "check out", "checkout", "dep"],
}

NONE = "— none —"


def read_spreadsheet(file_bytes: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """Return {sheet_name: DataFrame}. CSV files return a single 'CSV' sheet."""
    name = filename.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
        return {"CSV": _tidy(df)}
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, dtype=str)
    return {s: _tidy(df) for s, df in sheets.items()}


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").dropna(axis=1, how="all").fillna("")
    df.columns = make_unique([str(c).strip() or f"Column {i + 1}" for i, c in enumerate(df.columns)])
    return df.reset_index(drop=True)


def make_unique(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c} ({seen[c]})")
        else:
            seen[c] = 0
            out.append(c)
    return out


def guess_column(columns: list[str], field: str, exclude: tuple[str, ...] = ()) -> str:
    """Best-guess column for a field based on header text; NONE if nothing fits."""
    normalized = {c: re.sub(r"[^a-z# ]", " ", c.lower()).strip() for c in columns}
    for kw in GUESS_KEYWORDS[field]:
        for c, n in normalized.items():
            if c in exclude:
                continue
            if n == kw:
                return c
    for kw in GUESS_KEYWORDS[field]:
        for c, n in normalized.items():
            if c in exclude:
                continue
            if kw in n:
                return c
    return NONE


def to_guest_list(df: pd.DataFrame, mapping: dict, source: str) -> pd.DataFrame:
    """Convert a raw table into the standard guest list using a column mapping.

    mapping keys: mode ('separate' or 'full'), first, last, full, group_code,
                  confirmation, arrival, departure  (values are column names or NONE)
    """
    def col(field):
        c = mapping.get(field, NONE)
        return df[c].astype(str).str.strip() if c and c != NONE and c in df.columns else pd.Series([""] * len(df), index=df.index)

    if mapping.get("mode") == "full":
        split = col("full").apply(split_full_name)
        first = split.apply(lambda t: t[0])
        last = split.apply(lambda t: t[1])
    else:
        first, last = col("first"), col("last")

    out = pd.DataFrame({
        "first": first.values,
        "last": last.values,
        "group_code": col("group_code").str.upper().values,
        "created": col("created").str.replace(" 00:00:00", "", regex=False).values,
        "confirmation": col("confirmation").values,
        "arrival": col("arrival").str.replace(" 00:00:00", "", regex=False).values,
        "departure": col("departure").str.replace(" 00:00:00", "", regex=False).values,
        "source": [f"{source} row {i + 2}" for i in range(len(df))],
    })
    out = out.replace({"nan": "", "NAN": "", "None": ""})
    out = out[(out["first"] != "") | (out["last"] != "")]
    return out.reset_index(drop=True)
