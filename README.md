# deepwiki-action

**English** | [繁體中文](README.zh-TW.md)

A GitHub Action that keeps a repository's `.devin/wiki.json` in step with its code structure.

## What it does and why

When [DeepWiki](https://docs.devin.ai/work-with-devin/deepwiki) generates a wiki and finds `.devin/wiki.json` at the repository root, it creates **only** the pages listed there. The file is written by hand, so it drifts as the code changes: new modules get no page, and removed features keep theirs.

This Action uses Claude to read the repository structure during pull requests, re-plans the page list, and writes it back to `.devin/wiki.json`.

## How it works

```
PR opened against the target branch ──► Structure changed? ──no──► done (no API call, no cost)
                                          │yes
                                          ▼
                       Claude plans pages → format check → commit onto the PR's source branch
```

- The wiki.json update merges into the target branch together with your PR. For example, when develop has a PR into main, the update is committed straight onto develop and shows up in **that same PR**; no separate PR is opened.
- Every run first computes a "structure signature". If the structure has not changed, the run ends there, with **no Claude API call and no cost**. Most feature PRs fall into this case.
- If a PR is merged before the Action finishes (usually 1–2 minutes), the update is picked up by the next PR into the target branch.
- To have it caught up right after the merge instead, enable the [optional follow-up PR](#optional-open-a-follow-up-pr-after-merges).

---

## Installation

Do every step below in the **repository you want to cover**, not in this Action's repository. It takes about 10 minutes.

### Before you start

| Requirement | How to check |
|---|---|
| The repository can use this Action | If this Action's repository is private, only repositories with the **same owner** (the same user or organization) can use it (see the first row of "Troubleshooting"). |
| You have **Admin** permission on it | Open the repository page; the tab bar at the top must show **⚙ Settings** on the far right. If it does not, ask a repository admin to grant access or to do step 1 for you. |
| You have an Anthropic API key | See step 0. |
| You know the target branch | The branch PRs merge into, usually `main`, sometimes `master`. Check the branch drop-down at the top left of the repository page.<br>**For a flow where features go into develop and a release PR merges develop into main, use `main` as the target**: the Action runs on the release PR and commits the update onto develop, which then goes into main with the release. |

---

### Step 0: Get an Anthropic API key

The Action uses this key to call Claude; usage is billed to the Anthropic account that owns it.

1. First ask whoever manages your team's Anthropic account whether a key for CI already exists. If so, use it and skip to step 1.
2. To create one yourself, sign in to the [Claude Console](https://console.anthropic.com/) in a browser.
3. Open the **API keys** page and click **Create Key**.
4. Give it a recognizable name, such as `github-deepwiki-sync`, and create it.
5. **Copy the key right away** (it starts with `sk-ant-`). Once you close that screen, the full key is not shown again.
6. Keep it somewhere safe for the next step. Do not paste it into code, issues, or chat.

---

### Step 1: Store the API key as a repository secret

A secret is where GitHub keeps sensitive values. Once saved, nobody, including you, can read it back; only running workflows can.

**In the browser:**

1. On the repository page, click **⚙ Settings** at the far right of the tab bar.
2. In the left sidebar, scroll to the **Security** group, expand **Secrets and variables**, and click **Actions**.
3. The page has two tabs, **Secrets** and **Variables**; make sure **Secrets** is selected.
4. Under **Repository secrets**, click the green **New repository secret** button.
5. Fill in:
   - **Name**: `ANTHROPIC_API_KEY` (exactly this, in capitals)
   - **Secret**: the key from step 0
6. Click **Add secret**.
7. Back in the list, `ANTHROPIC_API_KEY` should appear with the time it was just updated.

**Or from the command line** (requires the [GitHub CLI](https://cli.github.com/) and `gh auth login`):

```bash
gh secret set ANTHROPIC_API_KEY -R <owner>/<repo>
# paste the key when you see "? Paste your secret", then press Enter
```

> **Can I use an organization secret instead?** On paid plans you can set it once for the organization and share it with several repositories. On the GitHub Free plan, organization secrets are not shared with private repositories, so each repository needs its own.

---

### Step 2: Add the workflow file

The workflow file tells GitHub when to run which Action. It must live in the repository's `.github/workflows/` folder.

**Prepare the content** (change `main` to your target branch; you can list several, such as `[main, release]`):

```yaml
name: DeepWiki wiki.json sync

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]          # ← your target branch(es)

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: deepwiki-wiki-sync-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  sync:
    if: github.event_name != 'pull_request' || !github.event.pull_request.draft
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: GlennCheng/deepwiki-action@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          # language: English      ← remove the leading # to set the page language
```

The same file is in [`examples/deepwiki-wiki-sync.yml`](examples/deepwiki-wiki-sync.yml).

What each part does:

| Section | Purpose |
|---|---|
| `on.pull_request` | Runs when a PR into the target branch is opened, gets new commits, is reopened, or moves from draft to ready |
| `permissions` | Lets the Action commit onto the PR's source branch |
| `concurrency` | When a PR gets several pushes in a row, cancels the older run so two runs never race to commit |
| `if: ... draft` | Skips draft PRs; runs once the PR is marked Ready for review |
| `with:` | Settings for the Action; see "Settings" for what you can add |

**Option A: create it on the GitHub website (no clone needed)**

1. Go to the repository's home page (the **<> Code** tab).
2. Above the file list, click **Add file** → **Create new file**.
3. In the file name box, type `.github/workflows/deepwiki-wiki-sync.yml`. Each `/` you type turns the text before it into a folder; that is expected.
4. Paste the content into the editor.
5. Click the green **Commit changes...** button at the top right.
6. In the dialog:
   - set **Commit message** to something like `ci: add DeepWiki wiki.json sync`;
   - choose **Create a new branch for this commit and start a pull request** (the only choice if the branch is protected, and easier to review);
   - click **Propose changes**.
7. On the "Open a pull request" page, check the base branch and click **Create pull request**.
   - Usual flow: set the base to the target branch (for example `main`).
   - develop → main flow: set the base to `develop`, like any other feature; it reaches main with the next release.

**Option B: with git on your machine**

```bash
git checkout -b ci/deepwiki-wiki-sync
mkdir -p .github/workflows
# save the content above as .github/workflows/deepwiki-wiki-sync.yml
git add .github/workflows/deepwiki-wiki-sync.yml
git commit -m "ci: add DeepWiki wiki.json sync"
git push -u origin ci/deepwiki-wiki-sync
gh pr create --base main --fill       # use --base develop for a develop -> main flow
```

---

### Step 3: Check that the first run succeeds

The first run happens on the **first PR into the target branch**:

- Usual flow: the PR from step 2 triggers it.
- develop → main flow: the PR from step 2 goes into develop and does not trigger it. The first run happens when the next release PR (develop → main) is opened, and the update is committed onto develop. Do the checks below on that release PR.

If the repository has no `.devin/wiki.json` yet, the first run creates the first version.

1. In the checks box at the bottom of the PR page, **DeepWiki wiki.json sync / sync (pull_request)** shows as running (yellow dot). It usually finishes in 1–3 minutes.
2. To watch it, click **Details** next to it and expand the steps under **Run GlennCheng/deepwiki-action@v1**. A successful run prints something like:

   ```
   stale: .devin/wiki.json does not exist
   wrote .devin/wiki.json with 18 pages
   Pushed the updated wiki.json to ci/deepwiki-wiki-sync.
   ```

   The branch in the last line is the PR's source branch (`develop` for a release PR).
3. The PR's **Commits** tab gains a `chore(deepwiki): update .devin/wiki.json` commit by `github-actions[bot]`.
4. Open `.devin/wiki.json` in the **Files changed** tab:
   - each page has a `title` and a `purpose` (what the page should cover);
   - pages with a `parent` are sub-pages.
   If you want changes, edit it right there (see "Adjusting pages").
5. Merge the PR once it looks right and the checks have finished (green tick).

**If the check shows a red cross:** click **Details** to read the error and look it up under "Troubleshooting" below. The most common cause is a misspelled secret name in step 1.

> **Note:** the Action adds a commit to the PR's source branch. Anyone who keeps working on that branch locally should `git pull` before pushing.

---

### Step 4: Have DeepWiki apply the new page plan

DeepWiki reads `.devin/wiki.json` **when it generates the wiki**. Its documentation says to commit the file and regenerate the wiki, and does not say that a commit triggers this, so regenerate manually after merging:

1. Sign in to Devin and open **Wiki** from the left sidebar ([app.devin.ai/wiki](https://app.devin.ai/wiki)).
2. Open this repository's wiki page and regenerate it.
3. When it finishes, the wiki's page list should match `.devin/wiki.json`.

> The documentation does not say exactly where the regenerate control is. If you cannot find it, ask whoever manages the Devin account.

---

### Installation checklist

- [ ] `ANTHROPIC_API_KEY` is listed under the repository's **Settings → Secrets and variables → Actions**
- [ ] `.github/workflows/deepwiki-wiki-sync.yml` is on the target branch
- [ ] `.devin/wiki.json` and `.devin/wiki-sync.lock.json` are on the target branch
- [ ] If the target branch has required checks, `push-token` is set (see "Required checks")
- [ ] The wiki has been regenerated in DeepWiki

From then on there is nothing to look after: whenever a PR changes the structure, wiki.json is updated with it.

---

## Day-to-day use

### What developers need to do

Very little. Two things to know:

1. **After the Action pushes a commit, `git pull` before you push again.** Otherwise your push is rejected (non-fast-forward).
2. **Glance at the `.devin/wiki.json` diff.** If the plan is off, edit it in the PR (see "Adjusting pages").

### What triggers a re-plan

Claude is called only when the *structure* changes:

| Change | Re-plans? |
|---|---|
| Adding or removing directories (down to depth 3 by default) | Yes |
| Editing a root README, ARCHITECTURE, or CONTRIBUTING | Yes |
| Editing `package.json`, `pyproject.toml`, `go.mod`, `composer.json`, a Dockerfile, compose files, and similar | Yes |
| Editing a README one level down (e.g. `api/README.md`) | Yes |
| Editing `repo_notes`, or adding, editing, or unpinning a pinned page (see "Pinning pages") | Yes |
| Changing Action settings (`language`, `max-pages`, `depth`, `extra-context`) | Yes |
| Adding or editing files inside existing directories | No |
| Changing files that git does not track | No |

The basis for this decision is stored in `.devin/wiki-sync.lock.json`. **Commit it along with wiki.json and do not edit it by hand.**

### Adjusting pages

- **Add repository-wide guidance** with a `repo_notes` entry. It is kept verbatim, and Claude reads it.

  ```json
  "repo_notes": [
    { "content": "payments/ is the core; document the refund flow in detail.", "author": "Platform Team" }
  ]
  ```

- **Keep a page exactly as it is**: see "Pinning pages" below.

- **All other pages** belong to Claude, which reads the current list and keeps existing titles where they still fit. You can edit them by hand, but the next structural change may adjust them.

### Pinning pages

The Action keeps pinned pages **exactly as they are** every time it re-plans; Claude plans only the rest. Pin pages written for a particular audience or in a particular way.

**How to pin:** in `.devin/wiki.json`, give the page a `page_notes` array with **at least one note that has text**.

```json
{
  "title": "Webhook Handling",
  "purpose": "How payments/webhooks receives and processes payment notifications",
  "parent": "Payments",
  "page_notes": [
    { "content": "Cover retries and idempotency, and add troubleshooting steps for failures." }
  ]
}
```

`page_notes` are also instructions to DeepWiki, which follows them when it writes that page. Write them as "how to write this page": who reads it, what to include, in what order.

**What counts as pinned:**

| `page_notes` | Pinned? |
|---|---|
| `[{ "content": "Include retry behavior." }]` | Yes |
| `[{ "content": "" }, { "content": "a note with text" }]` | Yes (one note with text is enough) |
| `[{ "content": "" }]` or `[{ "content": "   " }]` | **No** |
| `[]`, or no `page_notes` at all | No |

> **Why blank notes don't count:** after wiki.json is edited or updated through Devin, pages can be left with blank notes such as `"page_notes": [{ "content": "" }]`. That does not mean anyone wanted those pages fixed, so they are not pinned.

**What pinning does:**

- The title, `purpose`, `parent`, and `page_notes` are never changed, and the page is never removed.
- Pinned pages always come first in the page list, in their original order.
- Pinned pages count toward the page limit. With a limit of 30 and 3 pinned pages, Claude can plan at most 27.
- If a pinned page's `parent` is an unpinned page, Claude must keep that parent or its plan is sent back. Pinning the parent too is safest.

**How to unpin:** delete the page's `page_notes`, or empty the note text, and commit. On the next run Claude re-plans that page and may rewrite or remove it.

**Don't pin too much:** the more pages you pin, the fewer Claude can plan. When pins fill the limit, a new module has no room, the plan is sent back, and the job fails. Pin only pages that really need a particular treatment.

**Listing pinned pages:** run this locally (after the setup under "Maintaining this Action"):

```bash
python3 -c "import json,sys; sys.path.insert(0,'src'); import wiki_sync as w; \
d=json.load(open('/path/to/repo/.devin/wiki.json')); print([p['title'] for p in w.pinned_pages(d)])"
```

### Forcing a re-plan

Delete `.devin/wiki-sync.lock.json` in a PR and push. The Action treats the file as stale and re-plans.

---

## Optional: open a follow-up PR after merges

With the default setup, if a PR is merged before the Action finishes, the update waits for the next PR. To catch up right after the merge instead, add this optional setup: after a PR merges into the target branch the Action checks again, and if the file is still stale it **opens a separate PR straight into the target branch** (titled `chore(deepwiki): update .devin/wiki.json`) for you to review and merge.

### Which flows it suits

| Flow | Recommendation |
|---|---|
| Feature branches merge straight into main | Fine to enable |
| Features go into develop, and a release PR merges develop into main | **Do not enable** |

It does not suit a develop → main flow because the follow-up PR **bypasses develop and merges straight into main**:

1. Once the follow-up PR merges, main has commits develop lacks, and the two diverge;
2. when the next release PR is opened, the Action generates another version from develop's structure and commits it onto develop;
3. main and develop each hold a different `.devin/wiki.json`, so the release PR and any "merge main back into develop" PR conflict on those two files and need manual resolution.

> **What about making develop the target branch?** That also avoids the divergence, but makes more Claude API calls: every feature PR that changes the structure calls it once. Keeping main as the target and running only on PRs calls it at most once per release.

### How to enable it

**1. Allow GitHub Actions to open pull requests**

The Action opens the follow-up PR itself, which needs this permission.

In the browser:

1. In the repository's **⚙ Settings**.
2. In the left sidebar, under the **Code and automation** group, expand **Actions** and click **General**.
3. Scroll to the bottom of the page to the **Workflow permissions** section.
4. **Leave** the two options at the top, **Read and write permissions** and **Read repository contents and packages permissions**, as they are; the workflow file declares the permissions it needs.
5. Tick **Allow GitHub Actions to create and approve pull requests**.
6. Click **Save** below that section.

**If the checkbox is greyed out:** the organization has turned the option off. Ask an organization owner to open the organization's **Settings → Actions → General** (`https://github.com/organizations/<org-name>/settings/actions`), tick the same option under **Workflow permissions**, and save; then tick it in the repository.

Or from the command line (changes only this one setting):

```bash
gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow \
  -F can_approve_pull_request_reviews=true
```

**2. Add `push` and `workflow_dispatch` to the workflow**

Replace the `on:` block from step 2 with the following (keep both `main` entries in step):

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]          # ← your target branch(es)
  push:
    branches: [main]          # ← keep in step with the list above
  workflow_dispatch:
```

The full file is in [`examples/deepwiki-wiki-sync.with-followup.yml`](examples/deepwiki-wiki-sync.with-followup.yml).

### What happens once it is enabled

- The Action runs once more after each merge into the target branch. If the structure signature matches, it stops without calling the API; only if the file is still stale does it re-plan and open a follow-up PR.
- Follow-up PRs use a fixed branch (by default `deepwiki-wiki-sync/<target branch>`; change it with `sync-branch`). Only one follow-up PR is open at a time; later updates are added to the same PR instead of opening new ones.
- The follow-up PR itself does not trigger the Action, and the run after it merges finds a matching signature, so nothing loops.
- You can also run it by hand: **Actions → DeepWiki wiki.json sync → Run workflow**, then pick a branch. If the file is stale, it opens a follow-up PR.

---

## Settings

Set these under `with:` in the workflow.

| Input | Default | Description |
|---|---|---|
| `anthropic-api-key` | (required) | Anthropic API key |
| `language` | `English` | Language for page titles and purposes, e.g. `繁體中文` |
| `max-pages` | `30` | Page limit; `80` on DeepWiki enterprise plans |
| `depth` | `3` | How deep a directory change counts as structural |
| `extra-context` | empty | Extra files for Claude to read, as comma-separated globs, e.g. `docs/*.md,src/*/index.ts` |
| `model` | `claude-opus-5-5` | Claude model |
| `effort` | `medium` | Claude effort: `low`, `medium`, `high`, `xhigh`, `max` |
| `push-token` | empty | See "Required checks" below |
| `github-token` | `github.token` | Rarely needs changing |
| `sync-branch` | `deepwiki-wiki-sync/<target branch>` | Branch used for follow-up PRs (only matters when follow-up PRs are enabled) |

Outputs: `stale` (whether the file was out of date when the run started) and `changed` (whether a new file was written).

### Required checks (read this if the target branch has them)

To prevent infinite loops, GitHub does **not trigger other workflows** for commits pushed and PRs opened with the default `GITHUB_TOKEN`. If the target branch has required status checks:

- the commit the Action pushes onto a PR runs no CI, so the PR waits on checks forever;
- if follow-up PRs are enabled, the same happens to them.

Use a PAT or a GitHub App token instead:

1. Create a fine-grained PAT (or a GitHub App) with **Contents: Read and write** and **Pull requests: Read and write**, scoped to the repository.
2. Store it as a repository secret, e.g. `DEEPWIKI_SYNC_TOKEN`.
3. Add `push-token: ${{ secrets.DEEPWIKI_SYNC_TOKEN }}` under `with:` in the workflow.

Pushes then trigger CI as usual. The Action runs once more as well, but the structure signature already matches, so it makes no API call and does not loop.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Unable to resolve action GlennCheng/deepwiki-action@v1, repository not found` | This Action's repository is not shared with your repository. For a private Action repository, open its **Settings → Actions → General → Access** and choose the option that shares it with repositories of the same owner ("Accessible from repositories owned by the user …" or "… in the … organization"); only those repositories can use it. |
| `anthropic-api-key is empty` | The `ANTHROPIC_API_KEY` secret is missing or named differently. |
| `GitHub Actions is not permitted to create or approve pull requests` | Follow-up PRs are enabled but "Allow GitHub Actions to open pull requests" was not done. |
| Warning `Could not push to <branch>` | The PR branch moved or was merged while the Action was pushing. Not a failure; the next run catches up. |
| No run on PRs from forks | Skipped on purpose: forks get no secrets and cannot push. The next non-fork PR catches up. |
| No run on draft PRs | The example workflow skips drafts on purpose; it runs once the PR is marked Ready for review. |
| Job fails after `plan rejected` | Claude's plan broke DeepWiki's format limits twice in a row, so nothing was written. A re-run usually passes; if it keeps happening, pin fewer pages or raise `max-pages`. |
| `Claude declined the request` | Anthropic's safeguards declined the request and the fallback model did not complete it either. Check whether the repository holds content likely to trigger them. |
| PR stuck waiting on checks | See "Required checks" above. |
| main has `chore(deepwiki)` commits that develop lacks | Follow-up PRs are enabled in a develop → main flow. Remove `push` and `workflow_dispatch` as described in "Optional: open a follow-up PR after merges", and merge main back into develop once. |

---

## Cost and data

- **The API is called only on structural changes.** Ordinary feature PRs cost nothing.
- Each call sends: tracked file paths (up to 3,000), the directory list, the contents of up to 40 key files (up to 8,000 characters each), and the current wiki.json. **It does not send ordinary source files** unless you list them in `extra-context`.
- Cost per call depends on repository size: a few cents for a small repository, and usually under US$1 for a large one (estimated from Claude Opus 5.5 pricing, not measured).
- Before writing, the plan is checked against DeepWiki's limits: at least 1 page, at most `max-pages` pages, no empty or duplicate titles, parents that exist and do not form a cycle, at most 100 notes in total, and at most 10,000 characters per note.

## Turning it off

Delete `.github/workflows/deepwiki-wiki-sync.yml`. The existing `.devin/wiki.json` stays, and you can maintain it by hand from then on.

---

## Maintaining this Action

```bash
python3 -m venv .venv && .venv/bin/pip install anthropic==1.14.0 pytest
.venv/bin/python -m pytest -q tests

# Run against any repository locally
.venv/bin/python src/wiki_sync.py check    --repo /path/to/repo   # staleness only
.venv/bin/python src/wiki_sync.py validate --repo /path/to/repo   # check an existing wiki.json
ANTHROPIC_API_KEY=... .venv/bin/python src/wiki_sync.py generate --repo /path/to/repo [--force]
```

**Releasing:** tag `v1.x.y`, then move `v1` to the same commit. Use `v2` for breaking changes.

**When you change the prompt or output rules,** bump `GENERATOR_VERSION` in `src/wiki_sync.py` so every repository re-plans on its next run.
