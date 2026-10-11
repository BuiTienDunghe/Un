"""Không gian Nghiên cứu — /research. Read = read_guard (main.py); ghi = require_api_key.

Không route nào require_admin: member thấy và dùng được (README xếp "Nghiên cứu"
cạnh Tài liệu / Ghi nhớ). Khi bật tài khoản, member chỉ chạm dự án của mình.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.datastructures import UploadFile  # request.form() trả lớp của Starlette, không phải fastapi.UploadFile

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.routers.rag import _response_sources
from app.schemas.research_schema import (
    AnnotationCreateRequest, AnnotationPatchRequest, AnnotationRow, ClusterCreateRequest, ClusterPatchRequest, ClusterRow, EdgeCreateRequest, EdgeRow,
    InsightsResponse, OutlineResponse, PaperAttachRequest, PaperDetail, PaperPatchRequest, PaperRow, ProjectCreateRequest, ProjectDetail, ProjectPatchRequest,
    ProjectSummary, ResearchChatRequest, SummaryResponse,
)
from app.security.api_key import require_api_key
from app.security.auth import auth_enabled, ensure_conversation_access, resolve_identity
from app.services.answer_grounding import grade_rag_answer
from app.services.chat_service import ConversationNotFoundError
from app.services.postgres_document_service import DocumentNotFoundError, SourceUnavailableError
from app.services.rag_service import InsufficientContextError
from app.services.reranker_service import RerankerUnavailableError
from app.services.research_service import (
    AnnotationNotFoundError, ClusterNotFoundError, EdgeNotFoundError, InvalidEdgeError, NotIndexedError, PaperNotFoundError, ProjectNotFoundError,
    SummaryMissingError, compose_question,
)
from app.stores.qdrant_store import QdrantUnavailableError
from app.utils.sse import sse_event

router = APIRouter(prefix="/research", tags=["research"])
write = [Depends(require_api_key)]


def _owner(request: Request) -> str | None:
    """Member đăng nhập → chỉ dự án của mình; admin / service / tắt tài khoản → tất cả."""
    identity = resolve_identity(request)
    return identity.user_id if auth_enabled(request) and identity.is_user and identity.role != "admin" else None


def _service(request: Request):
    return request.app.state.research_service


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": code, "message": message})


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ProjectNotFoundError):
        return _error(404, "RESEARCH_PROJECT_NOT_FOUND", f"Dự án {error} không tồn tại.")
    if isinstance(error, PaperNotFoundError):
        return _error(404, "RESEARCH_PAPER_NOT_FOUND", f"Paper {error} không tồn tại.")
    if isinstance(error, AnnotationNotFoundError):
        return _error(404, "RESEARCH_ANNOTATION_NOT_FOUND", f"Highlight {error} không tồn tại.")
    if isinstance(error, ClusterNotFoundError):
        return _error(404, "RESEARCH_CLUSTER_NOT_FOUND", f"Cụm {error} không tồn tại.")
    if isinstance(error, EdgeNotFoundError):
        return _error(404, "RESEARCH_EDGE_NOT_FOUND", f"Kết nối {error} không tồn tại.")
    if isinstance(error, DocumentNotFoundError):
        return _error(404, "DOCUMENT_NOT_FOUND", f"Document {error} does not exist")
    if isinstance(error, SummaryMissingError):
        return _error(409, "RESEARCH_SUMMARY_MISSING", "Chưa paper nào trong dự án có tóm tắt; tạo tóm tắt cho ít nhất một paper trước.")
    if isinstance(error, NotIndexedError):
        return _error(409, "RESEARCH_NOT_INDEXED", "Paper chưa lập chỉ mục xong (chưa có chữ để đọc); thử lại sau ít phút.")
    if isinstance(error, SourceUnavailableError):
        return _error(409, "RESEARCH_SOURCE_UNAVAILABLE", "Tệp gốc của paper này đã bị gỡ.")
    if isinstance(error, InvalidEdgeError):
        return _error(422, "RESEARCH_EDGE_INVALID", str(error))
    if isinstance(error, OllamaModelNotLoadedError):
        return _error(502, "MODEL_NOT_LOADED", str(error))
    if isinstance(error, OllamaTimeoutError):
        return _error(504, "MODEL_TIMEOUT", str(error))
    if isinstance(error, OllamaUnavailableError):
        return _error(502, "OLLAMA_UNAVAILABLE", str(error))
    raise error


# ── Dự án ────────────────────────────────────────────────────────────────────
@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(request: Request) -> list[ProjectSummary]:
    return [ProjectSummary(**row) for row in _service(request).list_projects(_owner(request))]


@router.post("/projects", response_model=ProjectDetail, status_code=201, dependencies=write)
def create_project(payload: ProjectCreateRequest, request: Request) -> ProjectDetail:
    return ProjectDetail(**_service(request).create_project(_owner(request), payload.name, payload.description))


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, request: Request) -> ProjectDetail:
    try:
        return ProjectDetail(**_service(request).get_project(_owner(request), project_id))
    except Exception as error:
        raise _translate(error) from error


@router.patch("/projects/{project_id}", response_model=ProjectDetail, dependencies=write)
def patch_project(project_id: str, payload: ProjectPatchRequest, request: Request) -> ProjectDetail:
    try:
        return ProjectDetail(**_service(request).patch_project(_owner(request), project_id, payload.model_dump(exclude_unset=True)))
    except Exception as error:
        raise _translate(error) from error


@router.delete("/projects/{project_id}", status_code=204, dependencies=write)
def delete_project(project_id: str, request: Request) -> Response:
    try:
        _service(request).delete_project(_owner(request), project_id)
    except Exception as error:
        raise _translate(error) from error
    return Response(status_code=204)


@router.post("/projects/{project_id}/insights", response_model=InsightsResponse, dependencies=write)
def generate_insights(project_id: str, request: Request) -> InsightsResponse:
    try:
        return InsightsResponse(**_service(request).generate_insights(_owner(request), project_id))
    except Exception as error:
        raise _translate(error) from error


@router.get("/projects/{project_id}/bibtex", response_class=PlainTextResponse)
def project_bibtex(project_id: str, request: Request) -> PlainTextResponse:
    try:
        return PlainTextResponse(_service(request).bibtex(_owner(request), project_id), media_type="text/plain; charset=utf-8")
    except Exception as error:
        raise _translate(error) from error


# ── Cụm ──────────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/clusters", response_model=ClusterRow, status_code=201, dependencies=write)
def create_cluster(project_id: str, payload: ClusterCreateRequest, request: Request) -> ClusterRow:
    try:
        return ClusterRow(**_service(request).create_cluster(_owner(request), project_id, payload.name, payload.color_index))
    except Exception as error:
        raise _translate(error) from error


@router.patch("/clusters/{cluster_id}", response_model=ClusterRow, dependencies=write)
def patch_cluster(cluster_id: str, payload: ClusterPatchRequest, request: Request) -> ClusterRow:
    try:
        return ClusterRow(**_service(request).patch_cluster(_owner(request), cluster_id, payload.model_dump(exclude_unset=True)))
    except Exception as error:
        raise _translate(error) from error


@router.delete("/clusters/{cluster_id}", status_code=204, dependencies=write)
def delete_cluster(cluster_id: str, request: Request) -> Response:
    try:
        _service(request).delete_cluster(_owner(request), cluster_id)
    except Exception as error:
        raise _translate(error) from error
    return Response(status_code=204)


# ── Kết nối ──────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/edges", response_model=EdgeRow, status_code=201, dependencies=write)
def create_edge(project_id: str, payload: EdgeCreateRequest, request: Request) -> EdgeRow:
    try:
        return EdgeRow(**_service(request).create_edge(_owner(request), project_id, payload.model_dump()))
    except Exception as error:
        raise _translate(error) from error


@router.delete("/edges/{edge_id}", status_code=204, dependencies=write)
def delete_edge(edge_id: str, request: Request) -> Response:
    try:
        _service(request).delete_edge(_owner(request), edge_id)
    except Exception as error:
        raise _translate(error) from error
    return Response(status_code=204)


# ── Paper ────────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/papers", response_model=None, status_code=201, dependencies=write)
async def add_papers(project_id: str, request: Request) -> list[PaperRow] | PaperRow:
    """Ba kiểu thân: multipart `files` (nhiều PDF) → 201 [PaperRow]; JSON `{document_id}`
    (gắn tài liệu có sẵn) → 201 PaperRow (một đối tượng, theo spec); JSON `{url|doi|title}`
    → 501 vì máy chủ chạy offline."""
    service, owner = _service(request), _owner(request)
    content_type = request.headers.get("content-type", "")
    try:
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            files = [item for item in [*form.getlist("files"), *form.getlist("files[]"), *form.getlist("file")] if isinstance(item, UploadFile)]
            if not files:
                raise _error(422, "INVALID_INPUT", "Cần ít nhất một tệp PDF trong trường `files`.")
            return [PaperRow(**row) for row in await service.add_paper_files(owner, project_id, files, request.app.state.settings.max_upload_size_bytes)]
        payload = PaperAttachRequest.model_validate(await request.json())
        if payload.document_id:
            return PaperRow(**service.attach_paper(owner, project_id, payload.document_id))
        if payload.url or payload.doi or payload.title:
            raise _error(501, "RESEARCH_FETCH_UNSUPPORTED", "Máy chủ chạy offline; tải PDF rồi thả vào.")
        raise _error(422, "INVALID_INPUT", "Cần `files` (multipart) hoặc `document_id`.")
    except HTTPException:
        raise
    except ValueError as error:
        if error.__class__.__module__.startswith("pydantic"):
            raise _error(422, "INVALID_INPUT", str(error)) from error
        raise _error(415, "UNSUPPORTED_FILE_TYPE", "Chỉ nhận PDF, DOCX, TXT, MD.") from error
    except OverflowError as error:
        raise _error(413, "DOCUMENT_TOO_LARGE", "Tệp vượt giới hạn kích thước đã cấu hình.") from error
    except Exception as error:
        raise _translate(error) from error


@router.get("/papers/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: str, request: Request) -> PaperDetail:
    try:
        return PaperDetail(**_service(request).get_paper(_owner(request), paper_id))
    except Exception as error:
        raise _translate(error) from error


@router.patch("/papers/{paper_id}", response_model=PaperRow, dependencies=write)
def patch_paper(paper_id: str, payload: PaperPatchRequest, request: Request) -> PaperRow:
    try:
        return PaperRow(**_service(request).patch_paper(_owner(request), paper_id, payload.model_dump(exclude_unset=True)))
    except Exception as error:
        raise _translate(error) from error


@router.delete("/papers/{paper_id}", status_code=204, dependencies=write)
def delete_paper(paper_id: str, request: Request) -> Response:
    try:
        _service(request).delete_paper(_owner(request), paper_id)
    except Exception as error:
        raise _translate(error) from error
    return Response(status_code=204)


@router.post("/papers/{paper_id}/summary", response_model=SummaryResponse, dependencies=write)
def generate_summary(paper_id: str, request: Request) -> SummaryResponse:
    try:
        return SummaryResponse(**_service(request).generate_summary(_owner(request), paper_id))
    except Exception as error:
        raise _translate(error) from error


@router.get("/papers/{paper_id}/outline", response_model=OutlineResponse)
def paper_outline(paper_id: str, request: Request) -> OutlineResponse:
    try:
        return OutlineResponse(**_service(request).outline(_owner(request), paper_id))
    except Exception as error:
        raise _translate(error) from error


@router.get("/papers/{paper_id}/export.md", response_class=PlainTextResponse)
def export_paper(paper_id: str, request: Request) -> PlainTextResponse:
    try:
        return PlainTextResponse(_service(request).export_markdown(_owner(request), paper_id), media_type="text/markdown; charset=utf-8")
    except Exception as error:
        raise _translate(error) from error


# ── Highlight ────────────────────────────────────────────────────────────────
@router.get("/papers/{paper_id}/annotations", response_model=list[AnnotationRow])
def list_annotations(paper_id: str, request: Request) -> list[AnnotationRow]:
    try:
        return [AnnotationRow(**row) for row in _service(request).list_annotations(_owner(request), paper_id)]
    except Exception as error:
        raise _translate(error) from error


@router.post("/papers/{paper_id}/annotations", response_model=AnnotationRow, status_code=201, dependencies=write)
def create_annotation(paper_id: str, payload: AnnotationCreateRequest, request: Request) -> AnnotationRow:
    try:
        return AnnotationRow(**_service(request).create_annotation(_owner(request), paper_id, payload.model_dump()))
    except Exception as error:
        raise _translate(error) from error


@router.patch("/annotations/{annotation_id}", response_model=AnnotationRow, dependencies=write)
def patch_annotation(annotation_id: str, payload: AnnotationPatchRequest, request: Request) -> AnnotationRow:
    try:
        return AnnotationRow(**_service(request).patch_annotation(_owner(request), annotation_id, payload.model_dump(exclude_unset=True)))
    except Exception as error:
        raise _translate(error) from error


@router.delete("/annotations/{annotation_id}", status_code=204, dependencies=write)
def delete_annotation(annotation_id: str, request: Request) -> Response:
    try:
        _service(request).delete_annotation(_owner(request), annotation_id)
    except Exception as error:
        raise _translate(error) from error
    return Response(status_code=204)


# ── Hỏi AI ───────────────────────────────────────────────────────────────────
@router.post("/chat", dependencies=write)
def research_chat(payload: ResearchChatRequest, request: Request) -> StreamingResponse:
    """SSE y như /rag/chat (meta/token/done/error) — bên trong gọi rag_service.stream_response
    với document_ids của paper / dự án; `meta` thêm `papers` để UI vẽ chip [Paper · tr.N]."""
    identity = resolve_identity(request)
    owner = identity.user_id if identity.is_user else None
    try:
        if payload.conversation_id:
            ensure_conversation_access(request, payload.conversation_id)
        document_ids, papers = _service(request).chat_scope(_owner(request), payload.scope, payload.id)
        question = compose_question(payload.question, payload.quote)
        tokens, model_used, sources, conversation_id, retrieval_question = request.app.state.rag_service.stream_response(question, payload.top_k, document_ids, payload.conversation_id, user_id=owner)
    except ConversationNotFoundError as error:
        raise _error(404, "CONVERSATION_NOT_FOUND", f"Conversation {error} does not exist") from error
    except InsufficientContextError as error:
        raise _error(422, "INSUFFICIENT_CONTEXT", str(error)) from error
    except QdrantUnavailableError as error:
        raise _error(503, "QDRANT_UNAVAILABLE", str(error)) from error
    except RerankerUnavailableError as error:
        raise _error(503, "RERANKER_UNAVAILABLE", str(error)) from error
    except Exception as error:
        raise _translate(error) from error
    response_sources = [source.model_dump() for source in _response_sources(sources)]

    def events():
        yield sse_event("meta", {"model_used": model_used, "conversation_id": conversation_id, "retrieval_question": retrieval_question, "sources": response_sources, "papers": papers, "scope": payload.scope, "id": payload.id})
        answer_parts: list[str] = []
        try:
            for token in tokens:
                answer_parts.append(token)
                yield sse_event("token", {"content": token})
            yield sse_event("done", {"grounding": grade_rag_answer("".join(answer_parts), sources)})
        except (OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError) as error:
            yield sse_event("error", {"error_code": "STREAM_FAILED", "message": str(error)})

    return StreamingResponse(events(), media_type="text/event-stream")
