import time
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from app.config import settings


class GraphStore:
    def __init__(self):
        self.available = True
        self._unavailable_until = 0.0
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

    def _safe_run(self, query: str, **params):
        if not self.available and time.time() < self._unavailable_until:
            return None
        try:
            with self.driver.session() as session:
                result = session.run(query, **params)
                self.available = True
                self._unavailable_until = 0.0
                return result
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
            self._unavailable_until = time.time() + 60.0
            print(f"[graph_store] neo4j unavailable: {type(exc).__name__}: {exc}")
            return None

    def ensure_constraints(self):
        stmts = [
            "CREATE CONSTRAINT paper_link IF NOT EXISTS FOR (p:Paper) REQUIRE p.link IS UNIQUE",
            "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
            "CREATE CONSTRAINT method_name IF NOT EXISTS FOR (m:Method) REQUIRE m.name IS UNIQUE",
        ]
        try:
            with self.driver.session() as session:
                for stmt in stmts:
                    session.run(stmt)
        except (ServiceUnavailable, SessionExpired) as exc:
            print(f"[graph_store] skipped constraints: {type(exc).__name__}: {exc}")

    def upsert_paper(self, paper: dict, session_id: str, turn_id: str | None = None) -> None:
        """turn_id is optional so existing callers (e.g. upload.py, which has
        no notion of a chat turn) keep working unchanged. When provided, it's
        recorded as one of possibly many turns that referenced this paper —
        stored as a list so a paper surfaced across several turns in the same
        session still shows up correctly scoped to each turn it appeared in."""
        self._safe_run(
            """
            MERGE (p:Paper {link: $link})
            ON CREATE SET p.title = $title, p.published = $published,
                          p.source = $source, p.text_excerpt = $text_excerpt,
                          p.session = $session_id,
                          p.turn_ids = CASE WHEN $turn_id IS NULL THEN [] ELSE [$turn_id] END
            ON MATCH SET p.text_excerpt = coalesce(p.text_excerpt, $text_excerpt),
                         p.session = coalesce(p.session, $session_id),
                         p.turn_ids = CASE
                             WHEN $turn_id IS NULL THEN coalesce(p.turn_ids, [])
                             WHEN $turn_id IN coalesce(p.turn_ids, []) THEN p.turn_ids
                             ELSE coalesce(p.turn_ids, []) + $turn_id
                         END
            """,
            link=paper["link"], title=paper["title"],
            published=str(paper.get("published", "")), source=paper.get("source", "unknown"),
            text_excerpt=(paper.get("text") or paper.get("summary", ""))[:2000],
            session_id=session_id,
            turn_id=turn_id,
        )

    def upsert_author(self, name: str, paper_link: str) -> None:
        self._safe_run(
            """
            MERGE (a:Author {name: $name})
            MERGE (p:Paper {link: $link})
            MERGE (a)-[:WROTE]->(p)
            """,
            name=name, link=paper_link,
        )

    def link_concept(self, name: str, paper_link: str) -> None:
        self._safe_run(
            """
            MERGE (c:Concept {name: $name})
            MERGE (p:Paper {link: $link})
            MERGE (p)-[:DISCUSSES]->(c)
            """,
            name=name.lower().strip(), link=paper_link,
        )

    def link_method(self, name: str, paper_link: str) -> None:
        self._safe_run(
            """
            MERGE (m:Method {name: $name})
            MERGE (p:Paper {link: $link})
            MERGE (p)-[:USES_METHOD]->(m)
            """,
            name=name.lower().strip(), link=paper_link,
        )

    def link_dataset(self, name: str, paper_link: str) -> None:
        self._safe_run(
            """
            MERGE (d:Dataset {name: $name})
            MERGE (p:Paper {link: $link})
            MERGE (p)-[:USES_DATASET]->(d)
            """,
            name=name.lower().strip(), link=paper_link,
        )

    def link_citation(self, citing_link: str, cited_link: str) -> None:
        self._safe_run(
            """
            MERGE (a:Paper {link: $citing})
            MERGE (b:Paper {link: $cited})
            MERGE (a)-[:CITES]->(b)
            """,
            citing=citing_link, cited=cited_link,
        )

    def link_contradiction(self, link_a: str, link_b: str, reason: str) -> None:
        self._safe_run(
            """
            MERGE (a:Paper {link: $a}) MERGE (b:Paper {link: $b})
            MERGE (a)-[r:CONTRADICTS]-(b) SET r.reason = $reason
            """,
            a=link_a, b=link_b, reason=reason,
        )

    def get_clusters(self, session_id: str) -> list[dict]:
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (p:Paper)-[:DISCUSSES]->(c:Concept)
                    WHERE p.session = $session_id
                    WITH c, collect(p.title) AS papers, count(p) AS paper_count
                    RETURN c.name AS concept, papers, paper_count
                    ORDER BY paper_count DESC LIMIT 20
                    """,
                    session_id=session_id,
                )
                self.available = True
                return [dict(r) for r in result]
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
            print(f"[graph_store] neo4j unavailable: {type(exc).__name__}: {exc}")
            return []

    def get_node_neighborhood(self, paper_link: str, hops: int = 1) -> dict:
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (p:Paper {link: $link})
                    OPTIONAL MATCH (p)-[:CITES]->(child:Paper)
                    OPTIONAL MATCH (parent:Paper)-[:CITES]->(p)
                    OPTIONAL MATCH (p)-[:DISCUSSES]->(c:Concept)
                    OPTIONAL MATCH (p)-[:USES_METHOD]->(m:Method)
                    RETURN p, collect(DISTINCT child) AS children,
                           collect(DISTINCT parent) AS parents,
                           collect(DISTINCT c.name) AS concepts,
                           collect(DISTINCT m.name) AS methods
                    """,
                    link=paper_link,
                )
                self.available = True
                record = result.single()
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
            print(f"[graph_store] neo4j unavailable: {type(exc).__name__}: {exc}")
            return {}

        if not record:
            return {}
        return {
            "paper": dict(record["p"]),
            "children": [dict(n) for n in record["children"] if n],
            "parents": [dict(n) for n in record["parents"] if n],
            "concepts": record["concepts"],
            "methods": record["methods"],
        }

    def get_contradictions(self, session_id: str) -> list[dict]:
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (a:Paper)-[r:CONTRADICTS]-(b:Paper)
                    WHERE a.session = $session_id AND b.session = $session_id
                    RETURN a.title AS paper_a, b.title AS paper_b, r.reason AS reason
                    """,
                    session_id=session_id,
                )
                self.available = True
                return [dict(r) for r in result]
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
            print(f"[graph_store] neo4j unavailable: {type(exc).__name__}: {exc}")
            return []

    def get_session_papers(self, session_id: str) -> list[dict]:
        try:
            with self.driver.session() as session:
                result = session.run(
                    "MATCH (p:Paper) WHERE p.session = $session_id RETURN p",
                    session_id=session_id,
                )
                self.available = True
                return [dict(r["p"]) for r in result]
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
            print(f"[graph_store] neo4j unavailable: {type(exc).__name__}: {exc}")
            return []

    def clear_session(self, session_id: str):
        self._safe_run("MATCH (n {session: $session_id}) DETACH DELETE n", session_id=session_id)


    def delete_paper(self, link: str):
        self._safe_run(
            """
            MATCH (p:Paper {link:$link})
            DETACH DELETE p
            """,
            link=link,
        )

    def get_full_graph(self, session_id: str) -> dict:
        try:
            with self.driver.session() as session:
                nodes = []
                edges = []
                known_ids = set()

                res_papers = session.run("MATCH (p:Paper {session: $sid}) RETURN p", sid=session_id)
                for r in res_papers:
                    p = dict(r["p"])
                    nid = p["link"]
                    nodes.append({"id": nid, "name": p.get("title", "Paper"), "type": "paper", "val": 10})
                    known_ids.add(nid)

                res_concepts = session.run("MATCH (c:Concept)<-[:DISCUSSES]-(p:Paper {session: $sid}) RETURN DISTINCT c", sid=session_id)
                for r in res_concepts:
                    c = dict(r["c"])
                    nid = f"concept_{c['name']}"
                    nodes.append({"id": nid, "name": c["name"], "type": "concept", "val": 5})
                    known_ids.add(nid)

                res_methods = session.run("MATCH (m:Method)<-[:USES_METHOD]-(p:Paper {session: $sid}) RETURN DISTINCT m", sid=session_id)
                for r in res_methods:
                    m = dict(r["m"])
                    nid = f"method_{m['name']}"
                    nodes.append({"id": nid, "name": m["name"], "type": "method", "val": 5})
                    known_ids.add(nid)

                res_cites = session.run("MATCH (a:Paper {session: $sid})-[:CITES]->(b:Paper) RETURN a.link, b.link", sid=session_id)
                for r in res_cites:
                    if r["a.link"] in known_ids and r["b.link"] in known_ids:
                        edges.append({"source": r["a.link"], "target": r["b.link"], "type": "cites"})

                res_disc = session.run("MATCH (p:Paper {session: $sid})-[:DISCUSSES]->(c:Concept) RETURN p.link, c.name", sid=session_id)
                for r in res_disc:
                    src, tgt = r["p.link"], f"concept_{r['c.name']}"
                    if src in known_ids and tgt in known_ids:
                        edges.append({"source": src, "target": tgt, "type": "discusses"})

                res_meth = session.run("MATCH (p:Paper {session: $sid})-[:USES_METHOD]->(m:Method) RETURN p.link, m.name", sid=session_id)
                for r in res_meth:
                    src, tgt = r["p.link"], f"method_{r['m.name']}"
                    if src in known_ids and tgt in known_ids:
                        edges.append({"source": src, "target": tgt, "type": "uses"})
                
                def link_similar(self, link_a: str, link_b: str, weight: float) -> None:
                    self._safe_run(
                        """
                        MERGE (a:Paper {link: $a})
                        MERGE (b:Paper {link: $b})
                        MERGE (a)-[r:SIMILAR]-(b)
                        SET r.weight = $weight
                        """,
                        a=link_a, b=link_b, weight=weight,
                    )

                return {"nodes": nodes, "links": edges}
        except Exception as e:
            print(f"[graph_store] get_full_graph failed: {e}")
            return {"nodes": [], "links": []}

    def get_turn_graph(self, session_id: str, turn_id: str) -> dict:
        """Message-scoped graph — only papers/concepts/methods that were
        actually surfaced during this specific chat turn, filtered via the
        p.turn_ids list stamped by upsert_paper(..., turn_id=...). Falls back
        to an empty graph (not an error) if this turn never wrote anything,
        e.g. a turn with no ranked_papers."""
        try:
            with self.driver.session() as session:
                nodes = []
                edges = []
                known_ids = set()

                res_papers = session.run(
                    """
                    MATCH (p:Paper {session: $sid})
                    WHERE $turn_id IN coalesce(p.turn_ids, [])
                    RETURN p
                    """,
                    sid=session_id, turn_id=turn_id,
                )
                paper_links = set()
                for r in res_papers:
                    p = dict(r["p"])
                    paper_links.add(p["link"])
                    nodes.append({"id": p["link"], "name": p.get("title", "Paper"), "type": "paper", "val": 10})
                    known_ids.add(p["link"])

                if not paper_links:
                    return {"nodes": [], "links": []}

                res_concepts = session.run(
                    """
                    MATCH (c:Concept)<-[:DISCUSSES]-(p:Paper)
                    WHERE p.link IN $links
                    RETURN DISTINCT c
                    """,
                    links=list(paper_links),
                )
                for r in res_concepts:
                    c = dict(r["c"])
                    nid = f"concept_{c['name']}"
                    nodes.append({"id": nid, "name": c["name"], "type": "concept", "val": 5})
                    known_ids.add(nid)

                res_methods = session.run(
                    """
                    MATCH (m:Method)<-[:USES_METHOD]-(p:Paper)
                    WHERE p.link IN $links
                    RETURN DISTINCT m
                    """,
                    links=list(paper_links),
                )
                for r in res_methods:
                    m = dict(r["m"])
                    nid = f"method_{m['name']}"
                    nodes.append({"id": nid, "name": m["name"], "type": "method", "val": 5})
                    known_ids.add(nid)

                res_cites = session.run(
                    """
                    MATCH (a:Paper)-[:CITES]->(b:Paper)
                    WHERE a.link IN $links AND b.link IN $links
                    RETURN a.link, b.link
                    """,
                    links=list(paper_links),
                )
                for r in res_cites:
                    if r["a.link"] in known_ids and r["b.link"] in known_ids:
                        edges.append({"source": r["a.link"], "target": r["b.link"], "type": "cites"})

                res_disc = session.run(
                    """
                    MATCH (p:Paper)-[:DISCUSSES]->(c:Concept)
                    WHERE p.link IN $links
                    RETURN p.link, c.name
                    """,
                    links=list(paper_links),
                )
                for r in res_disc:
                    src, tgt = r["p.link"], f"concept_{r['c.name']}"
                    if src in known_ids and tgt in known_ids:
                        edges.append({"source": src, "target": tgt, "type": "discusses"})

                res_meth = session.run(
                    """
                    MATCH (p:Paper)-[:USES_METHOD]->(m:Method)
                    WHERE p.link IN $links
                    RETURN p.link, m.name
                    """,
                    links=list(paper_links),
                )
                for r in res_meth:
                    src, tgt = r["p.link"], f"method_{r['m.name']}"
                    if src in known_ids and tgt in known_ids:
                        edges.append({"source": src, "target": tgt, "type": "uses"})

                return {"nodes": nodes, "links": edges}
        except Exception as e:
            print(f"[graph_store] get_turn_graph failed: {e}")
            return {"nodes": [], "links": []}


graph_store = GraphStore()