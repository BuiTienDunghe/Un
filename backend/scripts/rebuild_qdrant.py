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

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--document-id"); args=parser.parse_args(); settings=get_settings()
    if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
    sessions=create_session_factory(create_postgres_engine(settings.database_url)); router=ModelRouter(OllamaClient(settings.ollama_base_url,settings.ollama_chat_timeout_seconds,settings.ollama_health_timeout_seconds,settings.ollama_retry_count),settings.load_models()); qdrant=QdrantStore(settings.qdrant_url,settings.qdrant_timeout_seconds,documents_collection=settings.qdrant_documents_collection)
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
            vectors=[router.embed(chunk.content)[0] for chunk in chunks]
            qdrant.upsert_chunks(document_id,str(version_id),filename,chunks,vectors,chunk_ids=[chunk.id for chunk in chunks])
    print({"documents":len(work),"chunks":total,"dry_run":args.dry_run})
if __name__=="__main__": main()
