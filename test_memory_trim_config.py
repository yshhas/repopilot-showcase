"""Tests for REACT_MAX_CONTEXT_CHARS / REACT_KEEP_RECENT_ROUNDS config."""

import config.settings as settings


def test_default_config_values():
    """Default config: 40000 chars, 10 rounds."""
    assert settings.REACT_MAX_CONTEXT_CHARS == 40000
    assert settings.REACT_KEEP_RECENT_ROUNDS == 10


def test_max_context_chars_zero_disables_trim(monkeypatch):
    """REACT_MAX_CONTEXT_CHARS=0 → _trim_memory() is a no-op."""
    monkeypatch.setattr("react_agent.REACT_MAX_CONTEXT_CHARS", 0)

    from react_agent import _trim_memory

    memory = [
        {"role": "user", "content": "hello " * 1000},
        {"role": "assistant", "content": "world " * 1000},
        {"role": "user", "content": "more " * 1000},
    ]
    original = list(memory)
    _trim_memory(memory)
    assert memory == original  # no trimming when threshold is 0


def test_system_messages_always_preserved(monkeypatch):
    """System role messages are never trimmed."""
    monkeypatch.setattr("react_agent.REACT_MAX_CONTEXT_CHARS", 100)
    monkeypatch.setattr("react_agent.REACT_KEEP_RECENT_ROUNDS", 1)

    from react_agent import _trim_memory

    memory = [
        {"role": "system", "content": "you are a helpful assistant"},
        {"role": "user", "content": "old question " * 100},      # past round → removed
        {"role": "assistant", "content": "old answer " * 100},    # past round → removed
        {"role": "user", "content": "recent q " * 50},            # recent round → kept
        {"role": "assistant", "content": "recent a " * 50},       # recent round → kept
    ]
    _trim_memory(memory)

    # system message always preserved
    assert any(m["role"] == "system" for m in memory)
    # old messages removed
    assert not any("old question" in str(m.get("content", "")) for m in memory)
    # recent round kept (REACT_KEEP_RECENT_ROUNDS=1 → 2 non-system msgs)
    assert any("recent q" in str(m.get("content", "")) for m in memory)


def test_recent_n_rounds_preserved(monkeypatch):
    """Only the last N rounds of conversation are kept."""
    monkeypatch.setattr("react_agent.REACT_MAX_CONTEXT_CHARS", 200)
    monkeypatch.setattr("react_agent.REACT_KEEP_RECENT_ROUNDS", 2)  # keep 2 rounds = 4 msgs

    from react_agent import _trim_memory

    # Simulate 5 rounds of conversation (10 non-system messages)
    memory = []
    for i in range(1, 6):
        memory.append({"role": "user", "content": f"q{i} " * 20})
        memory.append({"role": "assistant", "content": f"a{i} " * 20})

    _trim_memory(memory)

    # Should have exactly 4 non-system messages (rounds 4 and 5)
    non_system = [m for m in memory if m["role"] != "system"]
    assert len(non_system) == 4
    # Round 1 (oldest) should be gone
    assert not any("q1" in str(m.get("content", "")) for m in non_system)
    assert not any("a1" in str(m.get("content", "")) for m in non_system)
    # Rounds 4 and 5 should be present
    assert any("q4" in str(m.get("content", "")) for m in non_system)
    assert any("q5" in str(m.get("content", "")) for m in non_system)


def test_old_messages_removed(monkeypatch):
    """Messages beyond the recent N rounds are removed."""
    monkeypatch.setattr("react_agent.REACT_MAX_CONTEXT_CHARS", 100)
    monkeypatch.setattr("react_agent.REACT_KEEP_RECENT_ROUNDS", 1)

    from react_agent import _trim_memory

    memory = [
        {"role": "user", "content": "round 1 q " * 50},
        {"role": "assistant", "content": "round 1 a " * 50},
        {"role": "user", "content": "round 2 q " * 50},
        {"role": "assistant", "content": "round 2 a " * 50},
        {"role": "user", "content": "round 3 q " * 50},
        {"role": "assistant", "content": "round 3 a " * 50},
    ]
    _trim_memory(memory)

    # Oldest rounds (1, 2) should be gone
    for m in memory:
        assert "round 1" not in str(m.get("content", ""))
        assert "round 2" not in str(m.get("content", ""))

    # Round 3 preserved
    assert any("round 3" in str(m.get("content", "")) for m in memory)
