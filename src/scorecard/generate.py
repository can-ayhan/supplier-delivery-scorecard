"""Generate three SAP-style list exports to build the scorecard against.

Nothing in here is real company data. The generator imitates what lands on an
analyst's desk after exporting purchase order items (ME2N), material documents
(MB51) and inspection lots (QA32) to local files:

* semicolon separated, technical field names in the header
* dates as DD.MM.YYYY, numbers as 1.250,000 and negatives with a trailing minus
* vendor and material numbers padded with leading zeros (sometimes stripped by
  whoever opened the file in Excel before forwarding it)
* overlapping export runs, so a slice of the rows shows up twice

Each supplier gets its own delivery and quality behaviour so the resulting
scorecard has something to show. On top of that a known set of data problems is
planted and written to ``planted_issues.json`` so the validation layer can be
tested against it.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEED = 4217
PERIOD_START = date(2025, 2, 3)
EXPORT_DATE = date(2026, 7, 31)  # the day the three lists were pulled

PO_FILE = "purchase_orders_ME2N.csv"
GR_FILE = "goods_receipts_MB51.csv"
QA_FILE = "inspection_lots_QA32.csv"
MANIFEST_FILE = "planted_issues.json"

PO_COLUMNS = [
    "EBELN", "EBELP", "BEDAT", "LIFNR", "NAME1", "LAND1", "MATNR", "TXZ01", "MATKL",
    "WERKS", "MENGE", "MEINS", "NETPR", "PEINH", "WAERS", "EINDT", "LOEKZ", "ELIKZ",
]
GR_COLUMNS = [
    "MBLNR", "MJAHR", "ZEILE", "BUDAT", "BWART", "EBELN", "EBELP", "MATNR", "WERKS",
    "LIFNR", "MENGE", "MEINS",
]
QA_COLUMNS = [
    "PRUEFLOS", "WERK", "MATNR", "LIFNR", "EBELN", "EBELP", "MBLNR", "MJAHR", "ZEILE",
    "ENSTEHDAT", "LOSMENGE", "MENGENEINH", "VCODE", "VDATUM", "LMENGE01", "LMENGE04",
    "LMENGE07",
]

PLANTS = ["1000", "1000", "1000", "1100", "1100", "2000"]  # weighted

# --------------------------------------------------------------------------
# master data
# --------------------------------------------------------------------------


@dataclass
class Supplier:
    id: int
    name: str
    country: str
    lead_days: int        # typical quoted lead time
    on_time: float        # base probability a line arrives by the due date
    in_full: float        # base probability a line arrives complete
    defect: float         # base quality problem rate
    late_mean: float      # mean days late when a line is late
    weight: float         # share of purchase orders
    groups: tuple[str, ...]
    trend: int = 0        # +1 improving over the period, -1 getting worse
    old_name: str | None = None  # vendor master name before it was cleaned up


SUPPLIERS = [
    Supplier(100234, "Müller Präzisionsteile GmbH", "DE", 14, 0.93, 0.97, 0.004, 3, 7, ("CAST", "FAST"),
             old_name="MUELLER PRAEZISIONSTEILE GMBH"),
    Supplier(100871, "Kowalski Metal Sp. z o.o.", "PL", 10, 0.90, 0.96, 0.008, 3, 6, ("RAWM", "CAST")),
    Supplier(101455, "Bohemia Plast s.r.o.", "CZ", 12, 0.86, 0.95, 0.012, 4, 6, ("PLAS",)),
    Supplier(102018, "Officine Meccaniche Rossi S.p.A.", "IT", 21, 0.78, 0.93, 0.009, 6, 4, ("CAST", "BEAR"), trend=1),
    Supplier(102633, "Anadolu Döküm Sanayi A.S.", "TR", 28, 0.74, 0.90, 0.021, 7, 4, ("CAST",)),
    Supplier(103102, "Shenzhen Brightway Electronics Co., Ltd.", "CN", 56, 0.69, 0.92, 0.015, 10, 5, ("ELEC",)),
    Supplier(103547, "Nordlicht Verpackung GmbH", "DE", 7, 0.96, 0.99, 0.002, 2, 5, ("PACK",)),
    Supplier(104090, "Wisla Fasteners Sp. z o.o.", "PL", 9, 0.94, 0.98, 0.003, 2, 7, ("FAST",)),
    Supplier(104726, "Frankenlager Antriebstechnik GmbH", "DE", 18, 0.91, 0.97, 0.005, 4, 4, ("BEAR",)),
    Supplier(105311, "Ningbo Eastgate Casting Co., Ltd.", "CN", 63, 0.62, 0.88, 0.034, 12, 3, ("CAST",), trend=-1),
    Supplier(105968, "Tatra Tooling a.s.", "SK", 15, 0.88, 0.95, 0.010, 4, 4, ("CAST", "FAST")),
    Supplier(106420, "Silesia Components Sp. z o.o.", "PL", 11, 0.83, 0.93, 0.014, 5, 6, ("ELEC", "PLAS"), trend=-1,
             old_name="Silesia Components"),
    Supplier(107015, "Pune Precision Forgings Pvt. Ltd.", "IN", 60, 0.71, 0.91, 0.019, 9, 3, ("CAST",), trend=1),
    Supplier(107682, "Elektro-Bauteile Hartmann KG", "DE", 16, 0.89, 0.96, 0.006, 4, 6, ("ELEC",)),
    Supplier(108239, "Plásticos Levante S.L.", "ES", 24, 0.80, 0.94, 0.011, 6, 3, ("PLAS",)),
    Supplier(108804, "Bursa Kablo ve Elektrik A.S.", "TR", 26, 0.85, 0.95, 0.007, 5, 4, ("ELEC",)),
    Supplier(109377, "Carton Baltic UAB", "LT", 8, 0.92, 0.98, 0.003, 3, 4, ("PACK",)),
    Supplier(109950, "Lombarda Guarnizioni S.r.l.", "IT", 20, 0.87, 0.96, 0.008, 5, 3, ("PLAS",)),
    Supplier(110486, "Dongguan Hualong Plastic Co., Ltd.", "CN", 52, 0.66, 0.90, 0.027, 11, 3, ("PLAS",)),
    Supplier(111043, "Morava Ložiska s.r.o.", "CZ", 14, 0.90, 0.97, 0.006, 3, 4, ("BEAR",)),
    Supplier(111619, "Pomorze Odlewnia S.A.", "PL", 17, 0.79, 0.92, 0.024, 6, 4, ("CAST", "RAWM"), trend=1),
    Supplier(112204, "Alpen Schraubenwerk GmbH", "AT", 12, 0.95, 0.98, 0.002, 2, 5, ("FAST",)),
]

# group -> (uom, price range, typical quantity range, quantity step, price unit, share of receipts inspected)
GROUPS = {
    "FAST": ("ST", (2.0, 60.0), (2000, 40000), 500, 100, 0.35),
    "ELEC": ("ST", (0.40, 18.0), (200, 8000), 100, 1, 1.0),
    "PLAS": ("ST", (0.15, 4.5), (500, 20000), 250, 1, 1.0),
    "CAST": ("ST", (3.5, 48.0), (50, 2500), 10, 1, 1.0),
    "PACK": ("ST", (0.10, 2.2), (500, 15000), 100, 1, 0.25),
    "BEAR": ("ST", (2.8, 75.0), (20, 1500), 10, 1, 1.0),
    "RAWM": ("KG", (1.1, 6.5), (500, 12000), 100, 1, 1.0),
}

MATERIAL_TEXTS = {
    "FAST": [
        "Hex bolt M8x40 8.8 zinc", "Hex bolt M10x60 8.8 zinc", "Hex bolt M12x80 10.9",
        "Socket screw M5x16 12.9", "Socket screw M6x25 12.9", "Socket screw M8x30 A2-70",
        "Hex nut M8 DIN 934", "Hex nut M10 DIN 934", "Lock nut M12 DIN 985",
        "Washer 8.4 DIN 125", "Washer 10.5 DIN 125", "Spring washer M8 DIN 127",
        "Self-tapping screw 4.2x16", "Threaded rod M10x1000", "Rivet 4.8x12 alu/steel",
        "Dowel pin 6x30 h6",
    ],
    "ELEC": [
        "Connector 6-pin 2.54mm", "Connector 12-pin sealed", "Relay 12V 30A SPDT",
        "Relay 24V 10A DPDT", "Capacitor 470uF 35V", "Capacitor 100nF 50V X7R",
        "Resistor 10k 1% 0603", "Resistor 4R7 5W wirewound", "PCB assy controller rev C",
        "PCB assy sensor board rev B", "Cable harness main 1.8m", "Cable harness door 0.6m",
        "Fuse holder blade 30A", "Proximity sensor M12 PNP", "Temperature sensor NTC 10k",
        "Micro switch 5A lever", "LED indicator 24V green", "DC fan 80mm 24V",
    ],
    "PLAS": [
        "Housing cover ABS black", "Housing base ABS black", "Cable gland PG11 PA6",
        "Cable clip 8mm PA66", "Bezel front PC/ABS grey", "Knob 22mm PA6 GF30",
        "Gasket EPDM 120x80", "O-ring 34x3 NBR 70", "O-ring 52x2.5 FKM",
        "Seal lip 40x62x8 NBR", "Grommet 12mm TPE", "Spacer 10mm POM",
        "Hinge cap PP white", "Fan guard 80mm PA", "Air duct PP 300mm", "End cap 40x40 PE",
    ],
    "CAST": [
        "Bracket casting AlSi9 left", "Bracket casting AlSi9 right", "Gear housing GJL-250",
        "Bearing block GJS-400", "Flange forged C45 DN50", "Flange forged C45 DN80",
        "Shaft forged 42CrMo4 d40", "Lever arm cast steel", "Pump body AlSi10Mg",
        "Motor end shield GJL-200", "Mounting plate laser cut 6mm", "Bracket bent S235 3mm",
        "Hub forged C45 d120", "Cover plate die-cast Zn", "Heat sink extruded Al 150mm",
        "Yoke forged 16MnCr5",
    ],
    "PACK": [
        "Carton 400x300x200 BC flute", "Carton 600x400x300 BC flute", "Pallet box 1200x800x600",
        "PE bag 300x400 50my", "Foam insert PE 380x280", "Stretch film 500mm 23my",
        "Label 100x150 thermal", "Corner protector 50x50x1000",
    ],
    "BEAR": [
        "Ball bearing 6204-2RS", "Ball bearing 6206-2Z", "Ball bearing 6308-2RS C3",
        "Tapered roller bearing 30206", "Needle bearing HK2016", "Linear bearing LM20UU",
        "Timing belt HTD 5M-450-15", "V-belt SPA 1250", "Gear motor 0.37kW i=20",
        "Coupling jaw size 24",
    ],
    "RAWM": [
        "Steel bar C45 round d30", "Steel bar S355 flat 40x10", "Aluminium bar 6082 d50",
        "PA6 GF30 granulate black", "ABS granulate natural", "Sheet DC01 1.5mm",
    ],
}


@dataclass
class Material:
    id: int
    text: str
    group: str
    uom: str
    price: float
    price_unit: int
    typical_qty: int
    step: int
    suppliers: list[Supplier]


@dataclass
class PoLine:
    po: int
    item: int
    po_date: date
    supplier: Supplier
    material: Material
    plant: str
    qty: float
    price: float
    due: date
    deleted: bool = False
    closed: bool = False


@dataclass
class Posting:
    """One material document line (goods receipt, reversal or return)."""

    line: PoLine
    posting: date
    qty: float                 # always positive, sign comes from the movement type
    bwart: str = "101"
    inspect: bool = True       # erroneous postings that get reversed never reach QA
    doc: int = 0
    doc_item: int = 0


@dataclass
class Lot:
    receipt: Posting
    created: date
    decided: date | None
    code: str                  # A accept, AB accepted with part rejected, R rejected, "" open
    accepted: float = 0.0
    blocked: float = 0.0
    returned: float = 0.0
    number: int = 0


@dataclass
class Planted:
    """Keys of the problems that were deliberately put into the exports."""

    duplicate_po_lines: list = field(default_factory=list)
    duplicate_receipt_lines: list = field(default_factory=list)
    duplicate_lots: list = field(default_factory=list)
    receipts_without_po: list = field(default_factory=list)
    receipt_material_mismatch: list = field(default_factory=list)
    receipt_uom_mismatch: list = field(default_factory=list)
    over_delivery: list = field(default_factory=list)
    closed_short: list = field(default_factory=list)
    receipt_before_po_date: list = field(default_factory=list)
    receipt_bad_date: list = field(default_factory=list)
    lots_without_receipt: list = field(default_factory=list)
    deleted_line_with_receipt: list = field(default_factory=list)


# --------------------------------------------------------------------------
# formatting helpers (SAP list output style)
# --------------------------------------------------------------------------


def sap_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def sap_number(value: float, decimals: int = 3) -> str:
    """1250.5 -> '1.250,500', -40 -> '40,000-'."""
    text = f"{abs(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + "-" if value < 0 else text


def po_key(po: int, item: int) -> list[str]:
    return [f"{po:010d}", f"{item:05d}"]


def next_business_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def add_business_days(d: date, days: int) -> date:
    step = 1 if days >= 0 else -1
    for _ in range(abs(days)):
        d += timedelta(days=step)
        while d.weekday() >= 5:
            d += timedelta(days=step)
    return d


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------


def _materials(rng: random.Random) -> list[Material]:
    materials: list[Material] = []
    next_id = 40001000
    for group, texts in MATERIAL_TEXTS.items():
        uom, (p_lo, p_hi), (q_lo, q_hi), step, price_unit, _ = GROUPS[group]
        sources = [s for s in SUPPLIERS if group in s.groups]
        for text in texts:
            next_id += rng.randint(3, 40)
            price = round(p_lo * (p_hi / p_lo) ** rng.random(), 2)  # log-uniform, most parts are cheap
            typical = int(rng.uniform(q_lo, q_hi) // step * step) or step
            count = 1 if len(sources) == 1 else rng.choice([1, 2, 2, 3])
            materials.append(
                Material(next_id, text, group, uom, price, price_unit, typical, step,
                         rng.sample(sources, min(count, len(sources))))
            )
    return materials


def _progress(d: date) -> float:
    return (d - PERIOD_START).days / (EXPORT_DATE - PERIOD_START).days


def _purchase_orders(rng: random.Random, materials: list[Material]) -> list[PoLine]:
    by_supplier: dict[int, list[Material]] = {}
    for m in materials:
        for s in m.suppliers:
            by_supplier.setdefault(s.id, []).append(m)
    active = [s for s in SUPPLIERS if s.id in by_supplier]
    weights = [s.weight for s in active]

    lines: list[PoLine] = []
    po_number = 4500012000
    day = PERIOD_START
    last_po_day = EXPORT_DATE - timedelta(days=4)
    while day <= last_po_day:
        if day.weekday() < 5:
            for _ in range(rng.choice([2, 3, 4, 4, 5, 5, 6, 7])):
                supplier = rng.choices(active, weights)[0]
                catalogue = by_supplier[supplier.id]
                n_items = min(len(catalogue), rng.choice([1, 1, 2, 2, 3, 3, 4, 5]))
                po_number += rng.randint(1, 4)
                plant = rng.choice(PLANTS)
                for i, material in enumerate(rng.sample(catalogue, n_items), start=1):
                    qty = material.typical_qty * rng.lognormvariate(0, 0.45)
                    qty = max(material.step, round(qty / material.step) * material.step)
                    price = round(material.price * rng.uniform(0.97, 1.03), 2)
                    lead = max(3, supplier.lead_days + rng.randint(-2, 4))
                    due = next_business_day(day + timedelta(days=lead))
                    lines.append(PoLine(po_number, i * 10, day, supplier, material, plant, float(qty), price, due))
        day += timedelta(days=1)
    return lines


def _seasonal_penalty(supplier: Supplier, due: date) -> float:
    penalty = 0.0
    if due.month in (12, 1):
        penalty += 0.08          # year-end shutdowns
    if due.month == 8:
        penalty += 0.04          # summer holidays
    if supplier.country == "CN" and due.month in (2, 3):
        penalty += 0.15          # Chinese New Year backlog
    return penalty


def _receipts(rng: random.Random, lines: list[PoLine], planted: Planted) -> list[Posting]:
    postings: list[Posting] = []

    def post(line: PoLine, when: date, qty: float, **kw) -> None:
        when = next_business_day(max(when, line.po_date + timedelta(days=1)))
        if when <= EXPORT_DATE and qty > 0:
            postings.append(Posting(line, when, round(qty, 3), **kw))

    for line in lines:
        s = line.supplier
        drift = s.trend * (0.20 * _progress(line.po_date) - 0.10)

        # a few lines get cancelled before anything ships
        if rng.random() < 0.008:
            line.deleted = True
            continue

        p_on_time = min(0.99, max(0.05, s.on_time + drift - _seasonal_penalty(s, line.due)))
        on_time = rng.random() < p_on_time
        if on_time:
            arrival = add_business_days(line.due, -rng.choice([0, 0, 0, 0, 1, 1, 2, 3, 5]))
        else:
            arrival = line.due + timedelta(days=1 + int(rng.expovariate(1 / s.late_mean)))

        in_full = rng.random() < min(0.995, max(0.3, s.in_full + drift / 2))
        bulk = line.material.uom == "KG"
        full_qty = line.qty * (rng.uniform(0.985, 1.03) if bulk else 1.0)

        if in_full:
            if rng.random() < 0.8:
                post(line, arrival, full_qty)
            else:  # split shipment, the second part can slip past the due date
                first = round(full_qty * rng.uniform(0.4, 0.7) / line.material.step) * line.material.step
                first = min(max(first, line.material.step), full_qty)
                post(line, arrival, first)
                post(line, arrival + timedelta(days=rng.randint(2, 9)), full_qty - first)
        else:
            share = rng.uniform(0.55, 0.93)
            first = max(line.material.step, round(line.qty * share / line.material.step) * line.material.step)
            first = min(first, line.qty)
            post(line, arrival, first)
            if rng.random() < 0.5:
                post(line, arrival + timedelta(days=rng.randint(8, 25)), line.qty - first)
            elif rng.random() < 0.6 and arrival + timedelta(days=20) < EXPORT_DATE:
                line.closed = True  # buyer gave up on the rest and set "delivery completed"
                if first < line.qty * 0.9:
                    planted.closed_short.append(po_key(line.po, line.item))

    # posting errors: wrong quantity keyed in, reversed, posted again
    for wrong in rng.sample(postings, k=int(len(postings) * 0.012)):
        typo = round(wrong.qty * rng.choice([10, 0.1, 2]), 3)
        fix_day = next_business_day(wrong.posting + timedelta(days=rng.choice([0, 0, 1, 3])))
        if fix_day > EXPORT_DATE or typo == wrong.qty:
            continue
        postings.append(Posting(wrong.line, wrong.posting, typo, "101", inspect=False))
        postings.append(Posting(wrong.line, fix_day, typo, "102", inspect=False))
        wrong.posting = fix_day

    # over-deliveries well beyond tolerance (pallet rounding, double shipments)
    single = {}
    for p in postings:
        single.setdefault((p.line.po, p.line.item), []).append(p)
    candidates = [ps[0] for ps in single.values()
                  if len(ps) == 1 and ps[0].line.material.uom == "ST" and not ps[0].line.closed]
    for p in rng.sample(candidates, k=14):
        p.qty = float(round(p.line.qty * rng.uniform(1.12, 1.35) / p.line.material.step) * p.line.material.step)
        if p.qty <= p.line.qty * 1.1:
            p.qty = p.line.qty + 2 * p.line.material.step
        planted.over_delivery.append(po_key(p.line.po, p.line.item))

    # cancelled lines that somehow still received goods
    cancelled = [ln for ln in lines if ln.deleted]
    for line in rng.sample(cancelled, k=min(3, len(cancelled))):
        when = next_business_day(line.due)
        if when <= EXPORT_DATE:
            postings.append(Posting(line, when, line.qty))
            planted.deleted_line_with_receipt.append(po_key(line.po, line.item))

    return postings


def _inspection_lots(rng: random.Random, postings: list[Posting]) -> tuple[list[Lot], list[Posting]]:
    lots: list[Lot] = []
    returns: list[Posting] = []
    for p in postings:
        if p.bwart != "101" or not p.inspect:
            continue
        if rng.random() > GROUPS[p.line.material.group][5]:
            continue
        s = p.line.supplier
        defect = max(0.0005, s.defect * (1 - s.trend * (0.8 * _progress(p.posting) - 0.4)))
        decided = add_business_days(p.posting, rng.choice([0, 1, 1, 2, 2, 3, 5]))
        if decided > EXPORT_DATE:
            lots.append(Lot(p, p.posting, None, ""))
            continue
        roll = rng.random()
        if roll < defect * 1.2:
            lot = Lot(p, p.posting, decided, "R")
            if rng.random() < 0.7:
                lot.returned = p.qty
            else:
                lot.blocked = p.qty
        elif roll < defect * 6.2:
            bad = round(p.qty * rng.uniform(0.02, 0.25), 0 if p.line.material.uom == "ST" else 3)
            bad = min(p.qty, max(1.0, bad))
            lot = Lot(p, p.posting, decided, "AB", accepted=p.qty - bad)
            if rng.random() < 0.5:
                lot.returned = bad
            else:
                lot.blocked = bad
        else:
            lot = Lot(p, p.posting, decided, "A", accepted=p.qty)
        lots.append(lot)
        if lot.returned:
            back = next_business_day(decided + timedelta(days=rng.randint(1, 8)))
            if back <= EXPORT_DATE:
                returns.append(Posting(p.line, back, lot.returned, "122", inspect=False))
    return lots, returns


def _number_documents(postings: list[Posting], lots: list[Lot]) -> None:
    """Material documents are numbered in posting order, one per PO and day."""
    postings.sort(key=lambda p: (p.posting, p.line.po, p.bwart, p.line.item))
    doc = 5000031000
    current = None
    item = 0
    for p in postings:
        key = (p.posting, p.line.po, p.bwart)
        if key != current:
            current, item = key, 0
            doc += 1
        item += 1
        p.doc, p.doc_item = doc, item
    lots.sort(key=lambda lot: (lot.created, lot.receipt.doc, lot.receipt.doc_item))
    for n, lot in enumerate(lots, start=10000004200):
        lot.number = n


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


def _po_rows(rng: random.Random, lines: list[PoLine]) -> list[dict]:
    rename_cutoff = PERIOD_START + timedelta(days=150)
    rows = []
    for ln in lines:
        s = ln.supplier
        name = s.old_name if s.old_name and ln.po_date < rename_cutoff else s.name
        text = ln.material.text + (" " * rng.randint(1, 3) if rng.random() < 0.05 else "")
        rows.append({
            "EBELN": f"{ln.po:010d}",
            "EBELP": f"{ln.item:05d}",
            "BEDAT": sap_date(ln.po_date),
            "LIFNR": f"{s.id:010d}",
            "NAME1": name,
            "LAND1": s.country,
            "MATNR": f"{ln.material.id:018d}",
            "TXZ01": text,
            "MATKL": ln.material.group,
            "WERKS": ln.plant,
            "MENGE": sap_number(ln.qty),
            "MEINS": ln.material.uom,
            "NETPR": sap_number(ln.price, 2),
            "PEINH": str(ln.material.price_unit),
            "WAERS": "EUR",
            "EINDT": sap_date(ln.due),
            "LOEKZ": "L" if ln.deleted else "",
            "ELIKZ": "X" if ln.closed else "",
        })
    return rows


def _gr_rows(postings: list[Posting]) -> list[dict]:
    rows = []
    for p in postings:
        sign = 1 if p.bwart == "101" else -1
        rows.append({
            "MBLNR": f"{p.doc:010d}",
            "MJAHR": str(p.posting.year),
            "ZEILE": f"{p.doc_item:04d}",
            "BUDAT": sap_date(p.posting),
            "BWART": p.bwart,
            "EBELN": f"{p.line.po:010d}",
            "EBELP": f"{p.line.item:05d}",
            "MATNR": f"{p.line.material.id:018d}",
            "WERKS": p.line.plant,
            "LIFNR": f"{p.line.supplier.id:010d}",
            "MENGE": sap_number(sign * p.qty),
            "MEINS": p.line.material.uom,
        })
    return rows


def _qa_rows(lots: list[Lot]) -> list[dict]:
    rows = []
    for lot in lots:
        p = lot.receipt
        rows.append({
            "PRUEFLOS": f"{lot.number:012d}",
            "WERK": p.line.plant,
            "MATNR": f"{p.line.material.id:018d}",
            "LIFNR": f"{p.line.supplier.id:010d}",
            "EBELN": f"{p.line.po:010d}",
            "EBELP": f"{p.line.item:05d}",
            "MBLNR": f"{p.doc:010d}",
            "MJAHR": str(p.posting.year),
            "ZEILE": f"{p.doc_item:04d}",
            "ENSTEHDAT": sap_date(lot.created),
            "LOSMENGE": sap_number(p.qty),
            "MENGENEINH": p.line.material.uom,
            "VCODE": lot.code,
            "VDATUM": sap_date(lot.decided),
            "LMENGE01": sap_number(lot.accepted),
            "LMENGE04": sap_number(lot.blocked),
            "LMENGE07": sap_number(lot.returned),
        })
    return rows


def _gr_key(row: dict) -> list[str]:
    return [row["MBLNR"], row["MJAHR"], row["ZEILE"]]


def _plant_issues(rng: random.Random, po: list[dict], gr: list[dict], qa: list[dict],
                  materials: list[Material], planted: Planted) -> None:
    """Row level problems: the kind that come from how the files were exported and handled."""
    # Row level problems stay away from lines that already carry a quantity
    # mismatch. Dropping the only receipt of an over-delivered line would turn
    # it into "nothing received" and hide the problem it was meant to show.
    taken = {tuple(key) for key in planted.over_delivery}
    taken |= {(r["EBELN"], r["EBELP"]) for r in po if r["ELIKZ"] or r["LOEKZ"]}
    clean_gr = [r for r in gr if r["BWART"] == "101" and (r["EBELN"], r["EBELP"]) not in taken]

    # receipts posted against purchase orders older than the PO export window
    for n in range(8):
        template = dict(rng.choice(clean_gr))
        template["EBELN"] = f"{4499990000 + rng.randint(100, 9000):010d}"
        template["MBLNR"] = f"{4999990000 + n:010d}"
        template["ZEILE"] = "0001"
        gr.append(template)
        planted.receipts_without_po.append(_gr_key(template))

    picks = rng.sample(clean_gr, k=6 + 5 + 4 + 3)
    for row in picks[:6]:
        other = rng.choice([m for m in materials if f"{m.id:018d}" != row["MATNR"]])
        row["MATNR"] = f"{other.id:018d}"
        planted.receipt_material_mismatch.append(_gr_key(row))
    for row in picks[6:11]:
        row["MEINS"] = "KAR" if row["MEINS"] == "ST" else "ST"
        planted.receipt_uom_mismatch.append(_gr_key(row))
    for row in picks[11:15]:
        day, month, year = row["BUDAT"].split(".")
        row["BUDAT"] = f"{day}.{month}.{int(year) - 1}"  # wrong year keyed in
        planted.receipt_before_po_date.append(_gr_key(row))
    for row in picks[15:]:
        row["BUDAT"] = "00.00.0000"
        planted.receipt_bad_date.append(_gr_key(row))

    # inspection lots whose material document is not in the receipts export
    for row in rng.sample([r for r in qa if r["VCODE"] == "A"], k=5):
        row["MBLNR"] = f"{4999980000 + rng.randint(1, 9999):010d}"
        planted.lots_without_receipt.append(row["PRUEFLOS"])

    # overlapping export runs: the same rows twice
    for row in rng.sample(po, k=12):
        po.insert(rng.randrange(len(po)), dict(row))
        planted.duplicate_po_lines.append([row["EBELN"], row["EBELP"]])
    for row in rng.sample(clean_gr, k=25):
        gr.insert(rng.randrange(len(gr)), dict(row))
        planted.duplicate_receipt_lines.append(_gr_key(row))
    for row in rng.sample(qa, k=6):
        qa.insert(rng.randrange(len(qa)), dict(row))
        planted.duplicate_lots.append(row["PRUEFLOS"])

    # harmless formatting noise that the cleaning step has to cope with
    for row in gr:
        roll = rng.random()
        if roll < 0.03:  # leading zeros lost in Excel
            row["LIFNR"] = row["LIFNR"].lstrip("0")
            row["MATNR"] = row["MATNR"].lstrip("0")
        elif roll < 0.05 and row["BUDAT"] != "00.00.0000":  # internal date format
            day, month, year = row["BUDAT"].split(".")
            row["BUDAT"] = f"{year}{month}{day}"


def _write(path: Path, columns: list[str], rows: list[dict], encoding: str) -> None:
    with path.open("w", newline="", encoding=encoding) as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter=";", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(out_dir: Path, seed: int = SEED) -> dict:
    """Write the three exports plus the planted-issue manifest. Returns row counts."""
    rng = random.Random(seed)
    planted = Planted()

    materials = _materials(rng)
    lines = _purchase_orders(rng, materials)
    postings = _receipts(rng, lines, planted)
    lots, returns = _inspection_lots(rng, postings)
    postings.extend(returns)
    _number_documents(postings, lots)

    po_rows = _po_rows(rng, lines)
    gr_rows = _gr_rows(postings)
    qa_rows = _qa_rows(lots)
    _plant_issues(rng, po_rows, gr_rows, qa_rows, materials, planted)

    out_dir.mkdir(parents=True, exist_ok=True)
    # the PO list is the only one with free text; it comes out of the old
    # system in Windows-1252, the other two are plain ASCII
    _write(out_dir / PO_FILE, PO_COLUMNS, po_rows, "cp1252")
    _write(out_dir / GR_FILE, GR_COLUMNS, gr_rows, "ascii")
    _write(out_dir / QA_FILE, QA_COLUMNS, qa_rows, "ascii")

    counts = {PO_FILE: len(po_rows), GR_FILE: len(gr_rows), QA_FILE: len(qa_rows)}
    manifest = {
        "seed": seed,
        "export_date": EXPORT_DATE.isoformat(),
        "rows": counts,
        "planted": {name: sorted(keys) for name, keys in vars(planted).items()},
    }
    (out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return counts
