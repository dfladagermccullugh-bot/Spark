"""code_generator's tool loop with the new model's response shape."""

import pytest

from spark.actions import code_generator as cg
from spark.core import llm
from spark.db.connection import init_db
from tests.helpers import FakeClient, response, text_block, thinking_block, tool_block


@pytest.fixture
def project(tmp_path, monkeypatch):
    init_db(tmp_path / "t.db")
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(
        cg, "build_project_context",
        lambda pid: {
            "project_name": "p", "local_path": str(proj), "file_tree": "", "key_files": {},
        },
    )
    return proj


def test_tool_loop_preserves_blocks_and_never_forces_tool_choice(project, monkeypatch):
    first = response(
        [thinking_block(), text_block("writing"),
         tool_block("write_file", {"path": "a.py", "content": "x=1"})],
        "tool_use",
    )
    second = response([thinking_block(), text_block("All done")], "end_turn")
    client = FakeClient(first, second)
    monkeypatch.setattr(llm, "make_client", lambda k: client)
    monkeypatch.setattr(cg, "make_client", lambda k: client)

    result = cg.generate_code("pid", "do it", "k", model="m")

    assert result.success and result.files_changed == ["a.py"]
    assert result.summary == "All done"
    assert (project / "a.py").read_text() == "x=1"
    for call in client.calls:
        assert "tool_choice" not in call and "temperature" not in call
        assert call["thinking"] == {"type": "between_tools"}
    # assistant content (incl. thinking block) passed back unchanged
    assistant_turn = client.calls[1]["messages"][1]
    assert assistant_turn["role"] == "assistant" and assistant_turn["content"] is first.content


def test_refusal_fails_loudly(project, monkeypatch):
    client = FakeClient(response([], "refusal"))
    monkeypatch.setattr(cg, "make_client", lambda k: client)
    result = cg.generate_code("pid", "do it", "k", model="m")
    assert not result.success
    assert "Claude call failed" in result.summary and "refusal" in result.summary


def test_cli_backend_not_supported(project):
    llm._config = llm.LLMConfig(backend="claude-cli")
    result = cg.generate_code("pid", "do it", "", model="m")
    assert not result.success and "not supported" in result.summary
