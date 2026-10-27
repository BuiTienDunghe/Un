"""Read-only, after Step 2: are the qi passage vectors the same as the v0 ones they will be compared against?

On 27/10, documents_drill_heldout had been embedded on 08/09 under an older Ollama, while
documents_drill_heldout_qi was embedded that day. The probe compares two fresh embeddings and
cannot see that difference. Point ids are uuid5(document, version, index), so the active points
of both collections pair up by id. Bổ sung 2 compares the two collections under a new base
(e.g. documents_drill_heldout_r2 / documents_drill_heldout_r2_qi, documents_lab_r2 / documents_lab_r2_qi).

usage (from backend): python -m scripts.passage_drift [V0 QI [QDRANT_URL]]
No arguments = the 27/10 pair, so that run stays reproducible.
"""
import math
import sys

import httpx

DEFAULT_V0, DEFAULT_QI = "documents_drill_heldout", "documents_drill_heldout_qi"
DEFAULT_QDRANT = "http://127.0.0.1:6333"


def scroll(qdrant: str, name: str) -> dict[str, list[float]]:
    out, offset = {}, None
    while True:
        body = {"limit": 1000, "with_payload": False, "with_vector": True, **({"offset": offset} if offset else {})}
        result = httpx.post(f"{qdrant}/collections/{name}/points/scroll", json=body, timeout=60).json()["result"]
        out.update({str(p["id"]): p["vector"] for p in result["points"]})
        offset = result.get("next_page_offset")
        if not offset:
            return out


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def arguments(argv: list[str]) -> tuple[str, str, str]:
    """[] -> the 27/10 pair; [V0, QI] or [V0, QI, QDRANT_URL]. One argument is refused:
    before Bổ sung 2 it was the Qdrant URL, and reading it as V0 would be a silent swap."""
    if len(argv) not in (0, 2, 3):
        raise SystemExit("usage: python -m scripts.passage_drift [V0 QI [QDRANT_URL]]")
    v0, qi = argv[:2] if argv else (DEFAULT_V0, DEFAULT_QI)
    return v0, qi, (argv[2] if len(argv) == 3 else DEFAULT_QDRANT).rstrip("/")


def report(v0: dict[str, list[float]], qi: dict[str, list[float]]) -> list[str]:
    paired = sorted(cosine(v0[i], vector) for i, vector in qi.items() if i in v0)
    lines = [f"qi points {len(qi)} · paired with v0 {len(paired)} · unpaired {len(qi) - len(paired)}"]
    if paired:
        lines.append(f"cosine min {paired[0]:.8f} · p1 {paired[len(paired) // 100]:.8f} · median {paired[len(paired) // 2]:.8f}")
        lines.append(f"below 0.999999: {sum(1 for c in paired if c < 0.999999)}")
    return lines


def main(argv: list[str]) -> int:
    v0_name, qi_name, qdrant = arguments(argv)
    print(f"v0 {v0_name} · qi {qi_name} · {qdrant}")
    qi = scroll(qdrant, qi_name)
    v0 = scroll(qdrant, v0_name)
    print("\n".join(report(v0, qi)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
