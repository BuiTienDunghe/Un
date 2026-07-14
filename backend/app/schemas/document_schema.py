from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str


class IndexRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)


class IndexResponse(BaseModel):
    document_id: str
    chunks_created: int
    vectors_created: int
    status: str
    ocr_pages_count: int


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    chunks_count: int
    ocr_pages_count: int
    error_message: str | None = None
