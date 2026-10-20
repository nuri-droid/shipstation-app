"""One refresh = the old 1) export + 5) UPS rates + FedEx 'Run all' + archive, in one step."""
import config
import db
import logic


def run_refresh():
    warnings = []
    if config.MOCK_MODE:
        from services import mock
        orders = mock.mock_orders()
        reference, ref_warn = mock.mock_reference()
    else:
        from services import shipstation, sheets
        orders = shipstation.fetch_awaiting_orders()
        try:
            reference, ref_warn = sheets.load_reference_data()
        except Exception as e:  # noqa: BLE001
            reference = {"stock": {}, "aisles": {"IL": {}, "CA": {}, "TX": {}}, "landed_cost": {}, "titles": {}}
            ref_warn = [f"Google Sheets could not be opened: {e}"]
    warnings += ref_warn

    packages = {}
    for o in orders:
        packages.setdefault(logic.package_key(o), o)

    ups_rates = _rates("ups", packages, warnings)
    fedex_rates = _rates("fedex", packages, warnings)

    snapshot = {"orders": orders, "reference": reference, "ups_rates": ups_rates,
                "fedex_rates": fedex_rates, "warnings": warnings}
    db.save_snapshot(snapshot)

    rows = logic.compute(snapshot, db.manual_assignments())
    added = db.archive_rows(logic.archive_records(rows))
    return {"orders": len(orders), "packages": len(packages), "archived": added, "warnings": warnings}


def _rates(carrier, packages, warnings):
    cached = db.cached_rates(carrier, packages.keys())
    missing = {k: v for k, v in packages.items() if k not in cached}
    fresh = {}
    if missing:
        try:
            if config.MOCK_MODE:
                from services import mock
                fresh = mock.mock_rates(missing, carrier)
            elif carrier == "ups":
                from services import shipstation
                fresh = shipstation.ups_rates_for_packages(missing)
            else:
                from services import fedex
                fresh = fedex.fedex_rates_for_packages(missing)
            # only cache answers that returned at least one rate, so failures are retried next time
            db.store_rates(carrier, {k: v for k, v in fresh.items() if any(x is not None for x in v.values())})
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{carrier.upper()} rates failed: {e}")
    return {**cached, **fresh}
