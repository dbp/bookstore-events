"""Integration tests: send real commands at a real log, ask views about it.

Each test builds its own log, so there is nothing to reset between them. The
last two tests check properties this design has that the others do not: a log
replays to an identical snapshot, and a rejected command leaves no trace.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import core
import events as ev
import main
import views


def test_full_day_operations():
    """Sell, return, and close the books."""
    print("\n[TEST] Full Day Operations")
    print("-" * 40)

    shop = main.open_store()
    shop.must(ev.assign_shift("EMP001", "morning", "08:00", "16:00"))
    shop.must(ev.assign_shift("EMP002", "morning", "08:00", "16:00"))

    first = shop.must(ev.sell("EMP001", "978-0-13-468599-1", 2))[0]
    second = shop.must(ev.sell("EMP002", "978-0-596-00712-6", 1))[0]
    print(f"  Sale 1: OK (seq {first['seq']}); sale 2 seq {second['seq']}")

    stock = shop.book("978-0-13-468599-1")
    assert stock["on_hand"] == 10, f"expected 10 on hand, got {stock['on_hand']}"
    print(f"  Inventory check: {stock['title']} on hand {stock['on_hand']} (expected 10)")

    shop.must(ev.return_sale(first["seq"]))
    stock = shop.book("978-0-13-468599-1")
    assert stock["on_hand"] == 12, \
        f"returning a {first['quantity']}-copy sale should restore " \
        f"got on_hand {stock['on_hand']}"
    print(f"  Inventory after returning {first['quantity']} copies: "
          f"on hand {stock['on_hand']} (expected 12)")

    revenue = views.revenue_view(shop.events())
    assert revenue["sales_kept"] + revenue["sales_returned"] == 2
    print(f"  Revenue view: kept {revenue['sales_kept']}, "
          f"returned {revenue['sales_returned']}")

    alice = next(e for e in shop.employees() if e["id"] == "EMP001")
    assert alice["pay_total"] > 0
    print(f"  Payroll: {alice['name']} {config.format_currency(alice['pay_total'])}")
    print("  PASSED\n")


def test_low_stock_and_reordering():
    """Sell a title to zero, watch it go low, then order more."""
    print("\n[TEST] Low Stock and Reordering")
    print("-" * 40)

    shop = main.open_store()
    isbn = "978-0-321-12521-7"

    assert shop.book(isbn)["available"] == 3
    print(f"  Starting: {shop.book(isbn)['title']} has 3 available")

    sold = 0
    while True:
        result = shop.send(ev.sell("EMP003", isbn, 1))
        if not result["ok"]:
            break
        sold += 1
    assert sold == 3, f"expected to sell 3, sold {sold}"
    assert shop.book(isbn)["available"] == 0
    print(f"  Sold all {sold} copies; now {shop.book(isbn)['available']} available")

    report = shop.report("inventory")
    low_isbns = [i["isbn"] for i in report["low_stock"]]
    assert isbn in low_isbns
    print("  Low stock check: OK")

    order = shop.must(ev.place_order(isbn, 10))[0]
    shop.must(ev.receive_order(order["seq"]))
    assert shop.book(isbn)["on_hand"] == 10, \
        f"expected 10 after delivery, got {shop.book(isbn)['on_hand']}"
    print(f"  Ordered and received 10: on hand {shop.book(isbn)['on_hand']}")
    print("  PASSED\n")


def test_employee_lifecycle():
    """Hire, sell through them, fire; the sale history survives."""
    print("\n[TEST] Employee Lifecycle (hire + fire)")
    print("-" * 40)

    shop = main.open_store()
    shop.must(ev.hire("EMP999", "Test Employee", "cashier", 15.0))
    print("  Hired: Test Employee (cashier)")

    shop.must(ev.sell("EMP999", "978-0-13-468599-1", 1))
    temp = next(e for e in shop.employees() if e["id"] == "EMP999")
    assert temp["commission"] > 0
    print(f"  Commission derived from sales: {config.format_currency(temp['commission'])}")

    shop.must(ev.fire("EMP999"))
    assert all(e["id"] != "EMP999" for e in shop.employees())
    print("  Fired; no longer on the payroll")

    kept = [s for s in shop.sales() if s["employee_id"] == "EMP999"]
    assert len(kept) == 1, "their sale should still be in the log"
    print(f"  Sales history retained: {len(kept)} transaction still recorded")

    rejected = shop.send(ev.sell("EMP001", "978-0-13-468599-1", 1))
    assert rejected["ok"], "selling as a current employee should still work"
    print(f"  Selling as a current employee still works: seq "
          f"{rejected['events'][0]['seq']}")
    print("  PASSED\n")


def test_reservation_system():
    """Reserve sets copies aside; releasing gives back exactly what was set aside."""
    print("\n[TEST] Reservation System")
    print("-" * 40)

    shop = main.open_store()
    isbn = "978-0-596-00712-6"

    shop.must(ev.reserve(isbn, "EMP001", 2))
    book = shop.book(isbn)
    assert book["on_hand"] == 15 and book["reserved"] == 2 and book["available"] == 13
    print(f"  Reserved 2: on hand {book['on_hand']}, reserved {book['reserved']}, "
          f"available {book['available']}")

    mine = views.reservations_for(shop.events(), "EMP001")
    assert len(mine) == 1 and mine[0]["quantity"] == 2
    print(f"  Reservation visible in view: {mine}")

    shop.must(ev.release_reservation(isbn, "EMP001", 2))
    book = shop.book(isbn)
    assert book["reserved"] == 0, f"expected reserved 0, got {book['reserved']}"
    assert book["available"] == 15, f"expected available 15, got {book['available']}"
    print(f"  Released: on hand {book['on_hand']}, reserved {book['reserved']}, "
          f"available {book['available']}")

    over = shop.send(ev.release_reservation(isbn, "EMP001", 4))
    assert not over["ok"]
    print(f"  Releasing more than is reserved is refused: {over['error']}")
    print("  PASSED\n")


def test_supplier_ordering():
    """Order from a supplier and receive it into stock."""
    print("\n[TEST] Supplier Ordering")
    print("-" * 40)

    shop = main.open_store()
    isbn = "978-0-321-12521-7"

    order = shop.must(ev.place_order(isbn, 10))[0]
    assert len(shop.orders()) == 1
    print(f"  Order #{order['seq']} placed with {order['supplier_id']}")

    shop.must(ev.receive_order(order["seq"]))
    assert shop.book(isbn)["on_hand"] == 13, \
        f"expected 13 on hand, got {shop.book(isbn)['on_hand']}"
    print(f"  Received: on hand now {shop.book(isbn)['on_hand']} (was 3)")

    again = shop.send(ev.receive_order(order["seq"]))
    assert not again["ok"]
    print(f"  Receiving twice is refused: {again['error']}")

    unknown = shop.send(ev.place_order("000-0-00-000000-0", 5))
    assert not unknown["ok"]
    print(f"  Ordering a book we do not carry is refused: {unknown['error']}")
    print("  PASSED\n")


def test_reports_consistency():
    """Every report agrees with the others because all fold the same log."""
    print("\n[TEST] Reports Consistency")
    print("-" * 40)

    shop = main.open_store()
    shop.must(ev.sell("EMP001", "978-0-13-468599-1", 2))
    shop.must(ev.sell("EMP002", "978-0-596-00712-6", 1))

    daily = shop.report("daily")
    inventory = shop.report("inventory")
    staff = shop.report("employees")

    assert len(inventory["items"]) == 8
    print(f"  Inventory report: {len(inventory['items'])} titles - OK")

    assert len(staff["items"]) == 4
    print(f"  Employee report: {len(staff['items'])} employees - OK")

    assert daily["inventory"]["total_value"] == inventory["total_value"]
    print(f"  Daily and inventory agree on value: "
          f"{config.format_currency(daily['inventory']['total_value'])}")

    assert abs(daily["revenue"]["net"] - sum(
        s["total"] for s in shop.sales() if not s["returned"])) < 1e-9
    print(f"  Revenue matches the sales view: "
          f"{config.format_currency(daily['revenue']['net'])}")

    from_views = sum(e["commission"] for e in staff["items"])
    recomputed = sum(views.commission_view(shop.events()).values())
    assert abs(from_views - recomputed) < 1e-9
    print("  Commissions match across views: OK")
    print("  PASSED\n")


def test_discount_is_capped_by_rank():
    """A cashier cannot give a manager's discount, no matter what is asked."""
    print("\n[TEST] Discount Capped By Rank")
    print("-" * 40)

    shop = main.open_store()
    isbn = "978-0-13-468599-2"

    cashier_sale = shop.must(ev.sell("EMP004", isbn, 1, discount=0.90))[0]
    assert cashier_sale["discount"] == 0.05, \
        f"cashier should be capped at 0.05, got {cashier_sale['discount']}"
    print(f"  Cashier asked for 90%, got {cashier_sale['discount']:.0%}")

    manager_sale = shop.must(ev.sell("EMP001", isbn, 1, discount=0.90))[0]
    assert manager_sale["discount"] == 0.25, \
        f"manager should be capped at 0.25, got {manager_sale['discount']}"
    print(f"  Manager asked for 90%, got {manager_sale['discount']:.0%}")

    shop.must(ev.promote("EMP004", "shift_lead"))
    promoted_sale = shop.must(ev.sell("EMP004", isbn, 1, discount=0.90))[0]
    assert promoted_sale["discount"] == 0.15
    print(f"  After promotion: {promoted_sale['discount']:.0%}")
    print("  PASSED\n")


def test_log_replays_to_identical_state():
    """The snapshot is a pure function of the log, so replay is exact."""
    print("\n[TEST] Deterministic Replay")
    print("-" * 40)

    shop = main.open_store()
    log_before = shop.events()
    for cmd in [
        ev.assign_shift("EMP001", "morning", "08:00", "16:00"),
        ev.sell("EMP003", "978-0-13-468599-1", 2),
        ev.reserve("978-0-201-63361-0", "EMP002", 1),
    ]:
        shop.must(cmd)

    log = shop.events()
    assert core.fold(log) == shop.state(), "fold disagrees with the store's state"
    assert core.fold(log) == core.fold(log), "two folds of one log differ"
    print(f"  Folded {len(log)} events twice: identical snapshots")

    assert views.daily_report(log) == shop.report("daily")
    print("  Report rebuilt from the log alone: identical")

    prefix = core.fold(log_before)
    assert len(prefix["sales"]) == 0, "prefix of the log should not contain later sales"
    print(f"  Earlier snapshot still intact after {len(log) - len(log_before)} more events")
    print("  PASSED\n")


def test_rejected_commands_leave_no_trace():
    """A command the core refuses must not appear anywhere."""
    print("\n[TEST] Rejections Leave No Trace")
    print("-" * 40)

    shop = main.open_store()
    before_log = shop.events()
    before_state = shop.state()

    attempts = [
        ev.sell("EMP001", "000-0-00-000000-0", 1),
        ev.hire("EMP001", "Duplicate Name"),
        ev.fire("ghost"),
        ev.return_sale(999),
    ]
    for cmd in attempts:
        result = shop.send(cmd)
        assert not result["ok"], f"{cmd['type']} should have been refused"
        print(f"  {cmd['type']}: refused ({result['error']})")

    assert shop.events() == before_log, "log grew on a rejected command"
    assert shop.state() == before_state, "state changed on a rejected command"
    print(f"  Log still {len(shop.events())} events long: nothing written")
    print("  PASSED\n")


def test_full_sample_day():
    """Run the whole day and check the closing numbers."""
    print("\n[TEST] Full Sample Day (main.run_sample_day)")
    print("-" * 40)

    shop = main.open_store()
    report = main.run_sample_day(shop)

    revenue = report["revenue"]
    assert revenue["gross"] > 0
    assert revenue["sales_kept"] == 4, f"expected 4 kept, got {revenue['sales_kept']}"
    assert revenue["sales_returned"] == 1
    assert abs(revenue["net"] - (revenue["gross"] - revenue["returns"])) < 1e-9

    print(f"  Gross: {config.format_currency(revenue['gross'])}")
    print(f"  Net:   {config.format_currency(revenue['net'])}")
    print("  PASSED\n")


TESTS = [
    test_full_day_operations,
    test_low_stock_and_reordering,
    test_employee_lifecycle,
    test_reservation_system,
    test_supplier_ordering,
    test_reports_consistency,
    test_discount_is_capped_by_rank,
    test_log_replays_to_identical_state,
    test_rejected_commands_leave_no_trace,
    test_full_sample_day,
]


def run_all_tests():
    print("=" * 60)
    print("  CAMPUS BOOKSTORE - INTEGRATION TESTS (EVENT-SOURCED)")
    print("=" * 60)

    passed = failed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except AssertionError as exc:
            print(f"  FAILED: {exc}\n")
            failed += 1
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}\n")
            failed += 1

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed out of {len(TESTS)} tests")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
