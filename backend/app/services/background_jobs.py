from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable


@dataclass
class Job:
    events: deque[tuple[int, str]] = field(default_factory=lambda: deque(maxlen=4000))
    subscribers: set[asyncio.Queue[tuple[int, str]]] = field(default_factory=set)
    next_id: int = 0
    done: bool = False
    task: asyncio.Task | None = None


_jobs: dict[str, Job] = {}


def has(job_id: str) -> bool:
    return job_id in _jobs


def start(job_id: str, producer: Callable[[], AsyncIterator[str]]) -> Job:
    existing = _jobs.get(job_id)
    if existing and existing.task and not existing.task.done():
        return existing
    job = _jobs.setdefault(job_id, Job())

    async def run() -> None:
        try:
            async for event in producer():
                job.next_id += 1
                item = (job.next_id, event)
                job.events.append(item)
                for subscriber in list(job.subscribers):
                    subscriber.put_nowait(item)
        except Exception as exc:
            job.next_id += 1
            item = (job.next_id, f'data: {{"type":"error","message":"{type(exc).__name__}"}}\n\n')
            job.events.append(item)
            for subscriber in list(job.subscribers):
                subscriber.put_nowait(item)
        finally:
            job.done = True
            for subscriber in list(job.subscribers):
                subscriber.put_nowait((job.next_id + 1, ""))

    job.task = asyncio.create_task(run(), name=f"sykra-job-{job_id}")
    return job


async def stream(job_id: str, since: int = 0) -> AsyncIterator[str]:
    job = _jobs.get(job_id)
    if job is None:
        return
    for event_id, event in list(job.events):
        if event_id > since:
            yield event
    if job.done:
        return
    queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
    job.subscribers.add(queue)
    try:
        while True:
            event_id, event = await queue.get()
            if not event:
                return
            if event_id > since:
                since = event_id
                yield event
    finally:
        job.subscribers.discard(queue)


def stop(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job.done:
        return False
    return True
