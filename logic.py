"""All the calculations the Google Sheet did with formulas, in one place.

Input: the raw snapshot (orders + rates + reference data) and manual warehouse choices.
Output: rows ready for the Dashboard, Pick List, Rate Comparison and ShipStation Check pages.
"""
import re
from collections import defaultdict

import config

WH_KEYS = ["IL", "CA", "TX"]
LABEL_TO_KEY = {w["label"]: k for k, w in config.WAREHOUSES.items()}


def package_key(row):
    """Rows of the same ShipStation order share one package -> one set of rate requests."""
    return "|".join(str(x) for x in (row["order_id"], row["postal"], row["weight_oz"], row["length"],
                                     row["width"], row["height"], row["residential"]))


def marketplace(order_number):
    s = str(order_number)
    if re.fullmatch(r"\d{3}-\d{7}-\d{7}", s):
        return "Amazon"
    if re.fullmatch(r"\d{2}-\d{5}-\d{5}", s):
        return "eBay"
    if re.fullmatch(r"\d{18,20}", s):
        return "TikTok"
    if re.fullmatch(r"380\d{5}", s):
        return "Shopify"
    return "Other"


def _min(values):
    vals = [v for v in values if v is not None]
    return min(vals) if vals else None


def carrier_rate(row, wh):
    """Rate used for decisions at one warehouse, per ASSIGN_USING."""
    if config.ASSIGN_USING == "ups":
        return row["ups"].get(wh)
    return _min([row["ups"].get(wh), row["fedex"].get(wh)])


def auto_assign(row):
    """Port of the 'Automatic Warehouse Assign' formula.
    Chicago vs Texas: cheapest warehouse that has enough stock; on a tie, the one with more stock.
    California only when neither Chicago nor Texas has enough stock."""
    need = row["qty"]
    stock = row["stock"]
    eligible = {}
    for wh in ("IL", "TX"):
        rate = carrier_rate(row, wh)
        if stock[wh] >= need and rate is not None:
            eligible[wh] = rate
    if eligible:
        if len(eligible) == 2 and eligible["IL"] == eligible["TX"]:
            if stock["IL"] > stock["TX"]:
                return config.WAREHOUSES["IL"]["label"]
            if stock["TX"] > stock["IL"]:
                return config.WAREHOUSES["TX"]["label"]
            return "***Unassigned***"
        best = min(eligible, key=eligible.get)
        return config.WAREHOUSES[best]["label"]
    if stock["CA"] >= need:
        return config.WAREHOUSES["CA"]["label"]
    return "OUT OF STOCK"


def compute(snapshot, manual):
    ref = snapshot["reference"]
    ups = snapshot["ups_rates"]
    fedex = snapshot["fedex_rates"]
    rows = []
    for raw in snapshot["orders"]:
        r = dict(raw)
        key = package_key(r)
        r["ups"] = ups.get(key) or {k: None for k in WH_KEYS}
        r["fedex"] = fedex.get(key) or {k: None for k in WH_KEYS}
        r["stock"] = ref["stock"].get(r["sku"], {"IL": 0, "CA": 0, "TX": 0})
        r["title"] = ref["titles"].get(r["sku"], "")
        r["landed_unit"] = ref["landed_cost"].get(r["sku"])
        r["manual"] = manual.get((r["order_id"], r["sku"]), "")
        r["auto"] = auto_assign(r)
        r["assigned"] = r["manual"] or r["auto"]
        r["assigned_key"] = LABEL_TO_KEY.get(r["assigned"])
        r["aisle"] = (ref["aisles"].get(r["assigned_key"], {}).get(r["sku"], ".inform Manager")
                      if r["assigned_key"] else "")
        # WH Match: assignment differs from the warehouse already set in ShipStation
        a, w = r["assigned"], r["warehouse_id"]
        r["wh_match"] = not (("Chicago" in a and "Chicago" not in w) or ("California" in a and "California" not in w))
        rows.append(r)

    # Status column (the '-' column in the sheet)
    demand = defaultdict(int)
    for r in rows:
        demand[r["sku"]] += r["qty"]
    for r in rows:
        status = ""
        if not r["wh_match"]:
            status = "WH does not match"
        elif r["assigned"] == "OUT OF STOCK":
            status = "Not Enough Inventory"
        elif r["weight_oz"] > config.OVERWEIGHT_OZ:
            status = "Over 50 lbs."
        elif r["assigned_key"] and demand[r["sku"]] > r["stock"][r["assigned_key"]]:
            status = "Not Enough Inventory"
        r["status"] = status

    _profit(rows)
    _comparison(rows)
    return rows


def _profit(rows):
    """Cost tab port. Profit is per order number (all its rows show the same figures)."""
    by_number = defaultdict(list)
    for r in rows:
        wh = r["assigned_key"]
        r["shipping_cost"] = _min([r["ups"].get(wh), r["fedex"].get(wh)]) if wh else None
        by_number[r["order_number"]].append(r)

    for number, group in by_number.items():
        mkt = marketplace(number)
        fee = config.MARKETPLACE_FEES.get(mkt, 0)
        per_order = {}
        for r in group:
            per_order.setdefault(r["order_id"], r)
        amount = sum(r["amount_net"] for r in per_order.values())
        shipping = sum(r["shipping_cost"] or 0 for r in per_order.values())
        landed_known = all(r["landed_unit"] is not None for r in group)
        landed = sum((r["landed_unit"] or 0) * r["qty"] for r in group)
        referral = amount * fee
        profit = amount - landed - shipping - referral
        costs = landed + shipping + referral
        for r in group:
            r["marketplace"] = mkt
            r["order_amount"] = round(amount, 2)
            r["order_landed"] = round(landed, 2)
            r["order_shipping"] = round(shipping, 2)
            r["referral"] = round(referral, 2)
            r["landed_missing"] = not landed_known
            r["profit"] = round(profit, 2)
            r["profit_pct"] = (profit / costs) if costs else None


def _comparison(rows):
    """Rate Comparison tab port: best UPS vs best FedEx across all three warehouses."""
    for r in rows:
        best_ups = min(((v, k) for k, v in r["ups"].items() if v is not None), default=(None, ""))
        best_fed = min(((v, k) for k, v in r["fedex"].items() if v is not None), default=(None, ""))
        r["best_ups"], r["best_ups_wh"] = best_ups
        r["best_fedex"], r["best_fedex_wh"] = best_fed
        if best_ups[0] is None and best_fed[0] is None:
            r["cheapest_carrier"], r["cheapest_wh"], r["cheapest_rate"] = "", "", None
        elif best_fed[0] is None or (best_ups[0] is not None and best_ups[0] <= best_fed[0]):
            r["cheapest_carrier"], r["cheapest_wh"], r["cheapest_rate"] = "UPS", best_ups[1], best_ups[0]
        else:
            r["cheapest_carrier"], r["cheapest_wh"], r["cheapest_rate"] = "FedEx", best_fed[1], best_fed[0]
        if best_ups[0] is not None and best_fed[0] is not None:
            r["fedex_saves"] = round(best_ups[0] - best_fed[0], 2)
            r["fedex_saves_pct"] = round((best_ups[0] - best_fed[0]) / best_ups[0] * 100, 1) if best_ups[0] else None
        else:
            r["fedex_saves"] = r["fedex_saves_pct"] = None
        # cheapest visible rate cell on the Dashboard (Chicago/Texas, UPS/FedEx)
        cells = {("ups", "IL"): r["ups"]["IL"], ("ups", "TX"): r["ups"]["TX"],
                 ("fedex", "IL"): r["fedex"]["IL"], ("fedex", "TX"): r["fedex"]["TX"]}
        low = _min(cells.values())
        r["cheapest_cells"] = [f"{c}_{w}" for (c, w), v in cells.items() if v is not None and v == low]


def comparison_summary(rows):
    fedex_wins = sum(1 for r in rows if r["cheapest_carrier"] == "FedEx")
    saving = sum(r["fedex_saves"] for r in rows if r["fedex_saves"] and r["fedex_saves"] > 0)
    return {"compared": len(rows), "fedex_cheaper": fedex_wins,
            "ups_cheaper": len(rows) - fedex_wins, "total_saving": round(saving, 2)}


def archive_records(rows):
    return [{
        "order_id": r["order_id"], "order_number": r["order_number"], "sku": r["sku"],
        "state": r["state"], "postal": r["postal"], "assigned_wh": r["assigned"],
        "ups_il": r["ups"]["IL"], "ups_ca": r["ups"]["CA"], "ups_tx": r["ups"]["TX"],
        "fedex_il": r["fedex"]["IL"], "fedex_ca": r["fedex"]["CA"], "fedex_tx": r["fedex"]["TX"],
        "best_ups": r["best_ups"], "best_fedex": r["best_fedex"],
        "cheapest_carrier": r["cheapest_carrier"], "cheapest_wh": r["cheapest_wh"],
        "cheapest_rate": r["cheapest_rate"], "fedex_saves": r["fedex_saves"],
        "fedex_saves_pct": r["fedex_saves_pct"], "weight_oz": r["weight_oz"],
        "length": r["length"], "width": r["width"], "height": r["height"],
    } for r in rows if r["ups"]["IL"] is not None or r["fedex"]["IL"] is not None
            or r["ups"]["TX"] is not None or r["fedex"]["TX"] is not None]


def shipstation_check(rows):
    """'Multiple' = order numbers that appear on more than one row.
    'Zero Dimensions' = orders with a missing or zero length, width or height."""
    counts = defaultdict(int)
    for r in rows:
        counts[r["order_number"]] += 1
    multiple = [n for n in dict.fromkeys(r["order_number"] for r in rows) if counts[n] > 1]
    zero = list(dict.fromkeys(r["order_number"] for r in rows
                              if not r["length"] or not r["width"] or not r["height"]))
    details = [{"order_number": r["order_number"], "weight_oz": r["weight_oz"], "length": r["length"],
                "width": r["width"], "height": r["height"], "qty": r["qty"], "count": counts[r["order_number"]]}
               for r in rows]
    return {"multiple": multiple, "zero": zero, "rows": details}


def send_targets(rows):
    """Step 4: orders that get their warehouse + Custom Field 3 (aisle) written back to ShipStation.
    Same filter as the script: a real aisle location is required (not blank, not '.inform Manager').
    An order with several items keeps the last item's location, as the script did."""
    targets = {}
    for r in rows:
        if r["aisle"] and r["aisle"] != ".inform Manager":
            targets[r["order_id"]] = {"customField3": r["aisle"],
                                      "warehouseId": config.SEND_WAREHOUSE_IDS.get(r["assigned"])}
    return targets


def user_assignments(rows):
    """Step 5: {user_id: [order ids]} grouped by the assigned warehouse."""
    out = defaultdict(list)
    for r in rows:
        user = config.USER_IDS.get(r["assigned"])
        if user and r["order_id"] not in out[user]:
            out[user].append(r["order_id"])
    return dict(out)


def pick_list(rows, wh_key, selected_keys=None):
    """Groups the chosen rows by SKU + location, sorted by location (like the Pick List QUERY)."""
    chosen = [r for r in rows if r["assigned_key"] == wh_key
              and (selected_keys is None or f"{r['order_id']}|{r['sku']}" in selected_keys)]
    groups = {}
    for r in chosen:
        k = (r["sku"], r["aisle"])
        if k not in groups:
            groups[k] = {"sku": r["sku"], "location": r["aisle"], "qty": 0,
                         "stock": r["stock"][wh_key], "title": r["title"]}
        groups[k]["qty"] += r["qty"]
    items = sorted(groups.values(), key=lambda g: (g["location"] or "~", g["sku"]))
    return chosen, items
