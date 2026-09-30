"""Views: answers computed from the log, each by folding it independently.

A view never stores anything. Ask the same log the same question twice and you
get the same answer; ask a new question and you do not have to change how the
system records what happened. Money in particular is only ever derived — a sale
records unit price, quantity, and discount rate, and every total downstream is
arithmetic over those.

Each view takes the raw log (an iterable of events) so it can be recomputed from
scratch at any time.
"""

import config
import core
import events as ev


# ── Arithmetic over a single sale ───────────────────────────────────────────

def net_amount(unit_price, quantity, discount):
    return unit_price * quantity * (1.0 - discount)


def tax_amount(unit_price, quantity, discount):
    return net_amount(unit_price, quantity, discount) * config.TAX_RATE


def grand_total(unit_price, quantity, discount):
    return net_amount(unit_price, quantity, discount) + tax_amount(
        unit_price, quantity, discount)


# ── Indexes over the log ────────────────────────────────────────────────────

def returned_seqs(log):
    """Sequence numbers of sales that were subsequently returned."""
    return {e["transaction_seq"] for e in log if e["type"] == ev.SALE_RETURNED}


def sales_view(log):
    """Every sale, with its derived money and whether it came back."""
    returned = returned_seqs(log)
    out = []
    for e in log:
        if e["type"] != ev.SALE_COMPLETED:
            continue
        net = net_amount(e["unit_price"], e["quantity"], e["discount"])
        tax = net * config.TAX_RATE
        out.append({
            "seq": e["seq"],
            "at": e["at"],
            "isbn": e["isbn"],
            "employee_id": e["employee_id"],
            "quantity": e["quantity"],
            "unit_price": e["unit_price"],
            "discount": e["discount"],
            "net": net,
            "tax": tax,
            "total": net + tax,
            "returned": e["seq"] in returned,
        })
    return out


def revenue_view(log):
    """Gross takings from sales kept, value of returns, and the difference."""
    kept = [s for s in sales_view(log) if not s["returned"]]
    back = [s for s in sales_view(log) if s["returned"]]
    gross = sum(s["total"] for s in kept)
    refunds = sum(s["total"] for s in back)
    return {
        "gross": gross,
        "returns": refunds,
        "net": gross - refunds,
        "sales_kept": len(kept),
        "sales_returned": len(back),
    }


def commission_view(log):
    """Commission owed per employee: rate applied to what they actually sold."""
    totals = {}
    for s in sales_view(log):
        if s["returned"]:
            continue
        totals[s["employee_id"]] = totals.get(s["employee_id"], 0.0) + \
            net_amount(s["unit_price"], s["quantity"], s["discount"])
    return {emp: amount * config.COMMISSION_RATE for emp, amount in totals.items()}


def reservations_view(log):
    """Open reservations per (isbn, employee)."""
    out = {}
    for e in log:
        if e["type"] == ev.BOOK_RESERVED:
            key = (e["isbn"], e["employee_id"])
            out[key] = out.get(key, 0) + e["quantity"]
        elif e["type"] == ev.RESERVATION_RELEASED:
            key = (e["isbn"], e["employee_id"])
            out[key] = max(0, out.get(key, 0) - e["quantity"])
    return {key: qty for key, qty in out.items() if qty > 0}


def reservations_for(log, employee_id):
    return [{"isbn": isbn, "quantity": qty}
            for (isbn, emp), qty in reservations_view(log).items()
            if emp == employee_id]


def orders_view(log):
    """Purchase orders with their supplier and delivery status."""
    state = core.fold(log)
    return [dict(order, seq=seq) for seq, order in
            sorted(state["orders"].items(), key=lambda kv: kv[0])]


def stock_view(log):
    """Current stock per title, enriched with which suppliers carry it."""
    state = core.fold(log)
    carries_by_isbn = {}
    for sid, supplier in state["suppliers"].items():
        for isbn, price in supplier["carries"].items():
            carries_by_isbn.setdefault(isbn, []).append({
                "supplier_id": sid,
                "supplier_name": supplier["name"],
                "quoted_price": price,
            })

    items = []
    for isbn, book in state["books"].items():
        available = book["on_hand"] - book["reserved"]
        items.append({
            "isbn": isbn,
            "title": book["title"],
            "author": book["author"],
            "price": book["price"],
            "on_hand": book["on_hand"],
            "reserved": book["reserved"],
            "available": available,
            "value": book["price"] * book["on_hand"],
            "suppliers": carries_by_isbn.get(isbn, []),
        })
    return items


def employee_view(log):
    """Current staff with hours worked and commission earned."""
    state = core.fold(log)
    commissions = commission_view(log)
    items = []
    for emp_id, employee in state["employees"].items():
        commission = commissions.get(emp_id, 0.0)
        wages = employee["hours_worked"] * employee["hourly_rate"]
        items.append({
            "id": emp_id,
            "name": employee["name"],
            "rank": employee["rank"],
            "shifts": employee["shifts"],
            "hours_worked": employee["hours_worked"],
            "wages": wages,
            "commission": commission,
            "pay_total": wages + commission,
            "reservations": reservations_for(log, emp_id),
        })
    return items


# ── Reports assembled from the views above ──────────────────────────────────

def daily_report(log):
    state = core.fold(log)
    revenue = revenue_view(log)
    stock = stock_view(log)
    low = [i for i in stock if i["available"] <= config.LOW_STOCK_THRESHOLD]
    pending_orders = [o for o in orders_view(log) if o["status"] == "pending"]

    return {
        "report_type": "daily",
        "revenue": revenue,
        "inventory": {
            "titles": len(stock),
            "units": sum(i["on_hand"] for i in stock),
            "total_value": sum(i["value"] for i in stock),
            "low_stock_count": len(low),
            "low_stock_isbns": [i["isbn"] for i in low],
        },
        "employees": employee_view(log),
        "suppliers": {
            "registered": len(state["suppliers"]),
            "pending_orders": len(pending_orders),
        },
    }


def inventory_report(log):
    stock = stock_view(log)
    low = [i for i in stock if i["available"] <= config.LOW_STOCK_THRESHOLD]
    return {
        "report_type": "inventory",
        "items": stock,
        "total_value": sum(i["value"] for i in stock),
        "low_stock": low,
    }


def employee_report(log):
    items = employee_view(log)
    return {
        "report_type": "employees",
        "items": items,
        "total_payroll": sum(i["pay_total"] for i in items),
    }
