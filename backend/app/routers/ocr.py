from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.schemas.ocr_schema import OcrEvaluationRequest
from app.services.ocr_job_service import OcrPromotionError
from app.services.monitoring_service import system_metrics

from app.security.api_key import require_api_key
from app.security.auth import require_admin

router = APIRouter(prefix="/api/ocr", tags=["ocr-console"])

def _job(request: Request, job_id: str):
    try: return request.app.state.ocr_job_service.view(job_id)
    except KeyError as error: raise HTTPException(404, detail={"error_code":"OCR_JOB_NOT_FOUND", "message":"OCR job was not found"}) from error

@router.post("/jobs", status_code=201, dependencies=[Depends(require_api_key)])
async def create_job(request: Request, file: UploadFile = File(...), dpi: int = 200, page_range: str | None = None, output_format: str = "all"):
    try: return await request.app.state.ocr_job_service.create(file, dpi, page_range, output_format)
    except ValueError as error: raise HTTPException(422, detail={"error_code":"INVALID_OCR_INPUT", "message":str(error)}) from error

@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request): return _job(request, job_id)

@router.get("/jobs/{job_id}/events")
def get_events(job_id: str, request: Request): return {"events": _job(request, job_id)["events"]}

@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel(job_id: str, request: Request):
    try: return request.app.state.ocr_job_service.cancel(job_id)
    except KeyError as error: raise HTTPException(404, detail={"error_code":"OCR_JOB_NOT_FOUND", "message":"OCR job was not found"}) from error

@router.post("/jobs/{job_id}/evaluate", dependencies=[Depends(require_api_key)])
def evaluate(job_id: str, payload: OcrEvaluationRequest, request: Request):
    try: return request.app.state.ocr_job_service.evaluate(job_id, payload.ground_truth)
    except KeyError as error: raise HTTPException(404, detail={"error_code":"OCR_JOB_NOT_FOUND", "message":"OCR job was not found"}) from error

@router.post("/jobs/{job_id}/promote", status_code=202, dependencies=[Depends(require_api_key)])
def promote(job_id: str, request: Request):
    try:
        result = request.app.state.ocr_job_service.promote(job_id, request.app.state.document_service)
        run = result.get("ingestion")
        return {"document_id": result["document_id"], "duplicate": bool(result["duplicate"]), "reused_ocr": bool(result["reused_ocr"]), "ingestion_run_id": run["id"] if run else None, "index_version": run["index_version"] if run else None, "status": run["status"] if run else None}
    except KeyError as error:
        raise HTTPException(404, detail={"error_code":"OCR_JOB_NOT_FOUND", "message":"OCR job was not found"}) from error
    except OcrPromotionError as error:
        raise HTTPException(409, detail={"error_code":"OCR_PROMOTION_NOT_AVAILABLE", "message":str(error)}) from error

@router.get("/jobs/{job_id}/export")
def export(job_id: str, request: Request):
    try: return FileResponse(request.app.state.ocr_job_service.export(job_id), filename=f"{job_id}.zip", media_type="application/zip")
    except KeyError as error: raise HTTPException(404, detail={"error_code":"OCR_JOB_NOT_FOUND", "message":"OCR job was not found"}) from error

@router.get("/jobs/{job_id}/files/{file_path:path}")
def artifact(job_id: str, file_path: str, request: Request):
    job = _job(request, job_id); root = request.app.state.ocr_job_service.runs_path / job_id
    file = (root / file_path).resolve()
    if root.resolve() not in file.parents or not file.is_file(): raise HTTPException(404, detail={"error_code":"OCR_ARTIFACT_NOT_FOUND", "message":"Artifact was not found"})
    return FileResponse(file)

@router.get("/system/metrics")
def metrics(): return system_metrics()

@router.get("/history")
def history(request: Request): return {"runs": request.app.state.ocr_job_service.list_history()}

@router.delete("/history/{job_id}", status_code=204, dependencies=[Depends(require_api_key), Depends(require_admin)])
def delete_history(job_id: str, request: Request): request.app.state.ocr_job_service.delete(job_id)
