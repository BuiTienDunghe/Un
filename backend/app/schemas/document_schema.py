from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    duplicate: bool = False
    content_hash: str | None = None
    version_id: str | None = None
    run_id: str | None = None
    action_required: bool = False
    conflict: str | None = None
    available_actions: list[str] = []
    suggested_filename: str | None = None
    cancelled: bool = False
    renamed: bool = False


class IndexRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)


class IndexResponse(BaseModel):
    document_id: str
    ingestion_run_id: str
    index_version: int
    status: str
    stage: str
    version_id: str | None = None
    job_id: str | None = None


class IngestionStatusResponse(BaseModel):
    id: str
    document_id: str
    index_version: int
    version_id: str | None = None
    status: str
    stage: str
    total_pages: int
    processed_pages: int
    chunks_count: int
    vectors_count: int
    cancel_requested: bool
    error_code: str | None = None
    error_message: str | None = None
    progress_percent: int = 0
    ocr_pages: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0


class ReplaceSourceResponse(BaseModel):
    document_id: str
    duplicate: bool
    content_hash: str
    ingestion_run_id: str | None = None
    index_version: int | None = None
    status: str | None = None
    stage: str | None = None


class RetentionRequest(BaseModel):
    pinned: bool | None = None
    retention_policy: str | None = Field(default=None, pattern="^(permanent|temporary|knowledge_only)$")


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    chunks_count: int
    ocr_pages_count: int
    content_hash: str | None = None
    active_index_version: int = 0
    active_version_id: str | None = None
    source_available: bool = True
    source_removed_at: str | None = None
    pinned: bool = False
    retention_policy: str = "permanent"
    last_accessed_at: str | None = None
    ingestion: dict[str, object] | None = None
    error_message: str | None = None
