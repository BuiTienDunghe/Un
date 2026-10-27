"""The agent guide's standing instructions (ticket 10, change 1a).

Agent Eval v0.1/v0.2 measured the model answering questions about the user's own
system from general knowledge; the guide now makes looking it up the default.
These pin the wording's intent, not its effect: the effect is measured by the
Agent Eval runs recorded in the ticket.
"""
from app.services.agent_service import AGENT_GUIDE


def test_the_guide_makes_looking_it_up_the_default_for_questions_about_the_users_system():
    assert "tra `search_documents` trước" in AGENT_GUIDE
    assert "Đừng hỏi người dùng có muốn tra không" in AGENT_GUIDE
    assert "gọi `system_status`" in AGENT_GUIDE


def test_the_guide_keeps_the_cases_that_need_no_tool():
    # nt-01..03 (greeting, general knowledge, writing) and doc-17/18 (already in the turn).
    for exception in ("chào hỏi", "kiến thức", "có sẵn trong câu hỏi hay các lượt"):
        assert exception in AGENT_GUIDE
