"""Read the passive counter and answer the sizing question it exists for.

memory_design.md §13.6 job 1: the raw-ledger migration waits until this
report shows real flow. Run from the repo root or backend/:

    python -m scripts.passive_listen_report

Reads data/discord_listen/passive_counts.jsonl (ids and flags only — the
counter never stores content) and prints per-day, per-channel counts split
into human/bot and mention/passive, plus distinct speakers.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

CANDIDATES = (
    Path("data") / "discord_listen" / "passive_counts.jsonl",
    Path("..") / "data" / "discord_listen" / "passive_counts.jsonl",
)


def main() -> int:
    path = next((p for p in CANDIDATES if p.exists()), None)
    if path is None:
        print("Chua co du lieu: bo dem chua ghi dong nao "
              f"({CANDIDATES[0]}). Bot da bat DISCORD_LISTEN_CHANNEL_IDS chua?")
        return 1

    days: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {"total": 0, "human": 0, "bot": 0, "mention": 0, "authors": set()}
    )
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        key = (str(row.get("ts", ""))[:10], str(row.get("channel_id", "?")))
        bucket = days[key]
        bucket["total"] += 1
        bucket["bot" if row.get("author_is_bot") else "human"] += 1
        if row.get("is_mention"):
            bucket["mention"] += 1
        bucket["authors"].add(row.get("author_id"))

    print(f"nguon: {path}")
    print(f"{'ngay':<12}{'kenh':<22}{'tong':>6}{'nguoi':>7}{'bot':>5}{'mention':>9}{'nguoi noi':>11}")
    totals = {"total": 0, "human": 0}
    for (day, channel), bucket in sorted(days.items()):
        print(f"{day:<12}{channel:<22}{bucket['total']:>6}{bucket['human']:>7}"
              f"{bucket['bot']:>5}{bucket['mention']:>9}{len(bucket['authors']):>11}")
        totals["total"] += bucket["total"]
        totals["human"] += bucket["human"]
    day_count = len({day for day, _ in days}) or 1
    print(f"\ntong {totals['total']} tin / {day_count} ngay "
          f"= {totals['human'] / day_count:.1f} tin nguoi that/ngay "
          f"(nguong so goc trong ke hoach: khoi dau 30/ngay)")
    if skipped:
        print(f"(bo qua {skipped} dong hong)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
