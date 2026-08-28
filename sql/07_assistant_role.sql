-- Login for the text-to-SQL assistant.
--
-- The assistant runs model-written SQL, so its connection is locked down in
-- the database as well as in code: it can read the mart schema and nothing
-- else, every transaction is read-only and a query is cancelled after 5 s.
-- The password is a local development default (see .env.example).

do $$
begin
    if not exists (select from pg_roles where rolname = 'scorecard_reader') then
        create role scorecard_reader login password 'reader';
    end if;
end $$;

revoke all on schema staging, dq from scorecard_reader;
grant usage on schema mart to scorecard_reader;
grant select on all tables in schema mart to scorecard_reader;   -- tables are recreated on every build

alter role scorecard_reader set default_transaction_read_only = on;
alter role scorecard_reader set statement_timeout = '5s';
alter role scorecard_reader set search_path = mart;
