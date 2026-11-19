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
from ..models.evolution import EvolutionRound
from ..models.experiment import BenchmarkCase, ExperimentRun, ExperimentSpec
from ..models.gap import ResearchGap
from ..models.gap_pipeline import EvidenceCard, GapPipelineRun
from ..models.llm import BILLABLE_STATUSES, LLMCallRecord
from ..models.paper import FieldEvidence, Paper
from ..models.skill import SkillVersion
from ..models.workflow import WorkflowRun


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

            CREATE TABLE IF NOT EXISTS gaps (
                gap_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                gap_type TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence_label TEXT NOT NULL,
                title TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS gap_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gap_id TEXT NOT NULL,
                status TEXT NOT NULL,
                human_note TEXT,
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY (gap_id) REFERENCES gaps(gap_id)
            );

            CREATE INDEX IF NOT EXISTS idx_gaps_run ON gaps(run_id);
            CREATE INDEX IF NOT EXISTS idx_gaps_status ON gaps(status);

            CREATE TABLE IF NOT EXISTS benchmark_cases (
                case_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                split TEXT NOT NULL,
                reference_status TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiment_specs (
                spec_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiment_runs (
                run_id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                arm TEXT NOT NULL,
                split TEXT NOT NULL,
                skill_version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS skill_versions (
                version_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                parent_version TEXT,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evolution_rounds (
                round_id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                parent_version_id TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cases_split ON benchmark_cases(split);
            CREATE INDEX IF NOT EXISTS idx_expruns_spec ON experiment_runs(spec_id);
            CREATE INDEX IF NOT EXISTS idx_expruns_case ON experiment_runs(case_id);
            CREATE INDEX IF NOT EXISTS idx_skills_status ON skill_versions(skill_id, status);
            CREATE INDEX IF NOT EXISTS idx_evorounds_spec ON evolution_rounds(spec_id);

            CREATE TABLE IF NOT EXISTS llm_calls (
                request_id TEXT PRIMARY KEY,
                agent_role TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                pipeline_id TEXT,
                paper_id TEXT,
                prompt_version TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                response_hash TEXT,
                latency_ms INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                error TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                agent_role TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_cards (
                paper_id TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                abstract_hash TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (paper_id, prompt_version)
            );

            CREATE TABLE IF NOT EXISTS gap_pipelines (
                pipeline_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                run_id TEXT NOT NULL,
                workflow_id TEXT,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_llmcalls_role ON llm_calls(agent_role);
            CREATE INDEX IF NOT EXISTS idx_llmcalls_pipeline ON llm_calls(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_cards_pipeline ON evidence_cards(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_pipelines_workflow ON gap_pipelines(workflow_id);
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

        # Update the field, then re-run validation so evidence_status and
        # missing_fields are re-derived rather than left stale.
        setattr(paper, field, evidence)
        paper = Paper.model_validate(paper.model_dump())
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

    # -------------------------------------------------------------------- gaps
    def save_gap(self, gap: ResearchGap) -> None:
        self.conn.execute(
            """
            INSERT INTO gaps (gap_id, run_id, gap_type, status, confidence_label, title, json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gap_id) DO UPDATE SET
                status=excluded.status,
                confidence_label=excluded.confidence_label,
                title=excluded.title,
                json=excluded.json,
                updated_at=excluded.updated_at
            """,
            (
                gap.gap_id,
                gap.run_id,
                gap.gap_type,
                gap.status,
                gap.confidence_label,
                gap.title,
                gap.model_dump_json(),
                gap.created_at,
                gap.updated_at,
            ),
        )
        self.conn.commit()

    def get_gap(self, gap_id: str) -> ResearchGap | None:
        row = self.conn.execute("SELECT json FROM gaps WHERE gap_id=?", (gap_id,)).fetchone()
        return ResearchGap.model_validate_json(row["json"]) if row else None

    def list_gaps(
        self,
        run_id: str | None = None,
        status: str | None = None,
        gap_type: str | None = None,
    ) -> list[ResearchGap]:
        conditions: list[str] = []
        params: list[Any] = []
        if run_id:
            conditions.append("run_id=?")
            params.append(run_id)
        if status:
            conditions.append("status=?")
            params.append(status)
        if gap_type:
            conditions.append("gap_type=?")
            params.append(gap_type)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self.conn.execute(
            f"SELECT json FROM gaps WHERE {where} ORDER BY created_at DESC", params
        ).fetchall()
        return [ResearchGap.model_validate_json(row["json"]) for row in rows]

    def review_gap(
        self,
        gap_id: str,
        status: str,
        human_note: str | None = None,
        edits: dict[str, str] | None = None,
    ) -> ResearchGap | None:
        gap = self.get_gap(gap_id)
        if not gap:
            return None
        for field, value in (edits or {}).items():
            setattr(gap, field, value)
        gap.status = status
        gap.human_note = human_note
        gap.updated_at = datetime.now(timezone.utc).isoformat()
        gap = ResearchGap.model_validate(gap.model_dump())
        self.save_gap(gap)
        self.conn.execute(
            "INSERT INTO gap_reviews (gap_id, status, human_note, reviewed_at) VALUES (?, ?, ?, ?)",
            (gap_id, status, human_note, gap.updated_at),
        )
        self.conn.commit()
        return gap

    def list_gap_reviews(self, gap_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM gap_reviews WHERE gap_id=? ORDER BY reviewed_at", (gap_id,)
        ).fetchall()
        return [dict(row) for row in rows]

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

    # ------------------------------------------------------------- benchmark
    def save_benchmark_case(self, case: "BenchmarkCase") -> None:
        self.conn.execute(
            """
            INSERT INTO benchmark_cases (case_id, topic, split, reference_status, json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                topic=excluded.topic, split=excluded.split,
                reference_status=excluded.reference_status, json=excluded.json
            """,
            (
                case.case_id, case.topic, case.split, case.reference_status,
                case.model_dump_json(), case.created_at or _now(),
            ),
        )
        self.conn.commit()

    def get_benchmark_case(self, case_id: str) -> "BenchmarkCase | None":
        row = self.conn.execute(
            "SELECT json FROM benchmark_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        return BenchmarkCase.model_validate_json(row["json"]) if row else None

    def list_benchmark_cases(
        self, split: str | None = None, reference_status: str | None = None
    ) -> list["BenchmarkCase"]:
        query = "SELECT json FROM benchmark_cases"
        clauses, params = [], []
        if split:
            clauses.append("split=?")
            params.append(split)
        if reference_status:
            clauses.append("reference_status=?")
            params.append(reference_status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY topic, case_id"
        return [
            BenchmarkCase.model_validate_json(r["json"])
            for r in self.conn.execute(query, params).fetchall()
        ]

    # --------------------------------------------------------- experiment spec
    def save_spec(self, spec: "ExperimentSpec") -> None:
        self.conn.execute(
            """
            INSERT INTO experiment_specs (spec_id, template_id, json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(spec_id) DO UPDATE SET json=excluded.json
            """,
            (spec.spec_id, spec.template_id, spec.model_dump_json(), spec.created_at or _now()),
        )
        self.conn.commit()

    def get_spec(self, spec_id: str) -> "ExperimentSpec | None":
        row = self.conn.execute(
            "SELECT json FROM experiment_specs WHERE spec_id=?", (spec_id,)
        ).fetchone()
        return ExperimentSpec.model_validate_json(row["json"]) if row else None

    def list_specs(self) -> list["ExperimentSpec"]:
        rows = self.conn.execute(
            "SELECT json FROM experiment_specs ORDER BY created_at DESC"
        ).fetchall()
        return [ExperimentSpec.model_validate_json(r["json"]) for r in rows]

    # ---------------------------------------------------------- experiment run
    def save_experiment_run(self, run: "ExperimentRun", split: str) -> None:
        self.conn.execute(
            """
            INSERT INTO experiment_runs
                (run_id, spec_id, case_id, arm, split, skill_version_id, status, json,
                 started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status, json=excluded.json, finished_at=excluded.finished_at
            """,
            (
                run.run_id, run.spec_id, run.case_id, run.arm, split,
                run.skill_version_id, run.status, run.model_dump_json(),
                run.started_at or _now(), run.finished_at,
            ),
        )
        self.conn.commit()

    def get_experiment_run(self, run_id: str) -> "ExperimentRun | None":
        row = self.conn.execute(
            "SELECT json FROM experiment_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return ExperimentRun.model_validate_json(row["json"]) if row else None

    def list_experiment_runs(
        self,
        spec_id: str | None = None,
        case_id: str | None = None,
        arm: str | None = None,
        split: str | None = None,
    ) -> list["ExperimentRun"]:
        query = "SELECT json FROM experiment_runs"
        clauses, params = [], []
        for column, value in (
            ("spec_id", spec_id), ("case_id", case_id), ("arm", arm), ("split", split)
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC"
        return [
            ExperimentRun.model_validate_json(r["json"])
            for r in self.conn.execute(query, params).fetchall()
        ]

    # ------------------------------------------------------------ skill registry
    def save_skill_version(self, version: "SkillVersion") -> None:
        """Versions are immutable: an existing version_id is never rewritten."""
        existing = self.conn.execute(
            "SELECT version_id FROM skill_versions WHERE version_id=?", (version.version_id,)
        ).fetchone()
        if existing:
            raise ValueError(f"skill version {version.version_id} already exists and is immutable")
        self.conn.execute(
            """
            INSERT INTO skill_versions
                (version_id, skill_id, version_number, status, parent_version, json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.version_id, version.skill_id, version.version_number,
                version.status, version.parent_version, version.model_dump_json(),
                version.created_at or _now(),
            ),
        )
        self.conn.commit()

    def get_skill_version(self, version_id: str) -> "SkillVersion | None":
        row = self.conn.execute(
            "SELECT json FROM skill_versions WHERE version_id=?", (version_id,)
        ).fetchone()
        return SkillVersion.model_validate_json(row["json"]) if row else None

    def list_skill_versions(
        self, skill_id: str | None = None, status: str | None = None
    ) -> list["SkillVersion"]:
        query = "SELECT json FROM skill_versions"
        clauses, params = [], []
        if skill_id:
            clauses.append("skill_id=?")
            params.append(skill_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY version_number DESC"
        return [
            SkillVersion.model_validate_json(r["json"])
            for r in self.conn.execute(query, params).fetchall()
        ]

    def set_skill_status(self, version_id: str, status: str) -> "SkillVersion | None":
        version = self.get_skill_version(version_id)
        if not version:
            return None
        version.status = status  # type: ignore[assignment]
        self.conn.execute(
            "UPDATE skill_versions SET status=?, json=? WHERE version_id=?",
            (status, version.model_dump_json(), version_id),
        )
        self.conn.commit()
        return version

    def next_version_number(self, skill_id: str) -> int:
        row = self.conn.execute(
            "SELECT MAX(version_number) AS n FROM skill_versions WHERE skill_id=?", (skill_id,)
        ).fetchone()
        return int(row["n"] or 0) + 1

    def add_skill_event(self, version_id: str, event: str, detail: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO skill_events (version_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
            (version_id, event, json.dumps(detail or {}, ensure_ascii=False), _now()),
        )
        self.conn.commit()

    def list_skill_events(self, version_id: str | None = None) -> list[dict]:
        if version_id:
            rows = self.conn.execute(
                "SELECT * FROM skill_events WHERE version_id=? ORDER BY id", (version_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM skill_events ORDER BY id").fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"] or "{}")
            out.append(item)
        return out

    def save_evolution_round(self, record: "EvolutionRound") -> None:
        self.conn.execute(
            "INSERT INTO evolution_rounds (round_id, spec_id, parent_version_id, json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                record.round_id,
                record.spec_id,
                record.parent_version_id,
                record.model_dump_json(),
                record.created_at or _now(),
            ),
        )
        self.conn.commit()

    def get_evolution_round(self, round_id: str) -> "EvolutionRound | None":
        row = self.conn.execute(
            "SELECT json FROM evolution_rounds WHERE round_id=?", (round_id,)
        ).fetchone()
        return EvolutionRound.model_validate_json(row["json"]) if row else None

    def list_evolution_rounds(self, spec_id: str | None = None) -> list["EvolutionRound"]:
        if spec_id:
            rows = self.conn.execute(
                "SELECT json FROM evolution_rounds WHERE spec_id=? ORDER BY created_at DESC",
                (spec_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT json FROM evolution_rounds ORDER BY created_at DESC"
            ).fetchall()
        return [EvolutionRound.model_validate_json(r["json"]) for r in rows]

    def save_workflow(self, workflow: "WorkflowRun") -> None:
        """Upsert the whole workflow state so a crash never loses completed steps."""
        now = _now()
        self.conn.execute(
            """
            INSERT INTO workflows (workflow_id, topic, status, current_step, json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                status=excluded.status,
                current_step=excluded.current_step,
                json=excluded.json,
                updated_at=excluded.updated_at
            """,
            (
                workflow.workflow_id,
                workflow.topic,
                workflow.status,
                workflow.current_step,
                workflow.model_dump_json(),
                workflow.created_at or now,
                now,
            ),
        )
        self.conn.commit()

    def get_workflow(self, workflow_id: str) -> "WorkflowRun | None":
        row = self.conn.execute(
            "SELECT json FROM workflows WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        return WorkflowRun.model_validate_json(row["json"]) if row else None

    def list_workflows(self) -> list["WorkflowRun"]:
        rows = self.conn.execute(
            "SELECT json FROM workflows ORDER BY created_at DESC"
        ).fetchall()
        return [WorkflowRun.model_validate_json(r["json"]) for r in rows]

    # ------------------------------------------------- LLM audit, cache, cards
    def record_llm_call(self, record: "LLMCallRecord") -> None:
        """Append one audit row. Hashes only: no prompt text, no API key."""
        self.conn.execute(
            """
            INSERT INTO llm_calls (request_id, agent_role, provider, model, status, pipeline_id,
                paper_id, prompt_version, prompt_hash, response_hash, latency_ms, prompt_tokens,
                completion_tokens, total_tokens, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET status=excluded.status, error=excluded.error
            """,
            (
                record.request_id,
                record.agent_role,
                record.provider,
                record.model,
                record.status,
                record.pipeline_id,
                record.paper_id,
                record.prompt_version,
                record.prompt_hash,
                record.response_hash,
                record.latency_ms,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.error,
                record.created_at or _now(),
            ),
        )
        self.conn.commit()

    def list_llm_calls(
        self, pipeline_id: str | None = None, agent_role: str | None = None
    ) -> list["LLMCallRecord"]:
        sql = "SELECT * FROM llm_calls"
        clauses: list[str] = []
        params: list[Any] = []
        if pipeline_id:
            clauses.append("pipeline_id=?")
            params.append(pipeline_id)
        if agent_role:
            clauses.append("agent_role=?")
            params.append(agent_role)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql + " ORDER BY created_at, request_id", params).fetchall()
        return [LLMCallRecord.model_validate(dict(r)) for r in rows]

    def count_llm_attempts(self, agent_role: str | None = None) -> int:
        """Real HTTP attempts only. Cache hits and refusals never consume budget."""
        placeholders = ",".join("?" for _ in BILLABLE_STATUSES)
        sql = f"SELECT COUNT(*) AS n FROM llm_calls WHERE status IN ({placeholders})"
        params: list[Any] = sorted(BILLABLE_STATUSES)
        if agent_role:
            sql += " AND agent_role=?"
            params.append(agent_role)
        row = self.conn.execute(sql, params).fetchone()
        return int(row["n"] or 0)

    def read_llm_cache(self, cache_key: str) -> str | None:
        row = self.conn.execute(
            "SELECT content FROM llm_cache WHERE cache_key=?", (cache_key,)
        ).fetchone()
        return row["content"] if row else None

    def write_llm_cache(
        self, cache_key: str, agent_role: str, model: str, prompt_version: str, content: str
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO llm_cache (cache_key, agent_role, model, prompt_version, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET content=excluded.content
            """,
            (cache_key, agent_role, model, prompt_version, content, _now()),
        )
        self.conn.commit()

    def save_evidence_card(self, card: "EvidenceCard") -> None:
        self.conn.execute(
            """
            INSERT INTO evidence_cards (paper_id, prompt_version, pipeline_id, abstract_hash, json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id, prompt_version) DO UPDATE SET
                pipeline_id=excluded.pipeline_id,
                abstract_hash=excluded.abstract_hash,
                json=excluded.json
            """,
            (
                card.paper_id,
                card.prompt_version,
                card.pipeline_id,
                card.abstract_hash,
                card.model_dump_json(),
                _now(),
            ),
        )
        self.conn.commit()

    def get_evidence_card(self, paper_id: str, prompt_version: str) -> "EvidenceCard | None":
        row = self.conn.execute(
            "SELECT json FROM evidence_cards WHERE paper_id=? AND prompt_version=?",
            (paper_id, prompt_version),
        ).fetchone()
        return EvidenceCard.model_validate_json(row["json"]) if row else None

    def list_evidence_cards(self, pipeline_id: str | None = None) -> list["EvidenceCard"]:
        if pipeline_id:
            rows = self.conn.execute(
                "SELECT json FROM evidence_cards WHERE pipeline_id=? ORDER BY paper_id",
                (pipeline_id,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT json FROM evidence_cards ORDER BY paper_id").fetchall()
        return [EvidenceCard.model_validate_json(r["json"]) for r in rows]

    def save_gap_pipeline(self, pipeline: "GapPipelineRun") -> None:
        """Upsert the whole pipeline state so resume never re-runs finished stages."""
        now = _now()
        self.conn.execute(
            """
            INSERT INTO gap_pipelines (pipeline_id, topic, run_id, workflow_id, status,
                current_stage, json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pipeline_id) DO UPDATE SET
                status=excluded.status,
                current_stage=excluded.current_stage,
                json=excluded.json,
                updated_at=excluded.updated_at
            """,
            (
                pipeline.pipeline_id,
                pipeline.topic,
                pipeline.run_id,
                pipeline.workflow_id,
                pipeline.status,
                pipeline.current_stage,
                pipeline.model_dump_json(),
                pipeline.created_at or now,
                now,
            ),
        )
        self.conn.commit()

    def get_gap_pipeline(self, pipeline_id: str) -> "GapPipelineRun | None":
        row = self.conn.execute(
            "SELECT json FROM gap_pipelines WHERE pipeline_id=?", (pipeline_id,)
        ).fetchone()
        return GapPipelineRun.model_validate_json(row["json"]) if row else None

    def list_gap_pipelines(self, workflow_id: str | None = None) -> list["GapPipelineRun"]:
        if workflow_id:
            rows = self.conn.execute(
                "SELECT json FROM gap_pipelines WHERE workflow_id=? ORDER BY created_at DESC",
                (workflow_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT json FROM gap_pipelines ORDER BY created_at DESC"
            ).fetchall()
        return [GapPipelineRun.model_validate_json(r["json"]) for r in rows]

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
