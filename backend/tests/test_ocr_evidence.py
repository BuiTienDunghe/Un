import json
from types import SimpleNamespace

import pytest

from app.services.ocr_evidence import document_text, parse_evidence
from app.services.ocr_reader import read_evidence
from app.services.ocr_service import OCRService, OcrEvidenceError


TABLE = '<table><tr><th>Phòng ban</th><th>Dự án</th><th>Người phụ trách</th></tr><tr><td>Kỹ thuật</td><td>Bình Minh</td><td>Trần Tú</td></tr></table>'


def test_ovis_boxes_and_derived_table_rows_preserve_relations():
    raw = json.dumps([{"category": "table", "bbox": [10, 20, 900, 800], "content": TABLE}])
    blocks = parse_evidence(raw, "ovis_json", page=3)
    assert blocks[0].bbox == (10, 20, 900, 800)
    assert blocks[1].text == "Phòng ban: Kỹ thuật | Dự án: Bình Minh | Người phụ trách: Trần Tú"
    assert blocks[1].parent_id == "p3b1" and blocks[1].bbox is None
    assert "| Phòng ban | Dự án | Người phụ trách |" in document_text(blocks)
    assert "| Kỹ thuật | Bình Minh | Trần Tú |" in document_text(blocks)
    assert blocks[0].text == TABLE
    from app.utils.chunking import chunk_pages
    chunks = chunk_pages([(3, document_text(blocks), "ocr")], 480, 80)
    assert any(chunk.block_type == "table" and "Bình Minh" in chunk.content for chunk in chunks)
    assert blocks[1].payload(7)["parent_id"] == "p7b1"


@pytest.mark.parametrize("bbox", [[9, 0, 1, 20], [-1, 0, 100, 100], [0, 0, 1001, 100], [False, 0, 30, 50]])
def test_invalid_coordinates_are_rejected(bbox):
    with pytest.raises(ValueError):
        parse_evidence(json.dumps([{"category": "text", "content": "x", "bbox": bbox}]), "ovis_json")


def test_native_grounding_and_plain_tsv_keep_distinct_contracts():
    blocks = parse_evidence("![text](10, 20, 900, 200)\nMã: AB-71", "lighton_grounding")
    assert blocks[0].bbox == (10, 20, 900, 200)
    tsv = parse_evidence("Phòng\tSố tiền\nKế toán\t750.000")
    assert tsv[1].text == "Phòng: Kế toán | Số tiền: 750.000"
    assert parse_evidence("Nội dung", "text")[0].bbox is None
    with pytest.raises(ValueError):
        parse_evidence("unlocated text", "lighton_grounding")


def test_visual_descriptions_are_not_indexed_as_transcribed_text():
    raw = json.dumps([{"category": "image", "content": '<img src="images/bbox_10_20_50_60.jpg" />', "bbox": [10, 20, 50, 60]}])
    assert document_text(parse_evidence(raw, "ovis_json")) == ""


def test_columns_group_source_blocks_without_duplicating_indexed_text():
    records = [{"category": "text", "content": text, "bbox": box} for text, box in [
        ("Đơn Hà Nội", [50, 100, 200, 140]), ("Giao: 18/11", [50, 200, 200, 240]),
        ("Đơn Huế", [540, 100, 700, 140]), ("Giao: 21/11", [540, 200, 700, 240])]]
    blocks = parse_evidence(json.dumps(records), "ovis_json")
    group = next(block for block in blocks if block.id == "p1g2")
    assert group.text == "Đơn Huế\nGiao: 21/11" and group.bbox is None
    assert group.source_ids == ("p1b3", "p1b4")
    assert document_text(blocks).count("Giao: 21/11") == 1


def test_missing_phone_and_bank_account_abstain_without_model_call():
    class Never:
        def chat_structured(self, *_):
            pytest.fail("An absent typed field must not call the model")
    blocks = [{"id": "p1b1", "text": "Người nhận: Phạm Ngọc Quỳnh", "page": 1}]
    for question in ("Số điện thoại của người nhận là gì?", "Số tài khoản ngân hàng là gì?"):
        result = read_evidence(Never(), question, blocks)
        assert result["status"] == "insufficient_evidence" and result["selection_calls"] == 0


def test_reader_filters_requested_field_and_rejects_unknown_id():
    seen = []
    class Router:
        def chat_structured(self, mode, messages, schema, **kwargs):
            seen.append((messages, schema))
            return '{"block_ids":["invented"]}', "text-only"
    blocks = [{"id": "p1b1", "page": 1, "text": "Người nhận: An"},
              {"id": "p1b2", "page": 1, "text": "SĐT: 0912345678"}]
    result = read_evidence(Router(), "Số điện thoại là gì?", blocks)
    assert result["status"] == "rejected"
    assert seen[0][1]["properties"]["block_ids"]["items"]["enum"] == ["p1b2"]
    assert all(set(message) == {"role", "content"} for message in seen[0][0])


def test_cache_retains_raw_structured_evidence_and_all_generation_knobs():
    saved = {}
    class Store:
        def get_ocr_cache_with_key(self, *key): return saved.get(key)
        def save_ocr_cache_with_key(self, *args): saved[args[:-1]] = args[-1]
    class Router:
        models = {"ocr": {"name": "ovis", "revision": "r1", "output_contract": "ovis_json", "max_tokens": 8192}}
        calls = 0
        def ocr(self, *args, **kwargs):
            self.calls += 1
            return json.dumps([{"category": "text", "content": "Mã: PX-92", "bbox": [0, 0, 100, 100]}]), "ovis"
    router = Router()
    service = OCRService(router, Store())
    first, second = service.recognize_png(b"fake", 200), service.recognize_png(b"fake", 200)
    assert second.cache_hit and router.calls == 1 and first.blocks == second.blocks
    assert second.raw_text == first.raw_text and second.text == "Mã: PX-92"
    old = service.config_hash(200)
    router.models["ocr"]["max_tokens"] = 4096
    assert old != service.config_hash(200)


def test_invalid_json_keeps_raw_output_available_for_audit():
    router = SimpleNamespace(models={"ocr": {"output_contract": "ovis_json"}}, ocr=lambda *a, **k: ("broken JSON", "m"))
    with pytest.raises(OcrEvidenceError) as caught:
        OCRService(router).recognize_png(b"fake", 200)
    assert caught.value.raw_text == "broken JSON"


def test_structured_startup_probe_has_room_for_boxes_and_rejects_invalid_json(monkeypatch):
    from app.config.model_registry import ProductionProbes
    sent = []
    raw = json.dumps([{"category": "text", "content": "probe 4831", "bbox": [0, 0, 500, 500]}])
    def post(url, json, timeout):
        sent.append(json)
        return SimpleNamespace(status_code=200, is_success=True, json=lambda: {
            "done_reason": "stop", "message": {"content": raw}})
    monkeypatch.setattr("httpx.post", post)
    probes = ProductionProbes(SimpleNamespace(ollama_base_url="http://fake"))
    assert probes.ollama_ocr_stops("ovis", "native prompt", output_contract="ovis_json", probe_max_tokens=384)
    assert sent[0]["options"]["num_predict"] == 384
    assert "output_contract" not in sent[0]
    raw = "4831 is present, but this is not valid structured OCR"
    assert probes.ollama_ocr_stops("ovis", "native prompt", output_contract="ovis_json", probe_max_tokens=384) is False


def test_incomplete_table_is_rejected_instead_of_losing_last_row():
    with pytest.raises(ValueError, match="row"):
        parse_evidence('<table><tr><th>A</th></tr><tr><td>last</td></table>')


def test_headerless_table_keeps_first_data_row_without_inventing_column_names():
    blocks = parse_evidence('<table><tr><td>Mã</td><td>PX-19</td></tr><tr><td>Tổng</td><td>500.000</td></tr></table>')
    assert blocks[1].text == "Mã | PX-19"
    assert blocks[2].text == "Tổng | 500.000"
