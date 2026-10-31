import re

from app.agents.state import AgentState
from app.config import settings
from app.services.citation_grounding import ground_text
from app.services.reference_builder import (
    CitationNumberer,
    paper_id_to_ref_id_map,
)
from app.services.citation_formatter import format_apa
from app.agents.report_text import report_extra_text
from app.utils.numbers import number_in_text, sign_preserved


def _method_note(state, n_cited):
    if state.get("report_mode_enabled"):
        res = state.get("report_validation_results") or {}
        status = "passed" if res.get("passed", True) else "unresolved issues"
        return (
            f"Report mode: {n_cited} cited sources. Figures you supplied are reproduced as given; "
            f"automated validation: {status}. This is a draft, so verify before use."
        )
    mode = state.get("response_mode", "normal")
    ver = state.get("verification_status", "not_run")

    if mode == "normal":
        return (
            f"Direct mode: {n_cited} cited sources. "
            "Not a systematic review."
        )

    return (
        f"Researched mode: {n_cited} cited sources were checked against their abstracts "
        f"(claim audit: {ver}). This is not a systematic review."
    )


def citation_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])
    final_answer = state.get("final_answer", "") or ""
    report_update = {}

    if final_answer and papers:
        texts_by_id = {
            str(i): f"{p.get('title', '')}. {p.get('summary') or p.get('text') or ''}"
            for i, p in enumerate(papers)
        }
        final_answer, drops = ground_text(
            final_answer,
            texts_by_id,
            None,
            numeric_check=getattr(settings, "GROUNDING_NUMERIC_CHECK_ENABLED", True),
            extra_text=(report_extra_text(state) if state.get("report_mode_enabled")
                        else state.get("query", "")),
        )
        if drops:
            print(f"[ground:final] dropped/adjusted {len(drops)} claim(s) after revision")
            for d in drops:
                print(f"[ground:final]   - {d['reason']}: {d['sentence']}")

    if state.get("report_mode_enabled") and final_answer:
        lost = [
            rec for rec in (state.get("report_source_records") or [])
            if rec.get("category") == "user_provided"
            and rec.get("role") in ("count", "percentage", "amount")
            and (not number_in_text(rec["value"], final_answer)
                 or not sign_preserved(rec["value"], final_answer))
        ]
        if lost:
            res = dict(state.get("report_validation_results")
                       or {"passed": True, "errors": [], "warnings": []})
            res["passed"] = False
            res["errors"] = list(res.get("errors", [])) + [
                {"type": "lost_after_grounding", "severity": "error",
                 "description": f"Value {rec['value']} ({rec.get('field_name')}) was removed by the final citation check."}
                for rec in lost
            ]
            report_update["report_validation_results"] = res

    cited = []
    for pid in dict.fromkeys(
        re.findall(r"\[paper_id=(\d+)\]", final_answer)
    ):
        idx = int(pid)
        if 0 <= idx < len(papers):
            cited.append(papers[idx])
    citations = [format_apa(p) for p in cited]

    references = state.get("references", []) or []
    if final_answer:
        id_map = paper_id_to_ref_id_map(papers, references)
        numberer = CitationNumberer(id_map)
        final_answer = numberer.rewrite(final_answer)
        references = numberer.renumber_references(references)

    print("[cite-debug] final ref ids:", [r["id"] for r in references])

    return {
        "method_note": _method_note(state, len(references)),
        "citations": citations,
        "final_answer": final_answer,
        "references": references,
        **report_update,
    }