create table if not exists transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  import_id uuid not null references import_jobs(id) on delete cascade,
  source_file_id uuid not null references uploaded_files(id) on delete cascade,
  source_sheet varchar(32) not null,
  source_row_number integer not null,
  type varchar(16) not null,
  operation_at timestamptz not null,
  payment_at timestamptz,
  card_mask varchar(64),
  card_last4 varchar(4),
  status varchar(64),
  operation_amount numeric(18, 2) not null,
  operation_currency varchar(8),
  payment_amount numeric(18, 2),
  payment_currency varchar(8),
  cashback_amount numeric(18, 2),
  category_name varchar(255),
  mcc varchar(16),
  description text,
  bonus_amount numeric(18, 2),
  investment_rounding_amount numeric(18, 2),
  rounded_operation_amount numeric(18, 2),
  dedupe_key varchar(128) not null,
  raw_payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_transactions_user_file_sheet_row unique(user_id, source_file_id, source_sheet, source_row_number)
);

create index if not exists ix_transactions_user_operation_at on transactions(user_id, operation_at);
create index if not exists ix_transactions_user_category_name on transactions(user_id, category_name);
create index if not exists ix_transactions_user_mcc on transactions(user_id, mcc);
create index if not exists ix_transactions_user_card_last4 on transactions(user_id, card_last4);
create index if not exists ix_transactions_user_status on transactions(user_id, status);
create index if not exists ix_transactions_user_import_id on transactions(user_id, import_id);
