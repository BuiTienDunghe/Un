from __future__ import annotations

from dataclasses import dataclass


DISCORD_MEMORY_INGEST_JOB_TYPE = "discord_memory_ingest"
DOCUMENT_JOB_TYPES = frozenset({"extract_document", "index_document"})


class UnknownJobTypeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JobRoute:
    queue_name: str
    task_path: str


def resolve_job_route(
    job_type: str,
    *,
    memory_queue_name: str,
) -> JobRoute:
    routes = {
        "extract_document": JobRoute(
            queue_name="ocr",
            task_path="app.workers.tasks.extract_document",
        ),
        "index_document": JobRoute(
            queue_name="index",
            task_path="app.workers.tasks.index_document",
        ),
        DISCORD_MEMORY_INGEST_JOB_TYPE: JobRoute(
            queue_name=memory_queue_name,
            task_path="app.workers.memory_tasks.discord_memory_ingest",
        ),
    }
    try:
        return routes[job_type]
    except KeyError as error:
        raise UnknownJobTypeError(f"unsupported durable job type: {job_type}") from error

