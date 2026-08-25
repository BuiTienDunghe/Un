from typing import Any

from pydantic import BaseModel

from app.utils.vi_tokenizer import TOKENIZER_VERSION


class ModelsResponse(BaseModel):
    models: dict[str, dict[str, Any]]
    # T16: the segmentation contract behind every BM25 lexeme, reported by the
    # SERVER rather than guessed by the caller — the eval harness reads the
    # embedding model from this same endpoint for exactly that reason, and a
    # baseline is only comparable across an identical pair.
    tokenizer_version: str = TOKENIZER_VERSION
