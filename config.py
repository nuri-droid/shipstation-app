"""Settings. Everything secret comes from environment variables (.env file)."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def env(name, default=""):
    return os.environ.get(name, default).strip()


# --- Run mode ---------------------------------------------------------------
# MOCK_MODE=1 -> no API calls, sample orders/rates are generated (for trying the app)
MOCK_MODE = env("MOCK_MODE", "0") == "1"
DB_PATH = env("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))
# PostgreSQL connection string (Neon etc.). When set, it is used instead of the SQLite file.
DATABASE_URL = env("DATABASE_URL")
SECRET_KEY = env("SECRET_KEY", "change-me")

# Login. Format: "name:password,name2:password2". Empty = no login (only for running on your own PC).
APP_USERS = dict(p.split(":", 1) for p in env("APP_USERS").split(",") if ":" in p)

# --- ShipStation ------------------------------------------------------------
SS_V1_KEY = env("SS_V1_KEY")          # orders (V1)
SS_V1_SECRET = env("SS_V1_SECRET")
SS_V2_KEY = env("SS_V2_KEY")          # rates (V2)
SS_MAX_PAGES = int(env("SS_MAX_PAGES", "10"))

# --- FedEx ------------------------------------------------------------------
FEDEX_CLIENT_ID = env("FEDEX_CLIENT_ID")
FEDEX_CLIENT_SECRET = env("FEDEX_CLIENT_SECRET")
FEDEX_ACCOUNT = env("FEDEX_ACCOUNT")

# --- Google Sheets (stock, aisle locations, landed cost, product titles) ----
GOOGLE_SERVICE_ACCOUNT_FILE = env("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
FINALE_SHEET_ID = env("FINALE_SHEET_ID", "1zEIt6C3DD-7frRK4NtxfxQJuS-p1jveifhEjUljFNVM")
FINALE_TAB = env("FINALE_TAB", "Finale On Hand Quantities")
AISLE_SHEETS = {
    "IL": env("AISLE_IL_SHEET_ID", "1PUPq-IHGhMJ91JOcmUjQ19N3xji2lh57dkpbW4uNB1M"),
    "CA": env("AISLE_CA_SHEET_ID", "1MjJW0RbHGmIU5umamJTlH4Cs5Ql9TPWNvnCd8z_lzQk"),
    "TX": env("AISLE_TX_SHEET_ID", "1Ji5Q_NMctR5HP4_Wkv7Xu0PmS1n8O5QW4QDjpCC8Q1c"),
}
AISLE_TAB = env("AISLE_TAB", "Sheet3")
COST_SHEET_ID = env("COST_SHEET_ID", "13HPSNm_L462L8nB_gZpY0we4RyFVW0IdSYzuqhgTXEw")
COST_TAB = env("COST_TAB", "Price_Calculator")
SELLWARE_SHEET_ID = env("SELLWARE_SHEET_ID", "1-718OPciXx0kZ2UO4gZ286-kvdFNnN2h4n_8FWCJ3fo")
SELLWARE_TAB = env("SELLWARE_TAB", "SellwareData")

# --- Business rules ---------------------------------------------------------
# Which carriers the automatic warehouse assignment compares: "cheapest" (UPS + FedEx) or "ups"
ASSIGN_USING = env("ASSIGN_USING", "cheapest")
OVERWEIGHT_OZ = float(env("OVERWEIGHT_OZ", "790"))       # "Over 50 lbs." threshold used by the sheet
RATE_CACHE_HOURS = float(env("RATE_CACHE_HOURS", "12"))
MARKETPLACE_FEES = {"Amazon": 0.12, "eBay": 0.13, "Shopify": 0.03, "TikTok": 0.06, "Other": 0.0}

# Warehouses. Ship-from addresses and ShipStation V2 carrier ids are copied from the Apps Scripts.
WAREHOUSES = {
    "IL": {
        "name": "Chicago", "label": "-----Chicago-----",
        "ss_carrier_ids": ["se-759576", "se-724459"],
        "ss_from": {"address_line1": "350 Roma Jean Pkwy", "city_locality": "Streamwood",
                    "state_province": "IL", "postal_code": "60107"},
        "fedex_from": {"streetLines": ["380 Roma Jean Pkwy"], "city": "Streamwood",
                       "stateOrProvinceCode": "IL", "postalCode": "60107", "countryCode": "US"},
    },
    "CA": {
        "name": "California", "label": "California",
        "ss_carrier_ids": ["se-760556", "se-724459"],
        "ss_from": {"address_line1": "4422 E Airport Dr, Unit A", "city_locality": "Ontario",
                    "state_province": "CA", "postal_code": "91761"},
        "fedex_from": {"streetLines": ["4422 East Airport Dr"], "city": "Ontario",
                       "stateOrProvinceCode": "CA", "postalCode": "91761", "countryCode": "US"},
    },
    "TX": {
        "name": "Texas", "label": "___Texas___",
        "ss_carrier_ids": ["se-811825", "se-724459"],
        "ss_from": {"address_line1": "3900 N Dallas Ave, #200", "city_locality": "Lancaster",
                    "state_province": "TX", "postal_code": "75134"},
        "fedex_from": {"streetLines": ["3900 N DALLAS AVE"], "city": "LANCASTER",
                       "stateOrProvinceCode": "TX", "postalCode": "75134", "countryCode": "US"},
    },
}

# Step 4 (sendDataToShipstation): assigned warehouse -> ShipStation warehouseId to write back
SEND_WAREHOUSE_IDS = {"-----Chicago-----": 735994, "California": 1214269, "___Texas___": 1438098}

# Step 5 (assignOrdersToUser): assigned warehouse -> ShipStation user who gets the orders
USER_IDS = {
    "-----Chicago-----": env("USER_CHICAGO", "6713868a-a127-46af-a727-be3e697edc00"),   # Furkan
    "California": env("USER_CALIFORNIA", "0a831ee4-d72f-4a86-84e2-2b77420d136f"),     # Altyn
    "___Texas___": env("USER_TEXAS", "10e827dc-6c47-4c92-b8e6-0d4357741a74"),         # Talha
}

# ShipStation warehouseId -> label (from NoAssignExportAwaitingShipments)
SS_WAREHOUSE_IDS = {
    "735994": "735994, Chicago", "1355858": "1355858, Chicago",
    "1214269": "1214269, California", "1372367": "1372367, California",
    "1438098": "1438098, Texas", "1438099": "1438099, Texas",
}
