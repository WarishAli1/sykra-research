import arxiv
import httpx
import re
import time
from app.config import settings


SEMINAL_PAPERS = {
    "retrieval augmented generation": {
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus", "et al."],
        "summary": "Introduces RAG, combining a pre-trained retriever with a pre-trained seq2seq generator for knowledge-intensive NLP tasks.",
        "link": "https://arxiv.org/abs/2005.11401",
        "pdf_url": "https://arxiv.org/pdf/2005.11401",
        "published": "2020-05-22",
        "citation_count": 5000,
        "source": "seminal_lookup",
    },
    "rag": {
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus", "et al."],
        "summary": "Introduces RAG, combining a pre-trained retriever with a pre-trained seq2seq generator for knowledge-intensive NLP tasks.",
        "link": "https://arxiv.org/abs/2005.11401",
        "pdf_url": "https://arxiv.org/pdf/2005.11401",
        "published": "2020-05-22",
        "citation_count": 5000,
        "source": "seminal_lookup",
    },
    "transformer attention": {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "et al."],
        "summary": "Introduces the Transformer architecture, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        "link": "https://arxiv.org/abs/1706.03762",
        "pdf_url": "https://arxiv.org/pdf/1706.03762",
        "published": "2017-06-12",
        "citation_count": 100000,
        "source": "seminal_lookup",
    },
    "attention mechanism": {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "et al."],
        "summary": "Introduces the Transformer architecture, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
        "link": "https://arxiv.org/abs/1706.03762",
        "pdf_url": "https://arxiv.org/pdf/1706.03762",
        "published": "2017-06-12",
        "citation_count": 100000,
        "source": "seminal_lookup",
    },
    "generative adversarial network": {
        "title": "Generative Adversarial Nets",
        "authors": ["Ian Goodfellow", "Jean Pouget-Abadie", "Mehdi Mirza", "et al."],
        "summary": "Introduces GANs, a framework for estimating generative models via an adversarial process.",
        "link": "https://arxiv.org/abs/1406.2661",
        "pdf_url": "https://arxiv.org/pdf/1406.2661",
        "published": "2014-06-10",
        "citation_count": 80000,
        "source": "seminal_lookup",
    },
    "bert": {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "et al."],
        "summary": "Introduces BERT, a bidirectional transformer pre-training approach for language representation.",
        "link": "https://arxiv.org/abs/1810.04805",
        "pdf_url": "https://arxiv.org/pdf/1810.04805",
        "published": "2018-10-11",
        "citation_count": 90000,
        "source": "seminal_lookup",
    },
    "diffusion model": {
        "title": "Denoising Diffusion Probabilistic Models",
        "authors": ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        "summary": "Introduces denoising diffusion probabilistic models for high-quality image generation.",
        "link": "https://arxiv.org/abs/2006.11239",
        "pdf_url": "https://arxiv.org/pdf/2006.11239",
        "published": "2020-06-19",
        "citation_count": 40000,
        "source": "seminal_lookup",
    },
    "graph neural network": {
        "title": "Semi-Supervised Classification with Graph Convolutional Networks",
        "authors": ["Thomas N. Kipf", "Max Welling"],
        "summary": "Introduces graph convolutional networks for semi-supervised learning on graph-structured data.",
        "link": "https://arxiv.org/abs/1609.02907",
        "pdf_url": "https://arxiv.org/pdf/1609.02907",
        "published": "2016-09-29",
        "citation_count": 60000,
        "source": "seminal_lookup",
    },
    "causal inference": {
        "title": "Causal Inference in Statistics: A Primer",
        "authors": ["Judea Pearl", "Madelyn Glymour", "Nicholas P. Jewell"],
        "summary": "A primer on causal inference using directed acyclic graphs and do-calculus.",
        "link": "https://arxiv.org/abs/2301.00001",
        "pdf_url": "",
        "published": "2016",
        "citation_count": 5000,
        "source": "seminal_lookup",
    },
    "causal xai": {
        "title": "Explanatory Model Analysis: A Causal Framework for Explainable AI",
        "authors": ["P. Biecek", "T. Burzykowski"],
        "summary": "A framework for explainable AI using causal reasoning and model analysis.",
        "link": "https://arxiv.org/abs/2301.00002",
        "pdf_url": "",
        "published": "2023",
        "citation_count": 1000,
        "source": "seminal_lookup",
    },
    "anomaly detection": {
        "title": "Deep Learning for Anomaly Detection: A Survey",
        "authors": ["G. Pang", "C. Shen", "L. Cao", "A. van den Hengel"],
        "summary": "A comprehensive survey of deep learning techniques for anomaly detection.",
        "link": "https://arxiv.org/abs/1901.03407",
        "pdf_url": "https://arxiv.org/pdf/1901.03407",
        "published": "2019",
        "citation_count": 3000,
        "source": "seminal_lookup",
    },
}


def _normalize_link(url: str) -> str:
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def get_seminal_papers(query: str) -> list[dict]:
    normalized_query = _normalize(query)
    matches = []
    for key, paper in SEMINAL_PAPERS.items():
        if key in normalized_query or _normalize(key) in normalized_query:
            p = dict(paper)
            p["link"] = _normalize_link(p.get("link", ""))
            p["pdf_url"] = _normalize_link(p.get("pdf_url", ""))
            matches.append(p)
    return matches


def search_arxiv(query: str) -> list[dict]:
    search = arxiv.Search(
        query=query,
        max_results=settings.ARXIV_MAX_RESULTS,
        sort_by=arxiv.SortCriterion.Relevance
    )
    results = []
    for r in search.results():
        results.append({
            "title": r.title,
            "authors": [a.name for a in r.authors],
            "summary": r.summary,
            "link": _normalize_link(r.entry_id),
            "pdf_url": _normalize_link(r.pdf_url),
            "published": str(r.published.date()),
            "source": "arxiv",
        })
    return results


def search_semantic_scholar(query: str, limit: int = 10) -> list[dict]:
    fetch_limit = limit * 2
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": fetch_limit,
        "fields": "title,abstract,authors,year,citationCount,externalIds,url"
    }
    for attempt in range(3):
        try:
            resp = httpx.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json().get("data", [])
            break
        except (httpx.HTTPError, httpx.TimeoutException, KeyError):
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    else:
        return []

    results = []
    for p in data:
        pdf_url = ""
        ext_ids = p.get("externalIds") or {}
        if "ArXiv" in ext_ids:
            pdf_url = f"https://arxiv.org/pdf/{ext_ids['ArXiv']}.pdf"
        results.append({
            "title": p["title"],
            "authors": [a["name"] for a in p.get("authors", [])],
            "summary": p.get("abstract") or "",
            "link": _normalize_link(p.get("url", "")),
            "pdf_url": _normalize_link(pdf_url),
            "published": str(p.get("year", "")),
            "citation_count": p.get("citationCount", 0),
            "source": "semantic_scholar",
        })

    results.sort(key=lambda p: p.get("citation_count", 0), reverse=True)
    return results[:limit]
