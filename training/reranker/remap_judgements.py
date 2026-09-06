"""Carry the 813 chunk-level judgements over to the corrected chunker.

The judgements in ``chunk_judgements_raw.json`` record *chunk indices* under the
chunker that was live on 06/09/2026, which carried whole blocks as "overlap" and so
emitted chunks that contained the chunk before them. The corrected chunker draws
different boundaries, and only 44 of the 813 recorded indices still point at the
same text. The judged text itself is on disk, so the labels are recoverable — but
not by the obvious method.

Anchoring an old chunk by its first hundred characters is wrong here, because under
the old chunker the first hundred characters of chunk N *are the end of chunk N−1*:
the anchor lands on the wrong neighbour exactly in the duplicated cases, which are
95% of the two-chunk judgements.

What is used instead is the judgement's own structure. A judge marked every chunk
that contained the answer and left the rest unmarked. So a sentence that appears in
a marked chunk **and** in an unmarked chunk is not the answer — the judge saw it
twice and passed over it once — while a sentence that appears only in marked chunks
is. A new chunk is positive when it contains at least one such answer sentence.
Judgements whose answer sentences are all very short fall back to any answer
sentence; judgements that still map to nothing are listed for reading, not guessed.

Outputs, next to the inputs in ``data/evaluation/reranker_v1/``:

  chunk_judgements_remapped.json   per judgement: old and new indices, status
  chunk_labels_judged.jsonl        one row per positive (query, chunk) — same shape
                                   as chunk_labels_clean.jsonl
  chunk_labels_clean.jsonl         regenerated: single-chunk articles under the new
                                   chunker (asserted to still be single-chunk)

    python -m training.reranker.remap_judgements
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.utils.chunking import _SENTENCE_PATTERN, chunk_pages, count_tokens  # noqa: E402

RAW = PROJECT_ROOT / "data" / "heldout_raw" / "zalo-legal"
OUT = PROJECT_ROOT / "data" / "evaluation" / "reranker_v1"
CHUNK_TOKENS, CHUNK_OVERLAP = 480, 80
MIN_ANSWER_SENTENCE_TOKENS = 5

# One judgement was filed under the wrong article id. Its reason quotes the forest
# land-use penalty brackets of 35/2019/nđ-cp+12 — the query's only positive, and the
# one task in the batches that received no judgement — not the transport circular it
# names. Corrected explicitly rather than by any doc-id fallback, so it stays visible.
CORRECTIONS = {
    ("3da8a935155b3ba6d28d0a90b4cd387a", "23/2018/tt-bgtvt+32"): "35/2019/nđ-cp+12",
}


def document_chunks(doc: dict) -> list[str]:
    # Byte-for-byte the construction in build_judgement_tasks.py, so a chunk here is
    # what the index holds.
    title = (doc.get("title") or "").strip()
    text = (doc.get("text") or "").strip()
    body = f"# {title}\n\n{text}\n" if title else text + "\n"
    return [c.content for c in chunk_pages([(None, body, "text")], CHUNK_TOKENS, CHUNK_OVERLAP)]


def sentences(text: str) -> list[str]:
    out = []
    for block in text.split("\n"):
        for piece in _SENTENCE_PATTERN.split(block):
            piece = " ".join(piece.lower().split())
            if piece:
                out.append(piece)
    return out


_QUOTE = re.compile(r"'([^']{12,}?)'|\"([^\"]{12,}?)\"|“([^”]{12,}?)”")
_ELLIPSIS = re.compile(r"\.\.\.|…")


def citations(reason: str) -> list[str]:
    """Verbatim fragments the judge quoted, split on the ellipses they used to skip text."""
    out = []
    for groups in _QUOTE.findall(reason or ""):
        for quoted in groups:
            for part in _ELLIPSIS.split(quoted):
                part = " ".join(part.lower().split()).strip(" ,;:")
                if len(part) >= 12:
                    out.append(part)
    return out


def load_docs(wanted: set[str]) -> dict[str, dict]:
    docs = {}
    with (RAW / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["_id"] in wanted:
                docs[row["_id"]] = row
    return docs


def main() -> int:
    judgements = json.loads((OUT / "chunk_judgements_raw.json").read_text(encoding="utf-8"))
    tasks: dict[tuple[str, str], dict] = {}
    for batch in sorted((OUT / "judgement_batches").glob("batch_*.json")):
        for task in json.loads(batch.read_text(encoding="utf-8")):
            tasks[(task["query_id"], task["doc_id"])] = task
    clean_rows = [json.loads(l) for l in (OUT / "chunk_labels_clean.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    docs = load_docs({CORRECTIONS.get((j["query_id"], j["doc_id"]), j["doc_id"]) for j in judgements}
                     | {r["doc_id"] for r in clean_rows})
    new_chunks = {doc_id: document_chunks(doc) for doc_id, doc in docs.items()}

    remapped, judged_rows = [], []
    status = collections.Counter()
    prefix_disagreements = 0
    for j in judgements:
        if (j["query_id"], j["doc_id"]) in CORRECTIONS:
            j = {**j, "doc_id": CORRECTIONS[(j["query_id"], j["doc_id"])], "doc_id_corrected": True}
        key = (j["query_id"], j["doc_id"])
        task = tasks[key]
        old = task["chunks"]
        marked = sorted(set(j.get("chunk_indices") or []))
        fresh = new_chunks[j["doc_id"]]
        record = {"query_id": j["query_id"], "doc_id": j["doc_id"], "old_chunk_indices": marked,
                  "old_chunk_count": len(old), "new_chunk_count": len(fresh),
                  "confidence": j.get("confidence"), "doc_id_corrected": j.get("doc_id_corrected", False)}
        if not marked:
            record.update(new_chunk_indices=[], status="no_answer_in_document")
            status["no_answer_in_document"] += 1
            remapped.append(record)
            continue

        # Only a genuinely different unmarked chunk can rule a sentence out. Under the
        # old chunker an unmarked chunk often *contained* the marked one, and a judge
        # who marked chunk 2 but not its superset chunk 3 was not saying chunk 3 lacks
        # the answer — they marked one copy. Such near-duplicates share most of their
        # sentences with a marked chunk and are left out of the exclusion set.
        marked_sets = [set(sentences(old[i])) for i in marked]
        marked_sentences = set().union(*marked_sets)
        unmarked_sentences = set()
        for i, c in enumerate(old):
            if i in marked:
                continue
            own = set(sentences(c))
            if not own:
                continue
            duplicate_of_marked = (len(own & marked_sentences) / len(own) >= 0.5          # mostly inside a marked chunk
                                   or any(len(own & m) / len(m) >= 0.5 for m in marked_sets if m))  # or holds most of one
            if not duplicate_of_marked:
                unmarked_sentences.update(own)
        answer = [s for i in marked for s in sentences(old[i]) if s not in unmarked_sentences]
        long_answer = [s for s in answer if count_tokens(s) >= MIN_ANSWER_SENTENCE_TOKENS]
        probe = long_answer or answer
        fresh_norm = [" ".join(c.lower().split()) for c in fresh]
        positives = [k for k, c in enumerate(fresh_norm) if any(s in c for s in probe)]
        if not positives and probe:
            # A clause longer than the budget is token-sliced by the chunker, so no new
            # chunk holds the whole sentence. Fall back to 15-token windows of it.
            windows = []
            for s in probe:
                words = s.split()
                windows += [" ".join(words[k:k + 15]) for k in range(0, max(1, len(words) - 14), 8)]
            windows = [w for w in windows if len(w.split()) >= 8]
            positives = [k for k, c in enumerate(fresh_norm) if any(w in c for w in windows)]
            record["matched_by_window"] = bool(positives)

        # Cross-check against the prefix anchor, only to count how often it disagrees.
        anchored = set()
        for i in marked:
            head = " ".join(old[i].lower().split())[:100]
            hits = [k for k, c in enumerate(fresh_norm) if head and head in c]
            if hits:
                anchored.add(hits[0])
        if anchored != set(positives):
            prefix_disagreements += 1

        # A marked old chunk of 600-900 tokens covers two or three new chunks, and the
        # judgement alone cannot say which of them holds the answer. The judge's reason
        # usually can: 98% quote the answering text verbatim. When those quotes land in
        # a strict subset of the positives, the rest were only ever carried along.
        if len(positives) >= 2:
            quoted = citations(j.get("reason") or "")
            cited = [k for k in positives if any(q in fresh_norm[k] for q in quoted)]
            if quoted and cited and len(cited) < len(positives):
                record["narrowed_by_citation"] = {"from": positives, "to": cited}
                positives = cited

        if not positives:
            record.update(new_chunk_indices=[], status="unmatched", answer_sentences=probe[:3])
            status["unmatched"] += 1
        else:
            record.update(new_chunk_indices=positives, status="ok",
                          used_short_sentences=not long_answer)
            status["ok"] += 1
            for k in positives:
                judged_rows.append({"query_id": j["query_id"], "query": task["query"], "doc_id": j["doc_id"],
                                    "chunk_index": k, "text": fresh[k],
                                    "label_source": "judged 06/09/2026, remapped by answer sentence"})
        remapped.append(record)

    # Single-chunk articles: the label transfers only if the article is still one chunk.
    regenerated, split_now = [], []
    for row in clean_rows:
        pieces = new_chunks[row["doc_id"]]
        if len(pieces) != 1:
            split_now.append(row["doc_id"])
            continue
        regenerated.append({**row, "chunk_index": 0, "text": pieces[0]})
    if split_now:
        raise SystemExit(f"{len(split_now)} bai bao mot chunk nay chia nhieu manh: {split_now[:5]}")

    (OUT / "chunk_judgements_remapped.json").write_text(
        json.dumps(remapped, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "chunk_labels_judged.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in judged_rows), encoding="utf-8")
    (OUT / "chunk_labels_clean.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in regenerated), encoding="utf-8")

    per_pair = collections.Counter(len(r["new_chunk_indices"]) for r in remapped if r["status"] == "ok")
    print(f"ban an: {len(judgements)} · khop {status['ok']} · khong dap an {status['no_answer_in_document']} · KHONG KHOP {status['unmatched']}")
    print(f"so chunk duong moi cap: {dict(sorted(per_pair.items()))}")
    print(f"chunk duong tu ban an: {len(judged_rows)} (cu: {sum(len(j.get('chunk_indices') or []) for j in judgements)})")
    print(f"neo theo 100 ky tu dau se cho ket qua khac o {prefix_disagreements} ban an")
    narrowed = sum(1 for r in remapped if r.get("narrowed_by_citation"))
    print(f"thu hep nho trich dan cua tham phan: {narrowed} cap")
    print(f"nhan sach mot chunk: {len(regenerated)} (van mot chunk: {len(regenerated)}/{len(clean_rows)})")
    for r in remapped:
        if r["status"] == "unmatched":
            print(f"  DOC TAY: {r['query_id']} {r['doc_id']} cu={r['old_chunk_indices']} cau={r.get('answer_sentences')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
