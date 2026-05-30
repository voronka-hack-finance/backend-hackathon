create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email varchar(320) not null unique,
  password_hash varchar(255) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_users_email on users(email);
