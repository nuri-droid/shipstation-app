"""FedEx Ground / Home Delivery rates (same logic as the FedEx Apps Script)."""
from concurrent.futures import ThreadPoolExecutor

import requests

import config
from services.util import format_zip

AUTH_URL = "https://apis.fedex.com/oauth/token"
RATE_URL = "https://apis.fedex.com/rate/v1/rates/quotes"


def _token():
    res = requests.post(AUTH_URL, timeout=30, data={
        "grant_type": "client_credentials",
        "client_id": config.FEDEX_CLIENT_ID,
        "client_secret": config.FEDEX_CLIENT_SECRET,
    })
    data = res.json()
    if "access_token" not in data:
        raise RuntimeError(f"FedEx auth failed: {res.text[:300]}")
    return data["access_token"]


def _request(wh, pkg, zip_code):
    return {
        "accountNumber": {"value": config.FEDEX_ACCOUNT},
        "requestedShipment": {
            "shipper": {"address": wh["fedex_from"]},
            "recipient": {"address": {
                "streetLines": [(pkg["address"] or "123 Main St").split("\n")[0][:35]],
                "city": pkg["city"], "stateOrProvinceCode": pkg["state"],
                "postalCode": zip_code, "countryCode": "US",
                "residential": bool(pkg.get("residential", True)),
            }},
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "packagingType": "YOUR_PACKAGING",
            "rateRequestType": ["ACCOUNT", "LIST"],
            "preferredCurrency": "USD",
            "totalDeclaredValue": {"amount": 1, "currency": "USD"},
            "requestedPackageLineItems": [{
                "weight": {"units": "LB", "value": max(0.1, round((pkg["weight_oz"] or 0) / 16, 2))},
                "dimensions": {"length": max(1, round(pkg["length"] or 0)),
                               "width": max(1, round(pkg["width"] or 0)),
                               "height": max(1, round(pkg["height"] or 0)), "units": "IN"},
            }],
        },
    }


def _parse(res):
    if res is None or res.status_code >= 300:
        return None
    try:
        details = (res.json().get("output") or {}).get("rateReplyDetails") or []
    except ValueError:
        return None
    best = None
    for d in details:
        service = str(d.get("serviceType") or "")
        if "GROUND" not in service and "HOME_DELIVERY" not in service:
            continue
        shipments = d.get("ratedShipmentDetails") or []
        sd = next((x for x in shipments if x.get("rateType") in ("PAYOR_ACCOUNT_PACKAGE", "ACCOUNT")),
                  shipments[0] if shipments else None)
        if sd and sd.get("totalNetCharge") is not None:
            amount = float(sd["totalNetCharge"])
            best = amount if best is None else min(best, amount)
    return best


def fedex_rates_for_packages(packages):
    """packages: {key: pkg dict}. Returns {key: {"IL": rate|None, "CA": ..., "TX": ...}}."""
    out = {key: {"IL": None, "CA": None, "TX": None} for key in packages}
    if not packages:
        return out
    token = _token()
    jobs = []
    for key, pkg in packages.items():
        zip_code = format_zip(pkg["postal"])
        if len(zip_code) < 5:
            continue
        for wh_key, wh in config.WAREHOUSES.items():
            jobs.append((key, wh_key, _request(wh, pkg, zip_code)))

    def call(job):
        try:
            return requests.post(RATE_URL, json=job[2], timeout=60,
                                 headers={"Authorization": f"Bearer {token}"})
        except requests.RequestException:
            return None

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(call, jobs))
    for (key, wh_key, _), res in zip(jobs, responses):
        out[key][wh_key] = _parse(res)
    return out
