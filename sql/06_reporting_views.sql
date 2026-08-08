-- Views on top of the star schema.
--
-- Power BI imports the fact and dimension tables and calculates the KPIs in
-- DAX. These views hold the same definitions in SQL: they feed the Excel
-- workbook and are what the DAX measures are checked against.

-- One flat row per PO line, flags as 0/1 so they can be summed in a pivot.
create or replace view mart.v_delivery_lines as
select
    f.po_number,
    f.po_item,
    s.supplier_id,
    s.supplier_name,
    s.country_name,
    s.region,
    m.material_id,
    m.material_text,
    m.material_group_name,
    p.plant_name,
    od.date                                 as order_date,
    dd.date                                 as due_date,
    dd.year                                 as due_year,
    dd.quarter_label                        as due_quarter,
    dd.year_month                           as due_month,
    dl.date                                 as delivery_date,
    f.delivery_status,
    f.uom,
    f.ordered_qty,
    f.received_qty,
    f.returned_qty,
    f.order_value_eur,
    f.planned_lead_time_days,
    f.lead_time_days,
    f.days_late,
    f.is_due::integer                       as due_lines,
    (f.is_due and f.is_on_time)::integer    as on_time_lines,
    (f.is_due and f.is_in_full)::integer    as in_full_lines,
    (f.is_due and f.is_otif)::integer       as otif_lines
from mart.fact_po_line f
join mart.dim_supplier s using (supplier_key)
join mart.dim_material m using (material_key)
join mart.dim_plant p using (plant_key)
join mart.dim_date od on od.date_key = f.order_date_key
join mart.dim_date dd on dd.date_key = f.due_date_key
left join mart.dim_date dl on dl.date_key = f.delivery_date_key;


-- Supplier ranking over the whole period.
--
--   delivery score   = OTIF %
--   lead time score  = 100 when actual lead time equals the planned one,
--                      falling to 0 when it takes twice as long
--   quality score    = 100 at zero defects, 0 at the defect rate cap
--
-- A component a supplier has no data for is left out and the remaining
-- weights are rescaled, so nobody gets a free 100 for not being inspected.
create or replace view mart.v_supplier_scorecard as
with delivery as (
    select
        supplier_key,
        count(*) filter (where is_due)                                      as due_lines,
        count(*) filter (where is_due and is_on_time)                       as on_time_lines,
        count(*) filter (where is_due and is_in_full)                       as in_full_lines,
        count(*) filter (where is_due and is_otif)                          as otif_lines,
        count(*) filter (where is_due and days_late > 0)                    as late_lines,
        avg(lead_time_days) filter (where is_due)                           as avg_lead_time_days,
        avg(days_late) filter (where is_due and days_late > 0)              as avg_days_late,
        sum(lead_time_days) filter (where is_due and lead_time_days is not null)::numeric
            / nullif(sum(planned_lead_time_days) filter (where is_due and lead_time_days is not null), 0)
                                                                            as lead_time_ratio,
        coalesce(sum(order_value_eur) filter (where is_due), 0)             as order_value_eur
    from mart.fact_po_line
    group by supplier_key
),
quality as (
    select
        supplier_key,
        count(*) filter (where is_decided)                  as lots_inspected,
        count(*) filter (where is_decided and has_defects)  as lots_with_defects,
        count(*) filter (where is_rejected)                 as lots_rejected,
        sum(lot_qty) filter (where is_decided)              as inspected_qty,
        sum(rejected_qty) filter (where is_decided)         as rejected_qty
    from mart.fact_inspection
    group by supplier_key
),
kpi as (
    select
        s.supplier_key,
        s.supplier_id,
        s.supplier_name,
        s.country_name,
        s.region,
        coalesce(d.due_lines, 0)                            as due_lines,
        d.otif_lines::numeric / nullif(d.due_lines, 0)      as otif_pct,
        d.on_time_lines::numeric / nullif(d.due_lines, 0)   as on_time_pct,
        d.in_full_lines::numeric / nullif(d.due_lines, 0)   as in_full_pct,
        coalesce(d.late_lines, 0)                           as late_lines,
        d.avg_lead_time_days,
        d.avg_days_late,
        d.lead_time_ratio,
        coalesce(d.order_value_eur, 0)                      as order_value_eur,
        coalesce(q.lots_inspected, 0)                       as lots_inspected,
        coalesce(q.lots_with_defects, 0)                    as lots_with_defects,
        coalesce(q.lots_rejected, 0)                        as lots_rejected,
        q.inspected_qty,
        q.rejected_qty,
        q.rejected_qty / nullif(q.inspected_qty, 0)         as defect_rate
    from mart.dim_supplier s
    left join delivery d using (supplier_key)
    left join quality q using (supplier_key)
),
scored as (
    select
        kpi.*,
        100 * kpi.otif_pct                                              as delivery_score,
        100 * greatest(0, least(1, 2 - kpi.lead_time_ratio))            as lead_time_score,
        100 * greatest(0, 1 - kpi.defect_rate / k.defect_rate_cap)      as quality_score,
        k.weight_delivery, k.weight_lead_time, k.weight_quality
    from kpi
    cross join mart.kpi_params k
),
total as (
    select
        scored.*,
        (  coalesce(delivery_score * weight_delivery, 0)
         + coalesce(lead_time_score * weight_lead_time, 0)
         + coalesce(quality_score * weight_quality, 0))
        / nullif(  case when delivery_score  is null then 0 else weight_delivery end
                 + case when lead_time_score is null then 0 else weight_lead_time end
                 + case when quality_score   is null then 0 else weight_quality end, 0)
            as supplier_score
    from scored
)
select
    supplier_key,
    supplier_id,
    supplier_name,
    country_name,
    region,
    due_lines,
    round(otif_pct, 4)                          as otif_pct,
    round(on_time_pct, 4)                       as on_time_pct,
    round(in_full_pct, 4)                       as in_full_pct,
    late_lines,
    round(avg_lead_time_days, 1)                as avg_lead_time_days,
    round(avg_days_late, 1)                     as avg_days_late,
    round(lead_time_ratio, 3)                   as lead_time_ratio,
    order_value_eur,
    lots_inspected,
    lots_with_defects,
    lots_rejected,
    inspected_qty,
    rejected_qty,
    round(defect_rate, 5)                       as defect_rate,
    round(defect_rate * 1000000)                as defect_ppm,
    round(delivery_score, 1)                    as delivery_score,
    round(lead_time_score, 1)                   as lead_time_score,
    round(quality_score, 1)                     as quality_score,
    round(supplier_score, 1)                    as supplier_score,
    rank() over (order by supplier_score desc nulls last) as supplier_rank
from total;


-- Monthly trend per supplier: delivery by due month, quality by lot month.
create or replace view mart.v_supplier_month as
with delivery as (
    select
        f.supplier_key,
        d.month_start,
        count(*) filter (where f.is_due)                    as due_lines,
        count(*) filter (where f.is_due and f.is_on_time)   as on_time_lines,
        count(*) filter (where f.is_due and f.is_in_full)   as in_full_lines,
        count(*) filter (where f.is_due and f.is_otif)      as otif_lines,
        avg(f.lead_time_days) filter (where f.is_due)       as avg_lead_time_days
    from mart.fact_po_line f
    join mart.dim_date d on d.date_key = f.due_date_key
    group by f.supplier_key, d.month_start
),
quality as (
    select
        i.supplier_key,
        d.month_start,
        sum(i.lot_qty) filter (where i.is_decided)      as inspected_qty,
        sum(i.rejected_qty) filter (where i.is_decided) as rejected_qty
    from mart.fact_inspection i
    join mart.dim_date d on d.date_key = i.lot_date_key
    group by i.supplier_key, d.month_start
)
select
    s.supplier_id,
    s.supplier_name,
    month_start,
    to_char(month_start, 'YYYY-MM')                             as year_month,
    coalesce(dl.due_lines, 0)                                   as due_lines,
    coalesce(dl.on_time_lines, 0)                               as on_time_lines,
    coalesce(dl.in_full_lines, 0)                               as in_full_lines,
    coalesce(dl.otif_lines, 0)                                  as otif_lines,
    round(dl.otif_lines::numeric / nullif(dl.due_lines, 0), 4)  as otif_pct,
    round(dl.avg_lead_time_days, 1)                             as avg_lead_time_days,
    q.inspected_qty,
    q.rejected_qty,
    round(q.rejected_qty / nullif(q.inspected_qty, 0), 5)       as defect_rate
from delivery dl
full join quality q using (supplier_key, month_start)
join mart.dim_supplier s using (supplier_key)
where coalesce(dl.due_lines, 0) > 0 or q.inspected_qty is not null;
