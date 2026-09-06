"""Fetch the public held-out retrieval sets, with the licence checked first.

Why this exists as a script rather than a few download calls: the whole point of
a held-out set is that somebody else wrote it, which means somebody else owns it.
A number measured on data whose terms were never read is a number that cannot
safely be published, and the moment to find that out is before the download, not
after the model card is written.

So each dataset carries its licence here, and a dataset whose terms are unknown
is skipped unless it is asked for explicitly — in which case it is marked
local-eval-only and must not be redistributed or used to build a derived set.

The Hub rate-limits anonymous traffic hard (HTTP 429, "maximum queue size
reached"), so every download retries with a growing wait rather than failing the
run.

    python -m training.common.fetch_heldout --list
    python -m training.common.fetch_heldout --dataset zalo-legal
    python -m training.common.fetch_heldout --all
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "heldout_raw"

DATASETS: dict[str, dict] = {
    "zalo-legal": {
        "repo": "GreenNode/zalo-ai-legal-text-retrieval-vn",
        "files": ["queries.jsonl", "qrels/test.jsonl", "corpus.jsonl"],
        "licence": "mit",
        "redistributable": True,
        "note": "Zalo AI Challenge 2021 legal text retrieval, BEIR layout. The set the "
                "VLSP-2025 semi-hard-negative recipe is reproduced on.",
    },
    "table-vn": {
        "repo": "GreenNode/GreenNode-Table-Markdown-Retrieval-VN",
        "files": ["queries.jsonl", "qrels/test.jsonl", "corpus.jsonl"],
        "licence": "mit",
        "redistributable": True,
        "note": "Vietnamese table-in-markdown retrieval. A different document shape "
                "from prose, which is the point of including it.",
    },
    "viquad2": {
        "repo": "taidng/UIT-ViQuAD2.0",
        "files": ["data/validation-00000-of-00001.parquet"],
        "licence": None,
        "redistributable": False,
        "note": "NO LICENCE DECLARED on the Hub as of 04/09/2026. Scoring a model on it "
                "locally is ordinary benchmarking; redistributing it, or shipping a set "
                "derived from it, is not. Needs pyarrow, which the runtime venv lacks.",
    },
}


def fetch_file(repo: str, filename: str, destination: Path, attempts: int = 40) -> Path:
    """Stream one file to disk, resuming where a previous attempt stopped.

    `hf_hub_download` restarts from zero on every failure, and the Hub answers
    anonymous requests for a large file with 429 often enough that a 115 MB
    corpus never finishes: each retry throws away the bytes the last one got.
    A Range request continues instead, so a slow, interrupted download still
    converges.
    """
    import requests

    url = f"https://huggingface.co/datasets/{repo}/resolve/main/{filename}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    delay = 10
    for attempt in range(1, attempts + 1):
        have = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=120) as response:
                if response.status_code in (429, 503):
                    raise RuntimeError(f"HTTP {response.status_code} (rate limited)")
                if have and response.status_code == 200:
                    # The server ignored Range and is sending the whole file.
                    # Starting over is correct; appending would corrupt it.
                    have = 0
                    partial.unlink(missing_ok=True)
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0)) + have
                with partial.open("ab" if have else "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        handle.write(chunk)
            size = partial.stat().st_size
            if total and size < total:
                raise RuntimeError(f"truncated at {size}/{total} bytes")
            partial.replace(destination)
            return destination
        except Exception as error:
            got = partial.stat().st_size if partial.exists() else 0
            if attempt == attempts:
                raise RuntimeError(f"{filename}: gave up after {attempts} attempts at {got/1e6:.1f} MB — {error}") from error
            print(f"    {filename}: {error} (lan {attempt}/{attempts}, da co {got/1e6:.1f} MB), cho {delay}s", flush=True)
            time.sleep(delay)
            delay = min(int(delay * 1.6), 120)
    raise RuntimeError("unreachable")


def fetch(name: str, allow_unlicensed: bool) -> int:
    spec = DATASETS[name]
    if spec["licence"] is None and not allow_unlicensed:
        print(f"[{name}] BO QUA: khong khai bao giay phep. Dung --allow-unlicensed neu chi danh gia cuc bo.")
        print(f"          {spec['note']}")
        return 0
    print(f"[{name}] {spec['repo']}  licence={spec['licence'] or 'KHONG KHAI BAO'}  "
          f"redistributable={spec['redistributable']}")
    total = 0
    for filename in spec["files"]:
        # data/heldout_raw/ is gitignored: 115 MB of someone else's corpus does
        # not belong in this repository, and this script makes the fetch
        # reproducible without it.
        destination = RAW_DIR / name / filename
        if destination.exists():
            print(f"    {filename:34} {destination.stat().st_size/1e6:8.2f} MB (da co, bo qua)")
            total += destination.stat().st_size
            continue
        path = fetch_file(spec["repo"], filename, destination)
        size = path.stat().st_size
        total += size
        print(f"    {filename:34} {size/1e6:8.2f} MB")
    print(f"    tong {total/1e6:.1f} MB -> {RAW_DIR / name}")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), help="Fetch one dataset.")
    parser.add_argument("--all", action="store_true", help="Fetch every licensed dataset.")
    parser.add_argument("--list", action="store_true", help="Show what is declared, download nothing.")
    parser.add_argument("--allow-unlicensed", action="store_true",
                        help="Also fetch datasets with no declared licence. Local evaluation only: "
                             "do not redistribute and do not build a derived set from them.")
    arguments = parser.parse_args()

    if arguments.list or not (arguments.dataset or arguments.all):
        print(f"{'name':12} {'licence':10} {'redist':7} repo")
        for name, spec in sorted(DATASETS.items()):
            print(f"{name:12} {str(spec['licence'] or '-'):10} {str(spec['redistributable']):7} {spec['repo']}")
            print(f"{'':31}{spec['note']}")
        return 0

    names = sorted(DATASETS) if arguments.all else [arguments.dataset]
    for name in names:
        fetch(name, arguments.allow_unlicensed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
