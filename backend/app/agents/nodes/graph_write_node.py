import re
from app.agents.state import AgentState
from app.services.graph_store import graph_store


def _extract_concepts(text: str) -> list[str]:
    words = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]+)*", text)
    return [w.lower() for w in words if len(w) > 3][:10]


def _extract_methods(text: str) -> list[str]:
    methods = re.findall(r"(?:CNN|RNN|LSTM|Transformer|BERT|GPT|GAN|ResNet|SVM|K-means|PCA|t-SNE|ReLU|GRU|Attention|Reinforcement Learning|Backpropagation|Dropout|BatchNorm|Transfer Learning|Fine-tuning|Autoencoder|Diffusion|VAE)", text, re.IGNORECASE)
    return list(set(m.lower() for m in methods))


def graph_write_node(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    contradictions = []
    entities = []

    for paper in state.get("ranked_papers", []):
        paper_link = paper.get("link", "")
        if not paper_link:
            continue

        graph_store.upsert_paper(paper, session_id)

        paper_text = (paper.get("text") or paper.get("summary") or paper.get("title", ""))
        concepts = _extract_concepts(paper_text)
        for c in concepts:
            graph_store.link_concept(c, paper_link)
            entities.append({"type": "concept", "name": c, "paper": paper_link})

        methods = _extract_methods(paper_text)
        for m in methods:
            graph_store.link_method(m, paper_link)
            entities.append({"type": "method", "name": m, "paper": paper_link})

    for i, paper_a in enumerate(state.get("ranked_papers", [])):
        for paper_b in state.get("ranked_papers", [])[i + 1:]:
            link_a = paper_a.get("link", "")
            link_b = paper_b.get("link", "")
            if link_a and link_b:
                graph_store.link_citation(link_a, link_b)

    return {
        **state,
        "graph_contradictions": contradictions,
        "graph_entities": entities,
    }
