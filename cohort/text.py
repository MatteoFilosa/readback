import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase ASCII with every non-alphanumeric run collapsed to one space."""
    flat = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return _NON_ALNUM.sub(" ", flat).strip()


def tokens(text: str) -> list[str]:
    return fold(text).split()


def slug(text: str) -> str:
    return fold(text).replace(" ", "_")


def stem(word: str) -> tuple[str, bool]:
    """Matching key for a vocabulary word -> (key, is_prefix).

    Four-letter words match whole ("lung" must not match "lunga"), longer ones by prefix so
    that "diabetes", "diabete" and "diabetique" meet on "diabet"."""
    if len(word) <= 4:
        return word, False
    return word[:6] if len(word) >= 8 else word[:5], True


def hits(toks: list[str], key: str, prefix: bool) -> bool:
    if prefix:
        return any(t.startswith(key) for t in toks)
    return key in toks


def has_phrase(folded: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", folded) is not None
