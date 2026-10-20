"""ShipStation: awaiting-shipment orders (V1 API) and UPS rates (V2 API)."""
import base64
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import config
from services.util import parse_number

V1_URL = "https://ssapi.shipstation.com/"
V2_RATES_URL = "https://api.shipstation.com/v2/rates"


def _v1_headers():
    token = base64.b64encode(f"{config.SS_V1_KEY}:{config.SS_V1_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def clean_sku(sku):
    """Same rule as the Apps Script: drop a 'C-' / 'A-' prefix and anything after '_'."""
    sku = str(sku or "")
    if sku.startswith("C-") or sku.startswith("A-"):
        sku = sku[2:]
    return sku.split("_")[0]


def fetch_awaiting_orders():
    """Unassigned awaiting-shipment orders, newest first. Returns one dict per order item."""
    orders, pages = [], 1
    page = 1
    while page <= min(pages, config.SS_MAX_PAGES):
        url = (f"{V1_URL}orders?orderStatus=awaiting_shipment&pageSize=500"
               f"&sortBy=ModifyDate&sortDir=DESC&page={page}")
        for attempt in range(3):
            res = requests.get(url, headers=_v1_headers(), timeout=60)
            if res.status_code == 429:
                wait = int(res.headers.get("X-Rate-Limit-Reset", "60")) + 2
                time.sleep(wait)
                continue
            res.raise_for_status()
            data = res.json()
            orders.extend(data.get("orders") or [])
            pages = data.get("pages") or 1
            break
        page += 1
        time.sleep(0.3)

    rows = []
    for o in orders:
        if o.get("userId"):          # only orders that are not assigned to a user yet
            continue
        ship_to = o.get("shipTo") or {}
        adv = o.get("advancedOptions") or {}
        weight = o.get("weight") or {}
        dims = o.get("dimensions") or {}
        wh_id = str(adv.get("warehouseId") or "")
        residential = ship_to.get("residential")
        if residential is None:
            residential = not bool(str(ship_to.get("company") or "").strip())
        amount_net = (parse_number(o.get("amountPaid")) - parse_number(o.get("taxAmount"))
                      - parse_number(o.get("shippingAmount")))
        for item in o.get("items") or []:
            if not item.get("sku"):
                continue
            rows.append({
                "order_id": str(o.get("orderId")),
                "order_number": str(o.get("orderNumber") or ""),
                "qty": int(item.get("quantity") or 0),
                "sku": clean_sku(item.get("sku")),
                "item_name": item.get("name") or "",
                "weight_oz": _to_oz(weight),
                "length": parse_number(dims.get("length")),
                "width": parse_number(dims.get("width")),
                "height": parse_number(dims.get("height")),
                "address": "\n".join(x for x in [ship_to.get("street1"), ship_to.get("street2"),
                                                 ship_to.get("street3")] if x),
                "city": ship_to.get("city") or "",
                "state": ship_to.get("state") or "",
                "postal": ship_to.get("postalCode") or "",
                "warehouse_id": config.SS_WAREHOUSE_IDS.get(wh_id, wh_id),
                "residential": bool(residential),
                "custom_field1": adv.get("customField1") or "",
                "amount_net": round(amount_net, 2),
            })
    return rows


def _to_oz(weight):
    value = parse_number(weight.get("value"))
    units = str(weight.get("units") or "ounces").lower()
    if units.startswith("pound"):
        return value * 16
    if units.startswith("gram"):
        return value / 28.3495
    return value


# ---------------------------------------------------------------------------
# UPS rates through ShipStation V2 (same logic as getShipStationRatesOnDashboardV2)
# ---------------------------------------------------------------------------
def _rate_payload(carrier_id, wh, pkg):
    return {
        "rate_options": {"carrier_ids": [carrier_id]},
        "shipment": {
            "confirmation": "none",
            "ship_from": {"name": "Warehouse", "phone": "000-000-0000", "country_code": "US",
                          **wh["ss_from"]},
            "ship_to": {
                "name": "Customer", "phone": "000-000-0000",
                "address_line1": (pkg["address"] or "123 Main St").split("\n")[0][:35],
                "city_locality": pkg["city"], "state_province": pkg["state"],
                "postal_code": str(pkg["postal"]).strip(), "country_code": "US",
                "address_residential_indicator": "yes",
            },
            "packages": [{
                "weight": {"value": pkg["weight_oz"] or 1, "unit": "ounce"},
                "dimensions": {"unit": "inch", "length": pkg["length"] or 1,
                               "width": pkg["width"] or 1, "height": pkg["height"] or 1},
            }],
        },
    }


def _post_rate(payload):
    for attempt in range(4):
        res = requests.post(V2_RATES_URL, json=payload, timeout=60,
                            headers={"API-Key": config.SS_V2_KEY})
        if res.status_code == 429:
            time.sleep(int(res.headers.get("X-Rate-Limit-Reset", "10") or 10) + 1)
            continue
        if res.status_code != 200:
            return None
        return res.json()
    return None


def _cheapest_ground(data):
    if not data:
        return None
    rates = (data.get("rate_response") or {}).get("rates") or data.get("rates") or []
    best = None
    for r in rates:
        service = str(r.get("service_code") or "").lower()
        name = str(r.get("service_type") or r.get("service_name") or "").lower()
        if service == "ups_ground" or ("ground" in name and "saver" not in name):
            amount = (r.get("shipping_amount") or {}).get("amount")
            if amount is not None and (best is None or amount < best):
                best = float(amount)
    return best


def ups_rates_for_packages(packages):
    """packages: {key: pkg dict}. Returns {key: {"IL": rate|None, "CA": ..., "TX": ...}}."""
    jobs = []
    for key, pkg in packages.items():
        for wh_key, wh in config.WAREHOUSES.items():
            for carrier_id in wh["ss_carrier_ids"]:
                jobs.append((key, wh_key, _rate_payload(carrier_id, wh, pkg)))

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(lambda j: _cheapest_ground(_post_rate(j[2])), jobs))

    out = {key: {"IL": None, "CA": None, "TX": None} for key in packages}
    for (key, wh_key, _), rate in zip(jobs, answers):
        if rate is not None and (out[key][wh_key] is None or rate < out[key][wh_key]):
            out[key][wh_key] = rate
    return out


# ---------------------------------------------------------------------------
# 4) sendDataToShipstation: write warehouse + aisle location (Custom Field 3) back to the orders
# ---------------------------------------------------------------------------
def _get(url):
    for attempt in range(3):
        try:
            res = requests.get(url, headers=_v1_headers(), timeout=60)
        except requests.RequestException:
            time.sleep(2)
            continue
        if res.status_code == 429:
            time.sleep(int(res.headers.get("X-Rate-Limit-Reset", "2") or 2) + 1.5)
            continue
        return res
    return None


def send_to_shipstation(targets, max_pages=15):
    """targets: {order_id: {"customField3": str, "warehouseId": int}}.
    Fetches the full order objects (so nothing else on the order is lost), changes the two fields
    and saves them back with /orders/createorders, 100 at a time."""
    missing = set(targets)
    payload = []
    for page in range(1, max_pages + 1):
        if not missing:
            break
        res = _get(f"{V1_URL}orders?orderStatus=awaiting_shipment&pageSize=500"
                   f"&sortBy=ModifyDate&sortDir=DESC&page={page}")
        if res is None or res.status_code != 200:
            continue
        orders = res.json().get("orders") or []
        if not orders:
            break
        for o in orders:
            oid = str(o.get("orderId"))
            if oid in missing:
                payload.append(_with_targets(o, targets[oid]))
                missing.discard(oid)
        time.sleep(0.3)

    # a few stragglers are fetched one by one (same safety limit as the script)
    if 0 < len(missing) <= 5:
        for oid in list(missing):
            res = _get(f"{V1_URL}orders/{oid}")
            if res is not None and res.status_code == 200:
                payload.append(_with_targets(res.json(), targets[oid]))
                missing.discard(oid)
            time.sleep(0.3)

    errors, updated = [], 0
    for i in range(0, len(payload), 100):
        batch = payload[i:i + 100]
        res = requests.post(f"{V1_URL}orders/createorders", json=batch, headers=_v1_headers(), timeout=120)
        if res.status_code == 200:
            updated += len(batch)
        else:
            errors.append(f"Batch {i // 100 + 1}: {res.status_code} {res.text[:200]}")
    return {"updated": updated, "not_found": sorted(missing), "errors": errors}


def _with_targets(order, target):
    order.setdefault("advancedOptions", {})
    order["advancedOptions"] = order["advancedOptions"] or {}
    order["advancedOptions"]["customField3"] = target["customField3"]
    order["advancedOptions"]["warehouseId"] = target["warehouseId"]
    return order


# ---------------------------------------------------------------------------
# 5) assignOrdersToUser: give each warehouse's orders to that warehouse's user
# ---------------------------------------------------------------------------
def assign_orders_to_users(orders_by_user):
    """orders_by_user: {user_id: [order ids]}. Returns a list of result lines."""
    lines = []
    for user_id, order_ids in orders_by_user.items():
        for i in range(0, len(order_ids), 100):
            batch = [int(x) for x in order_ids[i:i + 100]]
            ok = False
            for attempt in range(3):
                try:
                    res = requests.post(f"{V1_URL}orders/assignuser", headers=_v1_headers(), timeout=60,
                                        json={"orderIds": batch, "userId": user_id})
                except requests.RequestException:
                    time.sleep(3)
                    continue
                if res.status_code == 429:
                    time.sleep(int(res.headers.get("X-Rate-Limit-Reset", "2") or 2) + 1.5)
                    continue
                if res.status_code == 404:      # orders still propagating in ShipStation
                    time.sleep(5)
                    continue
                ok = res.status_code == 200 and res.json().get("success", False)
                if not ok:
                    lines.append(f"Error for user {user_id}: {res.status_code} {res.text[:200]}")
                break
            if ok:
                lines.append(f"{len(batch)} orders assigned to user {user_id}")
    return lines
