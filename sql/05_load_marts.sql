-- Fill the star schema from the validated staging views.
-- Full rebuild every run: the exports are complete snapshots, not deltas.

-- The exports have no "report date", so use the last posting they contain.
update mart.kpi_params
set as_of_date = (select max(posting_date) from staging.v_goods_receipts_valid);


-- dimensions ---------------------------------------------------------------

insert into mart.dim_date
select
    to_char(d, 'YYYYMMDD')::integer,
    d::date,
    extract(year from d)::integer,
    extract(quarter from d)::integer,
    to_char(d, 'YYYY "Q"Q'),
    extract(month from d)::integer,
    to_char(d, 'FMMonth'),
    to_char(d, 'Mon'),
    to_char(d, 'YYYY-MM'),
    date_trunc('month', d)::date,
    extract(week from d)::integer,
    extract(isodow from d)::integer,
    to_char(d, 'FMDay'),
    extract(isodow from d) in (6, 7)
from generate_series(
    (select date_trunc('year', min(po_date)) from staging.v_purchase_orders_valid),
    (select date_trunc('year', max(due_date)) + interval '1 year' - interval '1 day'
     from staging.v_purchase_orders_valid),
    interval '1 day'
) as d;

-- The vendor name changed over time in the PO list; keep the latest spelling.
insert into mart.dim_supplier (supplier_id, supplier_name, country_code, country_name, region)
select distinct on (p.supplier_id)
    p.supplier_id,
    p.supplier_name,
    p.country_code,
    coalesce(c.country_name, p.country_code),
    coalesce(c.region, 'Unknown')
from staging.v_purchase_orders_valid p
left join staging.ref_countries c using (country_code)
order by p.supplier_id, p.po_date desc, p.row_num desc;

insert into mart.dim_material (material_id, material_text, material_group, material_group_name, base_uom)
select distinct on (p.material_id)
    p.material_id,
    p.material_text,
    p.material_group,
    coalesce(g.material_group_name, p.material_group),
    p.uom
from staging.v_purchase_orders_valid p
left join staging.ref_material_groups g using (material_group)
order by p.material_id, p.po_date desc, p.row_num desc;

insert into mart.dim_plant (plant_id, plant_name, city, country_code)
select distinct
    p.plant_id,
    coalesce(r.plant_name, 'Plant ' || p.plant_id),
    r.city,
    r.country_code
from staging.v_purchase_orders_valid p
left join staging.ref_plants r using (plant_id)
order by p.plant_id;


-- fact_po_line -------------------------------------------------------------
-- A line is "in full" once net receipts reach the ordered quantity minus the
-- tolerance. Its delivery date is the posting that got it there, and stays
-- there: a receipt that is reversed later does not count as completing it.

insert into mart.fact_po_line (
    po_number, po_item, supplier_key, material_key, plant_key,
    order_date_key, due_date_key, delivery_date_key,
    uom, ordered_qty, received_qty, returned_qty, order_value_eur, receipt_count,
    planned_lead_time_days, lead_time_days, days_late,
    is_due, is_delivery_complete, is_on_time, is_in_full, is_otif, delivery_status
)
with lines as (
    select
        p.*,
        p.ordered_qty * (1 - k.in_full_tolerance) as full_qty,
        k.on_time_grace_days                      as grace_days,
        k.as_of_date
    from staging.v_purchase_orders_valid p
    cross join mart.kpi_params k
),
movements as (
    select
        po_number,
        po_item,
        posting_date,
        quantity,
        -- lowest the running total gets from this posting onwards
        min(running_qty) over (
            partition by po_number, po_item
            order by posting_date desc, doc_number desc, doc_item desc
        ) as lowest_running_qty_after
    from (
        select
            g.*,
            sum(g.quantity) over (
                partition by g.po_number, g.po_item
                order by g.posting_date, g.doc_number, g.doc_item
            ) as running_qty
        from staging.v_goods_receipts_valid g
        where g.movement_type in ('101', '102')
    ) g
),
received as (
    select
        l.po_number,
        l.po_item,
        sum(m.quantity)                                                             as received_qty,
        count(*) filter (where m.quantity > 0)                                      as receipt_count,
        max(m.posting_date) filter (where m.quantity > 0)                           as last_receipt_date,
        min(m.posting_date) filter (where m.lowest_running_qty_after >= l.full_qty) as completion_date
    from lines l
    join movements m using (po_number, po_item)
    group by l.po_number, l.po_item
),
returned as (
    select po_number, po_item, -sum(quantity) as returned_qty
    from staging.v_goods_receipts_valid
    where movement_type = '122'
    group by po_number, po_item
),
delivered as (
    select
        l.*,
        coalesce(r.received_qty, 0)                 as received_qty,
        coalesce(r.receipt_count, 0)                as receipt_count,
        coalesce(t.returned_qty, 0)                 as returned_qty,
        coalesce(r.received_qty, 0) >= l.full_qty   as is_in_full,
        case
            when coalesce(r.received_qty, 0) >= l.full_qty then r.completion_date
            else r.last_receipt_date
        end                                         as delivery_date
    from lines l
    left join received r using (po_number, po_item)
    left join returned t using (po_number, po_item)
    -- cancelled lines are not orders to measure, unless goods arrived anyway
    where not l.is_deleted or coalesce(r.received_qty, 0) > 0
),
flagged as (
    select
        d.*,
        d.due_date <= d.as_of_date                                      as is_due,
        coalesce(d.delivery_date <= d.due_date + d.grace_days, false)   as is_on_time
    from delivered d
)
select
    f.po_number,
    f.po_item,
    s.supplier_key,
    m.material_key,
    p.plant_key,
    to_char(f.po_date, 'YYYYMMDD')::integer,
    to_char(f.due_date, 'YYYYMMDD')::integer,
    to_char(f.delivery_date, 'YYYYMMDD')::integer,
    f.uom,
    f.ordered_qty,
    f.received_qty,
    f.returned_qty,
    round(f.ordered_qty * f.net_price / f.price_unit, 2),
    f.receipt_count,
    f.due_date - f.po_date,
    f.delivery_date - f.po_date,
    f.delivery_date - f.due_date,
    f.is_due,
    f.is_delivery_complete,
    f.is_on_time,
    f.is_in_full,
    f.is_in_full and f.is_on_time,
    case
        when f.is_in_full and f.is_on_time  then 'On time in full'
        when not f.is_due                   then 'Open'
        when f.received_qty <= 0            then 'Not delivered'
        when f.is_in_full                   then 'Late'
        when f.is_on_time                   then 'Short'
        else 'Late and short'
    end
from flagged f
join mart.dim_supplier s using (supplier_id)
join mart.dim_material m using (material_id)
join mart.dim_plant p using (plant_id)
order by f.po_number, f.po_item;


-- fact_goods_receipt -------------------------------------------------------

insert into mart.fact_goods_receipt (
    po_line_key, supplier_key, material_key, plant_key, posting_date_key,
    doc_number, doc_year, doc_item, movement_type, movement, quantity, is_after_due_date
)
select
    f.po_line_key,
    f.supplier_key,
    f.material_key,
    f.plant_key,
    to_char(g.posting_date, 'YYYYMMDD')::integer,
    g.doc_number,
    g.doc_year,
    g.doc_item,
    g.movement_type,
    case g.movement_type
        when '101' then 'Goods receipt'
        when '102' then 'Reversal'
        when '122' then 'Return to supplier'
        else 'Other'
    end,
    g.quantity,
    g.posting_date > d.date
from staging.v_goods_receipts_valid g
join mart.fact_po_line f using (po_number, po_item)
join mart.dim_date d on d.date_key = f.due_date_key
order by g.posting_date, g.doc_number, g.doc_item;


-- fact_inspection ----------------------------------------------------------

insert into mart.fact_inspection (
    lot_number, supplier_key, material_key, plant_key, lot_date_key, decision_date_key,
    po_number, po_item, uom, lot_qty, accepted_qty, rejected_qty, blocked_qty, returned_qty,
    decision, is_decided, is_rejected, has_defects, inspection_days
)
select
    l.lot_number,
    s.supplier_key,
    m.material_key,
    p.plant_key,
    to_char(l.created_date, 'YYYYMMDD')::integer,
    to_char(l.decision_date, 'YYYYMMDD')::integer,
    l.po_number,
    l.po_item,
    l.uom,
    l.lot_qty,
    l.accepted_qty,
    l.blocked_qty + l.returned_qty,
    l.blocked_qty,
    l.returned_qty,
    case l.decision_code
        when 'A'  then 'Accepted'
        when 'AB' then 'Accepted with defects'
        when 'R'  then 'Rejected'
        else 'Open'
    end,
    l.decision_code is not null,
    coalesce(l.decision_code = 'R', false),
    l.blocked_qty + l.returned_qty > 0,
    l.decision_date - l.created_date
from staging.v_inspection_lots_valid l
join mart.dim_supplier s using (supplier_id)
join mart.dim_material m using (material_id)
join mart.dim_plant p using (plant_id)
order by l.lot_number;

analyze mart.fact_po_line;
analyze mart.fact_goods_receipt;
analyze mart.fact_inspection;
