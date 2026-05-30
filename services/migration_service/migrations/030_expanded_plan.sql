alter table users add column if not exists display_name varchar(255);

create table if not exists refresh_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  refresh_token_hash varchar(128) not null,
  status varchar(32) not null default 'active',
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);

create index if not exists ix_refresh_sessions_user_status on refresh_sessions(user_id, status);

create table if not exists bucket_bootstrap_runs (
  id uuid primary key default gen_random_uuid(),
  bucket_name varchar(255) not null unique,
  status varchar(32) not null,
  started_at timestamptz,
  finished_at timestamptz,
  error_message text
);

create table if not exists accounts (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references users(id) on delete cascade,
  family_group_id uuid,
  bank_source varchar(255),
  display_name varchar(255) not null,
  account_type varchar(64) not null default 'card',
  currency varchar(8) not null default 'RUB',
  card_last4 varchar(4),
  initial_balance numeric(18, 2) not null default 0,
  is_archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_accounts_owner_card on accounts(owner_user_id, card_last4);
create index if not exists ix_accounts_family_group on accounts(family_group_id);

create table if not exists account_categories (
  id uuid primary key default gen_random_uuid(),
  account_id uuid references accounts(id) on delete cascade,
  created_by_user_id uuid not null references users(id) on delete cascade,
  name varchar(255) not null,
  description text,
  icon_key varchar(128),
  is_archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_account_categories_account_name on account_categories(account_id, name);

create table if not exists category_limits (
  id uuid primary key default gen_random_uuid(),
  account_id uuid references accounts(id) on delete cascade,
  category_id uuid references account_categories(id) on delete set null,
  owner_user_id uuid not null references users(id) on delete cascade,
  limit_amount numeric(18, 2) not null,
  currency varchar(8) not null default 'RUB',
  period_days integer not null default 30,
  period_started_at timestamptz not null default now(),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_category_limits_account_category on category_limits(account_id, category_id);
create index if not exists ix_category_limits_owner_active on category_limits(owner_user_id, is_active);

create table if not exists savings_goals (
  id uuid primary key default gen_random_uuid(),
  account_id uuid references accounts(id) on delete cascade,
  owner_user_id uuid not null references users(id) on delete cascade,
  title varchar(255) not null,
  description text,
  target_amount numeric(18, 2) not null,
  current_amount numeric(18, 2) not null default 0,
  currency varchar(8) not null default 'RUB',
  target_date date,
  status varchar(32) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_savings_goals_account_status on savings_goals(account_id, status);
create index if not exists ix_savings_goals_owner_status on savings_goals(owner_user_id, status);

alter table transactions add column if not exists account_id uuid references accounts(id) on delete set null;
alter table transactions add column if not exists category_id uuid references account_categories(id) on delete set null;

create index if not exists ix_transactions_user_account_operation on transactions(user_id, account_id, operation_at);
create index if not exists ix_transactions_user_category_id on transactions(user_id, category_id);

create table if not exists regular_expenses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  account_id uuid references accounts(id) on delete cascade,
  category_id uuid references account_categories(id) on delete set null,
  merchant_pattern varchar(255) not null,
  average_amount numeric(18, 2) not null,
  currency varchar(8) not null default 'RUB',
  frequency_days integer not null default 30,
  next_expected_at timestamptz,
  confidence numeric(5, 4) not null default 0,
  status varchar(32) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists expected_incomes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  account_id uuid references accounts(id) on delete cascade,
  source_pattern varchar(255) not null,
  expected_amount numeric(18, 2) not null,
  currency varchar(8) not null default 'RUB',
  expected_at date,
  confidence numeric(5, 4) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists expected_expenses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  account_id uuid references accounts(id) on delete cascade,
  regular_expense_id uuid references regular_expenses(id) on delete set null,
  expected_amount numeric(18, 2) not null,
  currency varchar(8) not null default 'RUB',
  expected_at date,
  confidence numeric(5, 4) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists available_funds_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  actual_balance numeric(18, 2) not null,
  expected_income_total numeric(18, 2) not null,
  expected_expense_total numeric(18, 2) not null,
  available_amount numeric(18, 2) not null,
  currency varchar(8) not null default 'RUB',
  calculated_at timestamptz not null default now()
);

create index if not exists ix_regular_expenses_user_next on regular_expenses(user_id, account_id, next_expected_at);
create index if not exists ix_expected_incomes_user_expected on expected_incomes(user_id, expected_at);
create index if not exists ix_expected_expenses_user_expected on expected_expenses(user_id, expected_at);
create index if not exists ix_available_funds_user_period on available_funds_snapshots(user_id, period_start, period_end);

create table if not exists scheduled_reminders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  regular_expense_id uuid references regular_expenses(id) on delete set null,
  category_limit_id uuid references category_limits(id) on delete set null,
  reminder_type varchar(64) not null,
  status varchar(32) not null default 'planned',
  scheduled_at timestamptz not null,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_scheduled_reminders_user_scheduled_status on scheduled_reminders(user_id, scheduled_at, status);

create table if not exists notification_devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  device_id varchar(255) not null,
  platform varchar(64),
  firebase_token text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_notification_devices_user_device unique(user_id, device_id)
);

create table if not exists notification_preferences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade unique,
  push_enabled boolean not null default false,
  updated_at timestamptz not null default now()
);

create table if not exists notification_deliveries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  device_id uuid references notification_devices(id) on delete set null,
  reminder_id uuid references scheduled_reminders(id) on delete set null,
  notification_type varchar(64) not null,
  status varchar(32) not null,
  error_message text,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);

create table if not exists family_groups (
  id uuid primary key default gen_random_uuid(),
  created_by_user_id uuid not null references users(id) on delete cascade,
  name varchar(255) not null,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists family_members (
  id uuid primary key default gen_random_uuid(),
  family_group_id uuid not null references family_groups(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  role varchar(32) not null default 'member',
  status varchar(32) not null default 'active',
  joined_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_family_members_group_user unique(family_group_id, user_id)
);

create table if not exists family_invitations (
  id uuid primary key default gen_random_uuid(),
  family_group_id uuid not null references family_groups(id) on delete cascade,
  invited_by_user_id uuid not null references users(id) on delete cascade,
  invited_user_id uuid references users(id) on delete set null,
  invited_email varchar(320) not null,
  status varchar(32) not null default 'pending',
  message text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_family_invitations_group_email_status on family_invitations(family_group_id, invited_email, status);

create table if not exists chats (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  title varchar(255) not null,
  status varchar(32) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists chat_messages (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  role varchar(32) not null,
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists agent_recommendations (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid references chats(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  agent_key varchar(128) not null,
  title varchar(255) not null,
  content text not null,
  confidence numeric(5, 4) not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists ix_chats_user_updated on chats(user_id, updated_at);
create index if not exists ix_chat_messages_chat_created on chat_messages(chat_id, created_at);
