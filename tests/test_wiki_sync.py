import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import wiki_sync as ws  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    files = {
        "README.md": "# Shop\nAn online shop.",
        "package.json": '{"name": "shop"}',
        "src/api/orders.ts": "export {}",
        "src/web/App.tsx": "export {}",
        "src/web/README.md": "Web frontend",
        "docs/deep/a/b/c.md": "deep",
    }
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(tmp_path, "add", ".")
    return tmp_path


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Returns queued plans; records each request."""

    def __init__(self, *plans, stop_reason="end_turn"):
        self.plans = list(plans)
        self.calls = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        text = json.dumps(self.plans.pop(0))
        msg = SimpleNamespace(stop_reason=self.stop_reason, stop_details=None,
                              content=[SimpleNamespace(type="text", text=text)])
        return FakeStream(msg)


PLAN = {"pages": [
    {"title": "Overview", "purpose": "What the shop is (README.md)", "parent": None},
    {"title": "Orders API", "purpose": "src/api", "parent": "Overview"},
]}


def run(repo, *args, client=None):
    return ws.main(["generate" if client else "check", "--repo", str(repo), *args],
                   client_factory=(lambda: client) if client else None)


# ---------------------------------------------------------------- validation


def test_valid_document_passes():
    ws.validate_wiki({"repo_notes": [], "pages": [{"title": "A", "purpose": "x"}]})


@pytest.mark.parametrize("doc, fragment", [
    ({"pages": [{"title": "A", "purpose": "x"}]}, "repo_notes must be an array"),
    ({"repo_notes": [], "pages": []}, "non-empty"),
    ({"repo_notes": [], "pages": [{"title": "A", "purpose": "x"}, {"title": "A", "purpose": "y"}]},
     "duplicate title"),
    ({"repo_notes": [], "pages": [{"title": " ", "purpose": "x"}]}, "title must be"),
    ({"repo_notes": [], "pages": [{"title": "A", "purpose": ""}]}, "purpose must be"),
    ({"repo_notes": [], "pages": [{"title": "A", "purpose": "x", "parent": "Nope"}]},
     "is not a page title"),
    ({"repo_notes": [], "pages": [{"title": "A", "purpose": "x", "parent": "A"}]},
     "its own parent"),
    ({"repo_notes": [], "pages": [{"title": "A", "purpose": "x", "parent": "B"},
                                  {"title": "B", "purpose": "y", "parent": "A"}]},
     "parent cycle"),
    ({"repo_notes": [{"content": "x" * 10_001}], "pages": [{"title": "A", "purpose": "x"}]},
     "longer than"),
    ({"repo_notes": [{"content": "n"}] * 101, "pages": [{"title": "A", "purpose": "x"}]},
     "notes exceeds"),
])
def test_invalid_documents(doc, fragment):
    with pytest.raises(ws.ValidationError) as e:
        ws.validate_wiki(doc)
    assert any(fragment in p for p in e.value.problems), e.value.problems


def test_page_limit():
    pages = [{"title": f"P{i}", "purpose": "x"} for i in range(31)]
    with pytest.raises(ws.ValidationError):
        ws.validate_wiki({"repo_notes": [], "pages": pages})
    ws.validate_wiki({"repo_notes": [], "pages": pages}, max_pages=80)


# ------------------------------------------------------------------ snapshot


def test_snapshot_excludes_devin_and_limits_depth(repo):
    (repo / ".devin").mkdir()
    (repo / ".devin/wiki.json").write_text("{}")
    git(repo, "add", ".")
    snap = ws.snapshot(repo, 2, [], {})
    assert not any(f.startswith(".devin/") for f in snap.files)
    assert "docs/deep" in snap.dirs and "docs/deep/a" not in snap.dirs
    assert set(snap.key_files) == {"README.md", "package.json"}  # src/web/README.md is 3 deep


def test_untracked_files_are_ignored(repo):
    before = ws.signature(ws.snapshot(repo, 3, [], {}))
    (repo / "scratch").mkdir()
    (repo / "scratch/x.txt").write_text("x")
    assert ws.signature(ws.snapshot(repo, 3, [], {})) == before


# ---------------------------------------------------------- staleness/flow


def test_missing_wiki_is_stale(repo):
    snap = ws.snapshot(repo, 3, [], {})
    assert ws.is_stale(repo, snap) == (True, ".devin/wiki.json does not exist")


def test_generate_then_fresh_then_structure_change(repo):
    client = FakeClient(PLAN)
    assert run(repo, client=client) == 0
    doc = json.loads((repo / ".devin/wiki.json").read_text())
    assert doc == {"repo_notes": [], "pages": [
        {"title": "Overview", "purpose": "What the shop is (README.md)"},
        {"title": "Orders API", "purpose": "src/api", "parent": "Overview"},
    ]}
    git(repo, "add", ".")

    # Same structure: no API call.
    idle = FakeClient()
    assert run(repo, client=idle) == 0
    assert idle.calls == []

    # A new file in an existing directory is not structural.
    (repo / "src/api/refunds.ts").write_text("export {}")
    git(repo, "add", ".")
    assert run(repo, client=idle) == 0 and idle.calls == []

    # A new directory is.
    (repo / "src/payments").mkdir()
    (repo / "src/payments/stripe.ts").write_text("export {}")
    git(repo, "add", ".")
    again = FakeClient(PLAN)
    assert run(repo, client=again) == 0
    assert len(again.calls) == 1
    prompt = again.calls[0]["messages"][0]["content"]
    assert "src/payments" in prompt and "Current plan" in prompt


def test_readme_edit_is_structural(repo):
    run(repo, client=FakeClient(PLAN))
    git(repo, "add", ".")
    (repo / "README.md").write_text("# Shop\nNow also a marketplace.")
    snap = ws.snapshot(repo, 3, [], {"depth": 3, "max_pages": 30, "language": "English", "extra": []})
    assert ws.is_stale(repo, snap)[0]


def test_request_shape(repo):
    client = FakeClient(PLAN)
    run(repo, "--language", "繁體中文", client=client)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in call and "tool_choice" not in call
    assert "繁體中文" in call["messages"][0]["content"]


def test_notes_and_pinned_pages_survive(repo):
    (repo / ".devin").mkdir()
    (repo / ".devin/wiki.json").write_text(json.dumps({
        "repo_notes": [{"content": "Focus on billing.", "author": "Platform"}],
        "pages": [
            {"title": "Billing", "purpose": "billing/", "page_notes": [{"content": "Include retries."}]},
            {"title": "Old page", "purpose": "gone"},
        ],
    }))
    client = FakeClient({"pages": [
        {"title": "Billing", "purpose": "model tried to rewrite", "parent": None},
        {"title": "Retries", "purpose": "src/api retries", "parent": "Billing"},
    ]})
    run(repo, "--max-pages", "5", client=client)
    doc = json.loads((repo / ".devin/wiki.json").read_text())
    assert doc["repo_notes"] == [{"content": "Focus on billing.", "author": "Platform"}]
    assert doc["pages"][0] == {"title": "Billing", "purpose": "billing/",
                               "page_notes": [{"content": "Include retries."}]}
    assert [p["title"] for p in doc["pages"]] == ["Billing", "Retries"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "at most 4 pages" in prompt and "Focus on billing." in prompt
    # Pinned page is offered as context but not as part of the editable plan.
    assert '"Old page"' in prompt.split("Current plan")[1]

    # Regenerated output keeps the same signature, so the next run is idle.
    git(repo, "add", ".")
    idle = FakeClient()
    run(repo, "--max-pages", "5", client=idle)
    assert idle.calls == []


def test_blank_page_notes_do_not_pin(repo):
    # Shape seen in a real repo after edits in DeepWiki's own editor:
    # most pages carry an empty placeholder note.
    (repo / ".devin").mkdir()
    pages = [{"title": f"Page {i}", "purpose": "p", "page_notes": [{"content": ""}]}
             for i in range(26)]
    pages.append({"title": "Spaces", "purpose": "p", "page_notes": [{"content": "  \n"}]})
    pages.append({"title": "Kept", "purpose": "kept purpose",
                  "page_notes": [{"content": ""}, {"content": "Real note."}]})
    (repo / ".devin/wiki.json").write_text(json.dumps({"repo_notes": [], "pages": pages}))

    assert [p["title"] for p in ws.pinned_pages({"pages": pages})] == ["Kept"]

    client = FakeClient({"pages": [
        {"title": "Overview", "purpose": "o", "parent": None},
        {"title": "Page 0", "purpose": "re-planned", "parent": "Overview"},
    ]})
    run(repo, client=client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "at most 29 pages" in prompt
    current = prompt.split("Current plan")[1]
    assert '"Page 0"' in current and '"Spaces"' in current and '"Kept"' not in current

    doc = json.loads((repo / ".devin/wiki.json").read_text())
    assert doc["pages"][0] == pages[-1]  # the pinned page, verbatim
    assert doc["pages"][2] == {"title": "Page 0", "purpose": "re-planned", "parent": "Overview"}
    assert not any(p.get("page_notes") == [{"content": ""}] for p in doc["pages"])


def test_malformed_page_notes_do_not_pin():
    for notes in (None, "text", [], ["text"], [{"content": 3}], [{}]):
        assert not ws.is_pinned({"title": "A", "purpose": "p", "page_notes": notes})
    assert not ws.is_pinned({"purpose": "p", "page_notes": [{"content": "x"}]})


def test_invalid_plan_is_retried_with_feedback(repo):
    bad = {"pages": [{"title": "A", "purpose": "x", "parent": "Missing"}]}
    client = FakeClient(bad, PLAN)
    assert run(repo, client=client) == 0
    assert len(client.calls) == 2
    assert "previous plan was rejected" in client.calls[1]["messages"][0]["content"]


def test_two_invalid_plans_fail_without_writing(repo):
    bad = {"pages": []}
    with pytest.raises(ws.ValidationError):
        run(repo, client=FakeClient(bad, bad))
    assert not (repo / ".devin/wiki.json").exists()


def test_refusal_raises(repo):
    with pytest.raises(RuntimeError, match="declined"):
        run(repo, client=FakeClient(PLAN, stop_reason="refusal"))


def test_settings_change_makes_stale(repo):
    run(repo, client=FakeClient(PLAN))
    git(repo, "add", ".")
    idle = FakeClient()
    run(repo, client=idle)
    assert idle.calls == []
    changed = FakeClient(PLAN)
    run(repo, "--language", "日本語", client=changed)
    assert len(changed.calls) == 1


def test_corrupt_wiki_is_stale(repo):
    (repo / ".devin").mkdir()
    (repo / ".devin/wiki.json").write_text("{not json")
    snap = ws.snapshot(repo, 3, [], {})
    stale, reason = ws.is_stale(repo, snap)
    assert stale and "not valid JSON" in reason


def test_github_output(repo, tmp_path, monkeypatch):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    run(repo)
    text = out.read_text()
    assert "stale=true" in text and "signature=" in text


def test_validate_command(repo, capsys):
    assert ws.main(["validate", "--repo", str(repo)]) == 1
    run(repo, client=FakeClient(PLAN))
    assert ws.main(["validate", "--repo", str(repo)]) == 0
