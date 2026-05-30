create table if not exists uploaded_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  original_filename varchar(512) not null,
  content_type varchar(255),
  size_bytes integer not null,
  sha256 varchar(64) not null,
  storage_bucket varchar(255) not null,
  storage_key varchar(1024) not null,
  status varchar(64) not null default 'uploaded',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_uploaded_files_user_sha256 unique(user_id, sha256)
);

create index if not exists ix_uploaded_files_user_sha256 on uploaded_files(user_id, sha256);

create table if not exists import_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  file_id uuid not null references uploaded_files(id) on delete cascade,
  source_type varchar(128) not null,
  status varchar(64) not null default 'queued',
  started_at timestamptz,
  finished_at timestamptz,
  total_rows integer not null default 0,
  parsed_rows integer not null default 0,
  failed_rows integer not null default 0,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_import_jobs_user_file on import_jobs(user_id, file_id);

create table if not exists import_errors (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  import_id uuid not null references import_jobs(id) on delete cascade,
  sheet_name varchar(128),
  row_number integer,
  column_name varchar(255),
  raw_value text,
  error_code varchar(128) not null,
  message text not null,
  technical_details text,
  created_at timestamptz not null default now()
);

create index if not exists ix_import_errors_user_import on import_errors(user_id, import_id);
