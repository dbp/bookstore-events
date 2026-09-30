"""Entry point: build a log, send commands at it, ask views about it."""

from __future__ import annotations

import sys

import config
import events as ev
from store import Bookstore


SEED_SUPPLIERS = [
    ("SUP001", "Academic Books Inc.", "orders@academicbooks.com"),
    ("SUP002", "Campus Textbook Depot", "supply@campustextbooks.edu"),
    ("SUP003", "Rare & Used Books LLC", "info@rareusedbooks.com"),
]

SEED_CATALOG = [
    ("978-0-13-468599-1", "The C Programming Language", "Kernighan & Ritchie", 45.99, 12, "SUP001"),
    ("978-0-201-63361-0", "Design Patterns", "GoF", 54.99, 8, "SUP001"),
    ("978-0-596-00712-6", "Head First Design Patterns", "Freeman & Robson", 39.99, 15, "SUP002"),
    ("978-0-13-235088-4", "Clean Code", "Robert C. Martin", 42.99, 6, "SUP002"),
    ("978-0-321-12521-7", "Domain-Driven Design", "Eric Evans", 49.99, 3, "SUP003"),
    ("978-0-13-468599-2", "The C++ Programming Language", "Stroustrup", 52.99, 10, "SUP001"),
    ("978-0-13-212812-6", "The Pragmatic Programmer", "Hunt & Thomas", 47.99, 9, "SUP002"),
    ("978-0-596-51774-8", "JavaScript: The Good Parts", "Douglas Crockford", 29.99, 20, "SUP003"),
]

SEED_STAFF = [
    ("EMP001", "Alice Johnson", "manager", 22.0),
    ("EMP002", "Bob Smith", "shift_lead", 16.0),
    ("EMP003", "Carol Davis", "senior_cashier", 14.0),
    ("EMP004", "Dave Wilson", "cashier", 12.0),
]


def open_store():
    """A bookstore whose log contains nothing but the opening day's setup."""
    shop = Bookstore()
    for sid, name, email in SEED_SUPPLIERS:
        shop.send(ev.add_supplier(sid, name, email))
    for isbn, title, author, price, qty, sid in SEED_CATALOG:
        shop.send(ev.add_book(isbn, title, author, price, qty, sid))
    for sid, name, _email in SEED_SUPPLIERS:
        for isbn, _t, _a, price, _q, supplier in SEED_CATALOG:
            if supplier == sid:
                shop.send(ev.supplier_carries(sid, isbn, price))
    for emp_id, name, rank, rate in SEED_STAFF:
        shop.send(ev.hire(emp_id, name, rank, rate))
    return shop


def run_sample_day(shop):
    """One day of trading, then the reports people ask for at closing."""
    print("=" * 60)
    print("  CAMPUS BOOKSTORE — EVENT-SOURCED")
    print("  Sample Day Simulation")
    print("=" * 60)

    print("\n[8:00 AM] Opening the bookstore...")
    for emp_id, shift, start, end in [
        ("EMP001", "morning", "08:00", "16:00"),
        ("EMP002", "morning", "08:00", "16:00"),
        ("EMP003", "morning", "09:00", "17:00"),
        ("EMP004", "afternoon", "12:00", "20:00"),
    ]:
        shop.send(ev.assign_shift(emp_id, shift, start, end))

    print("\n[9:00 AM] Processing morning sales...")
    for i, (emp_id, isbn, qty) in enumerate(
        [("EMP003", "978-0-13-468599-1", 2),
         ("EMP003", "978-0-201-63361-0", 1),
         ("EMP004", "978-0-596-00712-6", 3)], start=1
    ):
        result = shop.send(ev.sell(emp_id, isbn, qty))
        label = "SUCCESS" if result["ok"] else "REJECTED"
        print(f"  Sale #{i}: {label} - {totals_of(result):.2f}")

    print("\n[1:00 PM] Processing afternoon sales...")
    tx_ids = []
    for i, (emp_id, isbn, qty) in enumerate(
        [("EMP004", "978-0-13-235088-4", 1),
         ("EMP001", "978-0-321-12521-7", 2)], start=4
    ):
        result = shop.send(ev.sell(emp_id, isbn, qty))
        label = "SUCCESS" if result["ok"] else "REJECTED"
        print(f"  Sale #{i}: {label} - {totals_of(result):.2f}")
        if result["ok"]:
            tx_ids.append(result["events"][0]["seq"])

    print("\n[3:00 PM] Processing a return...")
    refund = next(s["total"] for s in shop.sales() if s["seq"] == tx_ids[0])
    returned = shop.send(ev.return_sale(tx_ids[0]))
    print(f"  Return #1: {'SUCCESS' if returned['ok'] else 'REJECTED'} - "
          f"refund {refund:.2f}")

    print("\n[4:00 PM] Checking inventory levels...")
    low = [item for item in shop.stock()
           if item["available"] <= config.LOW_STOCK_THRESHOLD]
    if low:
        for item in low:
            print(f"  LOW STOCK: {item['title']} (ISBN: {item['isbn']}) "
                  f"- {item['available']} available")
    else:
        print("  All items adequately stocked.")

    print("\n[6:00 PM] Generating end-of-day reports...")
    daily = shop.report("daily")
    revenue = daily["revenue"]
    print(f"\n  DAILY REPORT:")
    print(f"    Gross Revenue:   {config.format_currency(revenue['gross'])}")
    print(f"    Returns:         {config.format_currency(revenue['returns'])}")
    print(f"    Net Revenue:     {config.format_currency(revenue['net'])}")
    print(f"    Transactions:    {revenue['sales_kept']} kept, "
          f"{revenue['sales_returned']} returned")
    print(f"    Low Stock Items: {daily['inventory']['low_stock_count']}")
    print(f"    Total Inventory Value: {config.format_currency(daily['inventory']['total_value'])}")

    emp_report = shop.report("employees")
    print("\n  EMPLOYEE REPORT:")
    for item in emp_report["items"]:
        print(f"    {item['name']} ({item['rank']}): "
              f"{config.format_currency(item['pay_total'])} "
              f"[{item['hours_worked']:.0f}h + {config.format_currency(item['commission'])}]")
    print(f"    Total Payroll: {config.format_currency(emp_report['total_payroll'])}")

    inv_report = shop.report("inventory")
    print("\n  INVENTORY REPORT:")
    print(f"    {config.format_currency(inv_report['total_value'])} value across "
          f"{len(inv_report['items'])} titles")
    if inv_report["low_stock"]:
        print(f"    Low Stock Titles: {len(inv_report['low_stock'])}")

    print("\n[6:00 PM] Closing the bookstore...")
    return daily


def totals_of(result):
    """Gross incl. tax for the sales a command just wrote into the log."""
    import views
    if not result["ok"]:
        return 0.0
    return sum(
        views.grand_total(e["unit_price"], e["quantity"], e["discount"])
        for e in result["events"] if e["type"] == ev.SALE_COMPLETED
    )


def interactive_mode(shop):
    print("=" * 60)
    print("  CAMPUS BOOKSTORE — EVENT-SOURCED")
    print("  Interactive Mode (type 'help' for commands)")
    print("=" * 60)

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if not line:
            continue

        parts = line.split()
        action = parts[0].lower()

        if action == "help":
            _show_help()
        elif action == "sale":
            if len(parts) >= 3:
                qty = int(parts[3]) if len(parts) > 3 else 1
                result = shop.send(ev.sell(parts[1], parts[2], qty))
                print(_describe(result))
            else:
                print("Usage: sale <employee_id> <isbn> [quantity]")
        elif action == "return":
            if len(parts) >= 2:
                print(_describe(shop.send(ev.return_sale(int(parts[1])))))
            else:
                print("Usage: return <transaction_seq>")
        elif action == "reserve":
            if len(parts) >= 3:
                qty = int(parts[3]) if len(parts) > 3 else 1
                print(_describe(shop.send(ev.reserve(parts[2], parts[1], qty))))
            else:
                print("Usage: reserve <employee_id> <isbn> [quantity]")
        elif action == "inventory":
            for item in shop.stock():
                print(f"  {item['isbn']}: {item['title']} "
                      f"on hand {item['on_hand']} (reserved {item['reserved']}) "
                      f"${item['price']}")
        elif action == "report":
            kind = parts[1] if len(parts) > 1 else "daily"
            report = shop.report(kind)
            print(f"  {report}")
        elif action == "log":
            for event in shop.events():
                print(f"  #{event['seq']} {event['type']} "
                      f"{_without(event, 'seq', 'at', 'type')}")
        elif action in ("quit", "exit"):
            print("Goodbye!")
            break
        else:
            print(f"Unknown command: {action}. Type 'help' for options.")


def _describe(result):
    if not result["ok"]:
        return f"REJECTED: {result['error']}"
    events = result["events"]
    return " + ".join(f"{e['type']}#{e['seq']}" for e in events)


def _without(event, *keys):
    return {k: v for k, v in event.items() if k not in keys}


def _show_help():
    print("""
Available commands:
  sale <emp> <isbn> [qty]        Ring up a sale
  return <seq>                   Return a transaction by its sequence number
  reserve <emp> <isbn> [qty]     Set copies aside for an employee
  inventory                      Show stock levels
  report [daily|inventory|employees]
  log                            Replay everything that happened
  quit                           Exit
""")


if __name__ == "__main__":
    shop = open_store()

    if "--demo" in sys.argv:
        run_sample_day(shop)
    elif "--interactive" in sys.argv or sys.stdin.isatty():
        interactive_mode(shop)
    else:
        run_sample_day(shop)
