# ShipStation Inventory web app (Python / Flask)

The Google Sheet's Dashboard, Pick List, UPS vs FedEx comparison + archive and ShipStation Check tabs,
as one web app. One **Refresh** button replaces the old run order
(1 awaitingShipmentsNoAssign → 5 shipstationRates → FedEx Run all → archive).

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
python app.py                   # open http://127.0.0.1:5000
```

`.env` starts with `MOCK_MODE=1`: sample orders and rates, no API calls. Use this to try the screens.
For real data set `MOCK_MODE=0` and fill in the keys.

## Where the data comes from

| Data | Source |
|---|---|
| Awaiting-shipment orders (unassigned) | ShipStation V1 API |
| UPS rates (Ground, no Ground Saver) | ShipStation V2 rates API, both carrier accounts per warehouse |
| FedEx rates (Ground / Home Delivery) | FedEx Rate API |
| Stock per warehouse | "Finale On Hand Quantities" sheet |
| Aisle locations | IL / TX / CA aisle sheets (Sheet3) |
| Landed cost | Price_Calculator tab |
| Product description | SellwareData sheet (Title) |

The Google Sheets are read with a **service account**: create one in Google Cloud, download its JSON key
as `service_account.json` next to `app.py`, and share each sheet in `.env` with the service account's
e-mail as Viewer. If a sheet can't be read the app still works and shows a warning.

Rates are cached per package (`RATE_CACHE_HOURS`), so a refresh only asks ShipStation/FedEx for new orders.

## Rules (same as the sheet, with these differences)

* **Automatic warehouse assign:** Chicago vs Texas, cheapest warehouse that has enough stock; tie → more
  stock; California only when Chicago and Texas can't cover it; otherwise OUT OF STOCK.
  `ASSIGN_USING=cheapest` compares UPS **and** FedEx; set `ups` for the sheet's UPS-only behaviour.
  A missing rate ("NO UPS SERVICE") now means "not available"; the sheet formula treated it as $0.
* **Status:** WH does not match / Not Enough Inventory / Over 50 lbs. (> 790 oz), as in the sheet.
* **Profit:** amount (paid − tax − shipping) − landed cost × qty − shipping (cheaper of UPS/FedEx at the
  assigned warehouse) − marketplace fee (Amazon 12 %, eBay 13 %, Shopify 3 %, TikTok 6 %).
  An order number split into several ShipStation orders adds up each order's amount once.
* **ShipStation Check:** the sheet's "(N Orders)" count was one short (it counted the `;` separators);
  the app counts the orders.
* **Manual Warehouse Assign** is saved in the app's database (`data.db`).

## Daily order (buttons at the top)

| Button | Replaces |
|---|---|
| **1–3 Refresh orders & rates** | NoAssignExportAwaitingShipments → getShipStationRatesOnDashboardV2 → FedEx Run all (incl. archive) |
| **4 Send to ShipStation** | sendDataToShipstation: writes the assigned warehouse and the aisle location (Custom Field 3) to each order. Orders without a real location (blank / `.inform Manager`) are skipped, as before. The full order is re-read first so no other field is lost. |
| **5 Assign to users** | assignOrdersToUser: Chicago → Furkan, California → Altyn, Texas → Talha (user ids in `config.py`, can be overridden in `.env`). Assigned orders drop off the list on the next refresh. |

Check the Dashboard (and fix with Manual Warehouse Assign) between 1–3 and 4. In `MOCK_MODE` buttons 4 and 5
only report what they would send.

## Tests

```bash
pytest -q
```

## Free server (Render + Neon)

1. **Database (Neon, free):** create a project at neon.tech and copy the connection string
   (`postgresql://...`). Render's free disk is wiped on every restart, so the archive and settings live here.
2. **GitHub:** create a private repository and upload the contents of this folder
   (not `.env`, not `service_account.json`).
3. **Render:** New → Blueprint → pick the repository. `render.yaml` sets everything up; fill in:
   * `DATABASE_URL` – the Neon connection string
   * `APP_USERS` – who can sign in, e.g. `nuri:StrongPass1,furkan:StrongPass2`
   * ShipStation and FedEx keys
   * `GOOGLE_SERVICE_ACCOUNT_JSON` – paste the whole content of the service account JSON file
4. Deploy. The address is `https://shipstation-inventory.onrender.com` (or similar).

Free plan limits: the app sleeps after 15 minutes without visits, and the first visit after that takes
about a minute to wake up. Data in Neon is kept.
