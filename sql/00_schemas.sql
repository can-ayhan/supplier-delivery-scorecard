-- Schemas and the parameters the KPIs depend on.

create schema if not exists staging;   -- exports as loaded, then typed
create schema if not exists dq;        -- data quality findings
create schema if not exists mart;      -- star schema the reports read

-- One row. Kept in the database so SQL, Power BI and Excel all use the
-- same thresholds instead of each hard-coding their own.
create table if not exists mart.kpi_params (
    only_row                 boolean primary key default true check (only_row),
    in_full_tolerance        numeric not null default 0.02,  -- complete from 98 % of the ordered quantity
    on_time_grace_days       integer not null default 0,
    over_delivery_tolerance  numeric not null default 0.10,  -- review threshold
    closed_short_tolerance   numeric not null default 0.10,  -- review threshold
    weight_delivery          numeric not null default 0.50,
    weight_lead_time         numeric not null default 0.20,
    weight_quality           numeric not null default 0.30,
    defect_rate_cap          numeric not null default 0.05,  -- defect rate at which the quality score is zero
    as_of_date               date                            -- last posting date in the exports, set by the build
);

insert into mart.kpi_params default values
on conflict do nothing;
