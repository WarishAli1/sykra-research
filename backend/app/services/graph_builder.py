import asyncio
import json
import math
import os
import re
import threading
import time

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.services.llm_client import get_llm
from app.services.vector_store import vector_store
from app.services.embeddings import embed_texts, similarity
from app.services.graph_store import graph_store

CACHE_SCHEMA = 2


class PaperEntities(BaseModel):
    paper_id: str = Field(description="Index matching the [paper_id=N] marker")
    concepts: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)


class BatchPaperEntities(BaseModel):
    papers: list[PaperEntities]


_ENTITY_EXTRACTION_PROMPT = """Extract real research concepts and named methods/techniques discussed in each paper below.
PAPERS:
{paper_block}
Rules:
concepts = genuine research topics/ideas the paper is actually about.
Use CANONICAL, widely-used topic names so papers about the same topic share the exact same concept string
(e.g. "vision transformers", "reinforcement learning", "machine translation", "physics-informed machine learning").
Prefer broad reusable topic names over paper-specific phrasings.
methods = specific named methods, algorithms, models, or techniques the paper uses or proposes.
datasets = named datasets/benchmarks the paper uses or introduces (e.g. ImageNet, MNIST, Atari ALE).
Never include author names, institution names, place names, or generic words.
Return one PaperEntities entry per paper, in the same order.
Return a BatchPaperEntities JSON object.
"""

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _session_lock(session_id: str) -> threading.Lock:
    with _locks_guard:
        if session_id not in _locks:
            _locks[session_id] = threading.Lock()
        return _locks[session_id]


def _safe_session(session_id: str) -> str:
    return re.sub(r"[^\w-]", "", session_id)[:128] or "default"


def _cache_path(session_id: str) -> str:
    return os.path.join(settings.GRAPH_CACHE_DIR, f"{_safe_session(session_id)}.json")


def _load_cache(session_id: str) -> dict:
    try:
        with open(_cache_path(session_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(session_id: str, data: dict) -> None:
    try:
        os.makedirs(settings.GRAPH_CACHE_DIR, exist_ok=True)
        tmp = _cache_path(session_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _cache_path(session_id))
    except Exception as e:
        print(f"[graph_builder] cache save failed: {e}")


def _norm_term(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower()).rstrip(".")


def _extract_entities(batch: list[dict]) -> dict[str, dict]:
    """batch items: {link, title, text}. Returns {link: {concepts, methods, datasets}}."""
    out: dict[str, dict] = {}
    if not batch:
        return out
    llm = get_llm(temperature=0, task="fast")
    paper_block = "\n\n".join(
        f"[paper_id={i}]\nTitle: {p['title']}\nAbstract: {p['text']}"
        for i, p in enumerate(batch)
    )
    try:
        result = llm.with_structured_output(BatchPaperEntities).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to BatchPaperEntities."),
                HumanMessage(content=_ENTITY_EXTRACTION_PROMPT.format(paper_block=paper_block)),
            ],
            config={"timeout": 20},
        )
        if isinstance(result, dict):
            result = BatchPaperEntities.model_validate(result)
        for e in result.papers:
            idx = int(e.paper_id) if str(e.paper_id).isdigit() else -1
            if 0 <= idx < len(batch):
                out[batch[idx]["link"]] = {
                    "concepts": [_norm_term(c) for c in e.concepts if c and c.strip()][: settings.GRAPH_MAX_CONCEPTS_PER_PAPER],
                    "methods": [_norm_term(m) for m in e.methods if m and m.strip()][: settings.GRAPH_MAX_METHODS_PER_PAPER],
                    "datasets": [_norm_term(d) for d in e.datasets if d and d.strip()][: settings.GRAPH_MAX_DATASETS_PER_PAPER],
                }
    except Exception as e:
        print(f"[graph_builder] entity extraction failed: {type(e).__name__}: {e}")
    return out


def _fetch_cites_edges(papers_meta: list[dict], cache: dict, force: bool) -> tuple[list[dict], dict]:
    """Real directed CITES edges between session papers via OpenAlex referenced_works."""
    if not settings.GRAPH_OPENALEX_CITATIONS:
        return cache.get("cites", []), cache.get("cites_map", {})
    try:
        from app.services.paper_search import fetch_referenced_work_ids_async
    except Exception:
        return cache.get("cites", []), cache.get("cites_map", {})

    oid_to_link = {p["openalex_id"]: p["link"] for p in papers_meta if p.get("openalex_id")}
    if not oid_to_link:
        return cache.get("cites", []), cache.get("cites_map", {})

    cites_map = {} if force else {
        k: v for k, v in (cache.get("cites_map") or {}).items() if k in oid_to_link
    }
    missing = [oid for oid in oid_to_link if oid not in cites_map]
    if missing:
        try:
            async def go():
                return await asyncio.gather(
                    *[fetch_referenced_work_ids_async(oid, 300) for oid in missing],
                    return_exceptions=True,
                )
            results = asyncio.run(go())
            for oid, res in zip(missing, results):
                cites_map[oid] = [] if isinstance(res, Exception) else (res or [])
        except Exception as e:
            print(f"[graph_builder] citation fetch failed: {type(e).__name__}: {e}")

    seen, edges = set(), []
    for oid, refs in cites_map.items():
        src = oid_to_link.get(oid)
        if not src:
            continue
        for r in refs:
            dst = oid_to_link.get(r)
            if dst and dst != src and (src, dst) not in seen:
                seen.add((src, dst))
                edges.append({"source": src, "target": dst, "type": "cites"})
    return edges, cites_map


def _assemble_graph(papers_meta: list[dict], entities: dict[str, dict], cites_edges: list[dict]) -> dict:
    nodes, links = [], []
    link_set: set[tuple[str, str]] = set()

    for p in papers_meta:
        nodes.append({
            "id": p["link"], "name": p.get("title", "Untitled"),
            "type": "paper", "val": 10, "source": p.get("source", "unknown"),
            "published": p.get("published", "") or "",
            "authors": p.get("authors", []) or [],
            "citation_count": int(p.get("citation_count", 0) or 0),
            "excerpt": (p.get("_text", "") or "")[:300],
        })
    texts_embed = [f"{p.get('title', '')}. {p.get('_text', '')[:500]}" for p in papers_meta]
    vecs = embed_texts(texts_embed) if texts_embed else []

    for e in cites_edges:
        links.append(e)
        link_set.add(tuple(sorted((e["source"], e["target"]))))

    best: dict[str, list[tuple[float, str]]] = {p["link"]: [] for p in papers_meta}
    for i in range(len(papers_meta)):
        for j in range(i + 1, len(papers_meta)):
            s = similarity(vecs[i], vecs[j])
            if s >= settings.GRAPH_SIMILAR_EDGE_THRESHOLD:
                a, b = papers_meta[i]["link"], papers_meta[j]["link"]
                best[a].append((s, b))
                best[b].append((s, a))
    for src, neigh in best.items():
        neigh.sort(key=lambda x: x[0], reverse=True)
        for s, dst in neigh[: settings.GRAPH_MAX_SIMILAR_EDGES_PER_PAPER]:
            key = tuple(sorted((src, dst)))
            if key in link_set:
                continue
            link_set.add(key)
            links.append({"source": src, "target": dst, "type": "similar", "weight": round(s, 3)})

    for p in papers_meta:
        ent = entities.get(p["link"], {})
        for c in ent.get("concepts", []):
            cid = f"concept_{c}"
            if not any(n["id"] == cid for n in nodes):
                nodes.append({"id": cid, "name": c, "type": "concept", "val": 5})
            links.append({"source": p["link"], "target": cid, "type": "discusses"})
        for m in ent.get("methods", []):
            mid = f"method_{m}"
            if not any(n["id"] == mid for n in nodes):
                nodes.append({"id": mid, "name": m, "type": "method", "val": 5})
            links.append({"source": p["link"], "target": mid, "type": "uses"})
        for d in ent.get("datasets", []):
            did = f"dataset_{d}"
            if not any(n["id"] == did for n in nodes):
                nodes.append({"id": did, "name": d, "type": "dataset", "val": 5})
            links.append({"source": p["link"], "target": did, "type": "evaluates"})

    degree: dict[str, int] = {}
    for l in links:
        degree[l["source"]] = degree.get(l["source"], 0) + 1
        degree[l["target"]] = degree.get(l["target"], 0) + 1
    cite_by_link = {p["link"]: int(p.get("citation_count", 0) or 0) for p in papers_meta}
    for n in nodes:
        d = degree.get(n["id"], 0)
        boost = min(6, int(math.log1p(cite_by_link.get(n["id"], 0))))
        n["val"] = (10 if n["type"] == "paper" else 5) + min(d, 12) + boost
    return {"nodes": nodes, "links": links}


def _mirror_neo4j(session_id: str, papers_meta: list[dict], entities: dict, graph: dict) -> None:
    if not settings.GRAPH_NEO4J_MIRROR:
        return

    def run():
        try:
            for p in papers_meta:
                graph_store.upsert_paper(
                    {
                        "link": p["link"], "title": p.get("title", ""),
                        "published": p.get("published", ""), "source": p.get("source", "unknown"),
                        "summary": p.get("_text", "")[:2000],
                    },
                    session_id,
                )
            for link, ent in entities.items():
                for c in ent.get("concepts", []):
                    graph_store.link_concept(c, link)
                for m in ent.get("methods", []):
                    graph_store.link_method(m, link)
                for d in ent.get("datasets", []):
                    graph_store.link_dataset(d, link)
            link_similar = getattr(graph_store, "link_similar", None)  # optional method
            for l in graph["links"]:
                if l["type"] == "similar" and link_similar:
                    link_similar(l["source"], l["target"], l.get("weight", 0.0))
                elif l["type"] == "cites":
                    graph_store.link_citation(l["source"], l["target"])
        except Exception as e:
            print(f"[graph_builder] neo4j mirror failed: {type(e).__name__}: {e}")

    threading.Thread(target=run, daemon=True).start()


def semantic_query(session_id: str, q: str, top_k: int = 6) -> list[dict]:
    """Natural-language navigation: rank graph nodes by embedding similarity."""
    graph = build_session_graph(session_id)
    nodes = graph["nodes"]
    if not nodes or not (q or "").strip():
        return []
    texts = [
        f"{n['name']}. {n.get('excerpt', '')[:220]}" if n["type"] == "paper" else n["name"]
        for n in nodes
    ]
    vecs = embed_texts([q] + texts)
    qv, nvecs = vecs[0], vecs[1:]
    scored = sorted(zip(nodes, nvecs), key=lambda nv: similarity(qv, nv[1]), reverse=True)
    return [
        {"id": n["id"], "name": n["name"], "type": n["type"], "score": round(similarity(qv, v), 3)}
        for n, v in scored[:top_k]
    ]


def build_session_graph(session_id: str, force: bool = False) -> dict:
    if not settings.GRAPH_ENABLED:
        return {"nodes": [], "links": []}
    with _session_lock(session_id):
        cache = _load_cache(session_id)
        papers_meta = [
            p for p in vector_store.get_session_papers(session_id)
            if p.get("link") and p.get("title")
        ][: settings.GRAPH_MAX_PAPERS]
        if not papers_meta:
            return {"nodes": [], "links": []}

        current_links = sorted(p["link"] for p in papers_meta)
        schema_ok = cache.get("schema") == CACHE_SCHEMA

        if not force and schema_ok and cache.get("graph") and cache.get("paper_links") == current_links:
            return cache["graph"]

        if force or not schema_ok:
            entities: dict[str, dict] = {}
            no_entities: set[str] = set()
            new_papers = list(papers_meta)
        else:
            entities = {k: v for k, v in cache.get("entities", {}).items() if k in set(current_links)}
            no_entities = {k for k in cache.get("no_entity_links", []) if k in set(current_links)}
            known = set(entities) | no_entities
            new_papers = [p for p in papers_meta if p["link"] not in known]

        if new_papers:
            for p in new_papers:
                p["_text"] = (vector_store.get_full_text_for_paper(p["link"], session_id) or "")
            for start in range(0, len(new_papers), 8):
                batch = new_papers[start:start + 8]
                for p in batch:
                    p["text"] = p.get("_text", "")[: settings.GRAPH_ABSTRACT_CHARS_FOR_EXTRACTION]
                extracted = _extract_entities(batch)
                for p in batch:
                    if p["link"] in extracted:
                        entities[p["link"]] = extracted[p["link"]]
                    else:
                        no_entities.add(p["link"])

        for p in papers_meta:
            if "_text" not in p:
                p["_text"] = (vector_store.get_full_text_for_paper(p["link"], session_id) or "")

        cites_edges, cites_map = _fetch_cites_edges(papers_meta, cache, force)
        graph = _assemble_graph(papers_meta, entities, cites_edges)
        _save_cache(session_id, {
            "schema": CACHE_SCHEMA,
            "built_at": time.time(),
            "paper_links": current_links,
            "entities": entities,
            "no_entity_links": sorted(no_entities),
            "cites_map": cites_map,
            "cites": cites_edges,
            "graph": graph,
        })
        _mirror_neo4j(session_id, papers_meta, entities, graph)
        return graph


def get_clusters(session_id: str) -> list[dict]:
    graph = build_session_graph(session_id)
    clusters: dict[str, list[str]] = {}
    paper_names = {n["id"]: n["name"] for n in graph["nodes"] if n["type"] == "paper"}
    for l in graph["links"]:
        if l["type"] == "discusses" and l["target"].startswith("concept_"):
            name = l["target"][len("concept_"):]
            clusters.setdefault(name, [])
            if l["source"] in paper_names and paper_names[l["source"]] not in clusters[name]:
                clusters[name].append(paper_names[l["source"]])
    out = [
        {"concept": c, "papers": ps, "paper_count": len(ps)}
        for c, ps in clusters.items() if ps
    ]
    out.sort(key=lambda x: x["paper_count"], reverse=True)
    return out[:20]


def get_contradictions(session_id: str) -> list[dict]:
    return []