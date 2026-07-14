from typing import Any

from pydantic import BaseModel


class ModelsResponse(BaseModel):
    models: dict[str, dict[str, Any]]
