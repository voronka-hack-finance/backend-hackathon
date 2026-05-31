create table if not exists ai_workflow_task_outbox (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null unique references chat_messages(id) on delete cascade,
  payload jsonb not null,
  published_at timestamptz,
  attempts integer not null default 0,
  last_error text,
  created_at timestamptz not null default now()
);

create index if not exists ix_ai_workflow_task_outbox_pending
  on ai_workflow_task_outbox (created_at)
  where published_at is null;
