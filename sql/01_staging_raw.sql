-- Landing tables: one per export, every column as text, exactly as it came
-- out of the file. Typing and cleaning happen in 02_staging_clean.sql so a
-- bad value never makes the load fail.

drop table if exists staging.raw_purchase_orders cascade;
create table staging.raw_purchase_orders (
    row_num     integer not null,   -- line in the file, header = 1
    source_file text    not null,
    ebeln text, ebelp text, bedat text, lifnr text, name1 text, land1 text,
    matnr text, txz01 text, matkl text, werks text, menge text, meins text,
    netpr text, peinh text, waers text, eindt text, loekz text, elikz text
);

drop table if exists staging.raw_goods_receipts cascade;
create table staging.raw_goods_receipts (
    row_num     integer not null,
    source_file text    not null,
    mblnr text, mjahr text, zeile text, budat text, bwart text, ebeln text,
    ebelp text, matnr text, werks text, lifnr text, menge text, meins text
);

drop table if exists staging.raw_inspection_lots cascade;
create table staging.raw_inspection_lots (
    row_num     integer not null,
    source_file text    not null,
    prueflos text, werk text, matnr text, lifnr text, ebeln text, ebelp text,
    mblnr text, mjahr text, zeile text, enstehdat text, losmenge text,
    mengeneinh text, vcode text, vdatum text, lmenge01 text, lmenge04 text,
    lmenge07 text
);

-- Small hand-maintained lookups for things the exports only carry as codes.
drop table if exists staging.ref_plants cascade;
create table staging.ref_plants (
    plant_id     text primary key,
    plant_name   text not null,
    city         text,
    country_code text
);

drop table if exists staging.ref_material_groups cascade;
create table staging.ref_material_groups (
    material_group      text primary key,
    material_group_name text not null
);

drop table if exists staging.ref_countries cascade;
create table staging.ref_countries (
    country_code text primary key,
    country_name text not null,
    region       text not null
);
