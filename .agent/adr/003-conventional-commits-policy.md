# [ADR-003] Conventional Commits Policy Engine & Scope Auditor Integration

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In autonomous multi-agent development and CI/CD pipelines, inconsistent or unstructured git commit messages degrade automated changelog generation, SemVer release calculations, and release auditing. Furthermore, non-standard commit messages violate repository engineering standards (`AGENTS.md`). An automated, hermetic policy engine is required to validate Conventional Commits both during git hooks (`commit-msg`), during Scope Auditor verification (`taskctl audit`), and before completing task lifecycle transitions (`taskctl done`).

## 2. Decision Outcome
We implemented a dedicated Conventional Commits parser and policy engine in `taskctl.core.commits` compliant with the Conventional Commits 1.0.0 specification:
- **Core Parser & AST:** `parse_conventional_commit` validates type, scope, breaking indicators (`!`, `BREAKING CHANGE:`), subject/description non-emptiness, maximum 100-character header length, and blank line separation before message body and footers.
- **Scope Auditor Rule:** `CommitConventionRule` is added to `ScopeAuditor` default verification chain, inspecting the repository's HEAD commit message on every `taskctl audit`.
- **CLI Subcommand:** `taskctl lint-commit [msg] [--file <path>]` provides turn-key integration for Git's `commit-msg` hook or manual message linting, returning semantic exit codes (`0: APPROVED`, `1: CHANGES REQUIRED`).
- **Atomic Transition Guard:** `taskctl done [custom_msg]` enforces Conventional Commits validation on custom commit messages prior to executing git commits, aborting if violations are found.

## 3. Alternatives Considered
- **External Node.js / Python Linters (`commitlint`, `gitlint`):** Rejected because `taskctl` must remain hermetic and lightweight with zero external runtime dependencies.
- **Audit-only Verification:** Rejected because catching formatting errors only after commit creation causes unnecessary git amends or rollback cycles. Adding `lint-commit` enables pre-commit and hook-level enforcement.

## 4. Consequences and Trade-offs
### Positive
- Zero external package dependencies (pure Python standard library).
- Immediate feedback in Git `commit-msg` hooks, CI runners, and Scope Auditor.
- Prevents non-standard commits from entering repository history.

### Negative / Accepted Risks
- Enforces strict Conventional Commit types (`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`), requiring contributors and agents to adhere strictly to the convention.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [.agent/NOTES.md](file:///home/yegear/github/taskctl/.agent/NOTES.md)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
