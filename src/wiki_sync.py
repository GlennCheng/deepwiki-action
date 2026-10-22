#!/usr/bin/env python3
"""Keep a repository's .devin/wiki.json in sync with its structure.

Subcommands:
  check     Decide whether .devin/wiki.json is stale (writes stale=true|false
            to $GITHUB_OUTPUT when running in GitHub Actions).
  generate  Ask Claude for a page plan, validate it, and write
            .devin/wiki.json plus .devin/wiki-sync.lock.json.
  validate  Validate an existing .devin/wiki.json against DeepWiki's limits.

Staleness is decided by a "structure signature": a SHA-256 over the
directory layout (up to --depth levels), the contents of key files
(READMEs, manifests), the human-written notes, and the generator settings.
The signature of the inputs used for the last generation is stored in the
lock file, so CI runs that change nothing structural cost no API calls.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Bump when the prompt or output rules change, so every repo regenerates.
GENERATOR_VERSION = "deepwiki-wiki-sync/1"

WIKI_PATH = Path(".devin/wiki.json")
LOCK_PATH = Path(".devin/wiki-sync.lock.json")

# DeepWiki limits (https://docs.devin.ai/work-with-devin/deepwiki).
MAX_NOTE_CHARS = 10_000
MAX_TOTAL_NOTES = 100
DEFAULT_MAX_PAGES = 30

# Files whose content describes what the repo is: matched at the repo root,
# plus READMEs one level down.
KEY_FILE_PATTERNS = [
    "README*", "readme*", "ARCHITECTURE*", "CONTRIBUTING*",
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt",
    "go.mod", "Cargo.toml", "composer.json", "Gemfile", "pom.xml",
    "build.gradle", "build.gradle.kts", "settings.gradle*", "*.csproj", "*.sln",
    "docker-compose*.yml", "docker-compose*.yaml", "compose.yaml", "Dockerfile",
    "mkdocs.yml", "nx.json", "turbo.json", "pnpm-workspace.yaml", "lerna.json",
]
SUBDIR_KEY_PATTERNS = ["README*", "readme*"]
MAX_KEY_FILE_CHARS = 8_000
MAX_KEY_FILES = 40
MAX_TREE_LINES = 3_000

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"


class ValidationError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# ---------------------------------------------------------------- repo facts


def list_repo_files(repo: Path) -> list[str]:
    """Tracked files, excluding .devin/ (our own output must not feed back)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8", "replace")
    files = [f for f in out.split("\0") if f]
    return sorted(f for f in files if not f.startswith(".devin/"))


def directories(files: list[str], depth: int) -> list[str]:
    dirs: set[str] = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, min(len(parts), depth) + 1):
            dirs.add("/".join(parts[:i]))
    return sorted(dirs)


def select_key_files(files: list[str], extra_patterns: list[str]) -> list[str]:
    chosen: list[str] = []
    for f in files:
        parts = f.split("/")
        name = parts[-1]
        if len(parts) == 1 and any(fnmatch.fnmatch(name, p) for p in KEY_FILE_PATTERNS):
            chosen.append(f)
        elif len(parts) == 2 and any(fnmatch.fnmatch(name, p) for p in SUBDIR_KEY_PATTERNS):
            chosen.append(f)
        elif any(fnmatch.fnmatch(f, p) for p in extra_patterns):
            chosen.append(f)
    # Root files first, then by path; cap the count.
    chosen.sort(key=lambda p: (p.count("/"), p))
    return chosen[:MAX_KEY_FILES]


def read_text(repo: Path, rel: str, limit: int) -> tuple[str, bool]:
    path = repo / rel
    if not path.is_file():  # e.g. a submodule or a deleted-but-staged path
        return "", False
    text = path.read_bytes().decode("utf-8", "replace")
    if len(text) > limit:
        return text[:limit], True
    return text, False


@dataclass
class RepoSnapshot:
    files: list[str]
    dirs: list[str]
    key_files: dict[str, tuple[str, bool]]  # path -> (content, truncated)
    existing: dict | None
    existing_error: str | None = None
    settings: dict = field(default_factory=dict)


def load_existing(repo: Path) -> tuple[dict | None, str | None]:
    path = repo / WIKI_PATH
    if not path.exists():
        return None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"existing {WIKI_PATH} is not valid JSON: {e}"
    if not isinstance(doc, dict):
        return None, f"existing {WIKI_PATH} is not a JSON object"
    return doc, None


def snapshot(repo: Path, depth: int, extra_patterns: list[str], settings: dict) -> RepoSnapshot:
    files = list_repo_files(repo)
    keys = {
        rel: read_text(repo, rel, MAX_KEY_FILE_CHARS)
        for rel in select_key_files(files, extra_patterns)
    }
    existing, err = load_existing(repo)
    return RepoSnapshot(files, directories(files, depth), keys, existing, err, settings)


# ------------------------------------------------------------ notes & pins


def repo_notes(doc: dict | None) -> list[dict]:
    if not doc or not isinstance(doc.get("repo_notes"), list):
        return []
    return doc["repo_notes"]


def is_pinned(page: object) -> bool:
    """A page is pinned when at least one of its page_notes has real text.

    DeepWiki's own editor saves pages with `"page_notes": [{"content": ""}]`;
    those placeholders are not a maintainer's intent and must not pin a page.
    """
    if not isinstance(page, dict) or not isinstance(page.get("title"), str):
        return False
    notes = page.get("page_notes")
    if not isinstance(notes, list):
        return False
    return any(isinstance(n, dict) and isinstance(n.get("content"), str) and n["content"].strip()
               for n in notes)


def pinned_pages(doc: dict | None) -> list[dict]:
    """Pages that carry maintainer page_notes. Kept verbatim on regeneration."""
    if not doc or not isinstance(doc.get("pages"), list):
        return []
    return [p for p in doc["pages"] if is_pinned(p)]


def signature(snap: RepoSnapshot) -> str:
    h = hashlib.sha256()

    def feed(label: str, value) -> None:
        h.update(label.encode())
        h.update(b"\0")
        h.update(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())
        h.update(b"\0")

    feed("generator", GENERATOR_VERSION)
    feed("settings", snap.settings)
    feed("dirs", snap.dirs)
    feed("key_files", {
        p: hashlib.sha256(c.encode()).hexdigest() for p, (c, _) in snap.key_files.items()
    })
    feed("repo_notes", repo_notes(snap.existing))
    feed("pinned", pinned_pages(snap.existing))
    return h.hexdigest()


def is_stale(repo: Path, snap: RepoSnapshot) -> tuple[bool, str]:
    if not (repo / WIKI_PATH).exists():
        return True, f"{WIKI_PATH} does not exist"
    if snap.existing_error:
        return True, snap.existing_error
    lock_file = repo / LOCK_PATH
    if not lock_file.exists():
        return True, f"{LOCK_PATH} does not exist"
    try:
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, f"{LOCK_PATH} is not valid JSON"
    if not isinstance(lock, dict) or lock.get("inputs_sha256") != signature(snap):
        return True, "repository structure changed since the last generation"
    return False, "up to date"


# --------------------------------------------------------------- validation


def validate_wiki(doc: object, max_pages: int = DEFAULT_MAX_PAGES) -> None:
    problems: list[str] = []
    if not isinstance(doc, dict):
        raise ValidationError(["top level must be a JSON object"])

    notes = doc.get("repo_notes")
    if not isinstance(notes, list):
        problems.append("repo_notes must be an array (use [] when empty)")
        notes = []
    pages = doc.get("pages")
    if not isinstance(pages, list) or not pages:
        problems.append("pages must be a non-empty array")
        pages = []
    if len(pages) > max_pages:
        problems.append(f"{len(pages)} pages exceeds the limit of {max_pages}")

    total_notes = 0

    def check_note(where: str, note: object) -> None:
        nonlocal total_notes
        total_notes += 1
        if not isinstance(note, dict) or not isinstance(note.get("content"), str):
            problems.append(f"{where}: each note needs a string 'content'")
        elif len(note["content"]) > MAX_NOTE_CHARS:
            problems.append(f"{where}: note longer than {MAX_NOTE_CHARS} characters")

    for i, n in enumerate(notes):
        check_note(f"repo_notes[{i}]", n)

    titles: set[str] = set()
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            problems.append(f"pages[{i}] must be an object")
            continue
        title = p.get("title")
        if not isinstance(title, str) or not title.strip():
            problems.append(f"pages[{i}]: title must be a non-empty string")
        elif title in titles:
            problems.append(f"pages[{i}]: duplicate title {title!r}")
        else:
            titles.add(title)
        purpose = p.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            problems.append(f"pages[{i}]: purpose must be a non-empty string")
        pn = p.get("page_notes", [])
        if not isinstance(pn, list):
            problems.append(f"pages[{i}]: page_notes must be an array")
        else:
            for j, n in enumerate(pn):
                check_note(f"pages[{i}].page_notes[{j}]", n)

    if total_notes > MAX_TOTAL_NOTES:
        problems.append(f"{total_notes} notes exceeds the limit of {MAX_TOTAL_NOTES}")

    parents: dict[str, str] = {}
    for p in pages:
        if not isinstance(p, dict) or not isinstance(p.get("title"), str):
            continue
        parent = p.get("parent")
        if parent is None:
            continue
        if not isinstance(parent, str) or parent not in titles:
            problems.append(f"page {p['title']!r}: parent {parent!r} is not a page title")
        elif parent == p["title"]:
            problems.append(f"page {p['title']!r} is its own parent")
        else:
            parents[p["title"]] = parent
    reported: set[str] = set()
    for start in parents:
        seen, cur = [], start
        while cur in parents and cur not in seen:
            seen.append(cur)
            cur = parents[cur]
        if cur in seen and cur not in reported:
            cycle = seen[seen.index(cur):]
            reported.update(cycle)
            problems.append("parent cycle: " + " -> ".join(repr(t) for t in cycle + [cur]))

    if problems:
        raise ValidationError(problems)


# ------------------------------------------------------------------ prompt

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "purpose": {"type": "string"},
                    "parent": {"type": ["string", "null"]},
                },
                "required": ["title", "purpose", "parent"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["pages"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You plan the page structure of a DeepWiki for a code repository. DeepWiki \
reads .devin/wiki.json and writes exactly the pages listed there, so your \
plan decides what documentation engineers will get.

A good plan:
- Starts with an overview page, then covers architecture, each major \
subsystem or module, key data flows, configuration, build/deploy, and \
testing, as far as the repository actually has them.
- Gives every page a purpose that says what to document and names the \
concrete directories or files it covers, so the writer knows where to look.
- Uses parent to group detail pages under a section page. Parents must be \
titles from your own plan or the kept pages you are told about. Keep nesting \
shallow (two levels is usually enough).
- Only describes what the evidence shows. Do not invent components.
- Keeps existing page titles when they still fit, so the wiki stays stable \
across regenerations; rename, merge, split, or drop pages only when the \
repository's structure calls for it.

Return only the JSON object required by the output schema."""


def build_user_prompt(snap: RepoSnapshot, budget: int, language: str) -> str:
    parts: list[str] = [f"Plan at most {budget} pages. Write titles and purposes in {language}."]

    pins = pinned_pages(snap.existing)
    if pins:
        listing = "\n".join(
            f"- {p['title']!r} (parent: {p.get('parent')!r}): {p.get('purpose', '')}"
            for p in pins
        )
        parts.append(
            "These pages carry maintainer notes and will be kept as they are. Do not "
            "include them in your output, but you may use their titles as parent:\n"
            + listing
        )

    if snap.existing and isinstance(snap.existing.get("pages"), list):
        current = [
            {"title": p.get("title"), "purpose": p.get("purpose"), "parent": p.get("parent")}
            for p in snap.existing["pages"]
            if isinstance(p, dict) and not is_pinned(p)
        ]
        if current:
            parts.append(
                "Current plan (keep what still fits):\n"
                + json.dumps(current, ensure_ascii=False, indent=1)
            )

    notes = repo_notes(snap.existing)
    if notes:
        parts.append(
            "Repository notes written by the maintainers:\n"
            + "\n".join(f"- {n.get('content', '')}" for n in notes if isinstance(n, dict))
        )

    tree = snap.files
    if len(tree) > MAX_TREE_LINES:
        parts.append(
            f"File list ({len(tree)} files; only the first {MAX_TREE_LINES} paths are "
            f"shown, the directory list below covers the rest):\n"
            + "\n".join(tree[:MAX_TREE_LINES])
        )
    else:
        parts.append(f"File list ({len(tree)} files):\n" + "\n".join(tree))
    parts.append("Directories:\n" + "\n".join(snap.dirs))

    for path, (content, truncated) in snap.key_files.items():
        note = f" (first {MAX_KEY_FILE_CHARS} characters only)" if truncated else ""
        parts.append(f'<file path="{path}"{note}>\n{content}\n</file>')

    return "\n\n".join(parts)


# -------------------------------------------------------------- generation


def ask_claude(client, model: str, effort: str, system: str, prompt: str) -> dict:
    with client.beta.messages.stream(
        model=model,
        max_tokens=64_000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the request: {message.stop_details}")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("Claude's answer was cut off at max_tokens")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no text block in response (stop_reason={message.stop_reason})")
    return json.loads(text)


def assemble(plan: dict, snap: RepoSnapshot) -> dict:
    pins = pinned_pages(snap.existing)
    pin_titles = {p["title"] for p in pins}
    pages = list(pins)
    for p in plan.get("pages", []):
        if p.get("title") in pin_titles:
            continue  # the pinned version wins
        page = {"title": p["title"], "purpose": p["purpose"]}
        if p.get("parent"):
            page["parent"] = p["parent"]
        pages.append(page)
    return {"repo_notes": repo_notes(snap.existing), "pages": pages}


def generate(snap: RepoSnapshot, client, *, model: str, effort: str,
             max_pages: int, language: str, log=print) -> dict:
    pins = pinned_pages(snap.existing)
    budget = max_pages - len(pins)
    if budget < 1:
        raise RuntimeError(
            f"{len(pins)} pages with notes leave no room under the {max_pages}-page limit"
        )
    prompt = build_user_prompt(snap, budget, language)
    last_error: ValidationError | None = None
    for attempt in (1, 2):
        if last_error:
            prompt += (
                "\n\nYour previous plan was rejected:\n- "
                + "\n- ".join(last_error.problems)
                + "\nReturn a corrected plan."
            )
        doc = assemble(ask_claude(client, model, effort, SYSTEM_PROMPT, prompt), snap)
        try:
            validate_wiki(doc, max_pages)
            return doc
        except ValidationError as e:
            log(f"attempt {attempt}: plan rejected: {e}")
            last_error = e
    raise last_error


def write_outputs(repo: Path, doc: dict, sig: str, model: str) -> None:
    (repo / WIKI_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / WIKI_PATH).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lock = {"generator": GENERATOR_VERSION, "model": model, "inputs_sha256": sig}
    (repo / LOCK_PATH).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------- CLI


def set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def env_or(name: str, default: str) -> str:
    # Composite actions pass unset inputs as empty strings.
    return os.environ.get(name) or default


def main(argv: list[str] | None = None, client_factory=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "generate", "validate"])
    ap.add_argument("--repo", default=".", type=Path)
    ap.add_argument("--depth", type=int, default=int(env_or("WIKI_SYNC_DEPTH", "3")))
    ap.add_argument("--max-pages", type=int,
                    default=int(env_or("WIKI_SYNC_MAX_PAGES", str(DEFAULT_MAX_PAGES))))
    ap.add_argument("--language", default=env_or("WIKI_SYNC_LANGUAGE", "English"))
    ap.add_argument("--model", default=env_or("WIKI_SYNC_MODEL", DEFAULT_MODEL))
    ap.add_argument("--effort", default=env_or("WIKI_SYNC_EFFORT", DEFAULT_EFFORT),
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--extra-context", default=env_or("WIKI_SYNC_EXTRA_CONTEXT", ""),
                    help="comma-separated glob patterns of extra files to show Claude")
    ap.add_argument("--force", action="store_true", help="generate even when up to date")
    args = ap.parse_args(argv)

    repo = args.repo.resolve()
    if args.command == "validate":
        existing, err = load_existing(repo)
        if err or existing is None:
            print(err or f"{WIKI_PATH} not found", file=sys.stderr)
            return 1
        try:
            validate_wiki(existing, args.max_pages)
        except ValidationError as e:
            print("invalid:\n- " + "\n- ".join(e.problems), file=sys.stderr)
            return 1
        print("valid")
        return 0

    extra = [p.strip() for p in args.extra_context.split(",") if p.strip()]
    # Settings that shape the output are part of the signature. The model is
    # not, so switching models alone does not regenerate every repo.
    settings = {"depth": args.depth, "max_pages": args.max_pages,
                "language": args.language, "extra": extra}
    snap = snapshot(repo, args.depth, extra, settings)
    sig = signature(snap)
    stale, reason = is_stale(repo, snap)
    print(f"{'stale' if stale else 'fresh'}: {reason}")
    set_output("stale", "true" if stale else "false")
    set_output("signature", sig)

    if args.command == "check":
        return 0
    if not stale and not args.force:
        set_output("changed", "false")
        return 0

    if client_factory is None:
        import anthropic  # imported late so `check` runs without the SDK
        client_factory = anthropic.Anthropic

    doc = generate(snap, client_factory(), model=args.model, effort=args.effort,
                   max_pages=args.max_pages, language=args.language)
    wiki, lock = repo / WIKI_PATH, repo / LOCK_PATH
    before = (wiki.read_bytes() if wiki.exists() else None,
              lock.read_bytes() if lock.exists() else None)
    write_outputs(repo, doc, sig, args.model)
    changed = (wiki.read_bytes(), lock.read_bytes()) != before
    print(f"wrote {WIKI_PATH} with {len(doc['pages'])} pages")
    set_output("changed", "true" if changed else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
