"""The agent guide's standing instructions (ticket 10, 1a-v2).

1a (a long list of when to search) cut "did not search" failures but lost more
tasks than it rescued, mostly file-name citations. v2 changes one sentence. These
pin the wording's intent, not its effect: the effect is measured cold by the
Agent Eval runs recorded in the ticket.
"""
from app.services.agent_service import AGENT_GUIDE


def test_the_guide_says_to_look_things_up_without_asking_permission():
    assert "gọi công cụ phù hợp trước khi trả lời" in AGENT_GUIDE
    assert "đừng hỏi người dùng có muốn tra không, cứ tra" in AGENT_GUIDE


def test_the_citation_rule_holds_even_where_a_document_has_no_page():
    # Markdown and text documents have no page; "file and page" let the model skip both.
    assert "luôn nêu tên tệp (và số trang nếu có)" in AGENT_GUIDE


def test_the_guide_keeps_the_cases_that_need_no_tool():
    for exception in ("Câu chào hỏi", "kiến thức phổ thông", "không gọi gì"):
        assert exception in AGENT_GUIDE
