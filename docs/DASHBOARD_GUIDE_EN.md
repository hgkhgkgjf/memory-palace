# Memory Palace Dashboard User Guide (English)

> This guide mirrors the **English interface** of the Memory Palace Dashboard.
>
> If your interface is currently in Chinese, click the language toggle in the top-right corner to switch to English. Your preference is saved automatically.

---

## Table of Contents

- [🌐 General Operations](#-general-operations)
- [📂 Memory Page](#-memory-page)
- [📋 Review Page](#-review-page)
- [🔧 Maintenance Page](#-maintenance-page)
- [📊 Observability Page](#-observability-page)
- [❓ FAQ](#-faq)

---

## 🌐 General Operations

### 🧭 Top Navigation Bar

The top of the page has four tabs:

| Tab | Page | What It Does |
|-----|------|-------------|
| **Memory** | Memory Page | Browse, create, and edit memories |
| **Review** | Review Page | View change history and decide whether to keep or rollback modifications |
| **Maintenance** | Maintenance Page | Clean up old or unused memories |
| **Observability** | Observability Page | Monitor system health and search performance |

### 🔑 Setting an API Key

In the top-right corner, you may see one of these states:

- **Set API key**: no stored key is configured yet; clicking opens the **first-run setup assistant**
- **Update API key / Clear key**: a local key is already stored in the browser
- **Runtime key active**: the page received a runtime-injected key

If neither a runtime key nor a browser-stored key is available, and the server-side setup status still does not report Dashboard auth as configured, the first-run setup assistant may open automatically on first load.

If the Dashboard shell opens but protected data does not load, the usual fix is:

**Set API key** → open the first-run setup assistant → enter the `MCP_API_KEY` value from your `.env` file → choose **Save dashboard key only** or **Save local `.env` settings**.

> If you set `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` for local development, protected data can load automatically without entering a key, as long as the request is a direct loopback request.

**About the two save options:**

- **Save dashboard key only** stores the Dashboard key in the current browser session (`sessionStorage`) until you clear it manually or the browser session ends. Saving takes effect immediately for protected Dashboard requests in the current page.
- **Save local `.env` settings** is only enabled when the app is running directly against a non-Docker local checkout **and** the current request is a direct loopback request. It only targets project-local `.env*` files. Docker container scenarios keep the button disabled by design.
- The first local `.env` save requires a non-empty Dashboard key.
- The assistant's `Profile C/D` presets follow the `router + reranker` path but are still only suggested starting points. You must replace documented placeholders such as `https://router.example.com/v1`, `router-embedding-model`, and `router-reranker-model` with real values, and supply a real positive-integer embedding dimension for remote backends.
- For provider API bases, enter the service base rather than concrete endpoint suffixes like `/embeddings`, `/rerank`, or `/chat/completions`. Common suffixes are trimmed automatically, but malformed or link-local targets are rejected.

<p align="center">
  <img src="images/setup-assistant-en.png" width="900" alt="Memory Palace first-run setup assistant (English mode)" />
</p>

### 🌍 Language Toggle

A language toggle button is in the top-right corner. Click it to switch between English and Chinese. Your preference is remembered by the browser.

If the browser already has a stored language choice, the frontend applies it before the app mounts, so the page title and `document.lang` match on first paint.

If the setup assistant is already open, it has its own language toggle in the upper right corner. Switching there updates the dialog immediately and keeps what you have already typed.

> If you open the Dashboard in Microsoft Edge, the frontend automatically switches to a lighter visual mode to reduce local lag. The layout, buttons, and flows in this guide still apply.

---

## 📂 Memory Page

> **What is this page for?** Browse and manage all your memory content. View existing memories, create new ones, edit content and metadata, or delete memories you no longer need.

### 🗂️ Page Layout

- **Left side — Conversation Vault**: Create new memories from dialogue
- **Right side — Current Node Content + Child Memories list**: View and edit existing memories

### 🧭 Breadcrumb Navigation

The breadcrumb bar shows your current location, for example: `root > core > agent > preferences`.

- Click any level in the path to jump directly
- **root** is the top-level node — it does not store memory content itself

### ✍️ Left Side: Conversation Vault

#### 📝 Field Descriptions

| Field | Placeholder | Description |
|-------|-----------------|-------------|
| **Memory title** | `Memory title (optional)` | A short name for this memory. Optional but recommended. |
| **Conversation** | Large text area | Paste the dialogue you want to save. **Required.** |
| **Priority** | `Priority` | Enter a number. **Smaller numbers mean higher priority**; `0` ranks ahead of `5`. |
| **Disclosure** | `Disclosure` | A text description controlling when this memory should be surfaced to an Agent. Optional. |

> **Disclosure**: A visibility rule you write in plain language. It tells the system under what conditions this memory should be shown to the AI. If you're unsure, leave it blank.
>
> The system also validates the final path length. If `parent path + title` is too long, the create request fails before the write starts. Shorten the title or step back to a higher parent.

#### ✅ Step-by-Step: Creating a Memory

1. Paste your dialogue into the **Conversation** text area
2. (Optional) Fill in **Memory title**, **Priority**, and **Disclosure**
3. Click **Store Memory**
4. The system runs a Write Guard check first
5. On success, a green notification appears at the bottom: `Memory created: core://xxx`

> **Write Guard**: A safety mechanism that evaluates each write before it is accepted. From the Dashboard side, the visible result is whether the write proceeds or returns `Skipped: write_guard blocked ...`.

### 📄 Right Side, Upper: Current Node Content

Displays the full detail of the memory you're currently viewing:

- **Content editor**: Directly edit the memory body text
- **Priority / Disclosure**: Modify those fields
- **Save** button: Save your changes
- **Delete Path** button: Remove this memory's access path (a confirmation dialog appears first)

#### 📌 Gist vs. Original View

Each memory may have a system-generated summary (Gist). Use the **Gist** / **Original** toggle to switch between views.

### 📑 Right Side, Lower: Child Memories

#### 🔍 Child Filters

| Filter | Placeholder | Description |
|--------|-----------------|-------------|
| **Search box** | `Search path / snippet` | Filter matching child memories by path and preview snippet |
| **Max priority** | `Max priority (optional)` | Only shows memories with priority ≤ this value |

- Each child card shows the current priority, path/title, and snippet or gist preview
- Click any card to navigate into that memory node
- Click **Load N more** at the bottom to reveal more

> If you are editing the current node and then click a breadcrumb or child card, the page asks whether you want to discard the unsaved edits first.

### 🧱 Layer Hierarchy

The Memory page also includes a **Layer Hierarchy** panel for reading the L0 / L1 / L2 relationship.

- L0 is the entry layer: roots and domains
- L1 is the concrete memory-node layer
- L2 is a summary derived from multiple L1 memories

You can expand an L2 summary to see which source memories produced it and whether the current source content still matches the hash captured at derivation time. The "generate summary" path returns a draft preview only; opening the panel does not silently write a new summary into the database.

> If the panel shows a sample / mock badge, the backend has no real L2 data to show yet.

---

## 📋 Review Page

> **What is this page for?** Every time a memory is created, modified, or deleted, the system takes a "before" snapshot. This page shows you those changes so you can decide: keep the change, or roll it back.
>
> **Scope**: the Review page only shows snapshot sessions for the **current database target**. Switching `.env`, Docker compose project, or SQLite file does not mix old sessions into the current queue.

### 🗂️ Page Layout

- **Left side — Review Ledger**: List of sessions and their snapshots
- **Right side — Diff View**: Detailed before/after comparison of a selected snapshot

### 📖 Left Side: Review Ledger

#### 🎯 Target Session

A dropdown labeled **Target Session**. Each batch of AI-driven modifications is grouped into a session.

- **No active sessions** means there are no pending changes to review
- Select a session to see all modification snapshots under it

#### 📸 Snapshot List

Each snapshot represents a single modification. The card shows:

- **Operation type**: Create / Content / Meta / Delete / Alias
- **Resource path**: The memory path that was modified (e.g., `core://agent/preferences`)

Click a snapshot to load its diff view on the right.

### 🔀 Right Side: Diff View

- **Red / strikethrough text**: Removed content
- **Green / highlighted text**: Added content
- **Metadata Shifts**: Changes to priority, disclosure, or other metadata

#### 🎛️ Action Buttons

| Button | What It Does |
|--------|-------------|
| **Integrate** | Accept this change — clears the snapshot from the review queue |
| **Reject** | Roll back the memory to its state before this change was made |
| **Integrate All** | Accept all pending changes in the current session at once |

> If a newer change lands after you opened this snapshot, the backend rechecks the current head inside the actual write path. An older snapshot does not silently overwrite newer content.
> Metadata-only rollback follows the same fail-closed idea: if the path disappeared before the actual write, it returns `404`; if the current target or metadata already changed, it returns `409`.

---

## 🔧 Maintenance Page

> **What is this page for?** Helps you clean up "garbage" memories. Over time, some memories become outdated, unreachable (no paths point to them), or decay in vitality.

### 📊 Summary Cards at the Top

| Card | Meaning |
|------|---------|
| **Deprecated** | Number of old versions left behind when memories were updated |
| **Orphaned** | Number of memories that no path can reach |
| **Low Vitality** | Number of memories whose vitality score has decayed enough to be deletable |

### 🧹 Upper Section: Orphan Cleanup

> **Orphan memory**: each memory is accessed via a path. If that path is deleted but the memory record still exists in the database, it becomes an "orphan" — it's there but unreachable.

Two categories:

- **Deprecated Versions**: Old history copies left by update operations
- **Orphaned Memories**: Records with zero paths pointing to them

#### ✅ Step-by-Step: Cleaning Up Orphans

1. Click **Refresh** to scan for the latest orphan memories
2. Select the memories you want to delete
3. Click **Delete N orphans**
4. Confirm the deletion in the popup dialog

> ⚠️ Deletion is permanent and cannot be undone.
>
> If a deprecated item is still the final migration target of older versions, the cleanup dialog will refuse that deletion first.

### 💚 Lower Section: Vitality Cleanup Candidates

> **Vitality**: Every memory has a vitality score representing how "active" it is. Newly created memories start with high vitality. Over time, the score naturally decays.

#### 🔍 Filter Fields

| Field | Description |
|-------|-------------|
| **Threshold** | Vitality score cutoff. Lower = stricter filter. |
| **Inactive days** | How many days a memory must have been unaccessed to qualify |
| **Limit** | Maximum candidates to display. Range: 1–500. |
| **Domain** | Only show candidates from a specific domain (e.g., `core`, `notes`) |
| **Path prefix** | Only show candidates whose path starts with this prefix |
| **Reviewer** | Records who initiated this cleanup review. Default: `maintenance_dashboard`. |

#### ✅ Step-by-Step: Vitality Cleanup

1. Fill in filter conditions and click **Apply Filters**
2. Review the candidate list. Each card shows:
   - `vitality N.NN`: Current vitality score
   - `inactive Nd`: How many days since last access
   - `deletable` or `active paths`: Whether it can be safely deleted
3. Select the memories you want to act on
4. Choose **Prepare Delete (N)** or **Prepare Keep (N)**
5. Click **Confirm delete** or **Confirm keep** — the system asks you to type a confirmation phrase
6. Type the exact confirmation phrase to execute the action

> **Run Decay + Refresh**: Manually triggers a vitality decay recalculation.
>
> If confirm fails (wrong phrase, rejected key, request timeout) before the backend used that prepared batch, the prepared review stays on the page so you can fix the problem and retry.

### 🧠 Forgetting Simulation and Archive Candidates

The Maintenance page also includes a **Forgetting** panel for previewing which memories would fall below a threshold after N more days.

- **Decay simulation** is read-only and does not modify the database
- **Candidate queue** lists low-vitality memories that still need human review
- **Keep** only removes the item from the current queue; it does not delete content
- **Archive** requires prepare first, then an exact confirmation phrase; the backend marks the original memory deprecated and writes an archive row instead of hard-deleting it

> The rule is simple: the system can find candidates, but it cannot forget for you. Any archive write requires human confirmation.

---

## 📊 Observability Page

> **What is this page for?** The system's "health report." It shows search engine performance, runtime status, and background job states. **Regular users don't need this page day-to-day** — it's mainly useful for troubleshooting.

### 📊 Summary Cards at the Top

| Card | Meaning |
|------|---------|
| **Queries** | Total number of search requests handled |
| **Latency** | Average search response time (ms). The hint below shows localized **P95** latency. |
| **Cache Hit Ratio** | Percentage of searches served from cache |
| **Index Latency** | Average time for index operations |
| **Cleanup p95** | 95th percentile cleanup time |
| **Cleanup Index Hit** | Hit rate for index lookups during cleanup operations |

### 🎛️ Top Action Buttons

| Button | Description |
|--------|-------------|
| **Refresh** | Reload all statistics |
| **Rebuild Index** | Submit a full index rebuild job request |
| **Sleep Consolidation** | Submit a memory consolidation job request |

### 📈 Search Quality Panel

The **Search Quality** panel shows MRR, Recall, p95, channel contribution, and RRF status by retrieval mode.

The backend endpoint is real and authenticated, but labelled quality samples are not persisted yet. It explicitly returns `is_mock=true` / `status=unavailable`; any MRR / Recall values shown are only to demonstrate the panel shape.

> For real retrieval numbers that can be cited, use the public benchmark wording in [EVALUATION_EN.md](EVALUATION_EN.md).

### 🔎 Search Console

A diagnostic tool that lets you run a test search.

#### 📝 Field Descriptions

| Field | Description |
|-------|-------------|
| **Query** | The keywords or question you want to search for |
| **Mode** | hybrid (recommended), semantic, keyword |
| **Session Id** | (Optional) If filled, results from this session are prioritized |
| **Max Results** | Maximum number of results to return |
| **Candidate x** | Internal candidate multiplier. Higher = broader search but slower. |
| **session-first** | Check this to prioritize current-session memories |
| **Domain filter** | (Optional) Restrict search to a specific domain |
| **Path prefix filter** | (Optional) Only search under a path prefix |
| **Scope hint** | (Optional) A hint to guide the search engine's scope |
| **Max priority filter** | (Optional) Only return memories with priority ≤ this value |

Click **Run Diagnostic Search** to execute.

### 🩺 Search Diagnostics

After running a search:

- **latency**: How many milliseconds the search took
- **mode**: The actual retrieval mode used
- **interaction tier**: Whether this search stayed on the fast path or escalated to the deep path
- **intent**: The query intent or applied intent label returned by the backend
- **intent LLM attempted**: Whether the backend actually tried the LLM-based intent classifier
- **strategy**: Which search strategy was selected
- **degraded**: Whether the backend marked this search as degraded; if so, the specific reasons are shown
- **Result list**: Each result shows its match score, content snippet, source path, and update metadata

> If a final path revalidation lookup fails, the stale result is dropped instead of being shown anyway, and the diagnostics surface the degradation reason.

### ⚙️ Runtime Snapshot

Displays the system's current operational status:

- Whether the index is healthy or degraded
- Queue depth (how many tasks are waiting)
- Last worker error message
- Sleep consolidation status
- Reflection workflow counters (prepared / executed / rolled back)

### 📋 Index Task Queue

Lists running or recently completed index tasks. Each task can be:

- **Inspect**: View task details
- **Cancel**: Stop a running task
- **Retry**: Re-execute a failed task

---

## ❓ FAQ

### Q: The page loads but shows no data?

This usually means **the API key hasn't been configured**. Click **Set API key** in the top-right corner to open the setup assistant, enter the `MCP_API_KEY` value from your `.env` file, and first use the browser-only save path so the Dashboard can authenticate. Only use the `.env` write path when you are on a non-Docker local checkout.

### Q: I clicked "Store Memory" and it says "Skipped"?

The Write Guard blocked this write request. From the Dashboard side, the exact backend reason is not always visible; modify the content and try again, or inspect the backend response if you need the detailed cause.

### Q: What number should I use for Priority?

There's no fixed range. A simple rule of thumb: use `0` for critical core memories, `5` for normal ones, and larger numbers for weaker hints. Remember: **smaller number = higher priority**.

### Q: Can I undo "Integrate" or "Reject"?

- **Integrate** clears the snapshot record, but the memory content itself is unchanged
- **Reject** rolls back the memory to its pre-change state; if you later decide the change was needed, you'll need to re-create it

### Q: Why did rollback return `409` or `404`?

That usually means the current path state changed after you opened the snapshot. A common `409` case is that the same URI already has a newer content snapshot in another Review session, or the current metadata changed again. A common `404` case is that the path disappeared before rollback actually wrote.

### Q: Why did I suddenly see the fallback error page?

That is the dashboard's root fallback shell. It means the frontend hit an unexpected render-phase error and stopped the page from continuing in a broken state. First try a normal refresh. If the same screen comes back, keep the browser console and backend logs from that moment for debugging.

### Q: Does vitality automatically recover?

No. Vitality only decays over time. However, each time a memory is accessed (through reads or search hits), the vitality receives a "refresh" that slows the decay rate.

### Q: When do I need to manually "Rebuild Index"?

When you notice that memories you know exist aren't showing up in search results. Under normal use, the index is maintained automatically.
</content>
