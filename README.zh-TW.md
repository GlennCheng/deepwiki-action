# DeepWiki Page Planner

[English](README.md) | **繁體中文**

讓 [DeepWiki](https://docs.devin.ai/work-with-devin/deepwiki) 的頁面規劃檔 `.devin/wiki.json` 自動跟著程式碼更新的 GitHub Action。PR 改到 repo 結構時，由 Claude 重新規劃頁面清單，並把更新 commit 到同一個 PR。

```yaml
- uses: GlennCheng/deepwiki-action@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## 這是什麼、為什麼需要

DeepWiki 產生 wiki 時，如果 repo 根目錄有 `.devin/wiki.json`，就**只會**產生裡面列出的頁面。這份檔案是手寫的，程式碼一改就容易過時：新模組沒有頁面、刪掉的功能還留著。

這個 Action 在 PR 階段讀取 repo 結構，請 Claude 重新規劃頁面清單，並寫回 `.devin/wiki.json`。

- **只在真的有變時才花錢。** 結構簽章沒變就不呼叫 API，大部分功能 PR 都屬於這種。
- **跟著你的 PR 一起合併。** 更新會 commit 到 PR 的來源 branch，預設不會另開 PR。
- **保留你手寫的內容。** `repo_notes` 和用 `page_notes` 釘選的頁面會原樣保留。
- **寫入前先檢查。** 每份規劃都會依 DeepWiki 文件記載的限制檢查；連續兩次不合格就不寫入任何檔案。
- **支援 release 流程。** develop → main 的流程下，更新會跟著 release PR 一起進 main。

> 這是獨立的開源專案，與 Cognition、Devin、DeepWiki 沒有隸屬或背書關係。

## 運作流程

```
PR 開往目標 branch ──► 結構有變嗎？──沒有──► 結束（不呼叫 API、不花錢）
                         │有
                         ▼
                Claude 規劃頁面 → 檢查格式 → commit 進這個 PR 的來源 branch
```

- wiki.json 的更新會跟著你的 PR 一起合併進目標 branch。例如 develop 開 PR 合併到 main 時，更新會直接 commit 到 develop，出現在**同一個 PR** 裡，不會另開 PR。
- 每次執行都會先算「結構簽章」，結構沒變就直接結束，**不呼叫 Claude API、不花費用**。一般功能開發的 PR 大多屬於這種。
- PR 如果在 Action 跑完前（一般 1～2 分鐘）就被合併，這次的更新會在下一個開往目標 branch 的 PR 補上。
- 想要「合併後立刻自動補上」的話，可以另外啟用[選用的補更新 PR](#選用合併後自動開補更新-pr)。

---

## 安裝教學

以下所有步驟都在**要套用的 repo** 上操作，不是這個 Action 的 repo。整個流程約 10 分鐘。

### 開始前確認

| 項目 | 怎麼確認 |
|---|---|
| repo 能使用這個 Action | 這個 Action 的 repo 是公開的話，任何 repo 都能用。如果你用的是 private 的複本，只有**同一個擁有者**（同一個使用者或組織）底下的 repo 能使用（見「疑難排解」第一列）。 |
| 你對該 repo 有 **Admin** 權限 | 打開 repo 頁面，上方分頁列最右邊要看得到 **⚙ Settings**。看不到就是權限不足，請 repo 管理者幫你加，或請他操作步驟 1。 |
| 有一把 Anthropic API key | 見步驟 0。 |
| 知道目標 branch | 也就是 PR 要合併進去的 branch，通常是 `main`，也可能是 `master`。到 repo 首頁左上角的 branch 下拉選單查看。<br>**功能先進 develop、再用 release PR 把 develop 合併進 main 的流程，目標 branch 填 `main`**：Action 會在 release PR 上執行，更新會 commit 到 develop，跟著 release 一起進 main。 |

---

### 步驟 0：取得 Anthropic API key

API key 是 Action 呼叫 Claude 用的，費用會算在這把 key 所屬的 Anthropic 帳戶。

1. 如果已經有專門給 CI 用的 key，可以直接使用，跳到步驟 1。
2. 沒有的話，用瀏覽器登入 [Claude Console](https://console.anthropic.com/)。
3. 進入 **API keys** 頁面，按 **Create Key**。
4. 名稱填好認的名字，例如 `github-deepwiki-sync`，按建立。
5. **立刻複製 key**（以 `sk-ant-` 開頭）。這個畫面關掉後就看不到完整的 key 了。
6. 暫時貼在安全的地方，下一步要用。不要貼進程式碼、issue 或聊天訊息。

---

### 步驟 1：把 API key 存成 repo secret

secret 是 GitHub 存放敏感資料的地方，存進去後任何人（包括你）都看不到內容，只有 workflow 執行時讀得到。

**網頁操作：**

1. 打開 repo 頁面，點上方分頁列最右邊的 **⚙ Settings**。
2. 左側選單往下捲，找到 **Security** 區塊，點 **Secrets and variables** 展開，再點 **Actions**。
3. 畫面上有 **Secrets** 和 **Variables** 兩個分頁，確認在 **Secrets**。
4. 在 **Repository secrets** 區塊按綠色的 **New repository secret**。
5. 填寫：
   - **Name**：`ANTHROPIC_API_KEY`（要一字不差，全大寫）
   - **Secret**：貼上步驟 0 的 key
6. 按 **Add secret**。
7. 回到列表，應該會看到 `ANTHROPIC_API_KEY`，旁邊顯示剛才的更新時間。

**或用指令**（需安裝 [GitHub CLI](https://cli.github.com/) 並已 `gh auth login`）：

```bash
gh secret set ANTHROPIC_API_KEY -R <owner>/<repo>
# 出現 "? Paste your secret" 時貼上 key，按 Enter
```

> **可以用組織層級的 secret 嗎？** 付費方案可以在組織設定一次、分享給多個 repo。GitHub Free 方案的組織 secret 不會分享給 private repo，這種情況每個 repo 都要各設一次。

---

### 步驟 2：加入 workflow 檔

workflow 檔告訴 GitHub「什麼時候、跑哪個 Action」。它必須放在 repo 的 `.github/workflows/` 資料夾。

**先準備好檔案內容**（把 `main` 改成你的目標 branch，可列多個，例如 `[main, release]`）：

```yaml
name: DeepWiki Page Planner

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]          # ← 改成你的目標 branch

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
          # language: 繁體中文      ← 想要中文頁面標題就拿掉開頭的 #
          # max-pages: "30"       ← 頁數上限，預設 30；DeepWiki enterprise 方案最多 80
```

同一份檔案也在 [`examples/deepwiki-wiki-sync.yml`](examples/deepwiki-wiki-sync.yml)。

各段的作用：

| 區段 | 作用 |
|---|---|
| `on.pull_request` | 開往目標 branch 的 PR 被開啟、有新 commit、重新開啟、或從 draft 轉為 ready 時執行 |
| `permissions` | 讓 Action 能 commit 到 PR 的來源 branch |
| `concurrency` | 同一個 PR 連續 push 時，取消舊的執行，避免兩次執行搶著 commit |
| `if: ... draft` | draft PR 不執行，轉為 Ready for review 後才執行 |
| `with:` | Action 的設定，可加的參數見「設定參數」 |

**方法 A：在 GitHub 網頁上建立（不用 clone）**

1. 回到 repo 首頁（**<> Code** 分頁）。
2. 按檔案列表上方的 **Add file** → **Create new file**。
3. 在檔名欄輸入 `.github/workflows/deepwiki-wiki-sync.yml`。每打一個 `/`，GitHub 會自動把前面那段變成資料夾，這是正常的。
4. 把上面的內容貼進編輯區。
5. 按右上角綠色的 **Commit changes...**。
6. 在跳出的視窗：
   - **Commit message** 可填 `ci: add DeepWiki Page Planner`；
   - 選 **Create a new branch for this commit and start a pull request**（branch 有保護時只能選這個，也比較好檢查）；
   - 按 **Propose changes**。
7. 進到「Open a pull request」頁面後，確認 base branch，按 **Create pull request**。
   - 一般流程：base 選目標 branch（例如 `main`）。
   - develop → main 的流程：base 選 `develop`，和一般功能一樣進 develop，之後跟著 release 進 main。

**方法 B：在本機用 git**

```bash
git checkout -b ci/deepwiki-wiki-sync
mkdir -p .github/workflows
# 把上面的內容存成 .github/workflows/deepwiki-wiki-sync.yml
git add .github/workflows/deepwiki-wiki-sync.yml
git commit -m "ci: add DeepWiki Page Planner"
git push -u origin ci/deepwiki-wiki-sync
gh pr create --base main --fill       # develop → main 的流程改成 --base develop
```

---

### 步驟 3：確認第一次執行成功

第一次執行發生在**第一個開往目標 branch 的 PR** 上：

- 一般流程：步驟 2 開的那個 PR 就會觸發。
- develop → main 的流程：步驟 2 的 PR 是開往 develop 的，不會觸發。第一次執行會在下一個 release PR（develop → main）開出來時發生，更新會 commit 到 develop。以下的檢查請在那個 release PR 上做。

repo 原本沒有 `.devin/wiki.json` 的話，第一次執行會產生第一版。

1. 在 PR 頁面最下方的檢查區塊，會看到 **DeepWiki Page Planner / sync (pull_request)** 正在跑（黃色圓點）。一般 1～3 分鐘完成。
2. 想看過程就按它右邊的 **Details**，展開 **Run GlennCheng/deepwiki-action@v1** 底下的步驟。成功時會看到類似：

   ```
   stale: .devin/wiki.json does not exist
   wrote .devin/wiki.json with 18 pages
   Pushed the updated wiki.json to ci/deepwiki-wiki-sync.
   ```

   最後一行的 branch 名稱是 PR 的來源 branch（release PR 就是 `develop`）。
3. 回到 PR 的 **Commits** 分頁，會多一個 `chore(deepwiki): update .devin/wiki.json`，作者是 `github-actions[bot]`。
4. 到 **Files changed** 分頁看 `.devin/wiki.json`：
   - 每一頁有 `title`（標題）和 `purpose`（這頁要寫什麼）；
   - 有 `parent` 的是子頁面。
   不滿意可以直接在這裡改（見「調整頁面」）。
5. 確認沒問題、而且檢查已跑完（綠色勾勾）後，再合併 PR。

**檢查出現紅色叉叉時：** 按 **Details** 看錯誤訊息，對照下方的「疑難排解」。最常見的是步驟 1 的 secret 名稱打錯。

> **提醒：** Action 會在 PR 的來源 branch 上加一個 commit。之後要在本機繼續修改這個 branch 的人，push 前要先 `git pull`。

---

### 步驟 4：讓 DeepWiki 套用新的頁面規劃

DeepWiki 是在**產生 wiki 時**讀取 `.devin/wiki.json`。官方文件的說法是「commit 檔案後重新產生 wiki」，沒有說 commit 會自動觸發，所以合併後請手動重新產生：

1. 登入 Devin，從左側選單進入 **Wiki**（[app.devin.ai/wiki](https://app.devin.ai/wiki)）。
2. 打開這個 repo 的 wiki 頁面，執行重新產生。
3. 產生完成後，wiki 的頁面清單應該和 `.devin/wiki.json` 一致。

> 官方文件沒有寫重新產生按鈕的確切位置。找不到的話，請查閱 DeepWiki 的文件，或詢問你們 Devin 工作區的管理員。

---

### 安裝完成檢查表

- [ ] repo 的 **Settings → Secrets and variables → Actions** 有 `ANTHROPIC_API_KEY`
- [ ] 目標 branch 上有 `.github/workflows/deepwiki-wiki-sync.yml`
- [ ] 目標 branch 上有 `.devin/wiki.json` 和 `.devin/wiki-sync.lock.json`
- [ ] 目標 branch 有 required checks 的話，已設定 `push-token`（見「Required checks」）
- [ ] 已在 DeepWiki 重新產生 wiki

之後就不用再管它。PR 改到結構時，wiki.json 會自動跟著更新。

---

## 日常使用

### 一般開發者需要做什麼

幾乎不用做什麼。要注意兩點：

1. **Action 推了 commit 後，請先 `git pull` 再繼續 push。** 否則你的 push 會被拒絕（non-fast-forward）。
2. **看一下 `.devin/wiki.json` 的 diff。** 頁面規劃不理想就直接在 PR 裡改（見下方「調整頁面」）。

### 什麼情況會觸發重新規劃

只有「結構」變了才會呼叫 Claude：

| 變更 | 會重新規劃嗎 |
|---|---|
| 新增或刪除目錄（預設看到第 3 層） | 會 |
| 修改根目錄的 README、ARCHITECTURE、CONTRIBUTING | 會 |
| 修改 `package.json`、`pyproject.toml`、`go.mod`、`composer.json`、Dockerfile、compose 等 | 會 |
| 修改第一層子目錄的 README（例如 `api/README.md`） | 會 |
| 修改 `repo_notes`，或新增、修改、解除釘選頁（見「釘選頁面」） | 會 |
| 修改 Action 的設定（`language`、`max-pages`、`depth`、`extra-context`） | 會 |
| 在既有目錄裡新增、修改檔案 | 不會 |
| 只改沒被 git 追蹤的檔案 | 不會 |

判斷依據存在 `.devin/wiki-sync.lock.json`，**請把這個檔案和 wiki.json 一起 commit，不要手動修改。**

### 調整頁面

- **加上 repo 層級的說明**：在 `repo_notes` 加一則。它會原封不動保留，Claude 也會讀到。

  ```json
  "repo_notes": [
    { "content": "payments/ 是核心，請詳細說明退款流程。", "author": "Platform Team" }
  ]
  ```

- **固定某一頁不讓 Claude 改**：見下方「釘選頁面」。

- **其他頁面**由 Claude 負責。它會參考現有清單並盡量沿用原本的標題。直接手改這些頁也可以，但下次結構變更時可能會被調整。

### 釘選頁面

釘選的頁面，Action 每次重新規劃時都會**原封不動**保留，Claude 只規劃其餘的頁面。適合用在要寫給特定讀者、或要求特定寫法的頁面。

**怎麼釘選：** 在 `.devin/wiki.json` 裡，幫那一頁加上 `page_notes`，並寫**至少一則有內容**的 note。

```json
{
  "title": "Webhook Handling",
  "purpose": "說明 payments/webhooks 如何接收與處理金流通知",
  "parent": "Payments",
  "page_notes": [
    { "content": "請包含重試行為與冪等處理，並附上失敗時的排查步驟。" }
  ]
}
```

`page_notes` 同時也是寫給 DeepWiki 的指示：DeepWiki 寫這一頁時會照著 note 的內容寫，所以 note 的內容應該是「這頁要怎麼寫」，例如讀者是誰、要包含什麼、用什麼順序。

**什麼算釘選：**

| `page_notes` 的內容 | 算釘選嗎 |
|---|---|
| `[{ "content": "請包含重試行為。" }]` | 算 |
| `[{ "content": "" }, { "content": "有字的 note" }]` | 算（只要有一則有字） |
| `[{ "content": "" }]` 或 `[{ "content": "   " }]` | **不算** |
| `[]`，或沒有 `page_notes` 欄位 | 不算 |

> **為什麼空白的不算：** 用 Devin 編輯或更新 wiki.json 後，頁面上可能會留下 `"page_notes": [{ "content": "" }]` 這種空白 note。這不代表有人要固定那一頁，所以不算釘選。

**釘選後會怎樣：**

- 標題、`purpose`、`parent`、`page_notes` 都不會被改動，也不會被刪除。
- 釘選頁一律排在頁面清單的最前面，順序和原本相同。
- 釘選頁會佔用頁數上限。例如上限 30 頁、釘選 3 頁，Claude 最多只能規劃 27 頁。
- 釘選頁的 `parent` 如果指向一個沒釘選的頁面，Claude 必須保留那個父頁面，否則規劃會被退回重做。最好連父頁面也一起釘選。

**怎麼解除釘選：** 把那一頁的 `page_notes` 刪掉，或把 note 內容清空，然後 commit。下次執行時 Claude 會重新規劃這一頁，可能會改寫或刪除它。

**別釘太多：** 釘選頁越多，Claude 能規劃的頁數越少。釘滿上限時，新模組就沒有位置，規劃會被退回，job 會失敗。建議只釘真正需要特定寫法的頁面。

**查看哪些頁被釘選：** 在本機跑以下指令（需先完成下方「開發」的安裝）：

```bash
python3 -c "import json,sys; sys.path.insert(0,'src'); import wiki_sync as w; \
d=json.load(open('/path/to/repo/.devin/wiki.json')); print([p['title'] for p in w.pinned_pages(d)])"
```

### 強制重新規劃

在 PR 裡刪除 `.devin/wiki-sync.lock.json` 並 push，Action 會視為過期並重新規劃。

---

## 選用：合併後自動開補更新 PR

預設設定下，PR 在 Action 跑完前就被合併的話，更新會等到下一個 PR 才補上。如果希望合併後立刻補上，可以加上這個選用設定：PR 合併進目標 branch 後再檢查一次，仍然過期就**另外開一個 PR 直接進目標 branch**（標題 `chore(deepwiki): update .devin/wiki.json`），審核後合併即可。

### 適合與不適合的流程

| 流程 | 建議 |
|---|---|
| 功能 branch 直接開 PR 進 main | 可以啟用 |
| 功能先進 develop、再用 release PR 把 develop 合併進 main | **不要啟用** |

develop → main 的流程不適合，原因是補更新 PR 會**繞過 develop、直接合併進 main**：

1. 補更新 PR 合併後，main 多出 develop 沒有的 commit，兩者分岔；
2. 下一次 release PR 開出來時，Action 又依 develop 的結構產生一份，commit 到 develop；
3. main 和 develop 各有一份不同的 `.devin/wiki.json`，release PR 和「main 拉回 develop」的 PR 都會在這兩個檔上衝突，需要手動處理。

> **那把目標 branch 改成 develop 呢？** 也能避免分岔，但 Claude API 的呼叫次數會變多：每個改到結構的功能 PR 都會各自呼叫一次。目標維持 main、只在 PR 時觸發的話，一次 release 最多呼叫一次。

### 啟用方式

**1. 允許 GitHub Actions 開 PR**

補更新 PR 是由 Action 自己開的，需要這個權限。

網頁操作：

1. 在 repo 的 **⚙ Settings**。
2. 左側選單 **Code and automation** 區塊，點 **Actions** 展開，再點 **General**。
3. 頁面捲到最下方，找到 **Workflow permissions** 區塊。
4. 上面的 **Read and write permissions**／**Read repository contents and packages permissions** 兩個選項**不用改**（workflow 檔會自己宣告需要的權限）。
5. 勾選 **Allow GitHub Actions to create and approve pull requests**。
6. 按這個區塊下方的 **Save**。

**如果勾選框是灰色的、不能勾：** 代表組織層級關掉了這個選項。請組織擁有者到組織的 **Settings → Actions → General**（網址 `https://github.com/organizations/<組織名稱>/settings/actions`），在同名的 **Workflow permissions** 區塊勾選後儲存，你再回來勾 repo 的。

或用指令（只會改這一個設定，不會動到其他權限）：

```bash
gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow \
  -F can_approve_pull_request_reviews=true
```

**2. 在 workflow 加上 `push` 和 `workflow_dispatch`**

把步驟 2 的 `on:` 換成以下內容（兩處 `main` 保持一致）：

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]          # ← 你的目標 branch
  push:
    branches: [main]          # ← 和上面保持一致
  workflow_dispatch:
```

完整檔案在 [`examples/deepwiki-wiki-sync.with-followup.yml`](examples/deepwiki-wiki-sync.with-followup.yml)。

### 啟用後的行為

- 合併進目標 branch 後會再執行一次。結構簽章相符就結束，不呼叫 API；仍然過期才重新規劃並開補更新 PR。
- 補更新 PR 使用固定的 branch（預設 `deepwiki-wiki-sync/<目標 branch>`，可用 `sync-branch` 參數改）。同時只會有一個開著的補更新 PR，之後的更新會疊加在同一個 PR 上，不會重複開。
- 補更新 PR 本身不會觸發 Action，合併後那次執行的簽章已相符，所以不會形成迴圈。
- 也可以手動執行：**Actions → DeepWiki Page Planner → Run workflow**，選擇 branch。過期時會開補更新 PR。

---

## 設定參數

都寫在 workflow 的 `with:` 底下。

| 參數 | 預設值 | 說明 |
|---|---|---|
| `anthropic-api-key` | （必填） | Anthropic API key |
| `language` | `English` | 頁面標題與 purpose 的語言，例如 `繁體中文` |
| `max-pages` | `30` | 頁數上限（含釘選頁）。可以設得比 30 小，讓 wiki 更精簡；DeepWiki 一般方案最多 30，enterprise 方案最多 `80` |
| `depth` | `3` | 多深的目錄變動算結構變更 |
| `extra-context` | 空 | 額外給 Claude 參考的檔案，glob 以逗號分隔，例如 `docs/*.md,src/*/index.ts` |
| `model` | `claude-opus-5-5` | Claude 模型 |
| `effort` | `medium` | Claude 思考強度：`low`、`medium`、`high`、`xhigh`、`max` |
| `push-token` | 空 | 見下方「Required checks」 |
| `github-token` | `github.token` | 一般不需要改 |
| `sync-branch` | `deepwiki-wiki-sync/<目標 branch>` | 補更新 PR 使用的 branch（只在啟用補更新 PR 時有作用） |

輸出值：`stale`（開始時是否過期）、`changed`（是否寫入了新檔）。

### Required checks（目標 branch 有必過檢查時必看）

GitHub 為了避免無限迴圈，用預設 `GITHUB_TOKEN` 推的 commit 和開的 PR **不會觸發其他 workflow**。如果目標 branch 設了 required status checks：

- Action 推到 PR 的 commit 不會跑 CI，PR 會卡在「等待檢查」；
- 有啟用補更新 PR 的話，補更新 PR 也一樣。

解法是改用 PAT 或 GitHub App token：

1. 建立 fine-grained PAT（或 GitHub App），權限 **Contents: Read and write**、**Pull requests: Read and write**，範圍包含該 repo。
2. 存成 repo secret，例如 `DEEPWIKI_SYNC_TOKEN`。
3. 在 workflow 的 `with:` 加上 `push-token: ${{ secrets.DEEPWIKI_SYNC_TOKEN }}`。

這樣 push 會正常觸發 CI。Action 自己雖然也會再跑一次，但結構簽章已經相符，不會再呼叫 API，也不會形成迴圈。

---

## 疑難排解

| 現象 | 原因與處理 |
|---|---|
| `Unable to resolve action GlennCheng/deepwiki-action@v1, repository not found` | 這個 Action 的 repo 沒有開放給你的 repo 使用。private 的 Action repo 要在它的 **Settings → Actions → General → Access**，選擇開放給同一個擁有者底下 repo 的選項（「Accessible from repositories owned by the user …」或「… in the … organization」），而且只有那些 repo 能用。 |
| `anthropic-api-key is empty` | 沒有設定 `ANTHROPIC_API_KEY` secret，或 secret 名稱不同。 |
| `GitHub Actions is not permitted to create or approve pull requests` | 啟用了補更新 PR，但沒做「允許 GitHub Actions 開 PR」。 |
| 警告 `Could not push to <branch>` | Action 推送時 PR branch 剛好被更新或已合併，不算失敗。下一次執行會補上。 |
| fork 來的 PR 沒有跑 | 刻意略過：fork 拿不到 secret 也不能 push。由下一個非 fork 的 PR 補上。 |
| draft PR 沒有跑 | 範例 workflow 刻意略過 draft，標成 Ready for review 後才會跑。 |
| `plan rejected` 後 job 失敗 | Claude 的規劃連續兩次不符合 DeepWiki 的格式限制，這時不會寫入任何檔案。重新執行通常就能通過；常發生的話，把釘選頁數量減少，或提高 `max-pages`。 |
| `Claude declined the request` | 請求被 Anthropic 的安全機制拒絕，且備援模型也沒有完成。請檢查 repo 是否含有可能觸發安全機制的內容。 |
| PR 一直卡在等待檢查 | 見上方「Required checks」。 |
| main 出現 develop 沒有的 `chore(deepwiki)` commit | develop → main 的流程啟用了補更新 PR。照「選用：合併後自動開補更新 PR」拿掉 `push` 和 `workflow_dispatch`，並把 main 合併回 develop 一次。 |

---

## 費用與資料

- **只有結構變更才會呼叫 API。** 一般功能開發的 PR 不會呼叫 API。每次執行仍會用到少量 GitHub Actions 時間（checkout 和檢查本身）。
- 每次呼叫送出的內容：git 追蹤中的檔案路徑（最多 3,000 條）、目錄清單、最多 40 個關鍵檔的內容（每個最多 8,000 字）、現有的 wiki.json。**不會送出一般原始碼檔案的內容**，除非你用 `extra-context` 指定。
- 單次費用依 repo 大小而定。小型 repo 粗估約數美分，大型 repo 也通常在 1 美元以內（以 Claude Opus 5.5 定價估算，未實測）。
- 寫檔前會依 DeepWiki 的限制檢查格式：至少 1 頁、最多 `max-pages` 頁、標題不可空白或重複、parent 必須存在且不能循環、notes 總數不超過 100、每則不超過 10,000 字。

## 停用

刪除 `.github/workflows/deepwiki-wiki-sync.yml` 即可。已經產生的 `.devin/wiki.json` 會保留，之後可以手動維護。

---

## 開發

這是一個 composite action：`action.yml` 串起各個步驟，`src/wiki_sync.py` 負責規劃與檢查，`scripts/` 是 git 相關的步驟。要修改的話：

```bash
python3 -m venv .venv && .venv/bin/pip install anthropic==1.14.0 pytest
.venv/bin/python -m pytest -q tests

# 對任一 repo 在本機執行
.venv/bin/python src/wiki_sync.py check    --repo /path/to/repo   # 只判斷是否過期
.venv/bin/python src/wiki_sync.py validate --repo /path/to/repo   # 檢查現有 wiki.json
ANTHROPIC_API_KEY=... .venv/bin/python src/wiki_sync.py generate --repo /path/to/repo [--force]
```

**發新版本：** 打 `v1.x.y` tag，再把 `v1` 移到同一個 commit。有不相容的變更時改用 `v2`。

**修改 prompt 或輸出規則時**，請調高 `src/wiki_sync.py` 的 `GENERATOR_VERSION`，讓所有 repo 下次都重新規劃。

## 授權

[MIT](LICENSE)
