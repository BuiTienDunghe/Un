"""OCR every manifest image with one registry OCR version of the code on PYTHONPATH.

Optionally asks --qa-model each manifest question with the whole OCR text as context
(an approximation of the old product: OCR text -> general model). No database, no index.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from app.config.model_registry import load_registry
from app.llm_clients.ollama_client import OllamaClient
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService

BASE = "http://127.0.0.1:11434"
QA_SYSTEM = ("Bạn trả lời câu hỏi dựa trên văn bản được chép từ một ảnh. Chỉ dùng thông tin có trong văn bản. "
             "Nếu văn bản không có thông tin được hỏi, nói rõ là không có.")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--qa-model")
    a = ap.parse_args()
    version = load_registry().get("ocr", a.version)
    models = {"ocr": dict(version.config)}
    if a.qa_model:
        models["general"] = {"provider": "ollama", "name": a.qa_model, "think": False,
                             "context": 16384, "temperature": 0, "keep_alive": "2m"}
    router = ModelRouter({"ollama": OllamaClient(BASE, 300, 3, 0)}, models)
    service = OCRService(router)
    manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
    tags = httpx.get(f"{BASE}/api/tags").json()["models"]
    wanted = {version.config.get("name"), a.qa_model}
    report = {"version": version.id, "model": version.config.get("name"), "qa_model": a.qa_model,
              "digests": {t["name"]: t["digest"] for t in tags if t["name"] in wanted},
              "ollama": httpx.get(f"{BASE}/api/version").json(), "cases": []}
    for case in manifest["cases"]:
        png = (a.manifest.parent / case["path"]).read_bytes()
        started = time.perf_counter()
        item = {"id": case["id"], "group": case.get("group"), "answers": []}
        try:
            result = service.recognize_png(png, 200)
            item["text"] = result.text
            item["raw_text"] = getattr(result, "raw_text", None)
        except Exception as error:  # keep the failure, do not retry
            item["text"], item["error"] = "", f"{type(error).__name__}: {error}"
        item["seconds"] = round(time.perf_counter() - started, 3)
        if a.qa_model:
            for question in case["questions"]:
                messages = [{"role": "system", "content": QA_SYSTEM},
                            {"role": "user", "content": f"Văn bản:\n{item['text']}\n\nCâu hỏi: {question['question']}"}]
                q_started = time.perf_counter()
                try:
                    answer, _ = router.chat("general", messages)
                except Exception as error:
                    answer = f"ERROR {type(error).__name__}: {error}"
                item["answers"].append({**question, "answer": answer,
                                        "seconds": round(time.perf_counter() - q_started, 3)})
        report["cases"].append(item)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": case["id"], "seconds": item["seconds"], "chars": len(item["text"]),
                          "error": item.get("error")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
