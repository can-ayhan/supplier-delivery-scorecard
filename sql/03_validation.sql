-- Validation before anything reaches the report.
--
-- Two kinds of findings:
--   error    the row cannot be trusted and is left out of the marts
--   warning  the row is kept, but somebody should look at it
--
-- Every *_checked view carries a reject_reason (NULL = fine). The *_valid
-- views are what the mart build reads, so "what was dropped and why" always
-- matches what the report shows.

drop table if exists dq.checks cascade;
create table dq.checks (
    check_id    text primary key,
    source      text not null,
    severity    text not null check (severity in ('error', 'warning')),
    handling    text not null,
    description text not null
);

insert into dq.checks values
    ('PO_DUPLICATE_LINE',    'Purchase orders', 'error',   'Later copy dropped', 'Same PO number and item exported more than once'),
    ('PO_UNREADABLE_VALUE',  'Purchase orders', 'error',   'Row dropped',        'Key, date or quantity is empty or could not be read'),
    ('GR_DUPLICATE_LINE',    'Goods receipts',  'error',   'Later copy dropped', 'Same material document line exported more than once'),
    ('GR_UNREADABLE_VALUE',  'Goods receipts',  'error',   'Row dropped',        'Posting date or quantity is empty or could not be read'),
    ('GR_NO_PURCHASE_ORDER', 'Goods receipts',  'error',   'Row dropped',        'Receipt refers to a PO line that is not in the PO export'),
    ('GR_MATERIAL_MISMATCH', 'Goods receipts',  'error',   'Row dropped',        'Receipt was posted for a different material than the PO line'),
    ('GR_UOM_MISMATCH',      'Goods receipts',  'error',   'Row dropped',        'Receipt unit differs from the PO line, quantities are not comparable'),
    ('GR_BEFORE_PO_DATE',    'Goods receipts',  'error',   'Row dropped',        'Receipt is dated before the purchase order was created'),
    ('GR_ON_DELETED_LINE',   'Goods receipts',  'warning', 'Kept',               'Goods were received on a PO line flagged as deleted'),
    ('LINE_OVER_DELIVERY',   'Ordered vs received', 'warning', 'Kept',           'Received quantity exceeds the ordered quantity beyond tolerance'),
    ('LINE_CLOSED_SHORT',    'Ordered vs received', 'warning', 'Kept',           'Line set to delivery completed with less than the tolerated quantity received'),
    ('QA_DUPLICATE_LOT',     'Inspection lots', 'error',   'Later copy dropped', 'Same inspection lot exported more than once'),
    ('QA_UNREADABLE_VALUE',  'Inspection lots', 'error',   'Row dropped',        'Lot number, date or quantity is empty or could not be read'),
    ('QA_NO_RECEIPT',        'Inspection lots', 'warning', 'Kept',               'Lot refers to a material document that is not in the receipts export'),
    ('QA_QTY_NOT_BALANCED',  'Inspection lots', 'warning', 'Kept',               'Accepted + blocked + returned does not add up to the lot quantity');


-- purchase order lines -----------------------------------------------------

create or replace view staging.v_purchase_orders_checked as
select
    p.*,
    case
        when p.dup_rank > 1 then 'PO_DUPLICATE_LINE'
        when p.po_number is null or p.po_item is null or p.po_date is null
          or p.due_date is null or p.supplier_id is null or p.material_id is null
          or p.ordered_qty is null or p.ordered_qty <= 0 then 'PO_UNREADABLE_VALUE'
    end as reject_reason
from staging.purchase_orders p;

create or replace view staging.v_purchase_orders_valid as
select * from staging.v_purchase_orders_checked where reject_reason is null;


-- goods receipts -----------------------------------------------------------

create or replace view staging.v_goods_receipts_checked as
select
    g.*,
    p.is_deleted as po_line_deleted,
    case
        when g.dup_rank > 1 then 'GR_DUPLICATE_LINE'
        when g.posting_date is null or g.quantity is null then 'GR_UNREADABLE_VALUE'
        when p.po_number is null then 'GR_NO_PURCHASE_ORDER'
        when g.material_id is distinct from p.material_id then 'GR_MATERIAL_MISMATCH'
        when g.uom is distinct from p.uom then 'GR_UOM_MISMATCH'
        when g.posting_date < p.po_date then 'GR_BEFORE_PO_DATE'
    end as reject_reason
from staging.goods_receipts g
left join staging.v_purchase_orders_valid p
       on p.po_number = g.po_number and p.po_item = g.po_item;

create or replace view staging.v_goods_receipts_valid as
select * from staging.v_goods_receipts_checked where reject_reason is null;


-- inspection lots ----------------------------------------------------------

create or replace view staging.v_inspection_lots_checked as
select
    l.*,
    case
        when l.dup_rank > 1 then 'QA_DUPLICATE_LOT'
        when l.lot_number is null or l.created_date is null or l.lot_qty is null
          or l.supplier_id is null or l.material_id is null then 'QA_UNREADABLE_VALUE'
    end as reject_reason
from staging.inspection_lots l;

create or replace view staging.v_inspection_lots_valid as
select * from staging.v_inspection_lots_checked where reject_reason is null;


-- ordered versus received --------------------------------------------------
-- Net receipts are 101 minus 102. Returns to the supplier (122) are a quality
-- outcome and are tracked separately, they do not make a delivery "short".

create or replace view dq.v_ordered_vs_received as
with received as (
    select
        po_number,
        po_item,
        coalesce(sum(quantity) filter (where movement_type in ('101', '102')), 0) as received_qty,
        coalesce(-sum(quantity) filter (where movement_type = '122'), 0)          as returned_qty,
        count(*) filter (where movement_type = '101')                             as receipt_count
    from staging.v_goods_receipts_valid
    group by po_number, po_item
)
select
    p.po_number,
    p.po_item,
    p.supplier_id,
    p.material_id,
    p.due_date,
    p.is_deleted,
    p.is_delivery_complete,
    p.uom,
    p.ordered_qty,
    coalesce(r.received_qty, 0)                                 as received_qty,
    coalesce(r.returned_qty, 0)                                 as returned_qty,
    coalesce(r.received_qty, 0) - p.ordered_qty                 as qty_difference,
    round(coalesce(r.received_qty, 0) / p.ordered_qty, 4)       as received_ratio,
    case
        when coalesce(r.received_qty, 0) = 0                                    then 'nothing received'
        when r.received_qty > p.ordered_qty * (1 + k.over_delivery_tolerance)   then 'over delivery'
        when r.received_qty >= p.ordered_qty * (1 - k.in_full_tolerance)        then 'complete'
        when p.is_delivery_complete                                             then 'closed short'
        else 'partially received'
    end                                                         as status
from staging.v_purchase_orders_valid p
left join received r using (po_number, po_item)
cross join mart.kpi_params k;


-- all findings in one table ------------------------------------------------

drop table if exists dq.issues;
create table dq.issues as
select
    reject_reason                                           as check_id,
    'purchase_orders_ME2N.csv'                              as source_file,
    row_num,
    po_number,
    po_item,
    format('PO %s / %s', po_number, po_item)                as record_key,
    format('ordered %s %s, due %s', ordered_qty, uom, due_date) as detail
from staging.v_purchase_orders_checked
where reject_reason is not null

union all
select
    reject_reason,
    'goods_receipts_MB51.csv',
    row_num,
    po_number,
    po_item,
    format('Doc %s / %s / %s', doc_number, doc_year, doc_item),
    format('movement %s, %s %s posted %s, material %s', movement_type, quantity, uom, posting_date, material_id)
from staging.v_goods_receipts_checked
where reject_reason is not null

union all
select
    'GR_ON_DELETED_LINE',
    'goods_receipts_MB51.csv',
    row_num,
    po_number,
    po_item,
    format('Doc %s / %s / %s', doc_number, doc_year, doc_item),
    format('%s %s posted %s on a deleted PO line', quantity, uom, posting_date)
from staging.v_goods_receipts_valid
where po_line_deleted

union all
select
    case status when 'over delivery' then 'LINE_OVER_DELIVERY' else 'LINE_CLOSED_SHORT' end,
    'purchase_orders_ME2N.csv',
    null,
    o.po_number,
    o.po_item,
    format('PO %s / %s', o.po_number, o.po_item),
    format('ordered %s, received %s %s (%s %%)', o.ordered_qty, o.received_qty, o.uom, round(o.received_ratio * 100, 1))
from dq.v_ordered_vs_received o
cross join mart.kpi_params k
where o.status = 'over delivery'
   or (o.is_delivery_complete and o.received_qty < o.ordered_qty * (1 - k.closed_short_tolerance))

union all
select
    reject_reason,
    'inspection_lots_QA32.csv',
    row_num,
    po_number,
    po_item,
    format('Lot %s', lot_number),
    format('%s %s created %s', lot_qty, uom, created_date)
from staging.v_inspection_lots_checked
where reject_reason is not null

union all
select
    'QA_NO_RECEIPT',
    'inspection_lots_QA32.csv',
    l.row_num,
    l.po_number,
    l.po_item,
    format('Lot %s', l.lot_number),
    format('material document %s / %s / %s not found', l.doc_number, l.doc_year, l.doc_item)
from staging.v_inspection_lots_valid l
where not exists (
    select 1
    from staging.goods_receipts g
    where g.doc_number = l.doc_number and g.doc_year = l.doc_year and g.doc_item = l.doc_item
)

union all
select
    'QA_QTY_NOT_BALANCED',
    'inspection_lots_QA32.csv',
    row_num,
    po_number,
    po_item,
    format('Lot %s', lot_number),
    format('lot %s, accepted %s + blocked %s + returned %s', lot_qty, accepted_qty, blocked_qty, returned_qty)
from staging.v_inspection_lots_valid
where decision_code is not null
  and accepted_qty + blocked_qty + returned_qty <> lot_qty;

create index on dq.issues (check_id);

create or replace view dq.v_summary as
select
    c.source,
    c.check_id,
    c.severity,
    c.handling,
    c.description,
    count(i.check_id) as findings
from dq.checks c
left join dq.issues i using (check_id)
group by c.source, c.check_id, c.severity, c.handling, c.description
order by c.source, c.severity, c.check_id;
