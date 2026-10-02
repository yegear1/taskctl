# Multi-Repository Ecosystem Topology & Contracts (ECOSYSTEM.md)

> 🎯 **Purpose:** Canonical source of truth for topology, sibling services, shared contracts, and cross-repo boundaries in the agent tooling ecosystem.
>
> ⚠️ **Mandatory Rules for the Agent:**
> 1. You MUST NOT break active contracts consumed by sibling repositories without an expand/contract deprecation period.
> 2. You MUST NOT attempt to directly inspect or mutate files outside this repository directory.
> 3. You MUST mock external service interactions in local automated tests.

---

## 1. Repository Topology Matrix

| Repository | Role / Responsibility | Relationship | Location / Repository URL | Owner / Team |
| :--- | :--- | :---: | :--- | :--- |
| **`taskctl`** *(Current)* | Task Lifecycle, Contract Engine & Multi-Agent CLI | `Self` | `https://github.com/yegear1/taskctl` | Platform Team |
| `template-agent` | Upstream Governance Baseline (Greenfield & Brownfield) | `Upstream (Dependency)` | `https://github.com/ye-sandbox/template-agent` | Governance Team |
| `agent-skills` | Central Skill Library & Cross-Repository Capabilities | `Upstream (Dependency)` | `https://github.com/ye-sandbox/agent-skills` | Core Agents |
| `maestri` | Spatial Canvas UI & Multi-Agent Terminal Orchestrator | `External (Supported Platform)` | Desktop App (Local IPC Socket) | Platform Integration |
| `multigravity-cli` | Multi-profile Quota Balancer, Isolation & Worktree CLI | `Downstream (Consumer)` | `https://github.com/yegear1/multigravity-cli` | Infrastructure |
| `victorialogs` | Structured Log & Audit Telemetry Sink | `Downstream (Consumer)` | `https://github.com/ye-sandbox/victorialogs` | Observability |

---

## 2. Shared Contracts & Source of Truth

- **Contract Strategy:** Local `.agent/TASK.md` format specification compliant with `template-agent` greenfield/brownfield AST schemas.
- **Contract Format:** Markdown AST + JSON Schema for Webhook Telemetry.
- **Sync Command / Workflow:** `taskctl audit` validates diffs and markdown invariant integrity.
- **Drift Prevention:** Every change affecting `TASK.md` parsing or serialization MUST be verified against `tests/test_parser.py` and `tests/test_webhooks.py`.

---

## 3. Cross-Repo Interfaces Catalog

### A. Consumed by this Repository (Upstream Dependencies)

| Source Service | Protocol / Transport | Target Endpoint / Topic | Contract / Schema | Fallback / Blast Radius |
| :--- | :---: | :--- | :--- | :--- |
| `template-agent` | Git / Filesystem | `.agent/TASK.md`, `AGENTS.md` | Markdown AST Spec | Graceful regex fallback |
| `maestri` | UNIX Domain Socket | `$MAESTRI_SOCKET_PATH` | JSON-RPC / IPC commands | Degrade to terminal stdout |
| `multigravity-cli` | CLI Subprocess | `multigravity quota --json` | JSON output | Fallback to default profile |

> **Architectural Separation of Concerns:**
> `taskctl` is an open, generic task contract engine (governing `.agent/TASK.md` transitions, scope audit, and DoD enforcement). It intentionally delegates multi-profile quota balancing, worktree management, and agent quota monitoring to [`multigravity-cli`](https://github.com/yegear1/multigravity-cli) via thin pluggable adapters to prevent feature overlap.

### B. Exposed by this Repository (Downstream Consumers)

| Route / Topic | Consumer(s) | Payload / Schema | Breaking Change Risk | Deprecation Policy |
| :--- | :--- | :--- | :---: | :--- |
| `WebhookDispatcher` | Vector / Telemetry Listeners | Task lifecycle event JSON (`task_started`, `audit`, `task_completed`) | **LOW** | Expand & contract |
| CLI Exit Codes | CI / Git Pre-commit Hooks | Semantic exit codes (`0: Approved`, `1: Changes Required`, `2: Rejected`) | **HIGH** | Strict SemVer |

---

## 4. Blast Radius & Contract Evolution Rules

1. **Additive-First (Expand / Contract):**
   - Never remove or alter existing CLI flag semantics or JSON telemetry keys without deprecation.
2. **Hermetic Testing & Zero Cross-Repo Mutation:**
   - Automated tests in `tests/` must never require a live Maestri socket, Multigravity profile daemon, or active network webhook endpoint.
   - All external provider and webhook tests must be mocked or hermetically tested.
3. **Fail-Safe Operation:**
   - Network timeouts or missing sockets must never block `taskctl done` or break git commit execution.
