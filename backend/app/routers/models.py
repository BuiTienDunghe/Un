from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config.model_registry import CLOUD_PROVIDERS, check_registry
from app.schemas.model_schema import ModelsResponse
from app.security.api_key import require_api_key
from app.security.auth import require_admin
from app.services import model_choice

router = APIRouter(tags=["models"])

# The roles the Model screen may switch. The others need more than a pick: embedding a rebuild
# of its collections, and the extractor refuses boot beside its tag pin in .env.
SWITCHABLE_ROLES = ("general",)
_GUARDS = [Depends(require_api_key), Depends(require_admin)]


class PromoteRequest(BaseModel):
    version: str


def _version_status(version_id: str, row: dict[str, Any], chosen: str | None) -> str:
    if version_id == row["requested"] and row["fallback"]:
        return "failed"
    if version_id == row["loaded"]:
        return "active" if version_id == chosen else "serving"
    return "pending" if version_id == chosen else "candidate"


def _registry_view(request: Request) -> dict[str, dict[str, Any]]:
    """/models.registry, plus what a switchable role can switch to: the running process read its
    pick at start, so `chosen` (the pick on disk) can differ from `loaded` until the restart."""
    resolved = request.app.state.model_registry
    view = resolved.registry_view()
    choices = model_choice.read_choices(model_choice.CHOICE_PATH)
    for role in SWITCHABLE_ROLES:
        row = view[role]
        # No line in the file: a shell pin, if any, is still what the next start serves.
        chosen = (choices[role] or row["active"]) if role in choices else row["requested"]
        row["switchable"] = True
        row["chosen"] = chosen
        row["versions"] = [
            {
                "id": record.id,
                "name": record.name,
                "status": _version_status(record.id, row, chosen),
                "cloud": record.provider in CLOUD_PROVIDERS,
            }
            for record in resolved.registry.roles[role].versions
        ]
    return view


def _switchable(role: str, request: Request) -> None:
    if role not in request.app.state.model_registry.registry.roles:
        raise HTTPException(status_code=404, detail={"error_code": "MODEL_ROLE_NOT_FOUND", "message": f"Unknown model role {role}"})
    if role not in SWITCHABLE_ROLES:
        raise HTTPException(status_code=409, detail={"error_code": "MODEL_ROLE_NOT_SWITCHABLE", "message": "Vai trò này chưa đổi được từ giao diện."})


@router.get("/models", response_model=ModelsResponse)
def models(request: Request) -> ModelsResponse:
    state = request.app.state
    return ModelsResponse(models=state.models, registry=_registry_view(request), rag=state.rag_flags)


@router.get("/models/check", dependencies=_GUARDS)
def check(request: Request) -> dict[str, Any]:
    errors, warnings = check_registry(request.app.state.settings.model_registry_file)
    return {"ok": not errors, "problems": errors, "output": "\n".join(warnings)}


@router.post("/models/{role}/promote", dependencies=_GUARDS)
def promote(role: str, payload: PromoteRequest, request: Request) -> dict[str, Any]:
    _switchable(role, request)
    entry = request.app.state.model_registry.registry.roles[role]
    if payload.version not in (record.id for record in entry.versions):
        raise HTTPException(status_code=404, detail={"error_code": "MODEL_VERSION_NOT_FOUND", "message": f"Unknown version {payload.version}"})
    # Picking the registry's own `active` is no pick at all: the machine follows the file again.
    model_choice.save_choice(model_choice.CHOICE_PATH, role, None if payload.version == entry.active else payload.version)
    return _registry_view(request)[role]


@router.post("/models/{role}/revert", dependencies=_GUARDS)
def revert(role: str, request: Request) -> dict[str, Any]:
    _switchable(role, request)
    model_choice.save_choice(model_choice.CHOICE_PATH, role, None)
    return _registry_view(request)[role]
