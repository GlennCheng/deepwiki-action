"""Run the git scripts against a local bare remote with a stub `gh`."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def sh(cwd, *args, env=None, check=True):
    r = subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode:
        pytest.fail(f"{args} exited {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    return r


@pytest.fixture
def setup(tmp_path):
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(work))
    sh(work, "git", "config", "user.name", "t")
    sh(work, "git", "config", "user.email", "t@t")
    (work / "README.md").write_text("hi")
    sh(work, "git", "add", ".")
    sh(work, "git", "commit", "-qm", "init")
    sh(work, "git", "push", "-q", "origin", "main")
    sh(work, "git", "push", "-q", "origin", "main:feature")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env bash
echo "$@" >> {log}
if [ "$1 $2" = "pr list" ]; then cat {tmp_path}/gh_list 2>/dev/null || true; fi
""")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_TOKEN": "x"}
    return work, remote, env, log, tmp_path


def write_devin(work, content='{"pages": []}'):
    (work / ".devin").mkdir(exist_ok=True)
    (work / ".devin/wiki.json").write_text(content)
    (work / ".devin/wiki-sync.lock.json").write_text('{"inputs_sha256": "abc"}')


def remote_files(remote, ref):
    return sh(remote, "git", "ls-tree", "-r", "--name-only", ref).stdout.split()


def test_commit_to_pr_pushes_to_head_branch(setup):
    work, remote, env, _, _ = setup
    sh(work, "git", "checkout", "-q", "feature")
    write_devin(work)
    r = sh(work, "bash", str(SCRIPTS / "commit_to_pr.sh"), env={**env, "HEAD_REF": "feature"})
    assert "Pushed" in r.stdout
    assert ".devin/wiki.json" in remote_files(remote, "feature")
    assert ".devin/wiki.json" not in remote_files(remote, "main")


def test_commit_to_pr_no_changes(setup):
    work, _, env, _, _ = setup
    r = sh(work, "bash", str(SCRIPTS / "commit_to_pr.sh"), env={**env, "HEAD_REF": "feature"})
    assert "No changes" in r.stdout


def test_commit_to_pr_lost_race_is_a_warning(setup):
    work, remote, env, _, tmp = setup
    sh(work, "git", "checkout", "-q", "feature")
    # Someone else pushes to the PR branch meanwhile.
    other = tmp / "other"
    sh(tmp, "git", "clone", "-q", "-b", "feature", str(remote), str(other))
    (other / "x.txt").write_text("x")
    sh(other, "git", "add", ".")
    sh(other, "git", "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-qm", "x")
    sh(other, "git", "push", "-q", "origin", "feature")

    write_devin(work)
    r = sh(work, "bash", str(SCRIPTS / "commit_to_pr.sh"), env={**env, "HEAD_REF": "feature"})
    assert r.returncode == 0 and "::warning::" in r.stdout


def test_followup_pr_created_then_reused(setup):
    work, remote, env, log, tmp = setup
    write_devin(work)
    r = sh(work, "bash", str(SCRIPTS / "open_followup_pr.sh"), env={**env, "BASE_BRANCH": "main"})
    assert r.returncode == 0, r.stderr
    assert ".devin/wiki.json" in remote_files(remote, "deepwiki-wiki-sync/main")
    assert ".devin/wiki.json" not in remote_files(remote, "main")
    calls = log.read_text()
    assert "pr create --base main --head deepwiki-wiki-sync/main" in calls

    # main moves on (another PR merged), and the next run is stale again
    # while the follow-up PR is still open: add a commit, no new PR.
    (tmp / "gh_list").write_text("7\n")
    sh(work, "git", "checkout", "-q", "main")
    (work / "new.txt").write_text("n")
    sh(work, "git", "add", "new.txt")
    sh(work, "git", "commit", "-qm", "another merge")
    sh(work, "git", "push", "-q", "origin", "main")
    write_devin(work, '{"pages": [1]}')
    r = sh(work, "bash", str(SCRIPTS / "open_followup_pr.sh"), env={**env, "BASE_BRANCH": "main"})
    assert "Updated existing pull request #7" in r.stdout
    assert log.read_text().count("pr create") == 1
    shown = sh(remote, "git", "show", "deepwiki-wiki-sync/main:.devin/wiki.json").stdout
    assert shown == '{"pages": [1]}'
    # Plain fast-forward push: history of the sync branch is kept.
    assert sh(remote, "git", "rev-list", "--count", "deepwiki-wiki-sync/main").stdout.strip() == "3"
    # The PR diff is only the .devin files although its base is older.
    diff = sh(remote, "git", "diff", "--name-only", "main...deepwiki-wiki-sync/main").stdout.split()
    assert diff == [".devin/wiki-sync.lock.json", ".devin/wiki.json"]

    # Same content again: nothing is pushed.
    sh(work, "git", "checkout", "-q", "main")
    write_devin(work, '{"pages": [1]}')
    r = sh(work, "bash", str(SCRIPTS / "open_followup_pr.sh"), env={**env, "BASE_BRANCH": "main"})
    assert "already holds this update" in r.stdout
    assert sh(remote, "git", "rev-list", "--count", "deepwiki-wiki-sync/main").stdout.strip() == "3"
