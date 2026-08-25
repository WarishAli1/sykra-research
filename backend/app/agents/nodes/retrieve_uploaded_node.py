import math
import re

from app.agents.state import AgentState
from app.agents.nodes.retrieval_plan_node import _decompose_uploaded_query
from app.services.embeddings import embed_texts, similarity
from app.services.vector_store import vector_store

_HEADING_RE = re.compile(r"(?im)^\s*(?:chapter|section|unit|part)\s+\d+(?:\.\d+)*[.:]\s*(.+?)\s*$")

RETRIEVE_CANDIDATES = 40        
BM25_TOP_N = 50                  
RRF_K = 60                       

MIN_CHUNK_SIM_NORMAL = 0.28     
MIN_CHUNK_SIM_DEEP = 0.22        

NEIGHBOR_CHARS_NORMAL = 450
NEIGHBOR_CHARS_DEEP = 800

MAX_DOCUMENTS_NORMAL = 3
MAX_DOCUMENTS_DEEP = 5

MAX_QUERIES = 8

_TOKEN_RE = re.compile(r"[a-z0-9+#.%/-]{3,}")

_HEADING_PATTERNS = (
    re.compile(r"(?im)^\s*(?:chapter|unit|part|section)\s+\d+[^\n]{0,80}\s*$"),
    re.compile(r"(?m)^\s*\d+(?:\.\d+)*\s+[A-Z][^\n]{2,80}\s*$"),
    re.compile(r"(?m)^\s*[A-Z][A-Z\s&,:()/-]{8,70}\s*$"),
)

_UPLOAD_SOURCE_LABELS = {
    "user_upload",
    "uploaded",
    "upload",
    "user_uploaded",
}


def _extract_document_map(chunks: list[dict]) -> str:
    """Extracts chapter/section headings to give the LLM structural awareness."""
    headings = []
    seen = set()
    sorted_chunks = sorted(chunks, key=lambda c: c.get("idx", 0))
    
    for c in sorted_chunks:
        text = c.get("text", "")
        for match in _HEADING_RE.finditer(text):
            heading = match.group(1).strip()
            if 3 < len(heading) < 100 and heading.lower() not in seen:
                seen.add(heading.lower())
                headings.append(heading)
    
    if not headings:
        return "No explicit table of contents or chapter headings detected in the chunks."
    
    return "DOCUMENT STRUCTURE & SCOPE (Use this to understand what the document actually covers):\n- " + "\n- ".join(headings[:25])


def _load_session_chunks(session_id: str) -> list[dict]:
    """
    Load all chunks for this session from the vector store.

    This is the document-collection layer. Instead of asking only
    "which chunks are similar to one query?", we first build an
    inventory of documents and chunks, then do hierarchical retrieval:

        document -> section -> chunk
    """
    try:
        res = vector_store.collection.get(
            where={"session_id": session_id},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        print(f"[retrieve_uploaded] session fetch failed: {type(e).__name__}: {e}")
        return []

    docs = res.get("documents", []) or []
    metas = res.get("metadatas", []) or []

    chunks: list[dict] = []

    for doc, meta in zip(docs, metas):
        meta = meta or {}
        try:
            idx = int(meta.get("chunk_index", 0))
        except Exception:
            idx = 0

        chunks.append(
            {
                "link": meta.get("link", "unknown"),
                "title": meta.get("title", "Uploaded document"),
                "idx": idx,
                "text": doc or "",
                "meta": meta,
            }
        )

    uploaded = [
        c
        for c in chunks
        if str(c["meta"].get("source", "")).lower() in _UPLOAD_SOURCE_LABELS
    ]

    if uploaded:
        chunks = uploaded

    return chunks


def _document_inventory(chunks: list[dict]) -> dict[str, dict]:
    inventory: dict[str, dict] = {}

    for chunk in chunks:
        link = chunk["link"]
        if link not in inventory:
            inventory[link] = {
                "title": chunk["title"],
                "chunks": [],
            }
        inventory[link]["chunks"].append(chunk)

    for link, entry in inventory.items():
        entry["chunks"].sort(key=lambda c: c["idx"])

    return inventory


def _section_label(text: str) -> str:
    """
    Deterministic heading detection.

    This does not require parser metadata. It detects common structural
    lines such as:

        Chapter 4 Environmental Impact of Energy Sources
        3.1 Solar Energy
        BATTERY HAZARDS

    The detected heading is used as a pseudo-section for diversity control
    and for making passage titles more useful.
    """
    best = ""

    for pattern in _HEADING_PATTERNS:
        for match in pattern.finditer(text or ""):
            candidate = " ".join(match.group(0).split())

            if not candidate:
                continue

            if len(candidate.split()) > 12:
                continue

            if len(candidate) > len(best):
                best = candidate

    return best[:90]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _build_keyword_index(
    chunks: list[dict],
) -> tuple[dict[str, float], list[list[str]]]:
    """
    Build a tiny BM25-style inverted statistic over the session chunks.

    This is deterministic and fast. It gives keyword recall for vocabulary
    mismatches such as:

        query: "environmental impact"
        document: "indoor air pollution health effects"

    Embedding similarity alone can miss this.
    """
    doc_tokens = [_tokenize(c["text"]) for c in chunks]
    n_docs = max(len(chunks), 1)

    df: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1

    idf = {
        token: math.log(1.0 + n_docs / (1.0 + doc_freq))
        for token, doc_freq in df.items()
    }

    return idf, doc_tokens


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    idf: dict[str, float],
) -> float:
    if not doc_tokens or not query_tokens:
        return 0.0

    tf: dict[str, int] = {}
    for token in doc_tokens:
        tf[token] = tf.get(token, 0) + 1

    score = 0.0

    for query_token in set(query_tokens):
        freq = tf.get(query_token, 0)
        if freq:
            score += idf.get(query_token, 1.0) * (1.0 + math.log(1.0 + freq))

    return score / (1.0 + math.log(1.0 + len(doc_tokens)))


def _rrf_merge(rank_lists: list[list[tuple]]) -> dict[tuple, float]:
    """
    Merge multiple ranked chunk lists using reciprocal rank fusion.

    Each rank list contains chunk keys:

        (document_link, chunk_index)

    RRF is robust, deterministic, and does not require score calibration
    between vector similarity and keyword scores.
    """
    scores: dict[tuple, float] = {}

    for ranked in rank_lists:
        for rank, key in enumerate(ranked):
            scores[key] = scores.get(key, 0.0) + (1.0 / (RRF_K + rank + 1))

    return scores


def _retrieval_queries(state: AgentState) -> list[str]:
    """
    Query strings to search the uploaded document collection with.

    Preference order:

    1. retrieval_plan intents from retrieval_plan_node.
    2. local deterministic decomposition fallback.
    3. raw user query.

    This node should never silently fall back to one raw query if the
    evidence mode is uploaded and the query can be decomposed.
    """
    plan = state.get("retrieval_plan") or {}
    intents = plan.get("intents") or []

    queries: list[str] = []
    seen: set[str] = set()

    for intent in intents:
        q = str((intent or {}).get("query") or "").strip()
        if not q:
            continue

        key = q.lower()
        if key in seen:
            continue

        seen.add(key)
        queries.append(q)

    if not queries and state.get("evidence_mode") in ("uploaded", "blended"):
        for q in _decompose_uploaded_query(state.get("query", "")):
            q = str(q or "").strip()
            if not q:
                continue

            key = q.lower()
            if key in seen:
                continue

            seen.add(key)
            queries.append(q)

    if not queries:
        queries = [state["query"]]

    return queries[:MAX_QUERIES]


def _retrieval_budget(
    state: AgentState,
    n_docs: int,
    n_chunks: int,
) -> dict:
    """
    Replace fixed MAX_PASSES with a collection-aware budget.

    Small upload:
        1-2 files / <100 pages
        -> 6-24 chunks

    Medium upload:
        3-10 files / 100-500 pages
        -> 24-32 chunks

    Large upload:
        10+ files / 500+ pages
        -> targeted retrieval
        -> stronger document filtering
        -> 32-40 chunks

    Normal mode keeps tighter limits to protect latency.
    """
    is_normal = state.get("response_mode", "normal") == "normal"
    n_docs = max(1, n_docs)

    if is_normal:
        max_total = 6 if n_docs <= 1 else 8
        max_docs = min(n_docs, MAX_DOCUMENTS_NORMAL)
    else:
        if n_chunks <= 200:
            max_total = 24
        elif n_chunks <= 600:
            max_total = 32
        else:
            max_total = 40

        max_docs = min(n_docs, MAX_DOCUMENTS_DEEP)

    if n_docs <= 1:
        per_doc_cap = max_total
    else:
        per_doc_cap = max(6, int(max_total * 0.45))

    min_per_doc = 1 if is_normal else 2

    return {
        "max_total": max_total,
        "max_docs": max_docs,
        "per_doc_cap": per_doc_cap,
        "min_per_doc": min_per_doc,
        "max_per_section": max(3, per_doc_cap // 3),
    }


def retrieve_uploaded_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "literature":
        return {"uploaded_context": []}

    session_id = state["session_id"]
    is_normal = state.get("response_mode", "normal") == "normal"

    queries = _retrieval_queries(state)

    chunks = _load_session_chunks(session_id)
    if not chunks:
        print("[retrieve_uploaded] no chunks found for session")
        return {"uploaded_context": []}

    inventory = _document_inventory(chunks)
    n_docs = len(inventory)

    budget = _retrieval_budget(state, n_docs, len(chunks))

    chunk_map: dict[tuple, dict] = {
        (c["link"], c["idx"]): c
        for c in chunks
    }

    print(
        f"[retrieve_uploaded] mode={state.get('evidence_mode')!r} "
        f"response_mode={state.get('response_mode')!r} "
        f"queries={len(queries)} docs={n_docs} chunks={len(chunks)} "
        f"budget_total={budget['max_total']} per_doc={budget['per_doc_cap']}"
    )


    vector_rankings: list[list[tuple]] = []
    n_results = min(RETRIEVE_CANDIDATES, len(chunks))

    for q in queries:
        try:
            results = vector_store.query_session(
                session_id=session_id,
                query_text=q,
                n_results=n_results,
            )
        except Exception as e:
            print(f"[retrieve_uploaded] vector query failed: {type(e).__name__}: {e}")
            continue

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            continue

        ranked: list[tuple] = []

        for meta in metadatas:
            meta = meta or {}
            try:
                idx = int(meta.get("chunk_index", 0))
            except Exception:
                idx = 0

            key = (meta.get("link", "unknown"), idx)

            if key in chunk_map:
                ranked.append(key)

        if ranked:
            vector_rankings.append(ranked)

    idf, doc_tokens = _build_keyword_index(chunks)

    keyword_rankings: list[list[tuple]] = []

    for q in queries:
        q_tokens = _tokenize(q)
        if not q_tokens:
            continue

        scored = []

        for i, tokens in enumerate(doc_tokens):
            score = _bm25_score(q_tokens, tokens, idf)
            if score > 0:
                chunk = chunks[i]
                scored.append(
                    (
                        score,
                        (chunk["link"], chunk["idx"]),
                    )
                )

        if not scored:
            continue

        scored.sort(key=lambda item: item[0], reverse=True)
        keyword_rankings.append([key for _, key in scored[:BM25_TOP_N]])

    combined = _rrf_merge(vector_rankings + keyword_rankings)

    if not combined:
        print("[retrieve_uploaded] no ranking signal produced")
        return {"uploaded_context": []}

    max_combined = max(combined.values()) or 1.0

    for key in combined:
        combined[key] = combined[key] / max_combined


    doc_scores: dict[str, float] = {}

    for link, entry in inventory.items():
        rels = sorted(
            (
                combined.get((link, c["idx"]), 0.0)
                for c in entry["chunks"]
            ),
            reverse=True,
        )

        top = rels[:3]

        if not top or top[0] <= 0:
            doc_scores[link] = 0.0
        else:
            doc_scores[link] = (0.6 * top[0]) + (0.4 * (sum(top) / len(top)))

    ranked_docs = sorted(
        doc_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    best_doc_score = ranked_docs[0][1] if ranked_docs else 0.0

    selected_docs: list[str] = []

    for link, score in ranked_docs:
        if len(selected_docs) >= budget["max_docs"]:
            break

        if selected_docs and score < max(0.20, 0.50 * best_doc_score):
            continue

        selected_docs.append(link)

    if not selected_docs and ranked_docs:
        selected_docs = [ranked_docs[0][0]]

    if len(selected_docs) == 1:

        budget["per_doc_cap"] = budget["max_total"]
        print(f"[retrieve_uploaded] single dominant doc, unlocking full budget: {budget['max_total']}")


    print(
        f"[retrieve_uploaded] selected documents="
        f"{[(link, round(doc_scores.get(link, 0.0), 3)) for link in selected_docs]}"
    )

    per_doc_selected: dict[str, list[dict]] = {}

    for link in selected_docs:
        doc_chunks = inventory[link]["chunks"]

        ordered = sorted(
            doc_chunks,
            key=lambda c: combined.get((link, c["idx"]), 0.0),
            reverse=True,
        )

        picked: list[dict] = []
        covered_windows: set[int] = set()
        section_counts: dict[str, int] = {}

        for chunk in ordered:
            if len(picked) >= budget["per_doc_cap"]:
                break

            key = (link, chunk["idx"])
            rel = combined.get(key, 0.0)

            if rel <= 0.0 and len(picked) >= budget["min_per_doc"]:
                continue

            window = chunk["idx"] // 2
            if window in covered_windows:
                continue

            section = _section_label(chunk["text"]) or f"block_{chunk['idx'] // 4}"

            if section_counts.get(section, 0) >= budget["max_per_section"]:
                continue

            covered_windows.add(window)
            section_counts[section] = section_counts.get(section, 0) + 1

            picked.append(chunk)

        per_doc_selected[link] = picked

    selected_chunks: list[dict] = []
    for link in selected_docs:
        selected_chunks.extend(per_doc_selected.get(link, []))
    print(
        f"[retrieve_uploaded] selected chunks before cosine verification="
        f"{len(selected_chunks)}"
    )

    for link in selected_docs:
        print(
            f"[retrieve_uploaded] "
            f"doc={inventory[link]['title']!r} "
            f"selected={len(per_doc_selected.get(link, []))}"
        )
    if not selected_chunks:
        print("[retrieve_uploaded] no chunks survived document/section selection")
        return {"uploaded_context": []}


    try:
        query_vecs = embed_texts(queries)

        candidate_vecs = embed_texts(
            [(c["text"] or "")[:1000] for c in selected_chunks]
        )
    except Exception as e:
        print(
            f"[retrieve_uploaded] embedding verification failed: "
            f"{type(e).__name__}: {e}"
        )
        query_vecs = []
        candidate_vecs = []

    if query_vecs and candidate_vecs:
        for chunk, candidate_vec in zip(selected_chunks, candidate_vecs):
            similarities = []

            for query_vec in query_vecs:
                try:
                    similarities.append(
                        float(similarity(query_vec, candidate_vec))
                    )
                except Exception:
                    continue

            chunk["_sim"] = max(similarities, default=0.0)

            if similarities:
                best_query_idx = max(
                    range(len(similarities)),
                    key=lambda i: similarities[i],
                )
                chunk["_sim_query_idx"] = best_query_idx
                chunk["_sim_query"] = queries[best_query_idx]
            else:
                chunk["_sim_query_idx"] = None
                chunk["_sim_query"] = ""

    else:
        for chunk in selected_chunks:
            chunk["_sim"] = combined.get(
                (chunk["link"], chunk["idx"]),
                0.0,
            )
            chunk["_sim_query_idx"] = None
            chunk["_sim_query"] = ""

    sim_floor = (
        MIN_CHUNK_SIM_NORMAL
        if is_normal
        else MIN_CHUNK_SIM_DEEP
    )

    final_chunks: list[dict] = []

    total_before_floor = len(selected_chunks)
    total_after_floor = 0

    for link in selected_docs:
        doc_selected = per_doc_selected.get(link, [])

        kept = [
            chunk
            for chunk in doc_selected
            if float(chunk.get("_sim", 0.0)) >= sim_floor
        ]

        total_after_floor += len(kept)

        if len(kept) < budget["min_per_doc"]:
            fallback = doc_selected[:budget["min_per_doc"]]

            existing = {
                (c["link"], c["idx"])
                for c in kept
            }

            for chunk in fallback:
                key = (chunk["link"], chunk["idx"])

                if key not in existing:
                    kept.append(chunk)

        final_chunks.extend(kept)

    final_chunks.sort(
        key=lambda c: float(c.get("_sim", 0.0)),
        reverse=True,
    )

    final_chunks = final_chunks[:budget["max_total"]]

    print(
        f"[retrieve_uploaded] cosine verification: "
        f"before={total_before_floor} "
        f"above_floor={total_after_floor} "
        f"after_fallback={len(final_chunks)} "
        f"floor={sim_floor}"
    )

    for i, chunk in enumerate(final_chunks[:10]):
        print(
            f"[retrieve_uploaded] top_chunk[{i}] "
            f"sim={float(chunk.get('_sim', 0.0)):.3f} "
            f"query_idx={chunk.get('_sim_query_idx')} "
            f"query={chunk.get('_sim_query', '')[:120]!r} "
            f"title={chunk.get('title', '')!r} "
            f"idx={chunk.get('idx')}"
        )

    if not final_chunks:
        print(
            "[retrieve_uploaded] all chunks failed similarity floor"
        )
        return {"uploaded_context": []}

    sibling_maps: dict[str, dict[int, str]] = {}

    for chunk in chunks:
        sibling_maps.setdefault(chunk["link"], {})[chunk["idx"]] = chunk["text"]

    neighbor_chars = NEIGHBOR_CHARS_NORMAL if is_normal else NEIGHBOR_CHARS_DEEP

    passages: list[dict] = []

    for chunk in final_chunks:
        link = chunk["link"]
        idx = chunk["idx"]

        siblings = sibling_maps.get(link, {})
        prev_text = siblings.get(idx - 1, "")
        next_text = siblings.get(idx + 1, "")

        merged = (
            (prev_text[-neighbor_chars:] + "\n" if prev_text else "")
            + chunk["text"]
            + ("\n" + next_text[:neighbor_chars] if next_text else "")
        )

        section = _section_label(chunk["text"])
        title = chunk["title"]

        if section and section.lower() not in title.lower():
            title = f"{title} — {section}"

        passages.append(
            {
                "title": title,
                "summary": merged,
                "link": f"user_upload://{link}",
                "source": "user_upload",
                "score": float(chunk.get("_sim", 0.0)),
                "published": chunk["meta"].get("published", None),
                "authors": (
                    [chunk["meta"].get("authors", "")]
                    if chunk["meta"].get("authors")
                    else []
                ),
            }
        )

    raw = list(state.get("raw_search_results", []))
    raw.extend(passages)

    print(
        f"[retrieve_uploaded] final passages={len(passages)} "
        f"budget={budget['max_total']} "
        f"docs={[p['title'].split(' — ')[0] for p in passages]}"
    )

    return {
        "raw_search_results": raw,
        "uploaded_context": passages,
        "document_map": _extract_document_map(chunks),
    }