"""Read-only, after Step 2: are the qi passage vectors the same as the v0 ones they will be compared against?

documents_drill_heldout was embedded on 08/09 under an older Ollama; documents_drill_heldout_qi is
embedded now. The probe compares two fresh embeddings and cannot see that difference. Point ids are
uuid5(document, version, index), so the active points of both collections pair up by id.

usage (from backend): python -m scripts.passage_drift [QDRANT_URL]
"""
import math
import sys

import httpx

Q = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6333").rstrip("/")
V0, QI = "documents_drill_heldout", "documents_drill_heldout_qi"


def scroll(name: str) -> dict[str, list[float]]:
    out, offset = {}, None
    while True:
        body = {"limit": 1000, "with_payload": False, "with_vector": True, **({"offset": offset} if offset else {})}
        result = httpx.post(f"{Q}/collections/{name}/points/scroll", json=body, timeout=60).json()["result"]
        out.update({str(p["id"]): p["vector"] for p in result["points"]})
        offset = result.get("next_page_offset")
        if not offset:
            return out


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


qi = scroll(QI)
v0 = scroll(V0)
paired = [cosine(v0[i], vector) for i, vector in qi.items() if i in v0]
paired.sort()
print(f"qi points {len(qi)} · paired with v0 {len(paired)} · unpaired {len(qi) - len(paired)}")
if paired:
    print(f"cosine min {paired[0]:.8f} · p1 {paired[len(paired) // 100]:.8f} · median {paired[len(paired) // 2]:.8f}")
    print(f"below 0.999999: {sum(1 for c in paired if c < 0.999999)}")
