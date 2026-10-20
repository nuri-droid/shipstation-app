"""Sample data so the app can be tried without any API keys (MOCK_MODE=1)."""
import random

SKUS = ["TR14IV", "TR711-WF", "TR8091", "TR8018", "TR950011", "TR555-CF", "TR8944",
        "TR456-VLSB-R", "TR460-VLBC-R", "TR035094", "TR2597AS", "BSW9978", "TR7659", "TRDP30"]
STATES = [("MS", "39564-2429", "OCEAN SPRINGS"), ("FL", "34473-3786", "OCALA"),
          ("CA", "94534-7901", "FAIRFIELD"), ("NJ", "07506-3824", "HAWTHORNE"),
          ("TX", "77082-8314", "HOUSTON"), ("MI", "48125-3329", "DEARBORN HEIGHTS"),
          ("IL", "60632-2825", "CHICAGO"), ("OH", "45371-2566", "TIPP CITY")]


def mock_orders(n=24, seed=7):
    rnd = random.Random(seed)
    rows = []
    order_id = 985300000
    i = 0
    while len(rows) < n:
        order_id += rnd.randint(1, 40)
        state, zip_code, city = rnd.choice(STATES)
        prefix = rnd.choice(["111", "112", "113", "114"])
        number = f"{prefix}-{rnd.randint(1000000, 9999999)}-{rnd.randint(1000000, 9999999)}"
        if i % 7 == 3:
            number = f"{rnd.randint(10, 27)}-{rnd.randint(15000, 15400)}-{rnd.randint(10000, 99999)}"
        weight = rnd.choice([4, 40, 76, 304, 480, 560.64, 820])
        zero_dims = i % 11 == 5
        for _ in range(2 if i % 6 == 0 else 1):
            rows.append({
                "order_id": str(order_id), "order_number": number,
                "qty": rnd.choice([1, 1, 1, 2, 4]), "sku": rnd.choice(SKUS), "item_name": "",
                "weight_oz": weight,
                "length": 0 if zero_dims else rnd.choice([8, 14, 20, 21]),
                "width": 0 if zero_dims else rnd.choice([8, 11, 15]),
                "height": 0 if zero_dims else rnd.choice([6, 10, 13]),
                "address": f"{rnd.randint(10, 9999)} MAIN ST", "city": city, "state": state,
                "postal": zip_code, "warehouse_id": rnd.choice(["735994, Chicago", "1438098, Texas"]),
                "residential": rnd.random() > 0.2, "custom_field1": "",
                "amount_net": round(rnd.uniform(15, 330), 2),
            })
        i += 1
    # one order number split into two ShipStation orders (shows up in ShipStation Check)
    dup = dict(rows[1]); dup["order_id"] = str(int(dup["order_id"]) + 1); rows.insert(2, dup)
    return rows[:n]


def mock_rates(packages, carrier, seed=11):
    rnd = random.Random(seed if carrier == "ups" else seed + 1)
    out = {}
    for key in sorted(packages):
        base = 7 + (packages[key]["weight_oz"] or 1) / 40
        out[key] = {}
        for wh in ("IL", "CA", "TX"):
            if carrier == "ups" and rnd.random() < 0.04:
                out[key][wh] = None          # "NO UPS SERVICE"
            else:
                out[key][wh] = round(base * rnd.uniform(0.85, 1.6), 2)
    return out


def mock_reference():
    rnd = random.Random(3)
    stock, aisles, landed, titles = {}, {"IL": {}, "CA": {}, "TX": {}}, {}, {}
    for s in SKUS:
        stock[s] = {"IL": rnd.choice([0, 3, 40, 160, 800]), "CA": 0, "TX": rnd.choice([0, 5, 60, 400])}
        aisles["IL"][s] = f"{rnd.choice('ABCDEFGH')}{rnd.randint(1, 12):02d}L{rnd.randint(0, 2)}"
        aisles["TX"][s] = f"{rnd.choice('ABCDEFGH')}{rnd.randint(1, 12):02d}{rnd.choice('ABC')}"
        landed[s] = round(rnd.uniform(4, 90), 2)
        titles[s] = f"Torque {s} replacement part for semi trucks"
    return {"stock": stock, "aisles": aisles, "landed_cost": landed, "titles": titles}, []
