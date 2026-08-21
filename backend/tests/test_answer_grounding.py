"""D3a — answer self-check without a model.

Every case here is synthetic and runs with no model: the point of the check is
that it costs zero inference, so its tests must too. The e2e test at the bottom
proves the report reaches both response shapes of /rag/chat.
"""
from __future__ import annotations

import json

from app.services import answer_grounding as ag

SOURCE = (
    "PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core. Mất nó là mất hội "
    "thoại, tài liệu, version, job và citation — Qdrant chỉ là chỉ mục và dựng lại được "
    "từ PostgreSQL. run-local-ai-core.bat khởi động một worker nền cùng lúc với backend. "
    "Chu kỳ mặc định 24 giờ, giữ lại 14 ngày, tối thiểu luôn giữ 3 bản mới nhất."
)


def test_answer_built_from_the_sources_is_grounded():
    answer = (
        "PostgreSQL là nguồn dữ liệu chuẩn duy nhất của hệ thống. "
        "Qdrant chỉ là chỉ mục và có thể dựng lại từ PostgreSQL. "
        "Backup chạy theo chu kỳ mặc định 24 giờ và giữ lại 14 ngày."
    )
    report = ag.grade_answer(answer, [SOURCE])
    assert report.label == "grounded"
    assert report.judged == 3 and report.grounded == 3 and report.ungrounded == 0
    assert report.grounded_ratio == 1.0
    # Grounded sentences do not travel to the client; only the gaps do.
    assert report.to_dict()["sentences"] == []


def test_invented_answer_is_ungrounded_with_every_sentence_listed():
    answer = (
        "Hệ thống sao lưu lên Google Drive mỗi tuần và mã hóa bằng AES-256. "
        "Bạn có thể khôi phục bằng giao diện web trong mục Cài đặt nâng cao."
    )
    report = ag.grade_answer(answer, [SOURCE])
    assert report.label == "ungrounded"
    assert report.ungrounded == 2 and report.grounded == 0
    listed = report.to_dict()["sentences"]
    assert len(listed) == 2 and all(item["label"] == "ungrounded" for item in listed)


def test_one_invented_sentence_makes_the_whole_answer_ungrounded():
    answer = (
        "PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core. "
        "Ngoài ra hệ thống còn đồng bộ tự động lên đám mây Amazon S3 mỗi đêm để phòng cháy nổ."
    )
    report = ag.grade_answer(answer, [SOURCE])
    assert report.label == "ungrounded"
    assert report.grounded == 1 and report.ungrounded == 1
    assert report.grounded_ratio == 0.5
    assert [item["text"][:20] for item in report.to_dict()["sentences"]] == ["Ngoài ra hệ thống cò"]


def test_cross_language_answer_is_capped_at_weak_never_grounded_never_ungrounded():
    # T12 blind spot: a faithful English rendering of Vietnamese sources shares
    # almost no tokens. The safe verdict is "cannot judge" (weak + flag).
    answer = (
        "PostgreSQL is the single source of truth for the whole system. "
        "Qdrant is only an index and can be rebuilt from PostgreSQL. "
        "Backups run every 24 hours and are kept for 14 days."
    )
    report = ag.grade_answer(answer, [SOURCE])
    assert report.label == "weak"
    assert report.language_mismatch is True
    assert report.grounded == 0 and report.ungrounded == 0
    # Same-language invented text must NOT get the cross-language mercy.
    same_language = ag.grade_answer("Hệ thống sao lưu lên Google Drive mỗi tuần và mã hóa bằng AES-256.", [SOURCE])
    assert same_language.label == "ungrounded" and same_language.language_mismatch is False


def test_no_sources_means_unsupported_in_any_language():
    answer = "PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core và Qdrant chỉ là chỉ mục."
    report = ag.grade_answer(answer, [])
    assert report.label == "ungrounded" and report.language_mismatch is False


def test_pleasantries_and_short_fragments_are_not_judged():
    report = ag.grade_answer("Chào bạn! Tóm lại: đúng vậy.\n\nCảm ơn bạn đã hỏi, hy vọng câu trả lời hữu ích.", [SOURCE])
    assert report.label == "unjudged" and report.judged == 0
    assert ag.grade_answer("", [SOURCE]).label == "unjudged"


def test_verbatim_run_grounds_a_sentence_even_with_extra_words():
    # Four consecutive content words copied from the source outweigh padding
    # the source never said — the memory guard's "evidence verbatim" rule.
    answer = "Nói hơi dài dòng một chút nhưng theo cách tôi hiểu thì mất nó là mất hội thoại, tài liệu, version, job và citation đấy nhé."
    vocabulary, runs, indexed = ag._source_index([SOURCE])
    verdict, _ = ag.judge_sentence(answer, vocabulary, runs, indexed)
    assert verdict.overlap < ag.GROUNDED_MINIMUM  # padding alone would leave it below the bar
    assert verdict.verbatim is True and verdict.label == "grounded"


def test_markdown_bullets_and_numbering_are_split_into_sentences():
    answer = "- PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core\n1. Qdrant chỉ là chỉ mục và dựng lại được từ PostgreSQL\n## Tiêu đề"
    assert ag.split_sentences(answer)[:2] == [
        "PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core",
        "Qdrant chỉ là chỉ mục và dựng lại được từ PostgreSQL",
    ]


def test_sources_are_scored_on_bare_content_not_retrieval_context():
    # The adapter reads `content` only: a generated retrieval_context that
    # happens to contain the answer's words must not make it grounded.
    sources = [{"content": "Chu kỳ mặc định 24 giờ, giữ lại 14 ngày, tối thiểu luôn giữ 3 bản mới nhất.", "retrieval_context": "Tài liệu này mô tả sao lưu lên Google Drive mỗi tuần mã hóa AES-256 cài đặt nâng cao"}]
    report = ag.grade_rag_answer("Hệ thống sao lưu lên Google Drive mỗi tuần và mã hóa bằng AES-256 trong cài đặt nâng cao.", sources)
    assert report["label"] == "ungrounded"


# ── API surface ─────────────────────────────────────────────────────


def _fake_sources():
    return [{
        "document_id": "doc_1", "filename": "a.txt", "chunk_id": "chk_1", "chunk_index": 0, "index_version": 1,
        "score": 0.9, "excerpt": SOURCE[:120], "content": SOURCE, "extraction_method": "text", "locations": [],
    }]


def test_rag_chat_reports_grounding_in_both_response_shapes(client, mock_ollama, monkeypatch):
    service = client.app.state.rag_service
    monkeypatch.setattr(service, "_retrieve_context", lambda question, top_k, document_id: (_fake_sources(), "Context"))
    monkeypatch.setattr(
        "app.services.model_router.ModelRouter.chat",
        lambda self, mode, messages, **kwargs: ("Hệ thống sao lưu lên Google Drive mỗi tuần và mã hóa bằng AES-256 trong cài đặt nâng cao.", "fake-model"),
    )
    response = client.post("/rag/chat", json={"message": "Backup hoạt động thế nào?"})
    assert response.status_code == 200
    grounding = response.json()["grounding"]
    assert grounding["label"] == "ungrounded" and grounding["judged"] == 1
    assert grounding["sentences"][0]["label"] == "ungrounded"

    def fake_stream(self, mode, messages, **kwargs):
        return iter(["PostgreSQL là nguồn dữ liệu chuẩn duy nhất ", "của Local AI Core."]), "fake-model"

    monkeypatch.setattr("app.services.model_router.ModelRouter.stream_chat", fake_stream)
    with client.stream("POST", "/rag/chat", json={"message": "Nguồn dữ liệu chuẩn là gì?", "stream": True}) as stream:
        events = [block for block in stream.read().decode("utf-8").split("\n\n") if block.strip()]
    done = [block for block in events if block.startswith("event: done")]
    assert len(done) == 1
    payload = json.loads(done[0].split("data: ", 1)[1])
    # The whole streamed answer was graded once, after the last token.
    assert payload["grounding"]["label"] == "grounded" and payload["grounding"]["judged"] == 1


# ── Mixed-language source pool (21/08 heavy-machine hand-check, cases #6/#10) ──

# Real fixture text: two English chunks that sat in a pool with Vietnamese ones.
EN_LEGACY_POINTS = (
    "Points that only contain legacy `index_version` are deliberately ignored by retrieval. "
    "Cleanup planning and execution also exclude legacy Qdrant points; there is no "
    "`legacy-qdrant` cleanup domain. Legacy-point audit is a separate, read-only Phase 9A "
    "command and no automatic cleanup policy exists."
)
EN_RQ_WORKERS = (
    "When `INGESTION_EXECUTION_BACKEND=rq`, this document's extraction and indexing steps "
    "run in separate RQ worker processes rather than the FastAPI thread. Their state "
    "transitions, version activation, and retrieval semantics are unchanged."
)
VI_FILLER = [
    "Chu kỳ backup mặc định 24 giờ, giữ lại 14 ngày, tối thiểu luôn giữ 3 bản mới nhất.",
    "Xưởng in Ánh Dương nhận in offset và in kỹ thuật số, báo giá trong ngày làm việc.",
    SOURCE,
]


def test_faithful_vietnamese_rendering_of_an_english_chunk_in_a_mixed_pool_is_weak_not_ungrounded():
    # Case #6: the pool as a whole "looks Vietnamese", but the evidence chunk
    # for this sentence is English → the old pool-level cap never fired and
    # the faithful translation was called ungrounded.
    answer = (
        "Các point chỉ mang index_version cũ bị retrieval cố ý bỏ qua, và việc lập kế hoạch "
        "lẫn thực thi dọn dẹp cũng loại trừ các point Qdrant kiểu cũ; không có miền dọn dẹp riêng cho legacy-qdrant."
    )
    report = ag.grade_answer(answer, VI_FILLER + [EN_LEGACY_POINTS])
    assert report.ungrounded == 0
    assert report.language_mismatch is True
    assert report.label in {"weak", "grounded"}


def test_case_10_rq_workers_translation_is_flagged_as_cross_language():
    answer = "Khi bật chế độ rq, các bước trích xuất và index chạy trong các tiến trình worker RQ riêng thay vì luồng FastAPI; ngữ nghĩa truy hồi không đổi."
    report = ag.grade_answer(answer, VI_FILLER + [EN_RQ_WORKERS])
    assert report.ungrounded == 0 and report.language_mismatch is True


def test_invented_vietnamese_sentence_in_a_mixed_pool_stays_ungrounded():
    # The cap must not become a blanket excuse: an invented sentence that
    # shares nothing with the English chunk and nothing with the Vietnamese
    # ones is still unsupported.
    answer = "Hệ thống tự động gửi email cảnh báo cho quản trị viên qua SendGrid mỗi khi dung lượng ổ đĩa vượt 90 phần trăm."
    report = ag.grade_answer(answer, VI_FILLER + [EN_LEGACY_POINTS])
    assert report.label == "ungrounded" and report.language_mismatch is False


def test_invented_sentence_whose_few_shared_words_point_at_a_vietnamese_chunk_is_not_excused():
    # Shares "backup"/"ngày" with a Vietnamese chunk → evidence is Vietnamese →
    # same language → no mercy, even though an English chunk sits in the pool.
    answer = "Backup được tải lên Google Drive và Dropbox mỗi ngày kèm mã hóa AES-256 và thông báo qua Telegram."
    report = ag.grade_answer(answer, VI_FILLER + [EN_LEGACY_POINTS])
    assert report.label == "ungrounded" and report.language_mismatch is False
