import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["MOCK_MODE"] = "1"

import logic  # noqa: E402


def row(**kw):
    base = {"order_id": "1", "order_number": "111-1234567-1234567", "qty": 1, "sku": "A", "weight_oz": 10,
            "length": 10, "width": 10, "height": 10, "address": "", "city": "", "state": "TX", "postal": "75001",
            "warehouse_id": "1438098, Texas", "residential": True, "custom_field1": "", "amount_net": 100.0,
            "item_name": ""}
    base.update(kw)
    return base


def snap(orders, stock, ups, fedex, landed=None):
    keys = {logic.package_key(o): o for o in orders}
    return {"orders": orders,
            "reference": {"stock": stock, "aisles": {"IL": {"A": "A01"}, "CA": {}, "TX": {"A": "T01"}},
                          "landed_cost": landed or {"A": 20.0}, "titles": {"A": "Part A"}},
            "ups_rates": {k: ups for k in keys}, "fedex_rates": {k: fedex for k in keys}}


def test_cheapest_warehouse_with_stock_wins():
    s = snap([row()], {"A": {"IL": 5, "CA": 0, "TX": 5}},
             {"IL": 12.0, "CA": 20.0, "TX": 9.0}, {"IL": 15.0, "CA": 20.0, "TX": 14.0})
    r = logic.compute(s, {})[0]
    assert r["assigned"] == "___Texas___"
    assert r["aisle"] == "T01"


def test_fedex_can_win_when_cheapest_mode():
    s = snap([row()], {"A": {"IL": 5, "CA": 0, "TX": 5}},
             {"IL": 12.0, "CA": 20.0, "TX": 11.0}, {"IL": 8.0, "CA": 20.0, "TX": 14.0})
    r = logic.compute(s, {})[0]
    assert r["assigned"] == "-----Chicago-----"
    assert r["shipping_cost"] == 8.0
    assert r["cheapest_cells"] == ["fedex_IL"]


def test_no_stock_falls_back_to_california_then_out_of_stock():
    s = snap([row(qty=3)], {"A": {"IL": 1, "CA": 5, "TX": 2}}, {"IL": 1.0, "CA": 1.0, "TX": 1.0}, {})
    assert logic.compute(s, {})[0]["assigned"] == "California"
    s = snap([row(qty=9)], {"A": {"IL": 1, "CA": 5, "TX": 2}}, {"IL": 1.0, "CA": 1.0, "TX": 1.0}, {})
    r = logic.compute(s, {})[0]
    assert r["assigned"] == "OUT OF STOCK" and r["status"] == "Not Enough Inventory"


def test_manual_override_and_wh_match():
    s = snap([row(warehouse_id="1438098, Texas")], {"A": {"IL": 5, "CA": 0, "TX": 5}},
             {"IL": 9.0, "CA": 9.0, "TX": 9.5}, {})
    r = logic.compute(s, {("1", "A"): "-----Chicago-----"})[0]
    assert r["assigned"] == "-----Chicago-----" and r["status"] == "WH does not match"


def test_profit_amazon():
    s = snap([row(qty=2)], {"A": {"IL": 0, "CA": 0, "TX": 5}}, {"IL": None, "CA": None, "TX": 10.0}, {})
    r = logic.compute(s, {})[0]
    # 100 - 40 landed - 10 shipping - 12 referral = 38 ; costs 62
    assert r["profit"] == 38.0
    assert round(r["profit_pct"], 4) == round(38 / 62, 4)


def test_shipstation_check_counts_correctly():
    rows = [row(order_number="X"), row(order_id="2", order_number="X"), row(order_id="3", order_number="Y", length=0)]
    s = snap(rows, {"A": {"IL": 9, "CA": 0, "TX": 9}}, {"IL": 1.0, "CA": 1.0, "TX": 1.0}, {})
    c = logic.shipstation_check(logic.compute(s, {}))
    assert c["multiple"] == ["X"] and c["zero"] == ["Y"]


def test_pick_list_groups_by_sku_and_location():
    rows = [row(), row(order_id="2", qty=3)]
    s = snap(rows, {"A": {"IL": 0, "CA": 0, "TX": 9}}, {"IL": None, "CA": None, "TX": 5.0}, {})
    _, items = logic.pick_list(logic.compute(s, {}), "TX")
    assert items == [{"sku": "A", "location": "T01", "qty": 4, "stock": 9, "title": "Part A"}]


def test_send_targets_and_user_assignments():
    rows = [row(), row(order_id="2", sku="B")]
    s = snap(rows, {"A": {"IL": 0, "CA": 0, "TX": 9}, "B": {"IL": 0, "CA": 0, "TX": 9}},
             {"IL": None, "CA": None, "TX": 5.0}, {})
    computed = logic.compute(s, {})
    # B has no aisle location -> '.inform Manager' -> not sent, like the script
    assert logic.send_targets(computed) == {"1": {"customField3": "T01", "warehouseId": 1438098}}
    users = logic.user_assignments(computed)
    assert list(users.values()) == [["1", "2"]]


def test_send_to_shipstation_keeps_full_order(monkeypatch):
    from services import shipstation

    class R:
        def __init__(self, code, data=None):
            self.status_code, self._d, self.headers, self.text = code, data, {}, ""

        def json(self):
            return self._d

    sent = []
    monkeypatch.setattr(shipstation.requests, "get",
                        lambda url, **k: R(200, {"orders": [{"orderId": 1, "orderNumber": "X",
                                                             "advancedOptions": {"customField1": "keep"}}]}
                                           if "page=1" in url else {"orders": []}))
    monkeypatch.setattr(shipstation.requests, "post", lambda url, json=None, **k: sent.append((url, json)) or R(200, {}))
    monkeypatch.setattr(shipstation.time, "sleep", lambda s: None)
    res = shipstation.send_to_shipstation({"1": {"customField3": "T01", "warehouseId": 1438098}})
    assert res["updated"] == 1 and not res["not_found"]
    url, body = sent[0]
    assert url.endswith("orders/createorders")
    assert body[0]["advancedOptions"] == {"customField1": "keep", "customField3": "T01", "warehouseId": 1438098}
