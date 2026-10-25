from sqlalchemy import select

from app.db.models import LibraryPaper, Message


def previous_papers_from_db(db, user_id, chat, limit: int = 12) -> list[dict]:
    try:
        last = db.scalar(
            select(Message)
            .where(
                Message.chat_id == chat.id,
                Message.role == "assistant",
                Message.status == "complete",
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        links = list(((last.citations or {}).get("paper_links") or [])) if last else []
        if not links:
            return []

        rows = db.scalars(
            select(LibraryPaper)
            .where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.chat_id == chat.id,
                LibraryPaper.link.in_(links),
            )
            .order_by(LibraryPaper.updated_at.desc())
        )

        out: list[dict] = []
        for r in rows:
            meta = r.paper_metadata or {}
            if meta.get("is_uploaded"):
                continue
            out.append(
                {
                    "title": r.title,
                    "link": r.link,
                    "authors": meta.get("authors") or [],
                    "summary": meta.get("summary") or "",
                    "published": meta.get("published"),
                    "source": meta.get("source", "unknown"),
                    "citation_count": meta.get("citation_count") or 0,
                    "_from_previous_turn": True,
                }
            )
        return out[:limit]

    except Exception as e:
        print(f"[previous_papers] load failed: {type(e).__name__}: {e}")
        return []