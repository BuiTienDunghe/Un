# Local AI Core — Milestones 1A and 1B

FastAPI backend for local Ollama chat/code, document RAG, memory, hybrid retrieval, OCR fallback, and a lightweight UI.

## Models

- General: `qwen3.5:9b`
- Code: `qwen2.5-coder:7b`
- Embedding (configured for later milestones): `qwen3-embedding:0.6b`

## Setup (Windows PowerShell)

```powershell
cd local-ai-core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
ollama pull qwen3.5:9b
ollama pull qwen2.5-coder:7b
ollama pull qwen3-embedding:0.6b
docker compose up -d
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### One-click launcher (Windows)

Double-click `run-local-ai-core.bat`. On its first run, it creates `.venv`, installs dependencies, starts Qdrant, starts Ollama if needed, and downloads the configured models. Keep its terminal window open while using the API.

## API

- `GET /health` returns `ok` when SQLite and Ollama are ready; otherwise `degraded` while the API itself remains reachable.
- `GET /models` returns the configured model metadata.
- `POST /chat` uses the general model.
- `POST /code/chat` uses the code model.
- `POST /documents/upload` accepts PDF, DOCX, TXT, or MD (up to 50MB).
- `POST /documents/index` creates a background ingestion run. Poll `GET /documents/ingestions/{ingestion_run_id}` for `queued`, `parsing`, `ocr`, `chunking`, `embedding`, `indexing`, and terminal status.
- `GET /documents/{document_id}/status` returns `uploaded`, `indexing`, `indexed`, or `failed`.
- `POST /rag/chat` performs dense retrieval and returns sources.
- `POST /memory/add`, `POST /memory/search`, `PUT /memory/{id}`, and `DELETE /memory/{id}` manage local memories.
- `GET /conversations`, `GET /conversations/{id}`, and `DELETE /conversations/{id}` manage chat history.
- `POST /vision/chat` is an explicit placeholder while vision input is not implemented.
- `GET /ui/` serves a lightweight browser interface.

Uploads validate both the filename extension and MIME type. The document-status endpoint returns the original filename, indexing status, chunk count, and any indexing error.

Source retention is explicit. Original files are retained by default; `DELETE /documents/{document_id}/source` removes only the original artifact while retaining indexed knowledge, and citations then report `source_available: false` and `verifiable: false`. `DELETE /documents/{document_id}` permanently cascades through document chunks, ingestion records, Qdrant vectors, and the document folder. Use `PATCH /documents/{document_id}/retention` with `pinned` and `retention_policy` (`permanent`, `temporary`, or `knowledge_only`) to control cleanup eligibility.

OCR evaluation and RAG use the same `OCRService` for rendering, DPI, prompt, model configuration, post-processing, and cache keys. A completed OCR evaluation run can be promoted with `POST /api/ocr/jobs/{job_id}/promote`; it copies the original source, reuses OCR page text only when the OCR configuration hash still matches, then performs chunking, embedding, and versioned RAG indexing.

RAG defaults to `hybrid` retrieval: vector search in Qdrant and BM25 search over versioned indexed SQLite chunks are combined using reciprocal-rank fusion. SQLite is the source of truth for chunk text; Qdrant stores vectors plus lightweight metadata only. A new index version is only activated after all chunks and vectors succeed, so a failed reindex leaves the prior version available. BM25 uses `pyvi` so Vietnamese compound terms such as `học_sinh` are preserved.

Chunking is structure-first and token-budgeted: heading, paragraph, sentence, then token fallback. Chunks can cross page boundaries and retain `page_start`, `page_end`, per-page offsets, heading path, section title, block type, and extraction method. Markdown tables preserve their header when rows must be split. The configured default is 480 tokenizer-like units with 80 units overlap; benchmark these limits against the selected embedding model before production tuning.

Pass `"use_memory": true` to `POST /chat` to retrieve relevant saved memories and add them as contextual system input. Request logs are retained in SQLite and rotated daily with Loguru under `data/logs/`.

`sentence-transformers` is intentionally not installed yet: it is only needed for the optional reranker extension, which remains disabled and out of scope for the completed 1C baseline.

## OCR fallback for scanned PDFs

PDF pages first use native PyMuPDF4LLM text extraction. Pages with fewer than 80 non-whitespace characters or with fewer than 45% alphanumeric characters are retried through the configured local vision/OCR model. Every indexed chunk records whether its text came from `native` extraction or `ocr`; RAG sources expose that value. OCR uses `glm-ocr:latest` by default and can be disabled through `models.ocr.enabled`.

## Optional reranker

Hybrid retrieval can optionally rerank its top candidates with a multilingual cross-encoder from `sentence-transformers`. It is disabled by default in `rag.reranker.enabled`; when enabled, the model is downloaded once on first use and candidates are reranked before the final RAG context is built. Compare evaluation reports before enabling it as the default because it increases latency and memory usage.

## Streaming responses

Set `stream` to `true` on `/chat`, `/code/chat`, or `/rag/chat` to receive Server-Sent Events. The stream begins with `meta`, emits one or more `token` events, and ends with `done`; failures emit an `error` event. The web UI exposes a Stream toggle in each of these tabs. Chat history is only persisted after a stream completes successfully.

## Local verification and evaluation

Run `./smoke-test-local.ps1` after launching the system. Add `-SampleFile <path>` to test the complete upload, index, and RAG flow. For a reproducible baseline, run `python backend/scripts/evaluate_rag.py` from the project root. It uploads the bundled fixture, indexes it, runs four RAG cases, and saves source recall, MRR, answer pass rate, and latency under `data/evaluation/results/`. Replace the bundled fixture/cases with real documents before using the metrics to make model or retrieval decisions.

Example:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/chat -ContentType 'application/json' -Body '{"message":"Explain RAG simply"}'
```

RAG example (replace the document ID after upload):

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/documents/upload -Form @{ file = Get-Item .\example.txt }
Invoke-RestMethod -Method Post http://127.0.0.1:8000/documents/index -ContentType 'application/json' -Body '{"document_id":"doc_xxx"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/rag/chat -ContentType 'application/json' -Body '{"message":"What does this document say?","document_id":"doc_xxx"}'
```

When `conversation_id` is omitted, `/chat` creates one. When it is provided but does not exist, the API returns `404 CONVERSATION_NOT_FOUND`.

## Tests

From `local-ai-core/backend` with the virtual environment active:

```powershell
pytest tests -v
```

The tests mock Ollama and do not require a downloaded model or running Ollama service.
