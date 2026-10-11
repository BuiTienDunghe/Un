"""Hợp đồng API của Không gian Nghiên cứu (xem .scratch/research-space/spec.md)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

PaperStatus = Literal["unread", "reading", "read"]
EdgeType = Literal["builds", "competes", "backbone"]
Stage = Literal["done", "running", "failed", "pending"]


# ── Dự án ────────────────────────────────────────────────────────────────────
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _at_least_one(self) -> "ProjectPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Cần ít nhất một trường để sửa.")
        return self


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    paper_count: int
    read_count: int
    updated_at: str


class ClusterRow(BaseModel):
    id: str
    name: str
    color_index: int
    position: int


class ClusterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    color_index: int = Field(default=1, ge=1, le=5)


class ClusterPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    color_index: int | None = Field(default=None, ge=1, le=5)
    position: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one(self) -> "ClusterPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Cần ít nhất một trường để sửa.")
        return self


class EdgeRow(BaseModel):
    id: str
    a_paper_id: str
    b_paper_id: str
    type: EdgeType
    explain: str | None = None
    quote: str | None = None
    quote_src: str | None = None
    confidence: float | None = None
    source: str = "manual"
    created_at: str


class EdgeCreateRequest(BaseModel):
    a_paper_id: str
    b_paper_id: str
    type: EdgeType
    explain: str | None = None
    quote: str | None = None
    quote_src: str | None = None


class PaperStages(BaseModel):
    ocr: Stage
    metadata: Stage
    outline: Stage
    summary: Stage


class PaperRow(BaseModel):
    id: str
    document_id: str
    short_name: str
    title: str | None = None
    authors: str | None = None
    venue: str | None = None
    year: int | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    url: str | None = None
    cluster_id: str | None = None
    status: PaperStatus
    stars: int
    last_page: int
    tags: list[str] = Field(default_factory=list)
    total_pages: int | None = None
    annotation_count: int = 0
    has_summary: bool = False
    document_status: str
    indexed: bool
    stages: PaperStages
    added_at: str
    updated_at: str


class AnnotationRect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)


class AnnotationRow(BaseModel):
    id: str
    paper_id: str
    page: int
    rects: list[AnnotationRect]
    color: str
    quote: str
    note: str | None = None
    section: str | None = None
    created_at: str
    updated_at: str


class AnnotationCreateRequest(BaseModel):
    page: int = Field(ge=1)
    rects: list[AnnotationRect] = Field(min_length=1)
    color: str = Field(min_length=4, max_length=16, pattern=r"^#[0-9a-fA-F]{3,8}$")
    quote: str = Field(min_length=1)
    note: str | None = None
    section: str | None = None


class AnnotationPatchRequest(BaseModel):
    note: str | None = None
    color: str | None = Field(default=None, min_length=4, max_length=16, pattern=r"^#[0-9a-fA-F]{3,8}$")

    @model_validator(mode="after")
    def _at_least_one(self) -> "AnnotationPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Cần ít nhất một trường để sửa.")
        return self


class PaperDetail(PaperRow):
    summary: dict[str, Any] | None = None
    summary_model: str | None = None
    summary_at: str | None = None
    outline: dict[str, Any] | None = None
    note_md: str | None = None
    annotations: list[AnnotationRow] = Field(default_factory=list)


class ProjectDetail(BaseModel):
    id: str
    name: str
    description: str | None = None
    insights: dict[str, Any] | None = None
    insights_at: str | None = None
    clusters: list[ClusterRow]
    papers: list[PaperRow]
    edges: list[EdgeRow]
    updated_at: str


class PaperPatchRequest(BaseModel):
    status: PaperStatus | None = None
    stars: int | None = Field(default=None, ge=0, le=5)
    last_page: int | None = Field(default=None, ge=1)
    note_md: str | None = None
    tags: list[str] | None = None
    cluster_id: str | None = None
    short_name: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = None
    authors: str | None = None
    venue: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=1800, le=2200)
    arxiv_id: str | None = Field(default=None, max_length=32)
    doi: str | None = Field(default=None, max_length=255)
    url: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "PaperPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Cần ít nhất một trường để sửa.")
        return self


class PaperAttachRequest(BaseModel):
    """Thân JSON của POST /research/projects/{id}/papers: gắn tài liệu có sẵn, hoặc
    xin lấy theo link/DOI/tiêu đề (chưa hỗ trợ — máy chủ offline)."""

    document_id: str | None = None
    url: str | None = None
    doi: str | None = None
    title: str | None = None


# ── Tóm tắt / insight: hình JSON ép model trả về ─────────────────────────────
class PaperSummary(BaseModel):
    brief: str = ""
    problem: str = ""
    idea: str = ""
    result: str = ""
    limits: str = ""
    input: str = ""
    compute: str = ""
    datasets: str = ""
    code: str = ""
    questions: list[str] = Field(default_factory=list)


class ProjectInsights(BaseModel):
    overview: str = ""
    central: str = ""
    trend: str = ""
    gap: str = ""


class SummaryResponse(BaseModel):
    summary: dict[str, Any]
    summary_model: str | None = None
    summary_at: str | None = None


class InsightsResponse(BaseModel):
    insights: dict[str, Any]
    insights_at: str | None = None


class OutlineResponse(BaseModel):
    toc: list[dict[str, Any]]
    figures: list[dict[str, Any]]


class ResearchChatRequest(BaseModel):
    scope: Literal["paper", "project"]
    id: str
    question: str = Field(min_length=1)
    quote: str | None = None
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)


# ── Trang tài liệu (routers/documents.py) ────────────────────────────────────
class PageWord(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int


class PageWordsResponse(BaseModel):
    page: int
    width: float
    height: float
    has_text: bool
    words: list[PageWord]


class PageBoxesResponse(BaseModel):
    boxes: list[dict[str, float]]
