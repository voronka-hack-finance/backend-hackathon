alter table bucket_bootstrap_runs
  add column if not exists policy_name varchar(64) not null default 'private',
  add column if not exists policy_applied_at timestamptz;
