"""Match group attendees to hotel reservations and decide who booked outside the block."""
from dataclasses import dataclass

import pandas as pd

from .names import clean, key
from .nicknames import same_person_first_name

try:  # rapidfuzz is fast; fall back to the standard library if it isn't installed
    from rapidfuzz import fuzz

    def similarity(a: str, b: str) -> float:
        return fuzz.ratio(a, b)
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


IN_BLOCK = "In Block"
OUTSIDE = "Booked Outside Block"
REVIEW_OUTSIDE = "Review - Possibly Outside Block"
REVIEW_IN = "Review - Possibly In Block"
NOT_FOUND = "No Booking Found"

STATUS_ORDER = [OUTSIDE, REVIEW_OUTSIDE, REVIEW_IN, NOT_FOUND, IN_BLOCK]
STATUS_COLORS = {
    IN_BLOCK: "#C6EFCE",
    OUTSIDE: "#FFC7CE",
    REVIEW_OUTSIDE: "#FCE4D6",
    REVIEW_IN: "#FFEB9C",
    NOT_FOUND: "#E7E6E6",
}
FLAG_STATUSES = [OUTSIDE, REVIEW_OUTSIDE]

# Match types, strongest first
EXACT = "Exact name"
SWAPPED = "First/last swapped"
NICKNAME = "Nickname"
FUZZY = "Similar spelling"
INITIAL = "Same last name + first initial"


@dataclass
class AuditSettings:
    valid_codes: list[str]
    fuzzy_threshold: int = 88
    use_nicknames: bool = True
    use_fuzzy: bool = True
    use_initials: bool = True


def booking_in_block(code_text: str, valid_codes: set[str]) -> bool:
    """A booking is in block if any code on it is one of the valid group codes.

    If no valid codes are given, any non-blank code counts as in block.
    """
    codes = {c.strip().upper() for c in str(code_text or "").replace(";", ",").split(",") if c.strip()}
    if not codes:
        return False
    return bool(codes & valid_codes) if valid_codes else True


def run_audit(attendees: pd.DataFrame, bookings: pd.DataFrame, settings: AuditSettings):
    """Return (attendee_results, bookings_with_match) DataFrames."""
    valid = {c.strip().upper() for c in settings.valid_codes if c and c.strip()}

    b = bookings.copy().reset_index(drop=True)
    for col in ["first", "last", "group_code", "created", "confirmation", "arrival", "departure", "source"]:
        if col not in b.columns:
            b[col] = ""
        b[col] = b[col].fillna("").astype(str)
    b["_first"] = b["first"].map(key)
    b["_last"] = b["last"].map(key)
    b["_full"] = (b["first"].map(clean) + " " + b["last"].map(clean)).str.strip()
    b["_in_block"] = b["group_code"].map(lambda c: booking_in_block(c, valid))
    b["matched_attendee"] = ""

    by_last: dict[str, list[int]] = {}
    for i, ln in enumerate(b["_last"]):
        by_last.setdefault(ln, []).append(i)

    results = []
    for _, a in attendees.reset_index(drop=True).iterrows():
        af, al = key(a.get("first", "")), key(a.get("last", ""))
        if not af and not al:
            continue
        matches, match_type, score = _find_matches(af, al, a, b, by_last, settings)
        row = {
            "Attendee First": a.get("first", ""),
            "Attendee Last": a.get("last", ""),
            "Attendee Group Code": a.get("group_code", ""),
        }
        if not matches:
            row.update({"Status": NOT_FOUND, "Match Type": "", "Match Score": None,
                        "Booked As": "", "Booking Group Code": "", "Booking Created": "", "Confirmation": "",
                        "Arrival": "", "Departure": "", "# Bookings Found": 0, "Booking Source": "", "Notes": ""})
            results.append(row)
            continue

        in_block_rows = [i for i in matches if b.at[i, "_in_block"]]
        chosen = in_block_rows[0] if in_block_rows else matches[0]
        bk = b.loc[chosen]
        exact = match_type == EXACT
        if in_block_rows:
            status = IN_BLOCK if exact else REVIEW_IN
        else:
            status = OUTSIDE if exact else REVIEW_OUTSIDE

        notes = []
        if len(matches) > 1:
            notes.append(f"{len(matches)} bookings under this name")
        if in_block_rows and len(in_block_rows) < len(matches):
            notes.append(f"{len(matches) - len(in_block_rows)} of them outside block")
        if not exact:
            notes.append("Verify it is the same person")

        row.update({
            "Status": status,
            "Match Type": match_type,
            "Match Score": score,
            "Booked As": f"{bk['first']} {bk['last']}".strip(),
            "Booking Group Code": bk["group_code"] or "(none)",
            "Booking Created": bk["created"],
            "Confirmation": bk["confirmation"],
            "Arrival": bk["arrival"],
            "Departure": bk["departure"],
            "# Bookings Found": len(matches),
            "Booking Source": bk["source"],
            "Notes": "; ".join(notes),
        })
        results.append(row)
        label = f"{a.get('first', '')} {a.get('last', '')}".strip()
        for i in matches:
            b.at[i, "matched_attendee"] = (b.at[i, "matched_attendee"] + "; " if b.at[i, "matched_attendee"] else "") + label

    res = pd.DataFrame(results)
    if not res.empty:
        empty_cols = [c for c in ["Booking Created", "Confirmation", "Arrival", "Departure"]
                      if (res[c].astype(str).str.strip() == "").all()]
        res = res.drop(columns=empty_cols)
        res["_order"] = res["Status"].map({s: n for n, s in enumerate(STATUS_ORDER)})
        res = res.sort_values(["_order", "Attendee Last", "Attendee First"]).drop(columns="_order").reset_index(drop=True)

    b["In Block?"] = b["_in_block"].map({True: "Yes", False: "No"})
    b["On Attendee List?"] = b["matched_attendee"].map(lambda m: "Yes" if m else "No")
    out_b = b.drop(columns=[c for c in b.columns if c.startswith("_")])
    # Hide optional columns the report didn't provide (e.g. confirmation / dates)
    optional = ["created", "confirmation", "arrival", "departure", "pdf_line"]
    out_b = out_b.drop(columns=[c for c in optional if c in out_b.columns and (out_b[c].astype(str).str.strip() == "").all()])
    return res, out_b


def _find_matches(af, al, a, b, by_last, s: AuditSettings):
    """Return (list of booking row indexes, match type, score) for one attendee."""
    same_last = by_last.get(al, [])

    exact = [i for i in same_last if b.at[i, "_first"] == af]
    if exact:
        return exact, EXACT, 100

    swapped = [i for i in by_last.get(af, []) if b.at[i, "_first"] == al]
    if swapped:
        return swapped, SWAPPED, 100

    if s.use_nicknames:
        nick = [i for i in same_last if same_person_first_name(af, b.at[i, "_first"])]
        if nick:
            return nick, NICKNAME, 95
        # "Mary Ann" vs "Mary": one first name starts with the other
        prefix = [i for i in same_last
                  if min(len(af), len(b.at[i, "_first"])) >= 3
                  and (af.startswith(b.at[i, "_first"]) or b.at[i, "_first"].startswith(af))]
        if prefix:
            return prefix, NICKNAME, 90

    if s.use_fuzzy:
        full = f"{clean(a.get('first', ''))} {clean(a.get('last', ''))}".strip()
        best, best_score = [], 0.0
        # Last names must be close too, so a matching first name alone never counts
        close_last = [ln for ln in by_last if ln and similarity(al, ln) >= s.fuzzy_threshold - 5]
        for i in (i for ln in close_last for i in by_last[ln]):
            sc = similarity(full, b.at[i, "_full"])
            if sc >= s.fuzzy_threshold:
                if sc > best_score:
                    best, best_score = [i], sc
                elif sc == best_score:
                    best.append(i)
        if best:
            return best, FUZZY, round(best_score)

    if s.use_initials and af:
        init = [i for i in same_last if b.at[i, "_first"][:1] == af[:1]]
        if init:
            return init, INITIAL, 70

    return [], "", None


def summarize(res: pd.DataFrame, bookings_out: pd.DataFrame) -> dict:
    counts = {s: int((res["Status"] == s).sum()) if not res.empty else 0 for s in STATUS_ORDER}
    total = int(len(res))
    unmatched_in_block = bookings_out[(bookings_out["In Block?"] == "Yes") & (bookings_out["On Attendee List?"] == "No")]
    return {
        "total_attendees": total,
        "counts": counts,
        "pct_outside": (counts[OUTSIDE] / total) if total else 0.0,
        "total_bookings": int(len(bookings_out)),
        "in_block_bookings": int((bookings_out["In Block?"] == "Yes").sum()),
        "unmatched_in_block": int(len(unmatched_in_block)),
    }
