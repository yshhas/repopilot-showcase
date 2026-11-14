from react_agent import react_agent


def test_react_agent_stops_at_max_steps(monkeypatch):

    calls = {"count": 0}


    def fake_ask_ai(memory, agent_mode=None):

        calls["count"] += 1

        return (
            '{"action": "git_status", "args": {}}'
        )


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    monkeypatch.setattr(
        "react_agent.run_tool",
        lambda action, args: "ok",
    )

    answer, memory = react_agent(
        "loop test",
        max_steps=3,
    )

    assert "已达到最大 ReAct 步数" in answer

    assert "(3)" in answer

    assert calls["count"] == 3


def test_react_agent_finishes_before_max_steps(monkeypatch):

    calls = {"count": 0}


    def fake_ask_ai(memory, agent_mode=None):

        calls["count"] += 1

        if calls["count"] == 1:

            return '{"action": "git_status", "args": {}}'

        return '{"action": "finish", "answer": "done"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    monkeypatch.setattr(
        "react_agent.run_tool",
        lambda action, args: "status ok",
    )

    answer, memory = react_agent(
        "finish test",
        max_steps=5,
    )

    assert answer == "done"

    assert calls["count"] == 2
