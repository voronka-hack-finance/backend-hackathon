-- Cross-file transaction deduplication: same user + dedupe_key must not repeat.
create unique index if not exists uq_transactions_user_dedupe_key on transactions(user_id, dedupe_key);

create index if not exists ix_refresh_sessions_refresh_token_hash on refresh_sessions(refresh_token_hash);
