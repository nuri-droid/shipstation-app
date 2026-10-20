import csv
import hmac
import io
from datetime import datetime, timedelta

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

import config
import db
import logic
from refresh import run_refresh

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=14)
db.init()

WH_OPTIONS = [(k, w["label"], w["name"]) for k, w in config.WAREHOUSES.items()]


@app.before_request
def require_login():
    if not config.APP_USERS or request.endpoint in ("login", "static", "health"):
        return None
    if not session.get("user"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        name = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        expected = config.APP_USERS.get(name)
        if expected is not None and hmac.compare_digest(expected, password):
            session["user"] = name
            session.permanent = True
            target = request.args.get("next", "/")
            return redirect(target if target.startswith("/") else "/")
        error = "Wrong user name or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return "ok"


def current_rows():
    created_at, snapshot = db.latest_snapshot()
    if not snapshot:
        return None, [], []
    return created_at, logic.compute(snapshot, db.manual_assignments()), snapshot.get("warnings", [])


@app.template_filter("money")
def money(v):
    return "" if v is None else f"${v:,.2f}"


@app.template_filter("pct")
def pct(v):
    return "" if v is None else f"{v * 100:.2f}%"


@app.template_filter("num")
def num(v):
    if v is None or v == "":
        return ""
    return f"{v:g}" if isinstance(v, float) else str(v)


@app.context_processor
def globals_():
    return {"mock": config.MOCK_MODE, "wh_options": WH_OPTIONS, "warehouses": config.WAREHOUSES}


@app.route("/")
def dashboard():
    created_at, rows, warnings = current_rows()
    wh = request.args.get("wh", "")
    status = request.args.get("status", "")
    shown = [r for r in rows
             if (not wh or r["assigned_key"] == wh or (wh == "none" and not r["assigned_key"]))
             and (not status or (status == "ok" and not r["status"]) or (status == "problem" and r["status"]))]
    counts = {}
    for r in rows:
        counts[r["assigned"]] = counts.get(r["assigned"], 0) + 1
    return render_template("dashboard.html", rows=shown, total=len(rows), created_at=created_at,
                           warnings=warnings, counts=counts, wh=wh, status=status)


@app.post("/refresh")
def refresh():
    try:
        result = run_refresh()
        flash(f"Refreshed: {result['orders']} order lines, {result['archived']} new rows archived.", "ok")
        for w in result["warnings"]:
            flash(w, "warn")
    except Exception as e:  # noqa: BLE001
        flash(f"Refresh failed: {e}", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/send")
def send():
    """Step 4: write warehouse + Custom Field 3 to ShipStation."""
    _, rows, _ = current_rows()
    targets = logic.send_targets(rows)
    if not targets:
        flash("No orders with an aisle location to send.", "warn")
    elif config.MOCK_MODE:
        flash(f"MOCK: {len(targets)} orders would be updated in ShipStation (nothing was sent).", "ok")
    else:
        from services import shipstation
        try:
            res = shipstation.send_to_shipstation(targets)
            flash(f"ShipStation updated: {res['updated']} of {len(targets)} orders.", "ok")
            if res["not_found"]:
                flash(f"Not found in awaiting shipments: {', '.join(res['not_found'])}", "warn")
            for e in res["errors"]:
                flash(e, "error")
        except Exception as e:  # noqa: BLE001
            flash(f"Sending to ShipStation failed: {e}", "error")
    return redirect(url_for("dashboard"))


@app.post("/assign-users")
def assign_users():
    """Step 5: assign each warehouse's orders to that warehouse's ShipStation user."""
    _, rows, _ = current_rows()
    groups = logic.user_assignments(rows)
    total = sum(len(v) for v in groups.values())
    if not total:
        flash("No orders to assign.", "warn")
    elif config.MOCK_MODE:
        flash(f"MOCK: {total} orders would be assigned to users (nothing was sent).", "ok")
    else:
        from services import shipstation
        try:
            for line in shipstation.assign_orders_to_users(groups):
                flash(line, "error" if line.startswith("Error") else "ok")
            flash("Assigned orders drop off the list on the next refresh.", "ok")
        except Exception as e:  # noqa: BLE001
            flash(f"Assigning users failed: {e}", "error")
    return redirect(url_for("dashboard"))


@app.post("/assign")
def assign():
    db.set_manual(request.form["order_id"], request.form["sku"], request.form.get("warehouse", ""))
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/picklist")
def picklist():
    created_at, rows, warnings = current_rows()
    wh = request.args.get("wh", "TX")
    selected = request.args.getlist("sel") if request.args.get("filtered") else None
    chosen, items = logic.pick_list(rows, wh, set(selected) if selected is not None else None)
    candidates = [r for r in rows if r["assigned_key"] == wh]
    return render_template("picklist.html", wh=wh, items=items, chosen=chosen, candidates=candidates,
                           selected=set(selected) if selected is not None else None,
                           printed=datetime.now().strftime("%m/%d/%Y %H:%M:%S"), created_at=created_at)


@app.route("/comparison")
def comparison():
    created_at, rows, warnings = current_rows()
    return render_template("comparison.html", rows=rows, summary=logic.comparison_summary(rows),
                           created_at=created_at)


@app.route("/archive")
def archive():
    search = request.args.get("q", "").strip()
    rows, total = db.archive_page(search)
    return render_template("archive.html", rows=rows, total=total, q=search, columns=db.ARCHIVE_COLUMNS)


@app.route("/archive.csv")
def archive_csv():
    return _csv(["archived_at"] + db.ARCHIVE_COLUMNS, db.archive_all(), "comparison_archive.csv")


@app.route("/check")
def check():
    created_at, rows, warnings = current_rows()
    return render_template("check.html", check=logic.shipstation_check(rows), created_at=created_at)


@app.route("/dashboard.csv")
def dashboard_csv():
    _, rows, _ = current_rows()
    cols = ["status", "manual", "auto", "order_id", "order_number", "qty", "sku", "weight_oz", "length",
            "width", "height", "address", "city", "state", "postal", "warehouse_id", "residential",
            "custom_field1", "amount_net", "aisle"]
    flat = []
    for r in rows:
        d = {c: r.get(c) for c in cols}
        for wh in logic.WH_KEYS:
            d[f"stock_{wh}"] = r["stock"][wh]
            d[f"ups_{wh}"] = r["ups"][wh]
            d[f"fedex_{wh}"] = r["fedex"][wh]
        d["profit"], d["profit_pct"] = r["profit"], r["profit_pct"]
        flat.append(d)
    header = cols + [f"{p}_{wh}" for p in ("stock", "ups", "fedex") for wh in logic.WH_KEYS] + ["profit", "profit_pct"]
    return _csv(header, flat, "dashboard.csv")


def _csv(header, rows, name):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
