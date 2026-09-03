"""Hard-delete everything one Discord member said (memory_design.md §9.5).

The design said the deletion story did not exist; this is it. Scope, in the
order the foreign keys allow — the RESTRICT cluster around memories →
candidates → turns dictates it, and getting it wrong fails loudly rather than
half-deleting:

  1. Qdrant vectors + the web mirror row for each of their memories.
     (The point id is uuid5-derived, so deleting the Postgres row alone
     leaves an orphan vector that search would still return.)
  2. discord_memory_sources rows authored by them.
  3. condensation propositions they spoke; batches that lose text are marked
     stale so the worker rebuilds them WITHOUT that person.
  4. discord_memories about them — newest version first (the supersedes
     self-FK is RESTRICT).
  5. discord_memory_candidates from or about them.
  6. discord_session_turns they wrote (deliveries cascade).
  7. discord_channel_messages they wrote — a plain DELETE, because the FTS
     index is per row.

Dry-run by default: it prints what it would delete and touches nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.postgres.database import (  # noqa: E402
    create_postgres_engine,
    create_session_factory,
)
from app.postgres.models import (  # noqa: E402
    DiscordChannelMessage,
    DiscordCondensationBatch,
    DiscordCondensationProposition,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
)
from app.stores.qdrant_store import QdrantStore  # noqa: E402


def _counts(database, guild_id: str, author_id: str) -> dict[str, int]:
    def count(model, *conditions) -> int:
        return int(
            database.scalar(select(func.count()).select_from(model).where(*conditions))
            or 0
        )

    return {
        "channel_messages": count(
            DiscordChannelMessage,
            DiscordChannelMessage.guild_id == guild_id,
            DiscordChannelMessage.author_id == author_id,
        ),
        "session_turns": count(
            DiscordSessionTurn, DiscordSessionTurn.author_id == author_id
        ),
        "candidates": count(
            DiscordMemoryCandidate,
            DiscordMemoryCandidate.guild_id == guild_id,
            (DiscordMemoryCandidate.source_author_id == author_id)
            | (DiscordMemoryCandidate.subject_id == author_id),
        ),
        "memories": count(
            DiscordMemory,
            DiscordMemory.guild_id == guild_id,
            DiscordMemory.subject_id == author_id,
        ),
        "memory_sources": count(
            DiscordMemorySource, DiscordMemorySource.source_author_id == author_id
        ),
        "propositions": count(
            DiscordCondensationProposition,
            DiscordCondensationProposition.guild_id == guild_id,
            DiscordCondensationProposition.speaker_id == author_id,
        ),
    }


def forget(guild_id: str, author_id: str, *, apply: bool) -> dict[str, object]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    factory = create_session_factory(
        create_postgres_engine(str(settings.database_url))
    )

    with factory() as database:
        planned = _counts(database, guild_id, author_id)
        memory_ids = list(
            database.scalars(
                select(DiscordMemory.id).where(
                    DiscordMemory.guild_id == guild_id,
                    DiscordMemory.subject_id == author_id,
                )
            )
        )
    payload: dict[str, object] = {
        "guild_id": guild_id,
        "author_id": author_id,
        "mode": "apply" if apply else "dry-run",
        "planned": planned,
        "mirror_ids": [f"mem_dc_{value.hex}" for value in memory_ids],
    }
    if not apply:
        payload["side_effects"] = False
        return payload

    # 1. Vectors first: a Postgres-only delete would leave them searchable.
    removed_vectors = 0
    if memory_ids:
        store = QdrantStore(
            settings.qdrant_url,
            settings.qdrant_timeout_seconds,
            settings.qdrant_memories_collection,
            settings.qdrant_documents_collection,
        )
        for value in memory_ids:
            try:
                store.delete_memory(f"mem_dc_{value.hex}")
                removed_vectors += 1
            except Exception as error:  # keep going; report at the end
                payload.setdefault("vector_errors", []).append(str(error))

    with factory.begin() as database:
        # 2. sources (RESTRICT-references memories, candidates and turns)
        database.execute(
            delete(DiscordMemorySource).where(
                DiscordMemorySource.source_author_id == author_id
            )
        )
        if memory_ids:
            database.execute(
                delete(DiscordMemorySource).where(
                    DiscordMemorySource.memory_id.in_(memory_ids)
                )
            )

        # 3. condensation propositions; their batches become stale so the
        #    worker rebuilds a summary without this person.
        batch_ids = list(
            database.scalars(
                select(DiscordCondensationProposition.batch_id).where(
                    DiscordCondensationProposition.guild_id == guild_id,
                    DiscordCondensationProposition.speaker_id == author_id,
                )
            )
        )
        database.execute(
            delete(DiscordCondensationProposition).where(
                DiscordCondensationProposition.guild_id == guild_id,
                DiscordCondensationProposition.speaker_id == author_id,
            )
        )
        if batch_ids:
            database.execute(
                update(DiscordCondensationBatch)
                .where(DiscordCondensationBatch.id.in_(set(batch_ids)))
                .values(status="stale")
            )

        # 4. memories — clear the pointers that RESTRICT-block them first.
        if memory_ids:
            database.execute(
                update(DiscordMemoryCandidate)
                .where(DiscordMemoryCandidate.target_memory_id.in_(memory_ids))
                .values(target_memory_id=None)
            )
            database.execute(
                update(DiscordMemory)
                .where(DiscordMemory.supersedes_memory_id.in_(memory_ids))
                .values(supersedes_memory_id=None)
            )
            database.execute(
                delete(DiscordMemory).where(DiscordMemory.id.in_(memory_ids))
            )

        # 5. candidates from or about them
        database.execute(
            delete(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.guild_id == guild_id,
                (DiscordMemoryCandidate.source_author_id == author_id)
                | (DiscordMemoryCandidate.subject_id == author_id),
            )
        )

        # 6. their turns (deliveries cascade)
        database.execute(
            delete(DiscordSessionTurn).where(
                DiscordSessionTurn.author_id == author_id
            )
        )

        # 7. their raw messages
        database.execute(
            delete(DiscordChannelMessage).where(
                DiscordChannelMessage.guild_id == guild_id,
                DiscordChannelMessage.author_id == author_id,
            )
        )

    with factory() as database:
        payload["remaining"] = _counts(database, guild_id, author_id)
    payload["vectors_removed"] = removed_vectors
    payload["stale_batches"] = len(set(batch_ids))
    payload["side_effects"] = True
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--author-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="thực sự xóa; mặc định chỉ in ra những gì sẽ xóa",
    )
    arguments = parser.parse_args()
    payload = forget(
        arguments.guild_id, arguments.author_id, apply=arguments.apply
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    remaining = payload.get("remaining")
    if isinstance(remaining, dict) and any(remaining.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
