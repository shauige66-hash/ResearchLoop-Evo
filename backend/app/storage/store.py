"""SQLite persistence for projects, runs, papers, and manual edits.

The store keeps a minimal schema: papers are stored as JSON blobs for flexibility,
with indexed columns for filtering. Manual edits are tracked in paper_edits.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..models.paper import FieldEvidence, Paper


class Store:
    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self.db_path = db_path or settings.db_path
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                paper_count INTEGER DEFAULT 0,
                sources TEXT,
                failed_sources TEXT,
                meta TEXT,
                source_errors TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                authors TEXT,
                publication_year INTEGER,
                venue TEXT,
                doi TEXT,
                abstract TEXT,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                is_review INTEGER DEFAULT 0,
                evidence_status TEXT,
                missing_fields TEXT,
                json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS paper_edits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL,
                field TEXT NOT NULL,
                value TEXT,
                evidence_source TEXT NOT NULL,
                evidence_span TEXT,
                note TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
            );

            CREATE INDEX IF NOT EXISTS idx_papers_run ON papers(run_id);
            CREATE INDEX IF NOT EXISTS idx_papers_project ON papers(project_id);
            CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(publication_year);
            CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
            """
        )
        self.conn.commit()

    def save_project(self, project_id: str, topic: str) -> None:
        """Insert or update a project."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO projects (id, topic, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET topic=excluded.topic, updated_at=excluded.updated_at
            """,
            (project_id, topic, now, now),
        )
        self.conn.commit()

    def save_run(self, run_id: str, project_id: str, topic: str, meta: dict, source_errors: list, paper_count: int) -> None:
        """Insert a run record."""
        now = datetime.now(timezone.utc).isoformat()
        sources = meta.get("sources_requested", [])
        failed = meta.get("sources_failed", [])
        self.conn.execute(
            """
            INSERT INTO runs (id, project_id, topic, created_at, finished_at, status, paper_count, sources, failed_sources, meta, source_errors)
            VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                topic,
                now,
                now,
                paper_count,
                json.dumps(sources),
                json.dumps(failed),
                json.dumps(meta),
                json.dumps([e.model_dump() for e in source_errors]),
            ),
        )
        self.conn.commit()

    def save_paper(self, paper: Paper, project_id: str) -> None:
        """Insert or update a paper."""
        self.conn.execute(
            """
            INSERT INTO papers (paper_id, run_id, project_id, title, authors, publication_year, venue, doi, abstract, source, source_url, is_review, evidence_status, missing_fields, json, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                run_id=excluded.run_id,
                title=excluded.title,
                authors=excluded.authors,
                publication_year=excluded.publication_year,
                venue=excluded.venue,
                doi=excluded.doi,
                abstract=excluded.abstract,
                source=excluded.source,
                source_url=excluded.source_url,
                is_review=excluded.is_review,
                evidence_status=excluded.evidence_status,
                missing_fields=excluded.missing_fields,
                json=excluded.json,
                retrieved_at=excluded.retrieved_at
            """,
            (
                paper.paper_id,
                paper.run_id,
                project_id,
                paper.title,
                json.dumps(paper.authors),
                paper.publication_year,
                paper.venue,
                paper.doi,
                paper.abstract,
                paper.source,
                paper.source_url,
                1 if paper.is_review else 0,
                paper.evidence_status,
                json.dumps(paper.missing_fields),
                paper.model_dump_json(),
                paper.retrieved_at,
            ),
        )
        self.conn.commit()

    def get_paper(self, paper_id: str) -> Paper | None:
        """Fetch a single paper by ID."""
        row = self.conn.execute("SELECT json FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
        if not row:
            return None
        return Paper.model_validate_json(row["json"])

    def list_papers(
        self,
        project_id: str | None = None,
        run_id: str | None = None,
        year: int | None = None,
        source: str | None = None,
        is_review: bool | None = None,
        evidence_status: str | None = None,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Paper], int]:
        """List papers with filters and pagination."""
        conditions: list[str] = []
        params: list[Any] = []

        if project_id:
            conditions.append("project_id=?")
            params.append(project_id)
        if run_id:
            conditions.append("run_id=?")
            params.append(run_id)
        if year:
            conditions.append("publication_year=?")
            params.append(year)
        if source:
            conditions.append("source=?")
            params.append(source)
        if is_review is not None:
            conditions.append("is_review=?")
            params.append(1 if is_review else 0)
        if evidence_status:
            conditions.append("evidence_status=?")
            params.append(evidence_status)
        if query:
            conditions.append("(title LIKE ? OR abstract LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        where = " AND ".join(conditions) if conditions else "1=1"

        # Count total
        count_row = self.conn.execute(f"SELECT COUNT(*) as cnt FROM papers WHERE {where}", params).fetchone()
        total = count_row["cnt"]

        # Fetch page
        offset = (page - 1) * page_size
        rows = self.conn.execute(
            f"SELECT json FROM papers WHERE {where} ORDER BY publication_year DESC, title LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        papers = [Paper.model_validate_json(row["json"]) for row in rows]
        return papers, total

    def update_paper_field(self, paper_id: str, field: str, evidence: FieldEvidence, note: str | None = None) -> Paper | None:
        """Manually update a paper field (e.g., after human review)."""
        paper = self.get_paper(paper_id)
        if not paper:
            return None

        # Update the field
        setattr(paper, field, evidence)
        paper.retrieved_at = datetime.now(timezone.utc).isoformat()

        # Save updated paper
        self.conn.execute(
            "UPDATE papers SET json=?, evidence_status=?, missing_fields=?, retrieved_at=? WHERE paper_id=?",
            (
                paper.model_dump_json(),
                paper.evidence_status,
                json.dumps(paper.missing_fields),
                paper.retrieved_at,
                paper_id,
            ),
        )

        # Record the edit
        self.conn.execute(
            """
            INSERT INTO paper_edits (paper_id, field, value, evidence_source, evidence_span, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                field,
                evidence.value,
                evidence.evidence_source,
                evidence.evidence_span,
                note,
                evidence.updated_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return paper

    def list_runs(self, project_id: str | None = None) -> list[dict]:
        """List all runs, optionally filtered by project."""
        if project_id:
            rows = self.conn.execute(
                "SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


_store: Store | None = None


def get_store() -> Store:
    """Get or create the global Store instance."""
    global _store
    if _store is None:
        _store = Store()
    return _store
