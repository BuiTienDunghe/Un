from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: bool = True
    error_code: str
    message: str
    detail: str | None = None
