"""Name cleanup helpers shared by every module."""
import re
import unicodedata

TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "mx", "rev"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "phd"}
# Small words that belong to a last name ("de la Cruz", "van Dyke")
PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von", "st", "mac", "mc", "bin", "al", "el"}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def clean(text) -> str:
    """Lowercase, remove accents and punctuation, collapse spaces. 'O'Brien-Lee ' -> 'obrien lee'."""
    if text is None:
        return ""
    text = str(text)
    if text.lower() in {"nan", "none"}:
        return ""
    text = strip_accents(text).lower()
    text = re.sub(r"[’'`\.]", "", text)          # O'Brien -> obrien, St. -> st
    text = re.sub(r"[^a-z\s]", " ", text)          # hyphens, commas, digits -> space
    return re.sub(r"\s+", " ", text).strip()


def key(text) -> str:
    """Compact comparison key: 'Mary Ann' -> 'maryann'."""
    return clean(text).replace(" ", "")


def strip_titles(text: str) -> str:
    words = [w for w in clean(text).split() if w not in TITLES and w not in SUFFIXES]
    return " ".join(words)


def split_full_name(full) -> tuple[str, str]:
    """Split a single name cell into (first, last).

    'SMITH, JOHN'      -> ('JOHN', 'SMITH')
    'John Smith'       -> ('John', 'Smith')
    'Mary Ann Taylor'  -> ('Mary Ann', 'Taylor')
    'Juan de la Cruz'  -> ('Juan', 'de la Cruz')
    """
    if full is None:
        return "", ""
    full = str(full).strip()
    if not full or full.lower() in {"nan", "none"}:
        return "", ""
    if "," in full:
        last, first = full.split(",", 1)
        first_words = [w for w in first.split() if clean(w) not in TITLES]
        return " ".join(first_words).strip(), last.strip()
    words = [w for w in full.split() if clean(w) not in TITLES and clean(w) not in SUFFIXES]
    if len(words) == 1:
        return "", words[0]
    # Walk back from the end to pick up particles that belong to the last name
    i = len(words) - 1
    while i - 1 > 0 and clean(words[i - 1]) in PARTICLES:
        i -= 1
    return " ".join(words[:i]), " ".join(words[i:])
