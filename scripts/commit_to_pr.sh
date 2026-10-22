#!/usr/bin/env bash
# Commit regenerated .devin files onto the pull request's head branch.
# A push that loses a race (the branch moved or was merged/deleted) is a
# warning, not a failure: the post-merge run catches anything missed.
set -euo pipefail

: "${HEAD_REF:?HEAD_REF is required}"

[ -d .devin ] && git add -- .devin/wiki.json .devin/wiki-sync.lock.json
if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

git -c user.name="${GIT_AUTHOR_NAME:-github-actions[bot]}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
    commit -m "chore(deepwiki): update .devin/wiki.json"

if git push origin "HEAD:refs/heads/${HEAD_REF}"; then
  echo "Pushed the updated wiki.json to ${HEAD_REF}."
else
  echo "::warning::Could not push to ${HEAD_REF} (it probably moved or was merged). The next run, or the post-merge run, will update wiki.json."
fi
