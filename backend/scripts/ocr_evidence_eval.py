"""Evaluate the production OCR/evidence reader without production DB/index writes.

Manifest: {"cases": [{"id", "path", "questions": [{"question", "expected": [...]}]}]}.
An absent-field question uses "abstain": true. Paths are relative to the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

from app.config.model_registry import load_registry
from app.llm_clients.ollama_client import OllamaClient
from app.services.model_router import ModelRouter
from app.services.ocr_reader import read_evidence
from app.services.ocr_evidence import parse_evidence
from app.services.ocr_service import OCRService


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ocr-version")
    # Default: the registry's active general version, the model /ocr/jobs/{id}/ask uses
    # (review 10/11, P2: the default used to be lfm3:1.7b while the API asks general).
    parser.add_argument("--answer-model", help="another Ollama tag as the evidence reader (default: active general)")
    parser.add_argument("--replay", type=Path, help="Reuse raw OCR from another report to measure reader/evidence changes")
    args = parser.parse_args()
    registry = load_registry()
    version = registry.get("ocr", args.ocr_version or registry.roles["ocr"].active)
    general = dict(registry.get("general", registry.roles["general"].active).config)
    if args.answer_model:
        general.update(name=args.answer_model)
    args.answer_model = general["name"]
    client = OllamaClient("http://127.0.0.1:11434", chat_timeout=150, health_timeout=3, retry_count=0)
    router = ModelRouter({"ollama": client}, {"ocr": dict(version.config), "general": general})
    service = OCRService(router)
    replay = {case["id"]: case for case in json.loads(args.replay.read_text(encoding="utf-8"))["cases"]} if args.replay else None
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = {"synthetic": bool(manifest.get("synthetic")), "ocr_version": version.id,
              "answer_model": args.answer_model, "answer_contains_images": False,
              "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(), "cases": []}
    tags = httpx.get("http://127.0.0.1:11434/api/tags").json()["models"]
    report["model_digests"] = {entry["name"]: entry["digest"] for entry in tags
                              if entry["name"] in {version.name, args.answer_model}}
    report["runtime"] = httpx.get("http://127.0.0.1:11434/api/version").json()
    try:
        report["gpu"] = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip()
    except (OSError, subprocess.SubprocessError):
        report["gpu"] = None
    for case in manifest["cases"]:
        item = {"id": case["id"], "group": case.get("group", "regression"), "answers": []}
        report["cases"].append(item)
        started = time.perf_counter()
        try:
            source = args.manifest.parent / case["path"]
            if replay:
                recorded = replay[case["id"]]
                item["text"], item["raw_text"] = recorded["text"], recorded["raw_text"]
                item["ocr_seconds"] = recorded["ocr_seconds"]
                blocks = [block.payload() for block in parse_evidence(recorded["raw_text"], version.config.get("output_contract", "text"))]
            else:
                result = service.recognize_png(source.read_bytes(), 200)
                item["ocr_seconds"] = round(time.perf_counter() - started, 3)
                item["text"], item["raw_text"] = result.text, result.raw_text
                blocks = [block.payload() for block in result.blocks]
            item["blocks"] = blocks
            for question in case["questions"]:
                answer = read_evidence(router, question["question"], blocks)
                text = answer["message"].casefold()
                passed = answer["status"] == "insufficient_evidence" if question.get("abstain") else (
                    answer["status"] == "cited" and all(value.casefold() in text for value in question["expected"])
                    and not any(value.casefold() in text for value in question.get("forbidden", [])))
                item["answers"].append({**question, "passed": passed, "answer": answer})
        except Exception as error:
            item["error"] = f"{type(error).__name__}: {error}"
        write(args.output / "report.json", report)
        print(json.dumps({"case": case["id"], "passed": sum(answer["passed"] for answer in item["answers"]),
                          "questions": len(case["questions"]), "error": item.get("error")}), flush=True)
    report["questions_total"] = sum(len(case["questions"]) for case in manifest["cases"])
    report["questions_passed"] = sum(answer["passed"] for case in report["cases"] for answer in case["answers"])
    report["groups"] = {group: {
        "total": sum(len(case["questions"]) for case in manifest["cases"] if case.get("group", "regression") == group),
        "passed": sum(answer["passed"] for case in report["cases"] if case["group"] == group for answer in case["answers"]),
    } for group in {case.get("group", "regression") for case in manifest["cases"]}}
    write(args.output / "report.json", report)


if __name__ == "__main__":
    main()
