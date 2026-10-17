from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from app.db.models import LibraryPaper


def _meta(p: dict) -> dict:
    score = p.get("final_score", p.get("relevance_score"))
    published = p.get("published")
    return {
        "authors": [str(a) for a in (p.get("authors") or [])],
        "summary": (p.get("summary") or "")[:2000],
        "published": str(published) if published else None,
        "relevance_score": float(score) if score is not None else None,
        "source": p.get("source", "unknown"),
        "is_uploaded": p.get("source") == "user_upload",
        "file_url": p.get("file_url"),
    }


def save_papers(db: DBSession, user_id, session_id, papers: list[dict], chat_id=None) -> int:
    """Upsert papers into library_papers, deduped by (user, session, link)."""
    try:
        sid = UUID(str(session_id))
        cid = UUID(str(chat_id)) if chat_id else None
    except ValueError:
        return 0
    papers = [p for p in papers if p.get("link")]
    if not papers:
        return 0
    try:
        existing = {
            r.link: r
            for r in db.scalars(
                select(LibraryPaper).where(
                    LibraryPaper.user_id == user_id,
                    LibraryPaper.session_id == sid,
                    LibraryPaper.chat_id == cid,
                    LibraryPaper.link.in_([p["link"] for p in papers]),
                )
            )
        }
        for p in papers:
            title = (p.get("title") or "Untitled")[:1000]
            row = existing.get(p["link"])
            if row:
                row.title = title
                row.paper_metadata = _meta(p)
            else:
                row = LibraryPaper(
                    user_id=user_id, session_id=sid, chat_id=cid, title=title,
                    link=p["link"][:2048], paper_metadata=_meta(p),
                )
                db.add(row)
                existing[p["link"]] = row
        db.commit()
        return len(papers)
    except Exception as e:
        db.rollback()
        print(f"[library] save_papers failed: {type(e).__name__}: {e}")
        return 0