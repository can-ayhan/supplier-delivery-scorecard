-- Typed copies of the three exports.
--
-- The functions below undo the SAP list formatting. They return NULL instead
-- of raising, so one unreadable cell turns into a data quality finding rather
-- than a failed load.

-- '31.07.2026' or '20260731' -> date
create or replace function staging.sap_date(value text) returns date
language plpgsql immutable as $$
declare
    v text := btrim(coalesce(value, ''));
begin
    if v ~ '^\d{2}\.\d{2}\.\d{4}$' then
        return to_date(v, 'DD.MM.YYYY');
    elsif v ~ '^\d{8}$' then
        return to_date(v, 'YYYYMMDD');
    end if;
    return null;
exception when others then
    return null;   -- 00.00.0000, 31.02.2026, ...
end $$;

-- '1.250,500' -> 1250.5, '40,000-' -> -40
create or replace function staging.sap_number(value text) returns numeric
language sql immutable as $$
    select case
        when v ~ '^-?\d{1,3}(\.\d{3})*(,\d+)?-?$' or v ~ '^-?\d+(,\d+)?-?$' then
            (case when v like '%-' or v like '-%' then -1 else 1 end)
            * replace(replace(replace(v, '-', ''), '.', ''), ',', '.')::numeric
    end
    from (select btrim(coalesce(value, ''))) as t(v)
$$;

-- '0000104090' and '104090' are the same vendor: compare without the padding
create or replace function staging.sap_id(value text) returns text
language sql immutable as $$
    select case
        when v = '' then null
        when v ~ '^0+$' then '0'
        when v ~ '^\d+$' then ltrim(v, '0')
        else v
    end
    from (select btrim(coalesce(value, ''))) as t(v)
$$;

create or replace function staging.sap_int(value text) returns integer
language sql immutable as $$
    select case when btrim(coalesce(value, '')) ~ '^\d{1,9}$' then btrim(value)::integer end
$$;


drop table if exists staging.purchase_orders cascade;
create table staging.purchase_orders as
select
    row_num,
    staging.sap_id(ebeln)                               as po_number,
    staging.sap_int(ebelp)                              as po_item,
    staging.sap_date(bedat)                             as po_date,
    staging.sap_id(lifnr)                               as supplier_id,
    nullif(btrim(name1), '')                            as supplier_name,
    nullif(upper(btrim(land1)), '')                     as country_code,
    staging.sap_id(matnr)                               as material_id,
    nullif(btrim(txz01), '')                            as material_text,
    nullif(upper(btrim(matkl)), '')                     as material_group,
    nullif(btrim(werks), '')                            as plant_id,
    staging.sap_number(menge)                           as ordered_qty,
    nullif(upper(btrim(meins)), '')                     as uom,
    staging.sap_number(netpr)                           as net_price,
    coalesce(nullif(staging.sap_number(peinh), 0), 1)   as price_unit,   -- price is per this many units
    nullif(upper(btrim(waers)), '')                     as currency,
    staging.sap_date(eindt)                             as due_date,
    btrim(coalesce(loekz, '')) <> ''                    as is_deleted,
    btrim(coalesce(elikz, '')) = 'X'                    as is_delivery_complete,
    row_number() over (
        partition by staging.sap_id(ebeln), staging.sap_int(ebelp)
        order by row_num
    )                                                   as dup_rank
from staging.raw_purchase_orders;

create index on staging.purchase_orders (po_number, po_item);


drop table if exists staging.goods_receipts cascade;
create table staging.goods_receipts as
select
    row_num,
    staging.sap_id(mblnr)                               as doc_number,
    staging.sap_int(mjahr)                              as doc_year,
    staging.sap_int(zeile)                              as doc_item,
    staging.sap_date(budat)                             as posting_date,
    nullif(btrim(bwart), '')                            as movement_type,  -- 101 receipt, 102 reversal, 122 return
    staging.sap_id(ebeln)                               as po_number,
    staging.sap_int(ebelp)                              as po_item,
    staging.sap_id(matnr)                               as material_id,
    nullif(btrim(werks), '')                            as plant_id,
    staging.sap_id(lifnr)                               as supplier_id,
    staging.sap_number(menge)                           as quantity,       -- signed, as exported
    nullif(upper(btrim(meins)), '')                     as uom,
    row_number() over (
        partition by staging.sap_id(mblnr), staging.sap_int(mjahr), staging.sap_int(zeile)
        order by row_num
    )                                                   as dup_rank
from staging.raw_goods_receipts;

create index on staging.goods_receipts (po_number, po_item);
create index on staging.goods_receipts (doc_number, doc_year, doc_item);


drop table if exists staging.inspection_lots cascade;
create table staging.inspection_lots as
select
    row_num,
    staging.sap_id(prueflos)                            as lot_number,
    nullif(btrim(werk), '')                             as plant_id,
    staging.sap_id(matnr)                               as material_id,
    staging.sap_id(lifnr)                               as supplier_id,
    staging.sap_id(ebeln)                               as po_number,
    staging.sap_int(ebelp)                              as po_item,
    staging.sap_id(mblnr)                               as doc_number,
    staging.sap_int(mjahr)                              as doc_year,
    staging.sap_int(zeile)                              as doc_item,
    staging.sap_date(enstehdat)                         as created_date,
    staging.sap_number(losmenge)                        as lot_qty,
    nullif(upper(btrim(mengeneinh)), '')                as uom,
    nullif(upper(btrim(vcode)), '')                     as decision_code,  -- A, AB, R or empty while open
    staging.sap_date(vdatum)                            as decision_date,
    coalesce(staging.sap_number(lmenge01), 0)           as accepted_qty,
    coalesce(staging.sap_number(lmenge04), 0)           as blocked_qty,
    coalesce(staging.sap_number(lmenge07), 0)           as returned_qty,
    row_number() over (
        partition by staging.sap_id(prueflos)
        order by row_num
    )                                                   as dup_rank
from staging.raw_inspection_lots;

create index on staging.inspection_lots (lot_number);
