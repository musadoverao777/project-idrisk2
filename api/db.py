"""
IDRISK2 — Camada de base de dados (SQLAlchemy).

Suporta PostgreSQL (recomendado) e SQLite (reserva), selecionado pela variável
de ambiente DATABASE_URL ou pelas componentes PGHOST/PGUSER/PGPASSWORD/...

Tabelas:
- users                  utilizadores do sistema (RBAC)
- classifications        resultado de cada classificação FoodEx2
- classification_facets  facetas FoodEx2 normalizadas (1 linha por faceta)
- reviews                fila e decisões de revisão humana (human-in-the-loop)
- audit_logs             registo de auditoria à prova de adulteração (HMAC)

As tabelas são criadas automaticamente no arranque (create_all). Há funções
de seed/migração para popular utilizadores e importar os dados já existentes.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, URL

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_metadata = MetaData()

# ---------------------------------------------------------------------------
# Definição das tabelas
# ---------------------------------------------------------------------------
users = Table(
    "users",
    _metadata,
    Column("id", String(64), primary_key=True),
    Column("username", String(64), nullable=False, unique=True),
    Column("email", String(160)),
    Column("role", String(20), nullable=False),       # inspector|supervisor|administrator|auditor
    Column("status", String(16), default="active"),   # active|inactive
    Column("created_at", String(40)),
    Column("password_hash", String(255)),             # reservado para autenticação futura
)

classifications = Table(
    "classifications",
    _metadata,
    Column("id", String(64), primary_key=True),
    Column("timestamp", String(40), nullable=False, index=True),
    Column("base_term_code", String(64)),
    Column("base_term_label", Text),
    Column("facets", Text),                            # JSON (cópia de conveniência)
    Column("confidence", String(16)),
    Column("requires_human_review", Boolean, default=False),
    Column("review_status", String(16), default="none"),
    Column("ocr_text", Text),
    Column("image_hash", String(128)),
    Column("submitted_by", String(64), ForeignKey("users.id")),
    Column("total_time_ms", Float),
)

classification_facets = Table(
    "classification_facets",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "classification_id",
        String(64),
        ForeignKey("classifications.id", ondelete="CASCADE"),
        index=True,
    ),
    Column("facet_group", String(16)),                 # ex.: F01, F04, F27
    Column("facet_code", String(64)),                  # ex.: A0F4B
)

reviews = Table(
    "reviews",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "classification_id",
        String(64),
        ForeignKey("classifications.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    ),
    Column("status", String(16), default="pending"),   # pending|approved|rejected
    Column("reviewer_id", String(64), ForeignKey("users.id")),
    Column("corrected_code", String(64)),
    Column("notes", Text),
    Column("created_at", String(40)),
    Column("reviewed_at", String(40)),
)

audit_logs = Table(
    "audit_logs",
    _metadata,
    Column("entry_id", String(64), primary_key=True),
    Column("timestamp", String(40), nullable=False, index=True),
    Column("event_type", String(40)),
    Column("user_id", String(64), ForeignKey("users.id")),
    Column("details", Text),                           # JSON
    Column("previous_hmac", String(128)),
    Column("hmac", String(128)),
)


# ---------------------------------------------------------------------------
# Ligação
# ---------------------------------------------------------------------------
def _data_dir() -> Path:
    return Path(os.environ.get("IDRISK2_DATA_DIR", "./data"))


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    host = os.environ.get("PGHOST", "").strip()
    if host:
        return URL.create(
            "postgresql+psycopg2",
            username=os.environ.get("PGUSER", "postgres"),
            password=os.environ.get("PGPASSWORD") or None,
            host=host,
            port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ.get("PGDATABASE", "postgres"),
            query={"sslmode": os.environ.get("PGSSLMODE", "require")},
        ).render_as_string(hide_password=False)
    path = _data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path / 'idrisk2.db'}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        logger.info("Base de dados: %s", url.split("@")[-1] if "@" in url else url)
    return _engine


def init_db() -> None:
    """Cria todas as tabelas/índices se ainda não existirem."""
    _metadata.create_all(get_engine())
    logger.info(
        "Esquema pronto: users, classifications, classification_facets, "
        "reviews, audit_logs."
    )


# ---------------------------------------------------------------------------
# Classificações
# ---------------------------------------------------------------------------
def _derive_review_status(requires_review: bool) -> str:
    return "pending" if requires_review else "none"


def _replace_facets(conn, classification_id: str, facets: dict[str, str] | None) -> None:
    conn.execute(
        delete(classification_facets).where(
            classification_facets.c.classification_id == classification_id
        )
    )
    for group, code in (facets or {}).items():
        conn.execute(
            insert(classification_facets).values(
                classification_id=classification_id,
                facet_group=str(group),
                facet_code=str(code),
            )
        )


def _upsert_review(conn, classification_id: str, status: str, created_at: str) -> None:
    conn.execute(delete(reviews).where(reviews.c.classification_id == classification_id))
    conn.execute(
        insert(reviews).values(
            classification_id=classification_id,
            status=status,
            created_at=created_at,
        )
    )


def insert_classification(
    *,
    id: str,
    timestamp: str,
    base_term_code: str,
    base_term_label: str,
    facets: dict[str, str] | None,
    confidence: str,
    requires_human_review: bool,
    ocr_text: str = "",
    image_hash: Optional[str] = None,
    submitted_by: Optional[str] = None,
    total_time_ms: Optional[float] = None,
    review_status: Optional[str] = None,
) -> None:
    """Insere (ou substitui) uma classificação + facetas normalizadas + review."""
    if review_status is None:
        review_status = _derive_review_status(requires_human_review)
    values = dict(
        id=id,
        timestamp=timestamp,
        base_term_code=base_term_code,
        base_term_label=base_term_label,
        facets=json.dumps(facets or {}),
        confidence=confidence,
        requires_human_review=bool(requires_human_review),
        review_status=review_status,
        ocr_text=ocr_text or "",
        image_hash=image_hash,
        submitted_by=submitted_by,
        total_time_ms=total_time_ms,
    )
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(delete(classifications).where(classifications.c.id == id))
        conn.execute(insert(classifications).values(**values))
        _replace_facets(conn, id, facets)
        if requires_human_review:
            _upsert_review(conn, id, review_status or "pending", timestamp)


def list_classifications(limit: int = 500) -> list[dict[str, Any]]:
    """Devolve o histórico, mais recente primeiro."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(classifications)
            .order_by(classifications.c.timestamp.desc())
            .limit(limit)
        ).mappings().all()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["facets"] = json.loads(item.get("facets") or "{}")
        except (json.JSONDecodeError, TypeError):
            item["facets"] = {}
        item["requires_human_review"] = bool(item.get("requires_human_review"))
        result.append(item)
    return result


def count_classifications() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(classifications)).scalar()
    return int(n or 0)


def _count(table) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(table)).scalar()
    return int(n or 0)


# ---------------------------------------------------------------------------
# Seed / migração de dados existentes
# ---------------------------------------------------------------------------
# id, username, email, role, status, created_at
# Os ids dos utilizadores de sistema/legados COINCIDEM com os valores já
# gravados em classifications.submitted_by e audit_logs.user_id, para que as
# foreign keys para users.id sejam satisfeitas.
_DEMO_USERS = [
    # Utilizadores de sistema / legados (referenciados pelos dados existentes)
    ("web_inspector", "web_inspector", "inspector@idrisk2.local", "inspector", "active", "2026-01-01"),
    ("web-inspector", "web-inspector (legacy)", None, "inspector", "inactive", "2026-01-01"),
    ("u001", "u001 (legacy)", None, "inspector", "inactive", "2026-01-01"),
    ("eval_runner", "eval_runner (system)", None, "inspector", "active", "2026-01-01"),
    ("test_probe", "test_probe (system)", None, "inspector", "inactive", "2026-01-01"),
    # Utilizadores de demonstração (ecrã de administração)
    ("u-jsmith", "j.smith", "j.smith@efsa.europa.eu", "inspector", "active", "2026-01-15"),
    ("u-mjones", "m.jones", "m.jones@efsa.europa.eu", "inspector", "active", "2026-01-20"),
    ("u-pwilson", "p.wilson", "p.wilson@efsa.europa.eu", "supervisor", "active", "2025-11-10"),
    ("u-agarcia", "a.garcia", "a.garcia@efsa.europa.eu", "administrator", "active", "2025-09-01"),
    ("u-rchen", "r.chen", "r.chen@efsa.europa.eu", "auditor", "active", "2026-02-05"),
    ("u-lbrown", "l.brown", "l.brown@efsa.europa.eu", "inspector", "inactive", "2025-08-12"),
]


def seed_users() -> int:
    """Insere utilizadores (sistema + demonstração) se a tabela estiver vazia."""
    if _count(users) > 0:
        return 0
    engine = get_engine()
    inserted = 0
    with engine.begin() as conn:
        for uid, username, email, role, status, created_at in _DEMO_USERS:
            conn.execute(
                insert(users).values(
                    id=uid,
                    username=username,
                    email=email,
                    role=role,
                    status=status,
                    created_at=created_at,
                    password_hash=None,
                )
            )
            inserted += 1
    if inserted:
        logger.info("Seed de utilizadores: %d inseridos.", inserted)
    return inserted


def migrate_existing_records(records_dir: Optional[str] = None) -> int:
    """
    Importa registos JSON antigos (data/records/*.json) para classifications
    (e, por arrasto, facetas + reviews). Só corre quando a tabela está vazia.
    """
    if count_classifications() > 0:
        return 0
    base = Path(records_dir) if records_dir else (_data_dir() / "records")
    if not base.exists():
        return 0
    imported = 0
    for jf in sorted(base.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cr = data.get("classification_result", {}) or {}
        confidence = (cr.get("confidence") or "").lower()
        requires_review = confidence in ("low", "medium")
        rec_id = data.get("record_id") or jf.stem
        try:
            insert_classification(
                id=rec_id,
                timestamp=data.get("timestamp") or "",
                base_term_code=cr.get("base_term_code") or "",
                base_term_label=cr.get("base_term_label") or "",
                facets=cr.get("facets") or {},
                confidence=confidence or "medium",
                requires_human_review=requires_review,
                ocr_text=data.get("ocr_text") or "",
                image_hash=data.get("image_hash"),
                submitted_by=data.get("submitted_by"),
            )
            imported += 1
        except Exception:
            continue
    if imported:
        logger.info("Importados %d registos antigos (classifications).", imported)
    return imported


def migrate_audit_logs(audit_dir: Optional[str] = None) -> int:
    """
    Importa entradas de auditoria JSON (data/audit/**/*.json com campo 'hmac')
    para a tabela audit_logs. Só corre quando a tabela está vazia.
    """
    if _count(audit_logs) > 0:
        return 0
    base = Path(audit_dir) if audit_dir else (_data_dir() / "audit")
    if not base.exists():
        return 0
    engine = get_engine()
    imported = 0
    with engine.begin() as conn:
        for jf in sorted(base.rglob("*.json")):
            try:
                entry = json.loads(jf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if "hmac" not in entry or "entry_id" not in entry:
                continue
            try:
                conn.execute(
                    insert(audit_logs).values(
                        entry_id=entry.get("entry_id"),
                        timestamp=entry.get("timestamp") or "",
                        event_type=entry.get("event_type") or "",
                        user_id=entry.get("user_id") or "",
                        details=json.dumps(entry.get("details") or {}),
                        previous_hmac=entry.get("previous_hmac"),
                        hmac=entry.get("hmac"),
                    )
                )
                imported += 1
            except Exception:
                continue
    if imported:
        logger.info("Importadas %d entradas de auditoria (audit_logs).", imported)
    return imported


def backfill_facets_and_reviews() -> int:
    """
    Popula classification_facets e reviews a partir das classificações já
    existentes na tabela (úteis quando as classificações foram inseridas antes
    de estas tabelas existirem). Só corre se classification_facets estiver vazia.
    """
    if _count(classification_facets) > 0:
        return 0
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                classifications.c.id,
                classifications.c.facets,
                classifications.c.requires_human_review,
                classifications.c.review_status,
                classifications.c.timestamp,
            )
        ).mappings().all()
    processed = 0
    with engine.begin() as conn:
        for row in rows:
            try:
                facets = json.loads(row.get("facets") or "{}")
            except (json.JSONDecodeError, TypeError):
                facets = {}
            _replace_facets(conn, row["id"], facets)
            if row.get("requires_human_review"):
                _upsert_review(
                    conn,
                    row["id"],
                    row.get("review_status") or "pending",
                    row.get("timestamp") or "",
                )
            processed += 1
    if processed:
        logger.info("Backfill de facetas/reviews para %d classificações.", processed)
    return processed


def bootstrap() -> dict[str, int]:
    """Cria tabelas e popula tudo o que estiver vazio. Devolve contagens importadas."""
    init_db()
    counts = {
        "users": seed_users(),
        "classifications": migrate_existing_records(),
        "audit_logs": migrate_audit_logs(),
    }
    counts["facets_reviews_backfill"] = backfill_facets_and_reviews()
    return counts


# ---------------------------------------------------------------------------
# Reviews (fila de revisão humana)
# ---------------------------------------------------------------------------
def list_reviews(status: Optional[str] = None, limit: int = 500) -> list[dict[str, Any]]:
    """Fila de revisão: junta reviews + dados da classificação."""
    j = reviews.join(classifications, reviews.c.classification_id == classifications.c.id)
    stmt = (
        select(
            reviews.c.classification_id,
            reviews.c.status,
            reviews.c.created_at,
            reviews.c.reviewer_id,
            reviews.c.corrected_code,
            reviews.c.notes,
            reviews.c.reviewed_at,
            classifications.c.submitted_by,
            classifications.c.timestamp,
            classifications.c.base_term_code,
            classifications.c.base_term_label,
            classifications.c.confidence,
            classifications.c.ocr_text,
        )
        .select_from(j)
        .order_by(classifications.c.timestamp.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(reviews.c.status == status)
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def decide_review(
    classification_id: str,
    status: str,
    reviewer_id: Optional[str] = None,
    corrected_code: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    """Aprova/rejeita uma revisão e atualiza o estado na classificação."""
    now = datetime.utcnow().isoformat()
    engine = get_engine()
    with engine.begin() as conn:
        res = conn.execute(
            update(reviews)
            .where(reviews.c.classification_id == classification_id)
            .values(
                status=status,
                reviewer_id=reviewer_id,
                corrected_code=corrected_code,
                notes=notes,
                reviewed_at=now,
            )
        )
        conn.execute(
            update(classifications)
            .where(classifications.c.id == classification_id)
            .values(review_status=status)
        )
    return res.rowcount > 0


# ---------------------------------------------------------------------------
# Utilizadores
# ---------------------------------------------------------------------------
def list_users() -> list[dict[str, Any]]:
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(users).order_by(users.c.created_at.desc())
        ).mappings().all()
    return [dict(r) for r in rows]


def create_user(username: str, email: str, role: str) -> dict[str, Any]:
    uid = "u-" + uuid.uuid4().hex[:10]
    created_at = datetime.utcnow().date().isoformat()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            insert(users).values(
                id=uid,
                username=username,
                email=email,
                role=role,
                status="active",
                created_at=created_at,
                password_hash=None,
            )
        )
    return {
        "id": uid,
        "username": username,
        "email": email,
        "role": role,
        "status": "active",
        "created_at": created_at,
    }


def set_user_status(user_id: str, status: str) -> bool:
    engine = get_engine()
    with engine.begin() as conn:
        res = conn.execute(
            update(users).where(users.c.id == user_id).values(status=status)
        )
    return res.rowcount > 0


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
def list_audit(limit: int = 500) -> list[dict[str, Any]]:
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(audit_logs)
            .order_by(audit_logs.c.timestamp.desc())
            .limit(limit)
        ).mappings().all()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item["details"] = json.loads(item.get("details") or "{}")
        except (json.JSONDecodeError, TypeError):
            item["details"] = {}
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Estatísticas do dashboard
# ---------------------------------------------------------------------------
def dashboard_stats() -> dict[str, Any]:
    """Distribuição de confiança + atividade dos últimos 7 dias + contagens."""
    engine = get_engine()
    with engine.connect() as conn:
        conf_rows = conn.execute(
            select(classifications.c.confidence, func.count())
            .group_by(classifications.c.confidence)
        ).all()
        ts_rows = conn.execute(select(classifications.c.timestamp)).all()
        total = conn.execute(
            select(func.count()).select_from(classifications)
        ).scalar() or 0
        pending = conn.execute(
            select(func.count()).select_from(reviews).where(reviews.c.status == "pending")
        ).scalar() or 0

    confidence = {"high": 0, "medium": 0, "low": 0}
    for conf, n in conf_rows:
        key = (conf or "").lower()
        if key in confidence:
            confidence[key] = int(n)

    # Atividade dos últimos 7 dias
    today = datetime.utcnow().date()
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    counts = {d.isoformat(): 0 for d in days}
    for (ts,) in ts_rows:
        if not ts:
            continue
        day = str(ts)[:10]
        if day in counts:
            counts[day] += 1
    weekly = [
        {"day": d.strftime("%a"), "date": d.isoformat(), "classifications": counts[d.isoformat()]}
        for d in days
    ]
    return {
        "confidence": confidence,
        "weekly": weekly,
        "total": int(total),
        "pending_reviews": int(pending),
    }
