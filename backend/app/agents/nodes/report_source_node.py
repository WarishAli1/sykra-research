import json
import logging
import re
from decimal import Decimal

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.nodes.retrieve_uploaded_node import load_uploaded_full_text
from app.agents.schemas import ExtractedRecord, ExtractionResult
from app.agents.state import AgentState
from app.config import settings
from app.services.llm_client import get_llm
from app.utils.numbers import parse_number

log = logging.getLogger("report_mode")
_MAX_PER_CHUNK = 25

class ExtractionError(RuntimeError):
    pass


_EXTRACT_SYSTEM = """You extract user-provided data points from text for a report.
Rules:
- Extract only numbers explicitly stated. Never compute, convert, round, or infer.
- value_raw: copy the number exactly as written (keep sign, decimal separator, thousands separators).
- original_text: copy a verbatim span (max 120 chars) from the text that contains value_raw.
- role: count | percentage | amount | rate | measurement | other.
  Skip years, dates, page numbers, list numbering and citation numbers.
- unit_of_analysis: what is being counted, if stated (sample, animal, household, transaction).
- numerator_ref / denominator_ref: for a percentage, give denominator_ref whenever the denominator is
  explicitly stated; give numerator_ref only if the numerator is also stated.
- ledger_side: debit or credit only if explicitly labeled.
- If unsure, omit the record.
- Each record is ONE complete JSON object. Never output keys or values as separate list items.
- Return at most 15 records and never repeat a value.
"""

_JSON_SHAPE = (
    '\nReturn ONLY JSON: {"records":[{"id":"r1","field_name":"","value_raw":"","unit":null,'
    '"role":"count","unit_of_analysis":null,"ledger_side":null,"numerator_ref":null,'
    '"denominator_ref":null,"original_text":""}]}'
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _split(text: str, size: int) -> list[str]:
    """Split on line boundaries so numbers are never cut in half."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if cur and len(cur) + len(line) > size:
            chunks.append(cur)
            cur = ""
        cur += line
        while len(cur) > size * 1.5:
            chunks.append(cur[:size])
            cur = cur[size:]
    if cur.strip():
        chunks.append(cur)
    return chunks


def build_source_text(query: str, uploaded_texts: list[str]) -> tuple[str, bool]:
    parts = [f"[USER REQUEST]\n{query}"] + [f"[UPLOADED DOCUMENT]\n{t}" for t in uploaded_texts if t]
    text = "\n\n".join(parts)
    cap = settings.REPORT_EXTRACT_MAX_CHARS
    return text[:cap], len(text) > cap


def _llm_extract(chunk: str) -> ExtractionResult:
    llm = get_llm(temperature=0, task="strong")
    raw = llm.invoke_json_mode(
        [SystemMessage(content=_EXTRACT_SYSTEM + _JSON_SHAPE), HumanMessage(content=chunk)],
        config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP},
    )
    data = getattr(raw, "content", raw)
    if isinstance(data, str):
        data = json.loads(data)
    items = data.get("records", []) if isinstance(data, dict) else []
    good = []
    for it in items[:_MAX_PER_CHUNK]:
        if not isinstance(it, dict):
            continue
        try:
            good.append(ExtractedRecord.model_validate(it))
        except Exception:
            continue
    return ExtractionResult(records=good)


def extract_records(source_text: str) -> tuple[list[dict], list[dict]]:
    """Returns (verified_records, dropped_records)."""
    norm_src = _norm(source_text)
    kept, dropped, seen = [], [], set()

    for k, chunk in enumerate(_split(source_text, settings.REPORT_EXTRACT_CHUNK_CHARS)):
        try:
            res = _llm_extract(chunk)
        except Exception as e:
            log.exception("report extraction failed chunk=%s", k)
            raise ExtractionError("Could not extract source data from your input.") from e

        for r in res.records:
            d = r.model_dump()
            ok = (parse_number(d["value_raw"]) is not None
                  and d["value_raw"] in d["original_text"]
                  and _norm(d["original_text"]) in norm_src)
            if not ok:
                dropped.append(d)
                continue
            key = (d["value_raw"], _norm(d["original_text"]))
            if key in seen:
                continue
            seen.add(key)
            pref = f"s{k}_"
            d["id"] = pref + d["id"]
            for ref in ("numerator_ref", "denominator_ref"):
                if d.get(ref):
                    d[ref] = pref + d[ref]
            d.update(category="user_provided", value=d["value_raw"], source_ref="user_input")
            kept.append(d)

    ids = {r["id"] for r in kept}
    for r in kept:                               # drop dangling refs
        for ref in ("numerator_ref", "denominator_ref"):
            if r.get(ref) and r[ref] not in ids:
                r[ref] = None
    return kept[: settings.REPORT_MAX_RECORDS], dropped


def compute_derived(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Only explicit relationships. No all-pairs ratios."""
    by_id = {r["id"]: r for r in records}
    derived, disc, n = [], [], 0

    totals = {}
    for side in ("debit", "credit"):
        vals = [(r, parse_number(r["value"])) for r in records if r.get("ledger_side") == side]
        vals = [(r, v) for r, v in vals if v is not None]
        if vals:
            total = sum((v for _, v in vals), Decimal(0))
            totals[side] = total
            n += 1
            derived.append({
                "id": f"derived_{n}", "category": "derived", "field_name": f"total_{side}",
                "value": format(total, "f"), "unit": vals[0][0].get("unit"), "role": "amount",
                "input_ids": [r["id"] for r, _ in vals],
                "transformation": f"sum of {len(vals)} {side} entries", "source_ref": "deterministic_calculation",
            })
    if len(totals) == 2:
        n += 1
        derived.append({
            "id": f"derived_{n}", "category": "derived", "field_name": "net_debit_minus_credit",
            "value": format(totals["debit"] - totals["credit"], "f"), "role": "amount",
            "transformation": "total_debit - total_credit", "source_ref": "deterministic_calculation",
        })

    for r in records:
        if r.get("role") != "percentage":
            continue
        num_rec, den_rec = by_id.get(r.get("numerator_ref")), by_id.get(r.get("denominator_ref"))
        if den_rec and not num_rec:
            stated, den = parse_number(r["value"]), parse_number(den_rec["value"])
            if stated is None or not den:
                continue
            mid = (stated * den / 100).to_integral_value()
            n += 1
            derived.append({
                "id": f"derived_{n}", "category": "derived",
                "field_name": f"approx_count_for_{r.get('field_name') or 'percentage'}",
                "value": format(mid, "f"), "unit": den_rec.get("unit"), "role": "count",
                "input_ids": [r["id"], den_rec["id"]],
                "transformation": f"approximately {mid} (percentage is rounded); do not show the calculation",
                "source_ref": "deterministic_calculation",
            })
            continue
        if not (num_rec and den_rec):
            continue
        num, den, stated = parse_number(num_rec["value"]), parse_number(den_rec["value"]), parse_number(r["value"])
        if None in (num, den, stated) or den == 0:
            continue
        actual = num / den * 100
        places = max(0, -stated.as_tuple().exponent)
        tol = Decimal("0.5") * (Decimal(10) ** -places)
        if abs(actual - stated) > tol:
            disc.append({
                "type": "percentage_mismatch", "severity": "warning",
                "description": f"Stated {r['value']}% does not match {num}/{den} = {actual:.2f}%.",
                "record_ids": [r["id"], num_rec["id"], den_rec["id"]],
            })
    counts = [(r, parse_number(r["value"])) for r in records
              if r.get("role") == "count" and (r.get("unit_of_analysis") or "").strip()]
    counts = [(r, v) for r, v in counts if v is not None and v > 0]
    found = 0
    for i, (a, va) in enumerate(counts):
        for b, vb in counts[i + 1:]:
            ua, ub = _norm(a["unit_of_analysis"]), _norm(b["unit_of_analysis"])
            if ua == ub:
                continue
            (big, vbig), (small, vsmall) = ((a, va), (b, vb)) if va >= vb else ((b, vb), (a, va))
            ratio = vbig / vsmall
            if ratio > 12 or ratio == ratio.to_integral_value():
                continue
            found += 1
            if found > 3:
                break
            disc.append({
                "type": "ratio_not_whole", "severity": "warning",
                "description": (
                    f"{vbig} {big['unit_of_analysis']} / {vsmall} {small['unit_of_analysis']} = {ratio:.2f} per "
                    f"{small['unit_of_analysis']}, which is not a whole number. If each "
                    f"{small['unit_of_analysis']} contributes a fixed number of {big['unit_of_analysis']}, "
                    f"these figures are inconsistent; ask the author to confirm."),
                "record_ids": [big["id"], small["id"]],
            })
    return derived, disc


def _build_evidence_ledger(
    state: AgentState,
    all_records: list[dict],
    discrepancies: list[dict],
) -> tuple[list[dict], list[str]]:
    items: list[dict] = []

    for r in all_records:
        category = r.get("category")
        if category not in ("user_provided", "derived"):
            category = "user_provided"

        value_raw = str(r.get("value_raw") or r.get("value") or "")
        unit = r.get("unit") or None
        field_name = r.get("field_name") or "value"

        items.append(
            {
                "id": f"ev_{r.get('id', 'unknown')}",
                "category": category,
                "content": f"{field_name}: {value_raw}" + (f" {unit}" if unit else ""),
                "value_raw": value_raw,
                "unit": unit,
                "source_type": "user_input" if category == "user_provided" else "derived_calculation",
                "source_ref": r.get("id"),
                "paper_id": None,
                "verified": True,
                "confidence": "high",
                "provenance": (
                    r.get("original_text")
                    or r.get("transformation")
                    or "Confirmed source record"
                ),
            }
        )

    papers = state.get("ranked_papers") or []
    for i, p in enumerate(papers[:8]):
        source = str(p.get("source") or "").lower()
        category = "uploaded_document" if source in ("user_upload", "uploaded") else "literature"
        title = str(p.get("title") or "Uploaded document")[:180]
        text = str(p.get("summary") or p.get("text") or "")[:500]

        items.append(
            {
                "id": f"ev_paper_{i}",
                "category": category,
                "content": f"{title}. {text}".strip(),
                "value_raw": None,
                "unit": None,
                "source_type": source or "retrieved_source",
                "source_ref": p.get("link"),
                "paper_id": i,
                "verified": True,
                "confidence": "medium",
                "provenance": "Retrieved source passage",
            }
        )

    gaps: list[str] = []
    contracts = state.get("report_section_contracts") or []

    has_source_evidence = any(
        item.get("category") in ("uploaded_document", "literature")
        for item in items
    )
    has_user_values = any(
        item.get("category") in ("user_provided", "derived")
        for item in items
    )

    for c in contracts:
        if not c.get("evidence_required"):
            continue
        if c.get("data_scope") == "none":
            continue

        if has_user_values or has_source_evidence:
            continue

        gaps.append(
            f"Section '{c.get('title')}' requires evidence, but no usable evidence was found."
        )

    for d in discrepancies[:3]:
        desc = d.get("description")
        if desc:
            gaps.append(f"Data discrepancy: {desc}")

    return items, gaps


def report_source_node(state: AgentState) -> AgentState:
    confirmed = state.get("confirmed_source_records")

    if confirmed:                              
        records = [{**r, "category": "user_provided", "value": r.get("value") or r["value_raw"]} for r in confirmed]
        ids = {r["id"] for r in records}
        for r in records:                      
            for ref in ("numerator_ref", "denominator_ref"):
                if r.get(ref) not in ids:
                    r[ref] = None

    elif state.get("report_evidence_attempts", 0) > 0 and state.get("report_source_records"):
        records = [r for r in state["report_source_records"] if r.get("category") == "user_provided"]

    else:
        texts = []
        if state.get("evidence_mode") in ("uploaded", "blended"):
            texts = load_uploaded_full_text(state["session_id"], settings.REPORT_EXTRACT_MAX_CHARS)
        source_text, _ = build_source_text(state.get("query", ""), texts)
        try:
            records, _ = extract_records(source_text)
        except ExtractionError:
            records = []

    derived, discrepancies = compute_derived(records)
    all_records = records + derived
    evidence_ledger, evidence_gaps = _build_evidence_ledger(state, all_records, discrepancies)

    log.info(
        "report_source records=%d derived=%d discrepancies=%d ledger=%d gaps=%d",
        len(records),
        len(derived),
        len(discrepancies),
        len(evidence_ledger),
        len(evidence_gaps),
    )

    return {
        "report_source_records": all_records,
        "report_derived_values": derived,
        "report_discrepancies": discrepancies,
        "evidence_ledger": evidence_ledger,
        "evidence_gaps": evidence_gaps,
    }


def _gap_queries_from_contracts(state: AgentState) -> list[str]:
    contracts = state.get("report_section_contracts") or []
    brief = state.get("report_brief") or {}
    topic = str((state.get("query_understanding") or {}).get("main_topic") or "").strip()[:80]

    queries: list[str] = []
    seen: set[str] = set()

    for contract in contracts:
        if not contract.get("evidence_required") or contract.get("data_scope") == "none":
            continue
        title = str(contract.get("title") or "").strip()
        query = " ".join(f"{topic} {title}".split())[:140]
        if len(query) < 8 or query.lower() in seen:
            continue
        seen.add(query.lower())
        queries.append(query)

    if not queries:
        for need in brief.get("information_needs") or []:
            query = str(need or "").strip()[:140]
            if query and query.lower() not in seen:
                seen.add(query.lower())
                queries.append(query)

    return queries[:4]


def report_evidence_gate_node(state: AgentState) -> AgentState:
    if (not state.get("report_mode_enabled")
            or state.get("report_execution_path") == "simple"
            or not getattr(settings, "REPORT_EVIDENCE_GAP_ENABLED", True)):
        return {"report_evidence_retry": False}

    attempts = int(state.get("report_evidence_attempts", 0) or 0)
    max_attempts = int(getattr(settings, "REPORT_EVIDENCE_GAP_MAX_ATTEMPTS", 1))
    gaps = state.get("evidence_gaps") or []

    if not gaps or attempts >= max_attempts:
        return {"report_evidence_retry": False, "report_evidence_attempts": attempts}

    queries = _gap_queries_from_contracts(state)
    if not queries:
        return {"report_evidence_retry": False, "report_evidence_attempts": attempts}

    old_plan = state.get("retrieval_plan") or {}
    new_plan = {
        **old_plan,
        "intents": [
            {"query": q, "purpose": "requirement", "priority": 2,
             "source_capabilities": ["secondary_research"]}
            for q in queries
        ],
        "max_search_intents": len(queries),
        "use_foundational_search": False,
        "use_citation_backtracking": False,
    }
    log.info("report_evidence_gate retry attempt=%d/%d queries=%s",
             attempts + 1, max_attempts, queries)

    return {
        "report_evidence_retry": True,
        "report_evidence_attempts": attempts + 1,
        "retrieval_plan": new_plan,
        "report_evidence_gap_queries": queries,
    }


def route_after_report_evidence_gate(state: AgentState) -> str:
    if not state.get("report_evidence_retry"):
        return "report_writer"
    if state.get("evidence_mode") in ("uploaded", "blended"):
        return "retrieve_uploaded"
    if state.get("evidence_mode") == "literature":
        return "report_gap_search"
    return "report_writer"


async def report_gap_search_node(state: AgentState) -> AgentState:
    """Gap retry: run search, but KEEP the papers from the first pass."""
    from app.agents.nodes.search_node import search_node
    from app.agents.research_engine import merge_duplicate_papers

    prior = list(state.get("ranked_papers") or []) + list(state.get("raw_search_results") or [])
    result = await search_node(state)
    result["raw_search_results"] = merge_duplicate_papers(
        prior + (result.get("raw_search_results") or [])
    )
    return result