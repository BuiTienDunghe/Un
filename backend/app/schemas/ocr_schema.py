from pydantic import BaseModel, Field


class OcrJobOptions(BaseModel):
    dpi: int = Field(default=200, ge=72, le=400)
    page_range: str | None = Field(default=None, max_length=100)
    output_format: str = Field(default="all", pattern="^(text|markdown|json|all)$")


class OcrEvaluationRequest(BaseModel):
    ground_truth: str = Field(min_length=1, max_length=2_000_000)
