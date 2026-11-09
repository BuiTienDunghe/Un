"""Summarise the 10/11 old-vs-new comparison. Reads OUT, prints tables, writes analysis.json."""
from __future__ import annotations

import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(r"~\local-ai-core\data\evaluation\results\c57-compare-20261110")
MANIFEST = Path(r"~\local-ai-core-wt\check-c57aa3e\data\benchmarks\ocr_evidence\v1\manifest.json")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def content(text: str) -> str:
    """Letters and digits only: drops HTML tags, markdown marks, table separators and punctuation."""
    text = re.sub(r"<[^>]+>", " ", unicodedata.normalize("NFC", text or ""))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]|_", " ", text)).strip().casefold()


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def ocr_tables(result: dict) -> None:
    manifest = {c["id"]: c for c in json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]}
    result["ocr"] = {}
    for name in ["ocr-old-v2-9b", "ocr-old-v1-glm", "ocr-new-ovis", "ocr-new-glm"]:
        path = OUT / "ocr" / f"{name}.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        rows, errs, chars, secs, cerrs, cchars = [], 0, 0, [], 0, 0
        for case in report["cases"]:
            secs_all = case["seconds"]
            if "reference" not in manifest[case["id"]]:
                rows.append({"id": case["id"], "cer": None, "seconds": secs_all, "error": case.get("error")})
                secs.append(secs_all)
                continue
            ref = norm(manifest[case["id"]]["reference"])
            dist = edit_distance(norm(case.get("text", "")), ref)
            cref = content(manifest[case["id"]]["reference"])
            cdist = edit_distance(content(case.get("text", "")), cref)
            errs, chars = errs + dist, chars + len(ref)
            cerrs, cchars = cerrs + cdist, cchars + len(cref)
            secs.append(case["seconds"])
            rows.append({"id": case["id"], "cer": round(100 * dist / max(len(ref), 1), 2),
                         "content_cer": round(100 * cdist / max(len(cref), 1), 2), "content_edits": cdist,
                         "seconds": case["seconds"], "error": case.get("error")})
        result["ocr"][name] = {"cer_total_pct": round(100 * errs / chars, 2),
                               "content_cer_total_pct": round(100 * cerrs / cchars, 2), "content_chars": cchars,
                               "per_image": rows, "median_seconds": statistics.median(secs),
                               "digests": report.get("digests")}
        print(f"{name:16} raw CER {100 * errs / chars:6.2f}%  content CER {100 * cerrs / cchars:5.2f}% "
              f"({cerrs}/{cchars})  median {statistics.median(secs):5.2f}s  "
              + " ".join(f"{r['id'][:8]}={r.get('content_edits')}" for r in rows if r['cer'] is not None))
    qa = OUT / "ocr" / "ocr-old-v2-9b.json"
    if qa.exists():
        answers = [a for c in json.loads(qa.read_text(encoding="utf-8"))["cases"] for a in c["answers"]]
        auto = [a for a in answers if not a.get("abstain")]
        hit = sum(all(v.casefold() in a["answer"].casefold() for v in a["expected"]) for a in auto)
        result["old_qa"] = {"non_abstain_total": len(auto), "non_abstain_hit": hit,
                            "abstain": [{"q": a["question"], "answer": a["answer"]} for a in answers if a.get("abstain")]}
        print(f"old QA (9B reads OCR text): expected value present {hit}/{len(auto)}; abstain questions to read by hand: "
              f"{len(answers) - len(auto)}")
    new = OUT / "ocr" / "ocr-new-evidence" / "report.json"
    if new.exists():
        report = json.loads(new.read_text(encoding="utf-8"))
        result["new_qa"] = {"passed": report.get("questions_passed"), "total": report.get("questions_total"),
                            "groups": report.get("groups")}
        print(f"new QA (Ovis + LFM3 evidence): {report.get('questions_passed')}/{report.get('questions_total')} {report.get('groups')}")


def ae_tables(result: dict) -> None:
    runs = {}
    for name in ["ae-A-main-9b", "ae-C-main-2b", "ae-B-branch-2b"]:
        path = OUT / "ae" / name / "task_results.jsonl"
        if path.exists():
            runs[name] = {json.loads(l)["task_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    result["agent_eval"] = {}
    for name, tasks in runs.items():
        lat = [t["latency_ms"] for t in tasks.values() if t.get("latency_ms") is not None]
        manifest = json.loads((OUT / "ae" / name / "manifest.json").read_text(encoding="utf-8"))
        keys = ["model", "general_version", "temperature", "top_p", "seed", "think", "num_ctx", "max_steps",
                "commit", "worktree_dirty", "ollama_version", "context_budget", "read_rest", "agent_guide_sha256"]
        result["agent_eval"][name] = {"passed": sum(t["passed"] for t in tasks.values()), "total": len(tasks),
                                      "errors": sum(bool(t.get("error")) for t in tasks.values()),
                                      "median_latency_ms": statistics.median(lat) if lat else None,
                                      "p90_latency_ms": sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None,
                                      "manifest": {k: manifest.get(k) for k in keys}}
        print(f"{name:16} {result['agent_eval'][name]}")
    for a, b in [("ae-A-main-9b", "ae-C-main-2b"), ("ae-C-main-2b", "ae-B-branch-2b"), ("ae-A-main-9b", "ae-B-branch-2b")]:
        if a in runs and b in runs:
            lost = sorted(t for t in runs[a] if runs[a][t]["passed"] and not runs[b].get(t, {}).get("passed"))
            won = sorted(t for t in runs[b] if runs[b][t]["passed"] and not runs[a].get(t, {}).get("passed"))
            result["agent_eval"][f"{a} -> {b}"] = {"lost": lost, "won": won}
            print(f"{a} -> {b}: lost {len(lost)} {lost}; won {len(won)} {won}")


def main() -> None:
    result: dict = {}
    progress = OUT / "progress.jsonl"
    if progress.exists():
        result["jobs"] = [json.loads(l) for l in progress.read_text(encoding="utf-8").splitlines() if '"done"' in l]
        for job in result["jobs"]:
            print(f"{job['job']:18} exit {job['exit']} {job['minutes']} min, VRAM peak {job['vram_peak_mib']} MiB, "
                  f"GPU peak {job['gpu_peak_c']} C, stopped {job['stopped']}")
    ocr_tables(result)
    ae_tables(result)
    (OUT / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
