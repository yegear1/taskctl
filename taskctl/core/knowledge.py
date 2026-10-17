"""Knowledge Cards Engine (K-Cards) with SQLite FTS5 and BM25 ranking.

Provides sub-millisecond lookup, incremental synchronization based on mtime,
error keyword reflex detection, and zero external dependencies (pure Python stdlib).
"""

import os
import re
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

from taskctl.core.parser import resolve_repo_path, find_repo_root


@dataclass
class KnowledgeCard:
    """In-memory representation of a Knowledge Card."""

    id: str
    title: str
    type: str = "gotcha"
    components: List[str] = field(default_factory=list)
    error_keywords: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    invariants_affected: List[str] = field(default_factory=list)
    problem: str = ""
    solution: str = ""
    never_do: str = ""
    filepath: str = ""
    mtime: float = 0.0
    raw_content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "components": self.components,
            "error_keywords": self.error_keywords,
            "platforms": self.platforms,
            "invariants_affected": self.invariants_affected,
            "problem": self.problem,
            "solution": self.solution,
            "never_do": self.never_do,
            "filepath": self.filepath,
            "mtime": self.mtime,
        }


def _parse_yaml_value(val: str) -> Any:
    """Parse a primitive YAML value (string, list, or inline list)."""
    val = val.strip()
    if not val:
        return ""
    # Inline list: [a, b, c]
    if val.startswith("[") and val.endswith("]"):
        items = val[1:-1].split(",")
        return [i.strip().strip("'\"") for i in items if i.strip()]
    # Strip quotes
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def parse_yaml_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter delimited by `---` at the start of content.

    Returns:
        (frontmatter_dict, markdown_body)
    """
    if not content.startswith("---"):
        return {}, content

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}, content

    yaml_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:]).strip()

    frontmatter: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None

    for line in yaml_lines:
        raw_line = line
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for list item under current_key
        if stripped.startswith("- ") and current_key is not None:
            item_val = stripped[2:].strip().strip("'\"")
            if current_list is None:
                current_list = []
                frontmatter[current_key] = current_list
            current_list.append(item_val)
            continue

        # Check for key: value
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", stripped)
        if match:
            k = match.group(1).strip()
            v = match.group(2).strip()
            current_key = k
            current_list = None

            if not v or v in ["|", ">"]:
                # Multi-line or pending list
                frontmatter[k] = []
                current_list = frontmatter[k]
            else:
                frontmatter[k] = _parse_yaml_value(v)
        else:
            # Continuation of previous value if multiline string
            if current_key and isinstance(frontmatter.get(current_key), str):
                frontmatter[current_key] += "\n" + stripped

    return frontmatter, body


def _extract_markdown_section(body: str, section_names: List[str]) -> str:
    """Extract content of a markdown section (e.g. ## Problem or ## Solution)."""
    pattern = (
        r"(?:^|\n)#{1,4}\s*(?:"
        + "|".join(re.escape(name) for name in section_names)
        + r")[^\n]*\n(.*?)(?=\n#{1,4}\s+[^\n]+|$)"
    )
    match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _normalize_string_list(val: Any) -> List[str]:
    """Ensure value is a list of strings."""
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        # Might be comma-separated
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def parse_knowledge_card(content: str, filepath: str = "", mtime: float = 0.0) -> KnowledgeCard:
    """Parse Knowledge Card from Markdown with YAML frontmatter."""
    fm, body = parse_yaml_frontmatter(content)

    stem_id = Path(filepath).stem if filepath else "K-UNKNOWN"
    card_id = str(fm.get("id") or "").strip() or stem_id

    # Title extraction: frontmatter -> first markdown H1 -> filename stem
    title = str(fm.get("title") or "").strip()
    if not title:
        h1_match = re.search(r"^#\s+([^\n]+)", body, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
        else:
            title = stem_id

    card_type = str(fm.get("type") or "gotcha").strip()

    components = _normalize_string_list(fm.get("components"))
    error_keywords = _normalize_string_list(fm.get("error_keywords"))
    platforms = _normalize_string_list(fm.get("platforms"))
    invariants_affected = _normalize_string_list(fm.get("invariants_affected"))

    # Extract problem, solution, never_do from frontmatter or markdown sections
    problem = str(fm.get("problem") or "").strip()
    if not problem:
        problem = _extract_markdown_section(body, ["Problem", "Context", "Issue", "Failure Mode"])

    solution = str(fm.get("solution") or "").strip()
    if not solution:
        solution = _extract_markdown_section(body, ["Solution", "Remediation", "Fix", "Prescription"])

    never_do = str(fm.get("never_do") or "").strip()
    if not never_do:
        never_do = _extract_markdown_section(
            body, ["Never Do", "Anti-Patterns", "What Not To Do", "Pitfalls"]
        )

    # If body has content but problem is empty, default body to problem
    if not problem and not solution and not never_do and body:
        problem = body

    return KnowledgeCard(
        id=card_id,
        title=title,
        type=card_type,
        components=components,
        error_keywords=error_keywords,
        platforms=platforms,
        invariants_affected=invariants_affected,
        problem=problem,
        solution=solution,
        never_do=never_do,
        filepath=filepath,
        mtime=mtime,
        raw_content=content,
    )


class KnowledgeEngine:
    """SQLite FTS5 full-text search and error reflex engine for Knowledge Cards."""

    def __init__(
        self,
        repo_path: Optional[str] = None,
        db_path: Optional[str] = None,
        knowledge_dir: Optional[str] = None,
    ):
        if repo_path:
            self.repo_root = resolve_repo_path(repo_path)
        else:
            self.repo_root = find_repo_root()

        if db_path:
            self.db_path = os.path.abspath(db_path)
        else:
            self.db_path = os.path.join(self.repo_root, ".agent", ".cache", "knowledge.db")

        if knowledge_dir:
            self.knowledge_dir = os.path.abspath(knowledge_dir)
        else:
            self.knowledge_dir = os.path.join(self.repo_root, ".agent", "knowledge")

        self._conn: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for high concurrency & performance
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass

        # Metadata table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_meta (
                id TEXT PRIMARY KEY,
                filepath TEXT UNIQUE,
                mtime REAL,
                title TEXT,
                type TEXT,
                components TEXT,
                error_keywords TEXT,
                platforms TEXT,
                invariants_affected TEXT,
                problem TEXT,
                solution TEXT,
                never_do TEXT,
                raw_content TEXT
            );
            """
        )

        # FTS5 virtual table with Porter stemmer & unicode61 tokenizer
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                id UNINDEXED,
                title,
                type,
                components,
                error_keywords,
                platforms,
                invariants_affected,
                problem,
                solution,
                never_do,
                tokenize='porter unicode61'
            );
            """
        )
        conn.commit()
        self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "KnowledgeEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def sync(self, force: bool = False) -> int:
        """Incrementally synchronize markdown cards from knowledge directory into SQLite FTS5.

        Uses file mtime for sub-millisecond change detection.
        Returns total number of cards currently in database.
        """
        # Graceful fail-open when directory does not exist
        if not os.path.isdir(self.knowledge_dir):
            if os.path.exists(self.db_path):
                # Clean up deleted references
                conn = self._get_connection()
                conn.execute("DELETE FROM knowledge_meta;")
                conn.execute("DELETE FROM knowledge_fts;")
                conn.commit()
            return 0

        conn = self._get_connection()

        # Existing metadata map: {filepath: (id, mtime)}
        cur = conn.execute("SELECT filepath, id, mtime FROM knowledge_meta")
        db_records = {row["filepath"]: (row["id"], float(row["mtime"])) for row in cur.fetchall()}

        disk_files: Dict[str, float] = {}
        for root, _, files in os.walk(self.knowledge_dir):
            for file in files:
                if file.endswith(".md"):
                    abs_p = os.path.abspath(os.path.join(root, file))
                    try:
                        disk_files[abs_p] = os.path.getmtime(abs_p)
                    except OSError:
                        pass

        # 1. Prune removed files
        to_delete = [p for p in db_records if p not in disk_files]
        for p in to_delete:
            card_id = db_records[p][0]
            conn.execute("DELETE FROM knowledge_meta WHERE filepath = ?", (p,))
            conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (card_id,))

        # 2. Upsert new / modified files
        for p, mtime in disk_files.items():
            needs_update = force or (p not in db_records) or (mtime > db_records[p][1])
            if not needs_update:
                continue

            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            card = parse_knowledge_card(content, filepath=p, mtime=mtime)

            # Delete old entry in FTS if ID changed or updating
            if p in db_records:
                old_id = db_records[p][0]
                conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (old_id,))
            else:
                conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (card.id,))

            # Upsert into knowledge_meta
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_meta (
                    id, filepath, mtime, title, type, components, error_keywords,
                    platforms, invariants_affected, problem, solution, never_do, raw_content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.id,
                    card.filepath,
                    card.mtime,
                    card.title,
                    card.type,
                    json.dumps(card.components),
                    json.dumps(card.error_keywords),
                    json.dumps(card.platforms),
                    json.dumps(card.invariants_affected),
                    card.problem,
                    card.solution,
                    card.never_do,
                    card.raw_content,
                ),
            )

            # Insert into knowledge_fts
            conn.execute(
                """
                INSERT INTO knowledge_fts (
                    id, title, type, components, error_keywords,
                    platforms, invariants_affected, problem, solution, never_do
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.id,
                    card.title,
                    card.type,
                    " ".join(card.components),
                    " ".join(card.error_keywords),
                    " ".join(card.platforms),
                    " ".join(card.invariants_affected),
                    card.problem,
                    card.solution,
                    card.never_do,
                ),
            )

        conn.commit()

        count_cur = conn.execute("SELECT COUNT(*) as cnt FROM knowledge_meta")
        return int(count_cur.fetchone()["cnt"])

    def _row_to_card(self, row: sqlite3.Row) -> KnowledgeCard:
        """Convert a database row from knowledge_meta to KnowledgeCard."""
        return KnowledgeCard(
            id=row["id"],
            title=row["title"],
            type=row["type"],
            components=json.loads(row["components"] or "[]"),
            error_keywords=json.loads(row["error_keywords"] or "[]"),
            platforms=json.loads(row["platforms"] or "[]"),
            invariants_affected=json.loads(row["invariants_affected"] or "[]"),
            problem=row["problem"] or "",
            solution=row["solution"] or "",
            never_do=row["never_do"] or "",
            filepath=row["filepath"] or "",
            mtime=float(row["mtime"] or 0.0),
            raw_content=row["raw_content"] or "",
        )

    def search(
        self,
        query: str,
        component: Optional[str] = None,
        limit: int = 10,
    ) -> List[Tuple[KnowledgeCard, float]]:
        """Search knowledge base with SQLite FTS5 BM25 ranking.

        Returns list of (card, score) sorted by relevance.
        """
        self.sync()

        conn = self._get_connection()
        clean_query = query.strip()

        # If query is empty or '*', return all cards sorted by title
        if not clean_query or clean_query == "*":
            sql = "SELECT * FROM knowledge_meta"
            params: List[Any] = []
            if component:
                sql += " WHERE components LIKE ?"
                params.append(f'%"{component}"%')
            sql += " ORDER BY title ASC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [(self._row_to_card(r), 0.0) for r in rows]

        # Extract tokens for FTS5 syntax safety
        tokens = re.findall(r"[\w\-]+", clean_query)
        if not tokens:
            return []

        # Sanitize tokens to avoid FTS5 syntax errors
        fts_query = " ".join([f'"{t}"' for t in tokens])

        sql = """
            SELECT m.*, bm25(knowledge_fts) as rank
            FROM knowledge_fts
            JOIN knowledge_meta m ON knowledge_fts.id = m.id
            WHERE knowledge_fts MATCH ?
        """
        params = [fts_query]

        if component:
            sql += " AND m.components LIKE ?"
            params.append(f'%"{component}"%')

        sql += " ORDER BY bm25(knowledge_fts) ASC LIMIT ?"
        params.append(limit)

        try:
            cur = conn.execute(sql, params)
            results = cur.fetchall()
        except sqlite3.OperationalError:
            # Fallback to LIKE query if FTS expression failed
            sql_fallback = """
                SELECT *, 0.0 as rank FROM knowledge_meta
                WHERE (title LIKE ? OR problem LIKE ? OR solution LIKE ? OR error_keywords LIKE ?)
            """
            p = f"%{clean_query}%"
            params_fb: List[Any] = [p, p, p, p]
            if component:
                sql_fallback += " AND components LIKE ?"
                params_fb.append(f'%"{component}"%')
            sql_fallback += " LIMIT ?"
            params_fb.append(limit)
            results = conn.execute(sql_fallback, params_fb).fetchall()

        cards: List[Tuple[KnowledgeCard, float]] = []
        for r in results:
            card = self._row_to_card(r)
            # In SQLite bm25, lower is better (negative float). We normalize to positive score for clarity.
            raw_rank = float(r["rank"]) if "rank" in r.keys() else 0.0
            score = round(abs(raw_rank), 8)
            cards.append((card, score))

        return cards

    def reflex(
        self,
        stderr_content: str,
        limit: int = 5,
    ) -> List[Tuple[KnowledgeCard, float, List[str]]]:
        """Perform headless error signature matching against stderr and stack traces.

        Matches stderr against card `error_keywords` and ranks candidate cards.
        Returns list of (card, reflex_score, matched_keywords).
        """
        self.sync()

        if not stderr_content or not stderr_content.strip():
            return []

        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM knowledge_meta")
        all_rows = cur.fetchall()

        if not all_rows:
            return []

        stderr_lower = stderr_content.lower()
        candidates: List[Tuple[KnowledgeCard, float, List[str]]] = []

        for row in all_rows:
            card = self._row_to_card(row)
            matched_keywords: List[str] = []

            # 1. Match error_keywords
            for kw in card.error_keywords:
                kw_clean = kw.strip().lower()
                if kw_clean and kw_clean in stderr_lower:
                    matched_keywords.append(kw)

            # 2. Match invariants affected
            for inv in card.invariants_affected:
                inv_clean = inv.strip().lower()
                if inv_clean and inv_clean in stderr_lower:
                    matched_keywords.append(inv)

            # Calculate reflex score
            score = 0.0
            if matched_keywords:
                # Strong signal: keyword match in stderr
                score += len(matched_keywords) * 10.0
                # Extra weight for title or problem overlap
                if card.title.lower() in stderr_lower:
                    score += 5.0
                candidates.append((card, score, matched_keywords))

        # If no error_keywords matched directly, attempt FTS query on error lines
        if not candidates:
            # Extract exception types and last non-empty lines
            err_lines = [l.strip() for l in stderr_content.splitlines() if l.strip()]
            search_terms: List[str] = []
            for line in err_lines[-5:]:
                # Extract words like OperationalError, FileNotFoundError, etc.
                matches = re.findall(r"([A-Za-z0-9_]+(?:Error|Exception|Fault|Fail|Failed))", line)
                search_terms.extend(matches)

            if search_terms:
                fts_query = " OR ".join(set(search_terms))
                fts_results = self.search(fts_query, limit=limit)
                for c, s in fts_results:
                    candidates.append((c, max(1.0, s), []))

        # Sort candidates descending by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:limit]
