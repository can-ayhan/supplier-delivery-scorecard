-- Star schema: three facts sharing four dimensions.
--
--   fact_po_line        one row per purchase order line   (delivery KPIs)
--   fact_goods_receipt  one row per material document line (receipt volume)
--   fact_inspection     one row per inspection lot         (quality KPIs)

drop table if exists mart.fact_inspection cascade;
drop table if exists mart.fact_goods_receipt cascade;
drop table if exists mart.fact_po_line cascade;
drop table if exists mart.dim_date cascade;
drop table if exists mart.dim_supplier cascade;
drop table if exists mart.dim_material cascade;
drop table if exists mart.dim_plant cascade;

create table mart.dim_date (
    date_key      integer primary key,          -- yyyymmdd
    date          date    not null unique,
    year          integer not null,
    quarter       integer not null,
    quarter_label text    not null,             -- 2026 Q1
    month         integer not null,
    month_name    text    not null,
    month_short   text    not null,
    year_month    text    not null,             -- 2026-03
    month_start   date    not null,
    iso_week      integer not null,
    weekday       integer not null,             -- 1 = Monday
    weekday_name  text    not null,
    is_weekend    boolean not null
);

create table mart.dim_supplier (
    supplier_key  integer generated always as identity primary key,
    supplier_id   text not null unique,         -- vendor number without leading zeros
    supplier_name text not null,
    country_code  text not null,
    country_name  text not null,
    region        text not null                 -- Domestic / EU / Non-EU
);

create table mart.dim_material (
    material_key        integer generated always as identity primary key,
    material_id         text not null unique,
    material_text       text not null,
    material_group      text not null,
    material_group_name text not null,
    base_uom            text not null
);

create table mart.dim_plant (
    plant_key    integer generated always as identity primary key,
    plant_id     text not null unique,
    plant_name   text not null,
    city         text,
    country_code text
);

create table mart.fact_po_line (
    po_line_key             integer generated always as identity primary key,
    po_number               text    not null,
    po_item                 integer not null,
    supplier_key            integer not null references mart.dim_supplier,
    material_key            integer not null references mart.dim_material,
    plant_key               integer not null references mart.dim_plant,
    order_date_key          integer not null references mart.dim_date,
    due_date_key            integer not null references mart.dim_date,
    delivery_date_key       integer references mart.dim_date,   -- day the line was complete, else last receipt
    uom                     text    not null,
    ordered_qty             numeric(15, 3) not null,
    received_qty            numeric(15, 3) not null,
    returned_qty            numeric(15, 3) not null,
    order_value_eur         numeric(15, 2) not null,
    receipt_count           integer not null,
    planned_lead_time_days  integer not null,           -- order date to due date
    lead_time_days          integer,                    -- order date to delivery date
    days_late               integer,                    -- delivery date minus due date, negative = early
    is_due                  boolean not null,           -- due on or before the as-of date
    is_delivery_complete    boolean not null,           -- buyer closed the line (ELIKZ)
    is_on_time              boolean not null,
    is_in_full              boolean not null,
    is_otif                 boolean not null,
    delivery_status         text    not null,
    unique (po_number, po_item)
);

create table mart.fact_goods_receipt (
    receipt_key       integer generated always as identity primary key,
    po_line_key       integer not null references mart.fact_po_line,
    supplier_key      integer not null references mart.dim_supplier,
    material_key      integer not null references mart.dim_material,
    plant_key         integer not null references mart.dim_plant,
    posting_date_key  integer not null references mart.dim_date,
    doc_number        text    not null,
    doc_year          integer not null,
    doc_item          integer not null,
    movement_type     text    not null,
    movement          text    not null,          -- Goods receipt / Reversal / Return to supplier
    quantity          numeric(15, 3) not null,   -- signed
    is_after_due_date boolean not null,
    unique (doc_number, doc_year, doc_item)
);

create table mart.fact_inspection (
    inspection_key    integer generated always as identity primary key,
    lot_number        text    not null unique,
    supplier_key      integer not null references mart.dim_supplier,
    material_key      integer not null references mart.dim_material,
    plant_key         integer not null references mart.dim_plant,
    lot_date_key      integer not null references mart.dim_date,
    decision_date_key integer references mart.dim_date,
    po_number         text,
    po_item           integer,
    uom               text    not null,
    lot_qty           numeric(15, 3) not null,
    accepted_qty      numeric(15, 3) not null,
    rejected_qty      numeric(15, 3) not null,   -- blocked + returned
    blocked_qty       numeric(15, 3) not null,
    returned_qty      numeric(15, 3) not null,
    decision          text    not null,          -- Accepted / Accepted with defects / Rejected / Open
    is_decided        boolean not null,
    is_rejected       boolean not null,          -- whole lot rejected
    has_defects       boolean not null,          -- any quantity rejected
    inspection_days   integer
);

create index on mart.fact_po_line (supplier_key);
create index on mart.fact_po_line (due_date_key);
create index on mart.fact_goods_receipt (po_line_key);
create index on mart.fact_inspection (supplier_key);
