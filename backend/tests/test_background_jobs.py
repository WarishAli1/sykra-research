import asyncio

from app.services import background_jobs


def test_generation_continues_after_subscriber_disconnects():
    async def scenario():
        async def producer():
            yield "data: {\"type\":\"generation\"}\n\n"
            await asyncio.sleep(0.01)
            yield "data: {\"type\":\"done\"}\n\n"

        job = background_jobs.start("disconnect-test", producer)
        first = []
        async for event in background_jobs.stream("disconnect-test"):
            first.append(event)
            break
        await job.task
        return first, job.done, len(job.events)

    events, done, stored = asyncio.run(scenario())
    assert events == ['data: {"type":"generation"}\n\n']
    assert done is True
    assert stored == 2
