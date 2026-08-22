"""Recreate active-version Qdrant vectors from PostgreSQL chunks; PostgreSQL remains truth."""
from __future__ import annotations
import argparse
from sqlalchemy import select
from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk
from app.services.model_router import ModelRouter
from app.stores.qdrant_store import QdrantStore
from app.utils.chunking import ChunkLocation, DocumentChunk as ChunkRecord, combined_retrieval_text


def _as_record(chunk: DocumentChunk) -> ChunkRecord:
    """ORM row -> the chunking dataclass QdrantStore.upsert_chunks expects.

    Only payload metadata travels to Qdrant (retrieval re-reads content from
    PostgreSQL), so the mapping mirrors what the live index path sends."""
    locations = tuple(ChunkLocation(loc.get("page"), int(loc.get("start", 0)), int(loc.get("end", 0))) for loc in (chunk.locations or []))
    heading = " > ".join(chunk.heading_path) if chunk.heading_path else None
    return ChunkRecord(chunk.content, chunk.page_start, chunk.page_end, locations, heading, chunk.section_title, chunk.block_type or "paragraph", chunk.extraction_method or "native", chunk.retrieval_context)

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--document-id"); args=parser.parse_args(); settings=get_settings()
    if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
    sessions=create_session_factory(create_postgres_engine(settings.database_url)); router=ModelRouter({"ollama": OllamaClient(settings.ollama_base_url,settings.ollama_chat_timeout_seconds,settings.ollama_health_timeout_seconds,settings.ollama_retry_count)},settings.load_models()); qdrant=QdrantStore(settings.qdrant_url,settings.qdrant_timeout_seconds,documents_collection=settings.qdrant_documents_collection)
    with sessions() as session:
        statement=select(Document).where(Document.status=="indexed",Document.active_version_id.is_not(None))
        if args.document_id: statement=statement.where(Document.id==args.document_id)
        documents=list(session.scalars(statement))
        work=[(doc.id,doc.active_version_id,doc.original_filename,list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id==doc.active_version_id).order_by(DocumentChunk.chunk_index)))) for doc in documents]
    total=0
    for document_id,version_id,filename,chunks in work:
        if not chunks: continue
        total+=len(chunks)
        if not args.dry_run:
            # Same input as the live index path (P4-2): context+content, never bare
            # content, or a rebuild would silently downgrade a contextual index.
            vectors=[router.embed(combined_retrieval_text(chunk.retrieval_context, chunk.content))[0] for chunk in chunks]
            qdrant.upsert_chunks(document_id,str(version_id),filename,[_as_record(chunk) for chunk in chunks],vectors,chunk_ids=[chunk.id for chunk in chunks])
    print({"documents":len(work),"chunks":total,"dry_run":args.dry_run})
if __name__=="__main__": main()
