alter table regular_expenses
  add column if not exists source_type varchar(32) not null default 'detected';

alter table regular_expenses
  add column if not exists expected_amount numeric(18, 2);

update regular_expenses
set expected_amount = average_amount
where expected_amount is null;

create index if not exists ix_regular_expenses_user_status_source
  on regular_expenses(user_id, status, source_type);
