---
name: database-migration
description: Canonical procedure for planning, authoring, testing, and executing database schema migrations with rollback support and zero-downtime expand-and-contract patterns.
---

# Database Migrations (`database-migration`)

## 1. Context and Objective
This skill instructs the agent on performing structural schema and data changes in relational databases (PostgreSQL, MySQL, SQLite, etc.) with **maximum operational safety**, ensuring changes are reversible, avoid table locking, and preserve backward compatibility (*zero-downtime migrations*).

---

## 2. When to Use (Triggers)
Activate this skill whenever the task involves:
- Creating new tables, views, or materialized views.
- Adding, renaming, modifying, or dropping columns.
- Creating or dropping indexes (`CREATE INDEX`, unique, compound).
- Adding or adjusting constraints (`FOREIGN KEY`, `CHECK`, `NOT NULL`).
- Data backfills in existing tables.

---

## 3. Associated Tools and MCP Servers
- **MCP Servers:** Database MCP servers (e.g. `postgres-mcp`) to inspect existing schema and index definitions (strictly in read-only mode).
- **CLI / Migration Tools:** Official project migration tooling (e.g., `alembic`, `prisma migrate`, `knex`, `golang-migrate`, `flyway`, `diesel`).

---

## 4. Step-by-Step Operational Procedure

### Step 1: Pre-Migration Inspection & Contracts
1. Inspect the active database schema via MCP or project model definitions.
2. Check the **Active Contracts** table in `.agent/NOTES.md` to identify dependencies on affected columns.
3. If shared across multiple services, ensure schema changes do not break active consumers.

### Step 2: Expand and Contract Pattern
To prevent breaking production during deployments when old and new code versions run concurrently:
- **Adding a required (`NOT NULL`) column:**
  1. *Phase 1 (Expand):* Add column as nullable (`NULL`) or with a safe `DEFAULT`.
  2. *Phase 2 (Backfill):* Populate existing rows if required.
  3. *Phase 3 (Contract):* Apply `NOT NULL` constraint only after all active application traffic writes the new field.
- **Renaming or removing a column:**
  1. Never drop or rename directly. Add the new column, dual-write in code, migrate reads, and prune the old column in a subsequent release.

### Step 3: Author Versioned Migration
1. Generate migration using the project's official migration tool.
2. **Mandatory Rollback:** Every migration MUST define reversible instructions (`down` or rollback script). Irreversible migrations are forbidden unless explicitly justified in `.agent/NOTES.md`.
3. Use descriptive file naming (e.g., `20260903_add_status_index_to_orders.sql`).

### Step 4: Local Validation Cycle
Before completing the task:
1. Run forward migration: `apply` / `migrate`.
2. Verify schema matches intended state.
3. Run rollback: `rollback` / `down`.
4. Verify schema cleanly returns to prior state without error.
5. Re-apply migration: `migrate` to leave the environment ready for use.

### Step 5: Update Application Models & Governance
1. Update corresponding application schemas/models (e.g., SQLAlchemy, Prisma, Pydantic, Zod).
2. If changing a shared data contract, log the update in `.agent/NOTES.md`.

---

## 5. Code Standards and Canonical Example

```sql
-- Canonical PostgreSQL Migration with safe rollback support

-- =============================================================================
-- UP: Apply Changes
-- =============================================================================
-- 1. Add column with safe default (avoids table rewrite lock in modern Postgres)
ALTER TABLE orders 
ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(32) NOT NULL DEFAULT 'PENDING';

-- 2. Create index concurrently to avoid table write locks
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_delivery_status 
ON orders (delivery_status);

-- =============================================================================
-- DOWN: Revert Changes
-- =============================================================================
-- 1. Drop the index first
DROP INDEX CONCURRENTLY IF EXISTS idx_orders_delivery_status;

-- 2. Drop the added column
ALTER TABLE orders 
DROP COLUMN IF EXISTS delivery_status;
```

---

## 6. Known Gotchas and Anti-Patterns
- ⚠️ **DO NOT:** Execute `ALTER TABLE ... DROP COLUMN` in production without prior deprecation.
- ⚠️ **DO NOT:** Mutate database schemas via ad-hoc MCP commands without committing versioned migration files to git.
- ⚠️ **DO NOT:** Create indexes on large tables without concurrent index creation (`CONCURRENTLY` in Postgres).
- 💡 **DO:** Test the full `up` $\rightarrow$ `down` $\rightarrow$ `up` cycle in the local development environment.
- 💡 **DO:** Keep migrations atomic and focused on a single entity or co-dependent set of changes.

---

## 7. Skill Completion Checklist
- [ ] Migration file created using official project tooling conventions.
- [ ] Rollback logic (`down`) implemented and verified.
- [ ] `apply` $\rightarrow$ `rollback` $\rightarrow$ `apply` cycle passes locally.
- [ ] Application models and schemas updated with matching strict types.
- [ ] Active contracts and gotchas documented in `.agent/NOTES.md`.
