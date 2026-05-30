create table if not exists health_score_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  period varchar(7) not null,
  financial_health_score numeric(5, 2),
  credit_load_index numeric(5, 2),
  financial_health_status varchar(32) not null,
  credit_load_zone varchar(16) not null,
  profile_json jsonb not null,
  score_components jsonb not null,
  calculated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint uq_health_score_snapshots_user_period unique(user_id, period)
);

create index if not exists ix_health_score_snapshots_user_calculated
  on health_score_snapshots(user_id, calculated_at desc);
