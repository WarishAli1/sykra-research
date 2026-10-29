def report_extra_text(state) -> str:
    """
    Everything the user supplied, everything deterministic code derived,
    and everything in the evidence ledger.

    This prevents final citation grounding from stripping user-provided
    or evidence-supported values.
    """
    bits: list[str] = []

    query = state.get("query", "")
    if query:
        bits.append(query)

    for record in state.get("report_source_records") or []:
        value = str(record.get("value", "") or "")
        original = str(record.get("original_text", "") or "")
        field_name = str(record.get("field_name", "") or "")

        if value:
            bits.append(value)

        if field_name:
            bits.append(field_name)

        if original:
            bits.append(original)

    for discrepancy in state.get("report_discrepancies") or []:
        description = str(discrepancy.get("description", "") or "")
        if description:
            bits.append(description)

    for item in state.get("evidence_ledger") or []:
        if item.get("category") == "gap":
            continue

        content = str(item.get("content", "") or "")
        value_raw = str(item.get("value_raw", "") or "")

        if content:
            bits.append(content[:300])

        if value_raw:
            bits.append(value_raw)

    cleaned = []

    for bit in bits:
        bit = str(bit or "").strip()
        if bit:
            cleaned.append(bit)

    return "\n".join(cleaned[:250])


def is_auto_title(title: str, query: str) -> bool:
    """True if the title is just the (truncated) user request."""
    t = " ".join((title or "").replace("…", "").split()).lower()
    q = " ".join((query or "").split()).lower()
    return not t or q.startswith(t) or t.startswith(q[:60])