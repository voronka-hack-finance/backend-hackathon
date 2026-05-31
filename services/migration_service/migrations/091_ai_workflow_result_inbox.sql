create table if not exists ai_workflow_result_inbox (
  workflow_run_id uuid primary key,
  request_id uuid not null,
  user_id uuid not null references users(id) on delete cascade,
  chat_id uuid not null references chats(id) on delete cascade,
  message_id uuid not null references chat_messages(id) on delete cascade,
  assistant_message_id uuid references chat_messages(id) on delete set null,
  status varchar(32) not null,
  processed_at timestamptz not null default now()
);

create index if not exists ix_ai_workflow_result_inbox_chat
  on ai_workflow_result_inbox (chat_id, processed_at);
