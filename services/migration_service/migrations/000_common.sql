create extension if not exists pgcrypto;

create table if not exists schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

create table if not exists bootstrap_runs (
  id uuid primary key default gen_random_uuid(),
  script_key text not null unique,
  script_group text not null,
  checksum text not null,
  status text not null,
  started_at timestamptz,
  finished_at timestamptz,
  error_message text
);
