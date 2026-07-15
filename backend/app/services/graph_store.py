from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from app.config import settings


class GraphStore:
    def __init__(self):
        self.available = True
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

    def _safe_run(self, query: str, **params):
        try:
            with self.driver.session() as session:
                result = session.run(query, **params)
                self.available = True
                return result
        except (ServiceUnavailable, SessionExpired) as exc:
            self.available = False
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

    def upsert_paper(self, paper: dict, session_id: str) -> None:
        self._safe_run(
            """
            MERGE (p:Paper {link: $link})
            ON CREATE SET p.title = $title, p.published = $published,
                          p.source = $source, p.text_excerpt = $text_excerpt,
                          p.session = $session_id
            ON MATCH SET p.text_excerpt = coalesce(p.text_excerpt, $text_excerpt),
                         p.session = coalesce(p.session, $session_id)
            """,
            link=paper["link"], title=paper["title"],
            published=str(paper.get("published", "")), source=paper.get("source", "unknown"),
            text_excerpt=(paper.get("text") or paper.get("summary", ""))[:2000],
            session_id=session_id,
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

    def get_full_graph(self, session_id: str) -> dict:
        try:
            with self.driver.session() as session:
                nodes = []
                edges = []

                res_papers = session.run("MATCH (p:Paper {session: $sid}) RETURN p", sid=session_id)
                for r in res_papers:
                    p = dict(r["p"])
                    nodes.append({"id": p["link"], "name": p.get("title", "Paper"), "type": "paper", "val": 10})

                res_concepts = session.run("MATCH (c:Concept)<-[:DISCUSSES]-(p:Paper {session: $sid}) RETURN DISTINCT c", sid=session_id)
                for r in res_concepts:
                    c = dict(r["c"])
                    nodes.append({"id": f"concept_{c['name']}", "name": c["name"], "type": "concept", "val": 5})

                res_methods = session.run("MATCH (m:Method)<-[:USES_METHOD]-(p:Paper {session: $sid}) RETURN DISTINCT m", sid=session_id)
                for r in res_methods:
                    m = dict(r["m"])
                    nodes.append({"id": f"method_{m['name']}", "name": m["name"], "type": "method", "val": 5})

                res_cites = session.run("MATCH (a:Paper {session: $sid})-[:CITES]->(b:Paper) RETURN a.link, b.link", sid=session_id)
                for r in res_cites:
                    edges.append({"source": r["a.link"], "target": r["b.link"], "type": "cites"})

                res_disc = session.run("MATCH (p:Paper {session: $sid})-[:DISCUSSES]->(c:Concept) RETURN p.link, c.name", sid=session_id)
                for r in res_disc:
                    edges.append({"source": r["p.link"], "target": f"concept_{r['c.name']}", "type": "discusses"})

                res_meth = session.run("MATCH (p:Paper {session: $sid})-[:USES_METHOD]->(m:Method) RETURN p.link, m.name", sid=session_id)
                for r in res_meth:
                    edges.append({"source": r["p.link"], "target": f"method_{r['m.name']}", "type": "uses"})

                return {"nodes": nodes, "links": edges}
        except Exception as e:
            print(f"[graph_store] get_full_graph failed: {e}")
            return {"nodes": [], "links": []}


graph_store = GraphStore()
