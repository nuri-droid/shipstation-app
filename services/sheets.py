"""Reference data that today lives in Google Sheets: stock (Finale export), aisle locations,
landed cost and product titles. Read with a Google service account."""
import config
from services.util import parse_number


def _client():
    """Service account from GOOGLE_SERVICE_ACCOUNT_JSON (the file's content, handy on a server)
    or from the file at GOOGLE_SERVICE_ACCOUNT_FILE."""
    import json
    import os

    import gspread
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return gspread.service_account_from_dict(json.loads(raw))
    return gspread.service_account(filename=config.GOOGLE_SERVICE_ACCOUNT_FILE)


def _values(client, sheet_id, tab):
    return client.open_by_key(sheet_id).worksheet(tab).get_all_values()


def load_reference_data():
    """Returns dict with stock, aisles, landed_cost and titles, plus a list of warnings."""
    client = _client()
    warnings = []
    ref = {"stock": {}, "aisles": {"IL": {}, "CA": {}, "TX": {}}, "landed_cost": {}, "titles": {}}

    # Stock. Finale columns: Product ID | CaliforniaWarehouse | ChicagoWarehouse | ... | TexasWarehouse
    try:
        rows = _values(client, config.FINALE_SHEET_ID, config.FINALE_TAB)
        header = [h.lower() for h in rows[0]]

        def col(word):
            return next(i for i, h in enumerate(header) if word in h)
        c_ca, c_il, c_tx = col("california"), col("chicago"), col("texas")
        for r in rows[1:]:
            if r and r[0]:
                ref["stock"][r[0].strip()] = {
                    "IL": parse_number(r[c_il] if c_il < len(r) else 0),
                    "CA": parse_number(r[c_ca] if c_ca < len(r) else 0),
                    "TX": parse_number(r[c_tx] if c_tx < len(r) else 0),
                }
    except Exception as e:  # noqa: BLE001 - shown on the page, app keeps working
        warnings.append(f"Stock (Finale sheet) could not be read: {e}")

    # Aisle locations. Sheet3: B = Part Number, C:E = main locations
    for wh, sheet_id in config.AISLE_SHEETS.items():
        if not sheet_id:
            continue
        try:
            for r in _values(client, sheet_id, config.AISLE_TAB)[1:]:
                if len(r) > 1 and r[1].strip():
                    locs = [x.strip() for x in r[2:5] if x.strip()]
                    if locs:
                        ref["aisles"][wh][r[1].strip()] = "\n".join(locs)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{wh} aisle locations could not be read: {e}")

    # Landed cost. Price_Calculator: A = Master_SKU, E = Landed Cost
    try:
        for r in _values(client, config.COST_SHEET_ID, config.COST_TAB)[1:]:
            if r and r[0].strip() and len(r) > 4 and r[4].strip():
                ref["landed_cost"][r[0].strip()] = parse_number(r[4])
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Landed cost (Price_Calculator) could not be read: {e}")

    # Titles. SellwareData: A = Master_SKU, F = Title
    try:
        for r in _values(client, config.SELLWARE_SHEET_ID, config.SELLWARE_TAB)[1:]:
            if r and r[0].strip() and len(r) > 5:
                ref["titles"][r[0].strip()] = r[5]
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Product titles (SellwareData) could not be read: {e}")

    return ref, warnings
