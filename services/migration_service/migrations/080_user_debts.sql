create table if not exists user_debts (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references users(id) on delete cascade,
  account_id uuid references accounts(id) on delete set null,
  title varchar(255) not null,
  description text,
  debt_type varchar(32) not null,
  remaining_balance numeric(18, 2) not null,
  credit_limit numeric(18, 2),
  monthly_payment numeric(18, 2),
  currency varchar(8) not null default 'RUB',
  payment_day smallint,
  overdue_days integer not null default 0,
  interest_rate numeric(8, 4),
  status varchar(32) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_user_debts_type check (debt_type in ('loan', 'credit_card', 'other')),
  constraint ck_user_debts_status check (status in ('active', 'closed', 'deleted')),
  constraint ck_user_debts_remaining_nonnegative check (remaining_balance >= 0),
  constraint ck_user_debts_credit_limit_card check (debt_type <> 'credit_card' or credit_limit > 0),
  constraint ck_user_debts_monthly_payment_nonnegative check (monthly_payment is null or monthly_payment >= 0),
  constraint ck_user_debts_payment_day check (payment_day is null or payment_day between 1 and 31),
  constraint ck_user_debts_overdue_nonnegative check (overdue_days >= 0),
  constraint ck_user_debts_interest_nonnegative check (interest_rate is null or interest_rate >= 0)
);

create index if not exists ix_user_debts_owner_status on user_debts(owner_user_id, status);
create index if not exists ix_user_debts_owner_type on user_debts(owner_user_id, debt_type);
create index if not exists ix_user_debts_account_id on user_debts(account_id);
