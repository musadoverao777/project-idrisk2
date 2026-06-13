-- IDRISK2 — Esquema da base de dados (PostgreSQL / Supabase)
-- Alternativa à criação automática pela aplicação: cola este SQL no
-- Supabase → SQL Editor → New query → Run.

create table if not exists users (
    id            text primary key,
    username      text not null unique,
    email         text,
    role          text not null,            -- inspector | supervisor | administrator | auditor
    status        text default 'active',    -- active | inactive
    created_at    text,
    password_hash text                      -- reservado para autenticação futura
);

create table if not exists classifications (
    id                    text primary key,
    timestamp             text not null,
    base_term_code        text,
    base_term_label       text,
    facets                text,             -- JSON (cópia de conveniência)
    confidence            text,             -- high | medium | low
    requires_human_review boolean default false,
    review_status         text default 'none',  -- none | pending | approved | rejected
    ocr_text              text,
    image_hash            text,             -- SHA-256 (imagem descartada por GDPR)
    submitted_by          text references users(id),
    total_time_ms         double precision
);
create index if not exists idx_classifications_ts on classifications(timestamp desc);

create table if not exists classification_facets (
    id                serial primary key,
    classification_id text references classifications(id) on delete cascade,
    facet_group       text,                 -- ex.: F01, F04, F27
    facet_code        text                  -- ex.: A0F4B
);
create index if not exists idx_facets_cid on classification_facets(classification_id);

create table if not exists reviews (
    id                serial primary key,
    classification_id text unique references classifications(id) on delete cascade,
    status            text default 'pending',   -- pending | approved | rejected
    reviewer_id       text references users(id),
    corrected_code    text,
    notes             text,
    created_at        text,
    reviewed_at       text
);

create table if not exists audit_logs (
    entry_id      text primary key,
    timestamp     text not null,
    event_type    text,
    user_id       text references users(id),
    details       text,                     -- JSON
    previous_hmac text,
    hmac          text
);
create index if not exists idx_audit_ts on audit_logs(timestamp desc);
