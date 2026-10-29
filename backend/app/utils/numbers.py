import re
from decimal import Decimal, InvalidOperation

_MINUS = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-"})
NUM_TOKEN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def parse_number(raw: str) -> Decimal | None:
    """'-500' -> -500, '(1,200.50)' -> -1200.50, '37,5' -> 37.5, '1,234' -> 1234. None if unparseable."""
    s = (raw or "").translate(_MINUS).strip().replace(" ", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = s.lstrip("+")
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):       
            s = s.replace(".", "").replace(",", ".")
        else:                                    
            s = s.replace(",", "")
    elif "," in s:
        head, tail = s.rsplit(",", 1)
        if s.count(",") > 1 or len(tail) == 3: 
            s = s.replace(",", "")
        else:                                    
            s = head + "." + tail
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d


def _variants(raw: str) -> set[str]:
    out = {raw.strip().lstrip("-+").strip("()")}
    d = parse_number(raw)
    if d is not None:
        a = abs(d)
        plain = format(a, "f")
        if "." in plain:
            plain = plain.rstrip("0").rstrip(".")
        out.add(plain)
        if a == a.to_integral_value():
            out.add(f"{int(a):,}")
    return {v for v in out if v}


def number_in_text(raw: str, text: str) -> bool:
    """True if the number appears as a whole token ('37' does NOT match '137' or '37.5')."""
    for v in _variants(raw):
        pat = r"(?<![\d.,])" + re.escape(v) + r"(?!\d|[.,]\d)"
        if re.search(pat, text):
            return True
    return False


def sign_preserved(raw: str, text: str) -> bool:
    """For negative values: the report must show the minus sign or parentheses."""
    d = parse_number(raw)
    if d is None or d >= 0:
        return True
    for v in _variants(raw):
        if re.search(r"[-\u2212\u2013(]\s*(?:[A-Za-z]{0,3}\s*)?" + re.escape(v), text):
            return True
    return False


def all_numbers(text: str) -> list[Decimal]:
    out = []
    for m in NUM_TOKEN.finditer(text):
        d = parse_number(m.group(0))
        if d is not None:
            out.append(d)
    return out