import json
import re
from typing import Callable, Optional

MARKER_RE = re.compile(r"[\[【]\s*paper[\s_]?id\s*[=＝]\s*(\d+)\s*[\]】]", re.IGNORECASE)
_MARKER_LEAD_RE = re.compile(r"[ \t]*" + MARKER_RE.pattern, re.IGNORECASE)

_SENT_SPLIT = re.compile(r"(?<=[.!?])(?:\*{1,2}|\))?\s+(?=[A-Z(*$βα]|\[(?!paper))")
_BULLET_RE = re.compile(r"^(\s*(?:[-*+•]|\d+[.)])\s+)")
_LABEL_RE = re.compile(r"^\W*(?:inference|estimate)\b", re.IGNORECASE)

_UNITS = (
    r"mm\s?hg|mmhg|%|percent|fold|bpm|beats|ms|mg|µg|ug|mcg|kg|"
    r"years?|months?|weeks?|days?|participants|patients|people|subjects|"
    r"trials|studies|rcts|cohorts"
)
_NUM = r"\d+(?:[.,]\d+)?"
_QUANT_RE = re.compile(
    rf"""(?ix)
    (?:
        {_NUM}(?:\s*(?:-|–|—|to)\s*{_NUM})?(?:\s*[:∶/]\s*{_NUM})?\s*-?\s*(?:{_UNITS})(?![A-Za-z])
      | {_NUM}(?:\s*(?:-|–)\s*{_NUM})?\s*[:∶]\s*{_NUM}
      | \b(?:n|p|hr|rr|or|ci)\s*[=<>]\s*[\d.]+
    )
    """
)
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")


def strip_markers(s: str) -> str:
    return re.sub(r"\s{2,}", " ", MARKER_RE.sub("", s)).strip()


def _norm_numbers(s: str) -> list[str]:
    s = _THOUSANDS_RE.sub("", s.replace("\u2212", "-"))
    return _NUM_TOKEN_RE.findall(s)


def extract_quantities(sentence: str) -> list[list[str]]:
    """Each quantity -> list of its numeric tokens, e.g. '5-7 mm Hg' -> ['5', '7']."""
    clean = MARKER_RE.sub("", sentence)
    out = []
    for m in _QUANT_RE.finditer(clean):
        nums = _norm_numbers(m.group(0))
        if nums:
            out.append(nums)
    return out


def _number_tokens(text: str) -> set[str]:
    return set(_norm_numbers(text or ""))


def rewrite_sentences(text: str, fn: Callable[[str], Optional[str]]) -> str:
    """Apply fn to every prose sentence (skips headings, tables, code, math).
    fn returns the new sentence, or None to drop it. Untouched lines are kept verbatim."""
    out: list[str] = []
    in_code = in_math = False
    for line in (text or "").split("\n"):
        st = line.strip()
        if st.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if st == "$$":
            in_math = not in_math
            out.append(line)
            continue
        if (
            in_code
            or in_math
            or not st
            or st.startswith(("#", "|", "$$", ">"))
            or set(st) <= set("-=_* ")
        ):
            out.append(line)
            continue

        m = _BULLET_RE.match(line)
        prefix = m.group(1) if m else ""
        body = line[len(prefix):]
        sents = _SENT_SPLIT.split(body)
        kept = []
        for s in sents:
            r = fn(s)
            if r is not None:
                kept.append(r)
        if kept == sents:
            out.append(line)
        elif kept:
            out.append(prefix + " ".join(k.strip() for k in kept))

    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _short(s: str, n: int = 140) -> str:
    s = strip_markers(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def ground_text(
    text: str,
    texts_by_id: dict[str, str],
    visible_ids: Optional[set[str]] = None,
    numeric_check: bool = True,
) -> tuple[str, list[dict]]:
    visible = set(visible_ids) if visible_ids else set(texts_by_id)
    drops: list[dict] = []

    def _fn(sent: str) -> Optional[str]:
        ids = MARKER_RE.findall(sent)
        vis = [i for i in ids if i in visible]

        if ids and not vis:
            drops.append({"reason": "cites only papers the model was not shown", "sentence": _short(sent)})
            return None

        if ids and len(vis) != len(ids):
            sent = _MARKER_LEAD_RE.sub(
                lambda m: m.group(0) if m.group(1) in visible else "", sent
            )

        if numeric_check and not _LABEL_RE.match(sent.strip()):
            quants = extract_quantities(sent)
            if quants:
                pool = vis if vis else sorted(visible)
                tokens = _number_tokens(" ".join(texts_by_id.get(i, "") for i in pool))
                for q in quants:
                    missing = [n for n in q if n not in tokens]
                    if missing:
                        drops.append(
                            {
                                "reason": f"numbers {missing} not found in the cited source text",
                                "sentence": _short(sent),
                            }
                        )
                        return None
        return sent

    return rewrite_sentences(text, _fn), drops


def _parse_verdicts(raw) -> dict[int, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    if isinstance(raw, dict):
        raw = raw.get("results") or raw.get("verdicts") or []
    verdicts: dict[int, str] = {}
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            try:
                idx = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            v = str(r.get("verdict", "")).strip().lower()
            if v.startswith("unsupp") or v.startswith("not"):
                verdicts[idx] = "unsupported"
            elif v.startswith("part"):
                verdicts[idx] = "partial"
            elif v.startswith("supp"):
                verdicts[idx] = "supported"
    return verdicts


_SUPPORT_SYSTEM = (
    "You are a strict fact-checker. You judge whether a source supports a claim "
    "using ONLY the source text provided. Never use outside knowledge. "
    "Return only valid JSON."
)


def verify_support(
    texts: list[str],
    texts_by_id: dict[str, str],
    invoke_json: Callable[[str, str], object],
    strict: bool = False,
    max_items: int = 40,
    source_chars: int = 1400,
) -> tuple[list[str], list[dict]]:
    """
    texts: markdown bodies (already passed through ground_text).
    invoke_json(system, user) -> parsed JSON (dict/list) or raises.
    Fail-open: any error keeps the text unchanged.
    """
    items: list[tuple[int, str, str]] = []
    sentence_items: dict[int, list[int]] = {}
    counter = {"k": 0}

    def _collect(sent: str) -> Optional[str]:
        ids = list(dict.fromkeys(MARKER_RE.findall(sent)))
        if ids and not _LABEL_RE.match(sent.strip()):
            k = counter["k"]
            counter["k"] += 1
            claim = strip_markers(sent)[:320]
            for pid in ids:
                if len(items) < max_items and texts_by_id.get(pid):
                    sentence_items.setdefault(k, []).append(len(items))
                    items.append((len(items), pid, claim))
        return sent

    for t in texts:
        rewrite_sentences(t, _collect)

    if not items:
        return texts, []

    used = sorted({pid for _, pid, _ in items}, key=int)
    sources = "\n".join(f"[paper_id={p}] {texts_by_id[p][:source_chars]}" for p in used)
    claims = "\n".join(f"#{i} (cites paper {pid}): {claim}" for i, pid, claim in items)
    user = (
        "SOURCES (the only evidence you may use):\n"
        f"{sources}\n\n"
        "CLAIMS TO CHECK. For each, judge ONLY the cited paper:\n"
        f"{claims}\n\n"
        "Verdicts:\n"
        '- "supported": the source text states the claim, including its specific numbers, drugs, populations and mechanisms.\n'
        '- "partial": the source supports the general point but not every specific detail.\n'
        '- "unsupported": the source text does not say this, is about something else, or contradicts it.\n'
        'Return JSON: {"results":[{"id":0,"verdict":"supported"}]} with one entry per claim.'
    )
    try:
        verdicts = _parse_verdicts(invoke_json(_SUPPORT_SYSTEM, user))
    except Exception as e:  # fail open
        print(f"[ground] support check skipped: {type(e).__name__}: {e}")
        return texts, []

    bad = {"unsupported", "partial"} if strict else {"unsupported"}
    drops: list[dict] = []
    counter["k"] = 0

    def _apply(sent: str) -> Optional[str]:
        ids = list(dict.fromkeys(MARKER_RE.findall(sent)))
        if not ids or _LABEL_RE.match(sent.strip()):
            return sent
        k = counter["k"]
        counter["k"] += 1
        rejected = set()
        for item_id in sentence_items.get(k, []):
            if verdicts.get(item_id) in bad:
                rejected.add(items[item_id][1])
        if not rejected:
            return sent
        if rejected >= set(ids):
            drops.append({"reason": "no cited source supports this claim", "sentence": _short(sent)})
            return None
        drops.append({"reason": f"removed unsupported citation(s) {sorted(rejected)}", "sentence": _short(sent)})
        return _MARKER_LEAD_RE.sub(lambda m: "" if m.group(1) in rejected else m.group(0), sent)

    return [rewrite_sentences(t, _apply) for t in texts], drops


ABSTAIN_TEXT = (
    "The sources retrieved for this question do not contain enough direct evidence "
    "to cover this part reliably."
)