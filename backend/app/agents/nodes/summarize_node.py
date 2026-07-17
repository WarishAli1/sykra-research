import json
import re
from difflib import SequenceMatcher
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import BatchPaperSummaries, NormalAnswer, ResearchAnswer, PaperSummaryItem
from app.services.llm_client import get_llm
from app.services.reference_builder import (
    build_references, paper_id_to_ref_id_map, rewrite_inline_citations, format_reference_block,
)
from app.utils.text_cleaning import sanitize_abstract


def _invoke_structured_with_repair(llm, messages, schema, max_retries=2):
    """Invokes the LLM with structured output, retrying with error feedback if validation fails."""
    for attempt in range(max_retries + 1):
        try:
            result = llm.with_structured_output(schema).invoke(messages, config={"timeout": 45})
            # Fallback manual validation if the provider returns a dict instead of a Pydantic model
            if isinstance(result, dict):
                result = schema.model_validate(result)
            return result
        except Exception as e:
            if attempt == max_retries:
                print(f"[summarize] Structured output failed after {max_retries} retries: {e}")
                return None

            error_str = str(e)
            if len(error_str) > 1000:
                error_str = error_str[:1000] + "... (truncated)"

            repair_msg = (
                f"Your previous output failed schema validation.\n"
                f"Errors:\n{error_str}\n\n"
                f"Please correct your output to exactly match the required schema. "
                f"Do not omit any required fields, and ensure all fields are of the correct type."
            )
            messages = messages + [HumanMessage(content=repair_msg)]
            print(f"[summarize] Schema validation failed, retrying ({attempt + 1}/{max_retries})...")


def _classify_evidence_type(paper: dict, query: str, summaries: dict) -> str:
    """Classify paper as direct, supporting, or background evidence."""
    summary = summaries.get(paper.get("_idx", "0"), {})
    relevance = summary.get("relevance_to_query", "").lower()
    contribution = summary.get("key_contribution", "").lower()
    title = paper.get("title", "").lower()

    # Direct evidence: explicitly studies the requested topic
    direct_indicators = ["directly addresses", "explicitly studies", "proposes", "introduces", "framework for"]
    if any(ind in relevance for ind in direct_indicators):
        return "direct"

    # Check if paper's main contribution matches query intent
    query_words = set(query.lower().split())
    title_words = set(title.split())
    if len(query_words & title_words) >= 3:
        return "direct"

    # Supporting evidence: related method/dataset/domain
    supporting_indicators = ["related to", "similar approach", "applies to", "uses", "dataset for"]
    if any(ind in relevance for ind in supporting_indicators):
        return "supporting"

    # Background: general concepts only
    return "background"

def _build_paper_block_with_classification(papers: list[dict], summaries: dict) -> str:
    """Build paper block with evidence type classification."""
    paper_parts = []
    for i, p in enumerate(papers):
        p["_idx"] = str(i)  # Track index for classification
        abstract = p.get("text", sanitize_abstract(p.get("summary", " ")))
        if len(abstract) < 20 or "\x02" in abstract or "\x01" in abstract:
            abstract = f"[Abstract stripped. Paper: {p['title']}]"

        evidence_type = _classify_evidence_type(p, "", summaries)
        paper_parts.append(
            f"[paper_id={i}] [Evidence: {evidence_type.upper()}]\n"
            f"Title: {p['title']}\n"
            f"Abstract: {abstract[:1500]}"
        )
    return "\n\n".join(paper_parts)

def _summarize_papers(llm, papers: list[dict], query: str) -> dict:
    """Summarize papers and classify evidence type."""
    paper_block = _build_paper_block_with_classification(papers, {})

    batch_messages = [
        SystemMessage(content="Summarize each paper using BatchPaperSummaries. Classify evidence type as 'direct', 'supporting', or 'background' based on how directly it addresses the query."),
        HumanMessage(content=f"Query: {query}\n\n{paper_block}"),
    ]

    try:
        result: BatchPaperSummaries = llm.with_structured_output(BatchPaperSummaries).invoke(
            batch_messages, config={"timeout": 20}
        )
        summaries = {s.paper_id: s.model_dump() for s in result.summaries}

        # Trust the LLM's evidence classification — it's more accurate than
        # keyword-based re-classification which over-counts "direct" due to
        # common academic language like "proposes" and "introduces".
        for i, p in enumerate(papers):
            p["_idx"] = str(i)

        return summaries
    except Exception:
        return {
            str(i): {
                "paper_id": str(i),
                "key_contribution": p['title'],
                "methodology": "",
                "findings": "",
                "relevance_to_query": "",
                "evidence_type": "supporting"
            }
            for i, p in enumerate(papers)
        }

def _count_evidence_types(summaries: dict) -> dict:
    """Count papers by evidence type."""
    counts = {"direct": 0, "supporting": 0, "background": 0}
    for s in summaries.values():
        etype = s.get("evidence_type", "supporting")
        counts[etype] = counts.get(etype, 0) + 1
    return counts

def _select_top_references(papers: list[dict], summaries: dict, mode: str, max_refs: int = 5) -> list[str]:
    """Select most relevant paper IDs for references."""
    direct_ids = []
    supporting_ids = []

    for i, p in enumerate(papers):
        sid = str(i)
        if sid not in summaries:
            continue
        etype = summaries[sid].get("evidence_type", "supporting")
        if etype == "direct":
            direct_ids.append(sid)
        elif etype == "supporting":
            supporting_ids.append(sid)

    if mode == "normal":
        # Normal mode: 1-3 most relevant
        selected = direct_ids[:2] + supporting_ids[:1]
        return selected[:3]
    else:
        # Research mode: up to 8, prioritize direct
        selected = direct_ids + supporting_ids
        return selected[:max_refs]

def _run_normal_mode(llm, state: AgentState, papers: list[dict], summaries: dict) -> NormalAnswer:
    """Generate concise but detailed normal mode answer."""
    evidence_counts = _count_evidence_types(summaries)
    n_direct = evidence_counts["direct"]
    n_supporting = evidence_counts["supporting"]

    # Determine evidence strength and FORCE confidence rules (Consistent with Researched mode)
    if n_direct >= 2:
        evidence_strength = "High"
        strength_reason = "Multiple directly relevant studies found with consistent evidence."
    elif n_direct == 1:
        evidence_strength = "Medium"
        strength_reason = "Only one direct study found; lacks broader validation or comparisons."
    else:
        evidence_strength = "Low"
        strength_reason = "No direct studies found; relying on indirect or theoretical support."

    paper_block = "\n\n".join([
        f"[{i}] [{summaries.get(str(i), {}).get('evidence_type', 'supporting').upper()}] {p['title']}: {summaries.get(str(i), {}).get('key_contribution', '')}"
        for i, p in enumerate(papers)
    ])

    prompt = f"""You are a research assistant providing a direct but thorough answer.
QUERY: {state['query']}
EVIDENCE AVAILABLE:
Direct evidence: {n_direct} paper(s)
Supporting evidence: {n_supporting} paper(s)
PAPERS:
{paper_block}

INSTRUCTIONS & STRUCTURE:
1. DIRECT ANSWER: Provide 2-4 sentences directly answering the query.
2. BRIEF CONTEXT: Explain essential concepts in EXACTLY ONE sentence. ONLY include if strictly necessary.
3. EVIDENCE: This is the most important section. Do NOT just write a single paragraph. Summarize 2-4 key studies (or explain the single direct study in depth if only one exists). For each study, explicitly cover:
   - What the study proposed
   - How it was evaluated
   - Datasets used
   - Main findings
   - Why it matters
   Use bolding for study names or key terms to make it readable.
4. LIMITATIONS: Provide an expanded list of limitations (at least 3-5 points). You MUST include specific methodological gaps such as: lack of replication, absence of user studies, limited benchmarks, no comparison with other techniques, or uncertain generalizability.
5. CONCLUSION: Instead of a single sentence, briefly answer these three questions:
   - What is supported by the evidence?
   - What remains uncertain?
   - What should future work investigate?

CONFIDENCE RULES (CRITICAL - MUST BE CONSISTENT):
- If direct evidence >= 2: Confidence is "High".
- If direct evidence == 1: Confidence is "Medium". (Do NOT use High for a single study).
- If direct evidence == 0: Confidence is "Low".

CRITICAL RULES:
- Do NOT claim a paper solves the problem unless it explicitly does.
- Do NOT combine unrelated papers into a fictional framework.
- If evidence is weak, explicitly state that in the Conclusion.

Generate a NormalAnswer JSON object matching the schema exactly."""

    try:
        answer = _invoke_structured_with_repair(
            llm,
            [
                SystemMessage(content="Respond with ONLY a function call to NormalAnswer. No text before or after."),
                HumanMessage(content=prompt)
            ],
            NormalAnswer,
            max_retries=2
        )
        if answer is None:
            raise ValueError("Failed to generate valid NormalAnswer after retries")

        # Override LLM confidence with actual evidence-based confidence to ensure consistency
        answer.confidence = evidence_strength
        answer.confidence_explanation = strength_reason
        return answer
    except Exception as e:
        print(f"[summarize] Normal mode failed: {e}")
        return NormalAnswer(
            direct_answer="I could not generate a structured answer due to a processing error.",
            brief_context=None,
            evidence="",
            limitations=["Processing error occurred."],
            conclusion="Please try again.",
            confidence="Low",
            confidence_explanation="Processing error.",
            references=[]
        )

def _run_researched_mode(llm, state: AgentState, papers: list[dict], summaries: dict) -> ResearchAnswer:
    """Generate detailed research mode answer."""
    evidence_counts = _count_evidence_types(summaries)
    n_direct = evidence_counts["direct"]
    n_total = len(papers)

    paper_block = "\n\n".join([
        f"[{i}] [{summaries.get(str(i), {}).get('evidence_type', 'supporting').upper()}] {p['title']}: {summaries.get(str(i), {}).get('key_contribution', '')}"
        for i, p in enumerate(papers)
    ])

    # Determine which sections to include
    include_comparative = n_direct >= 2

    prompt = f"""You are a domain researcher writing a detailed literature review.
QUERY: {state['query']}
EVIDENCE AVAILABLE:
Total papers: {n_total}
Direct evidence: {n_direct} paper(s)
Supporting evidence: {evidence_counts['supporting']} paper(s)
PAPERS:
{paper_block}

INSTRUCTIONS & STRUCTURE:
1. EXECUTIVE SUMMARY: High-level summary of what literature supports, what is uncertain, and the final answer.
2. BACKGROUND CONCEPTS: Explain concepts from general → specific. Teach before evaluating. Only include what's relevant.
3. RELATED RESEARCH: Briefly cover adjacent areas and explain their relevance to the question.
4. LITERATURE REVIEW: Synthesize key papers (methods, datasets, metrics, findings). Synthesize, do NOT just list papers one by one.
5. COMPARATIVE ANALYSIS {'(REQUIRED - multiple direct studies exist)' if include_comparative else '(OPTIONAL - include only if meaningful)'}: Compare methods, datasets, or findings. Use a markdown table if helpful.
6. EVIDENCE ASSESSMENT: Discuss strength, consistency, and limitations of current evidence.
7. RESEARCH GAPS: Identify genuine unanswered questions or missing areas.
8. PRACTICAL IMPLICATIONS: Actionable implications. Clearly separate established evidence from speculation.
9. FINAL ANSWER: The definitive, synthesized answer to the user's original question.

FORMATTING REQUIREMENTS:
- Use proper markdown formatting throughout.
- Use ## for section headers.
- Use bullet points (- item) for lists.
- Each paragraph should be separated by a blank line.

CRITICAL RULES:
- Synthesize literature instead of listing papers.
- Support claims with citations (use [paper_id=N] format).
- Clearly distinguish established evidence from speculation.
- Do NOT combine unrelated studies into fictional frameworks.
- If no direct evidence exists, state "No direct evidence was found" and explain the closest research.

Generate a ResearchAnswer JSON object matching the schema exactly."""

    try:
        answer = _invoke_structured_with_repair(
            llm,
            [
                SystemMessage(content="Respond with ONLY a function call to ResearchAnswer. No text before or after."),
                HumanMessage(content=prompt)
            ],
            ResearchAnswer,
            max_retries=2
        )
        if answer is None:
            raise ValueError("Failed to generate valid ResearchAnswer after retries")

        # Handle adaptive sections
        if not include_comparative:
            answer.comparative_analysis = None
        return answer
    except Exception as e:
        print(f"[summarize] Research mode failed: {e}")
        return ResearchAnswer(
            executive_summary="Processing error occurred.",
            background_concepts="",
            related_research="",
            literature_review="",
            comparative_analysis=None,
            evidence_assessment="",
            research_gaps="",
            practical_implications="",
            final_answer="I could not generate a structured answer due to a processing error.",
            confidence="Low",
            confidence_explanation="Processing error.",
            references=[]
        )

def _stitch_normal_answer(answer: NormalAnswer) -> str:
    """Format normal mode answer."""
    parts = []
    parts.append(f"## Direct Answer\n\n{answer.direct_answer}\n")

    if answer.brief_context:
        parts.append(f"## Brief Context\n\n{answer.brief_context}\n")

    evidence = answer.evidence.replace("\\n", "\n")
    parts.append(f"## Evidence\n\n{evidence}\n")

    if answer.limitations:
        parts.append("## Limitations\n")
        for lim in answer.limitations:
            parts.append(f"- {lim}")
        parts.append("")

    conclusion = answer.conclusion.replace("\\n", "\n")
    parts.append(f"## Conclusion\n\n{conclusion}\n")
    parts.append(f"**Confidence**: {answer.confidence} – {answer.confidence_explanation}\n")

    return "\n".join(parts)


def _stitch_research_answer(answer: ResearchAnswer) -> str:
    """Format research mode answer with proper markdown."""
    parts = []

    if answer.executive_summary:
        parts.append(f"## Executive Summary\n\n{answer.executive_summary.replace(chr(92)+'n', chr(10))}\n")
    if answer.background_concepts:
        parts.append(f"## Background Concepts\n\n{answer.background_concepts.replace(chr(92)+'n', chr(10))}\n")
    if answer.related_research:
        parts.append(f"## Related Research\n\n{answer.related_research.replace(chr(92)+'n', chr(10))}\n")
    if answer.literature_review:
        parts.append(f"## Literature Review\n\n{answer.literature_review.replace(chr(92)+'n', chr(10))}\n")
    if answer.comparative_analysis:
        parts.append(f"## Comparative Analysis\n\n{answer.comparative_analysis.replace(chr(92)+'n', chr(10))}\n")
    if answer.evidence_assessment:
        parts.append(f"## Evidence Assessment\n\n{answer.evidence_assessment.replace(chr(92)+'n', chr(10))}\n")
    if answer.research_gaps:
        gaps = answer.research_gaps.replace(chr(92)+'n', chr(10))
        gaps = re.sub(r'\d+\)\s*', '- ', gaps)
        parts.append(f"## Research Gaps\n\n{gaps}\n")
    if answer.practical_implications:
        parts.append(f"## Practical Implications\n\n{answer.practical_implications.replace(chr(92)+'n', chr(10))}\n")
    if answer.final_answer:
        parts.append(f"## Final Answer\n\n{answer.final_answer.replace(chr(92)+'n', chr(10))}\n")

    ce = answer.confidence_explanation.replace(chr(92)+'n', chr(10))
    parts.append(f"## Confidence: {answer.confidence}\n\n{ce}\n")

    return "\n".join(parts)

def summarize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    papers = state["ranked_papers"]
    mode = state.get("response_mode", "normal")

    if not papers:
        attempts = state.get("search_attempts", 0)
        terms_tried = state.get("search_terms") or [state.get("query", "")]
        terms_str = ", ".join(f'"{t}"' for t in terms_tried)
        message = (
            f"I searched arXiv and OpenAlex ({attempts} attempt(s), terms: {terms_str}) but couldn't find "
            f"papers that scored above a usable relevance threshold for this query. This usually means the "
            f"topic is very narrow, very new, or phrased differently in the literature.\n\n"
            f"Try: broadening the query, using more standard field terminology, or rephrasing around a related "
            f"technique or application area."
        )
        return {
            **state,
            "final_answer": message,
            "coverage_gaps": state.get("search_terms", []),
            "references": [],
        }

    # Summarize papers with evidence classification
    summaries = _summarize_papers(llm, papers, state["query"])

    # Generate answer based on mode
    if mode == "researched":
        final = _run_researched_mode(llm, state, papers, summaries)
        answer_text = _stitch_research_answer(final)
        ref_ids = final.references if final.references else _select_top_references(papers, summaries, mode, max_refs=8)
    else:
        final = _run_normal_mode(llm, state, papers, summaries)
        answer_text = _stitch_normal_answer(final)
        ref_ids = final.references if final.references else _select_top_references(papers, summaries, mode, max_refs=3)

    # Build references and rewrite citations (NO markdown block appended)
    references = build_references(papers)
    id_map = paper_id_to_ref_id_map(papers, references)
    answer_text = rewrite_inline_citations(answer_text, id_map)

    # Filter to only selected references (3-5 for normal, up to 8 for researched)
    selected_refs = [r for i, r in enumerate(references) if str(i) in ref_ids] if references else []

    # For researched mode, show ALL references in the frontend UI.
    # For normal mode, only show the 3-5 selected references.
    frontend_references = references if mode == "researched" else selected_refs

    # Handle confidence and caveats
    domain_caveat = state.get("domain_caveat")
    if state.get("low_confidence_results"):
        low_conf_note = (
            "Few strongly relevant papers were found, so the relevance threshold was relaxed. "
            "Treat this answer as a starting point rather than a comprehensive review."
        )
        domain_caveat = f"{domain_caveat} {low_conf_note}" if domain_caveat else low_conf_note

    return {
        **state,
        "summaries": summaries,
        "final_answer": answer_text,
        "coverage_gaps": [],
        "domain_caveat": domain_caveat,
        "references": frontend_references,
    }
