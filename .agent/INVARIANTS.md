# Critical System Invariants (taskctl)

1. **Schema & AST Parsing:** `.agent/TASK.md` format must be strictly parsable by `taskctl.core.parser`.
2. **Deterministic Precedence:** Local task definitions override remote inferences.
3. **Fail-Safe Webhooks:** External telemetry drops or network timeouts must never abort developer commits.
4. **Strict Typing:** All taskctl core logic must pass Python 3.10+ type checks and syntax compilation.
5. **Chesterton's Fences:** Do not remove defensive timeouts, provider fallbacks, or regex protections without regression testing.
