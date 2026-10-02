# [ADR-006] Task Dependency Graph Engine, Visualizers, and Cycle Detection Policy

- **Status:** Approved
- **Date:** 2026-10-02
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In multi-agent and complex engineering lifecycles, tasks across active contracts, completed logs, and upcoming backlogs frequently have strict topological ordering constraints. Without an automated dependency engine:
1. Agents risk executing dependent tasks out of order or creating circular prerequisite deadlocks.
2. Humans and orchestrators cannot easily visualize project pipelines or DAG progression in terminal or documentation.
3. Contract specifications lacked a standardized, flexible Markdown schema for declaring prerequisites across active, backlog, and completed states.

## 2. Decision Outcome
We implemented a hermetic task dependency graph engine in `taskctl.core.graph`, enhanced markdown parsing in `taskctl.core.parser`, provided CLI visualization commands in `taskctl.cli`, and integrated an interactive DAG viewer into the terminal user interface:

- **Dependency Contract & Flexible Markdown Schema:**
  - **Active Task:** Supports `- **Depends On:** [04.1], [03.7]` or `- **Dependencies:** [04.1]`.
  - **Backlog & Log Items:** Supports annotations such as `(deps: [04.1])`, `(depends: [04.1])`, `(after: [04.1])`, and flexible formatting (`**[ID]**`, `` `[ID]` ``, or `[ID]`).
  - **Implicit Sequential Inference:** If no explicit dependencies are specified, tasks within an epic (`[XX.Y]`) sequentially depend on the preceding sequence item (`[XX.Y-1]`), and subtasks (`[XX.Y.Z]`) depend on their parent task (`[XX.Y]`), establishing natural DAG progression without redundant boilerplate.
- **Graph Engine & Cycle Detector (`taskctl.core.graph`):**
  - `TaskDependencyGraph`: Directed graph representation of `TaskNode` models (`id`, `title`, `status`, `section`, `dependencies`, `dependents`).
  - `find_cycles()` / `has_cycle()`: Deterministic cycle detection using DFS recursion coloring (white/gray/black), extracting normalized cycle paths to prevent infinite loops.
  - `topological_sort()`: Kahn's algorithm producing deterministic execution sequences, raising `CycleDetectedError` when cycles exist.
  - `render_ascii_tree()`: Unicode multi-root forest tree visualizer (`├── `, `└── `, `│   `) with status tags (`[DONE]`, `[RUNNING]`, `[PLANNING]`, `[BACKLOG]`) and cyclic edge protection (`(CYCLE -> [ID])`).
  - `render_mermaid()`: Valid Mermaid `graph TD` diagrams with subgraphs (`Completed`, `Active`, `Backlog`), dependency arrows, and CSS styling classes.
  - `to_dict()`: JSON serialization for external orchestrators and pipelines.
- **CLI Subcommand (`taskctl graph`):**
  - `taskctl graph [--tree] [--mermaid] [--json] [--check-cycles] [--file <path>] [--no-infer]`:
    Provides formatted ASCII tree by default, raw Mermaid diagram with `--mermaid`, JSON with `--json`, and CI-compatible cycle verification with `--check-cycles` (exit code `0` on clean DAG, `1` on cycle).
- **TUI DAG Visualizer (`taskctl ui --dag` / `taskctl dashboard`):**
  - Integrated `render_dag_view` into TUI renderer.
  - Keyboard toggle `v` switches seamlessly between cockpit dashboard and DAG dependency visualizer.

## 3. Alternatives Considered
- **External Graphviz / NetworkX Library:** Rejected to preserve strict zero non-standard runtime dependencies in `taskctl` (standard library only).
- **Separate `.agent/DAG.yaml` File:** Rejected in favor of maintaining `.agent/TASK.md` as the single source of truth for task contracts and metadata.

## 4. Consequences and Trade-offs
### Positive
- Strict cycle detection prevents agent deadlock and broken execution orders.
- Native Mermaid diagram generation embeds directly in GitHub/GitLab markdown documentation.
- Zero external dependencies with 100% test coverage.
- Fully backwards compatible with existing `.agent/TASK.md` formats.

### Negative / Accepted Risks
- Very large task histories (>1000 tasks) may require pagination or depth limiting in ASCII tree displays.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [ADR-001](file:///home/yegear/github/taskctl/.agent/adr/001-modular-cli-architecture.md)
- [ADR-005](file:///home/yegear/github/taskctl/.agent/adr/005-cross-repo-telemetry-aggregation-daemon.md)
