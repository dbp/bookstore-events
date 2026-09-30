"""The pure core: fold events into a snapshot, and decide what commands permit.

Nothing here mutates anything. `apply` takes a state and an event and returns a
new state. `handle` takes a state and a command and returns the events that
command deserves, or raises `Rejection`. Because these functions are pure, the
same log always produces the same snapshot.

The core reads event shapes but does not invent them: every fact it can produce
comes from a named constructor in `events.py`, so what a `SaleCompleted` holds is
decided in one place. Handlers also get to decide *which* fact a command becomes,
which is why `AddBook` may yield `BookAdded` or `StockAdjusted` and a refusal
yields none.

State is a plain nested dict:

    books       isbn   -> {title, author, price, on_hand, reserved, supplier_id}
    employees   emp_id -> {name, rank, hourly_rate, shifts, hours_worked}
    suppliers   sid    -> {name, email, phone, rating, carries: {isbn: price}}
    sales       seq    -> {isbn, employee_id, quantity, unit_price, discount, returned}
    orders      seq    -> {isbn, quantity, supplier_id, urgent, status}

`on_hand` is physical stock; `reserved` is the part of it set aside for someone.
Available to sell is `on_hand - reserved`.
"""

import config
import events as ev


class Rejection(Exception):
    """A command that will not be written to the log."""


def empty_state():
    return {"books": {}, "employees": {}, "suppliers": {}, "sales": {}, "orders": {}}


# ── Pure helpers for copy-on-write dict updates ─────────────────────────────

def _replace(mapping, key, value):
    out = dict(mapping)
    out[key] = value
    return out


def _dissoc(mapping, key):
    out = dict(mapping)
    out.pop(key, None)
    return out


def _patch(record, **fields):
    out = dict(record)
    out.update(fields)
    return out


def _rekey(state, slot, mapping):
    return _replace(state, slot, mapping)


def shift_hours(start_time, end_time):
    """Hours between two "HH:MM" strings; never negative."""
    start_h, start_m = _split_clock(start_time)
    end_h, end_m = _split_clock(end_time)
    return max(0.0, ((end_h * 60 + end_m) - (start_h * 60 + start_m)) / 60.0)


def _split_clock(text):
    parts = text.split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


# ── The fold ────────────────────────────────────────────────────────────────

def apply(state, event):
    """Fold one event into a snapshot. Returns a new state; never mutates."""
    kind = event["type"]
    books, employees = state["books"], state["employees"]

    if kind == ev.BOOK_ADDED:
        book = {"title": event["title"], "author": event["author"],
                "price": event["price"], "on_hand": event["quantity"],
                "reserved": 0, "supplier_id": event.get("supplier_id")}
        return _rekey(state, "books", _replace(books, event["isbn"], book))

    if kind == ev.BOOK_REMOVED:
        return _rekey(state, "books", _dissoc(books, event["isbn"]))

    if kind == ev.STOCK_ADJUSTED:
        isbn = event["isbn"]
        book = books[isbn]
        moved = _patch(book, on_hand=max(0, book["on_hand"] + event["delta"]))
        return _rekey(state, "books", _replace(books, isbn, moved))

    if kind == ev.EMPLOYEE_HIRED:
        employee = {"name": event["name"], "rank": event["rank"],
                    "hourly_rate": event["hourly_rate"], "shifts": 0,
                    "hours_worked": 0.0}
        return _rekey(state, "employees",
                      _replace(employees, event["emp_id"], employee))

    if kind == ev.EMPLOYEE_FIRED:
        return _rekey(state, "employees", _dissoc(employees, event["emp_id"]))

    if kind == ev.EMPLOYEE_PROMOTED:
        emp_id = event["emp_id"]
        updated = _patch(employees[emp_id], rank=event["new_rank"])
        return _rekey(state, "employees", _replace(employees, emp_id, updated))

    if kind == ev.SHIFT_ASSIGNED:
        emp_id = event["emp_id"]
        employee = employees[emp_id]
        worked = shift_hours(event["start_time"], event["end_time"])
        updated = _patch(employee, shifts=employee["shifts"] + 1,
                         hours_worked=employee["hours_worked"] + worked)
        return _rekey(state, "employees", _replace(employees, emp_id, updated))

    if kind == ev.SALE_COMPLETED:
        isbn = event["isbn"]
        sale = {"isbn": isbn, "employee_id": event["employee_id"],
                "quantity": event["quantity"], "unit_price": event["unit_price"],
                "discount": event["discount"], "returned": False}
        book = books[isbn]
        books = _replace(books, isbn,
                         _patch(book, on_hand=max(0, book["on_hand"] - event["quantity"])))
        return {"books": books, "employees": employees,
                "suppliers": state["suppliers"],
                "sales": _replace(state["sales"], event["seq"], sale),
                "orders": state["orders"]}

    if kind == ev.SALE_RETURNED:
        sales = state["sales"]
        seq = event["transaction_seq"]
        sales = _replace(sales, seq, _patch(sales[seq], returned=True))
        book = books.get(event["isbn"])
        if book is not None:
            books = _replace(books, event["isbn"],
                             _patch(book, on_hand=book["on_hand"] + event["quantity"]))
        return {"books": books, "employees": employees,
                "suppliers": state["suppliers"], "sales": sales,
                "orders": state["orders"]}

    if kind == ev.BOOK_RESERVED:
        isbn = event["isbn"]
        book = books[isbn]
        moved = _patch(book, reserved=book["reserved"] + event["quantity"])
        return _rekey(state, "books", _replace(books, isbn, moved))

    if kind == ev.RESERVATION_RELEASED:
        isbn = event["isbn"]
        book = books[isbn]
        moved = _patch(book, reserved=max(0, book["reserved"] - event["quantity"]))
        return _rekey(state, "books", _replace(books, isbn, moved))

    if kind == ev.SUPPLIER_ADDED:
        supplier = {"name": event["name"], "email": event["contact_email"],
                    "phone": event.get("phone"), "rating": event.get("rating", 5.0),
                    "carries": {}}
        return _rekey(state, "suppliers",
                      _replace(state["suppliers"], event["supplier_id"], supplier))

    if kind == ev.SUPPLIER_CARRIES:
        suppliers = state["suppliers"]
        sid = event["supplier_id"]
        supplier = suppliers[sid]
        carries = _replace(supplier["carries"], event["isbn"], event["price"])
        updated = _patch(supplier, carries=carries)
        return _rekey(state, "suppliers", _replace(suppliers, sid, updated))

    if kind == ev.ORDER_PLACED:
        order = {"isbn": event["isbn"], "quantity": event["quantity"],
                 "supplier_id": event["supplier_id"], "urgent": event["urgent"],
                 "status": "pending"}
        return _rekey(state, "orders",
                      _replace(state["orders"], event["seq"], order))

    if kind == ev.ORDER_RECEIVED:
        orders = state["orders"]
        order = orders[event["order_seq"]]
        orders = _replace(orders, event["order_seq"], _patch(order, status="delivered"))
        book = books.get(order["isbn"])
        if book is not None:
            books = _replace(books, order["isbn"],
                             _patch(book, on_hand=book["on_hand"] + order["quantity"]))
        return {"books": books, "employees": employees,
                "suppliers": state["suppliers"], "sales": state["sales"],
                "orders": orders}

    raise Rejection(f"unknown event type: {kind}")


def fold(log):
    """Fold a whole log into the snapshot it describes."""
    state = empty_state()
    for event in log:
        state = apply(state, event)
    return state


# ── Command handlers: (state, command) -> events, or Rejection ──────────────

def _require(condition, message):
    if not condition:
        raise Rejection(message)


def _available(book):
    return book["on_hand"] - book["reserved"]


def _add_book(state, cmd):
    existing = state["books"].get(cmd["isbn"])
    if existing is None:
        return [ev.book_added(isbn=cmd["isbn"], title=cmd["title"],
                              author=cmd["author"], price=cmd["price"],
                              quantity=cmd["quantity"], supplier_id=cmd["supplier_id"])]
    _require(cmd["quantity"] > 0, f"{cmd['isbn']} already exists; restock it instead")
    return [ev.stock_adjusted(cmd["isbn"], cmd["quantity"])]


def _restock(state, cmd):
    _require(cmd["isbn"] in state["books"], f"no book with isbn {cmd['isbn']}")
    _require(cmd["quantity"] != 0, "restock quantity must not be zero")
    return [ev.stock_adjusted(cmd["isbn"], cmd["quantity"])]


def _remove_book(state, cmd):
    _require(cmd["isbn"] in state["books"], f"no book with isbn {cmd['isbn']}")
    return [ev.book_removed(cmd["isbn"])]


def _hire(state, cmd):
    _require(cmd["emp_id"] not in state["employees"],
             f"employee {cmd['emp_id']} is already on staff")
    return [ev.employee_hired(emp_id=cmd["emp_id"], name=cmd["name"],
                              rank=cmd["rank"], hourly_rate=cmd["hourly_rate"])]


def _fire(state, cmd):
    _require(cmd["emp_id"] in state["employees"], f"no employee with id {cmd['emp_id']}")
    return [ev.employee_fired(cmd["emp_id"])]


def _promote(state, cmd):
    _require(cmd["emp_id"] in state["employees"], f"no employee with id {cmd['emp_id']}")
    return [ev.employee_promoted(emp_id=cmd["emp_id"], new_rank=cmd["new_rank"])]


def _assign_shift(state, cmd):
    _require(cmd["emp_id"] in state["employees"], f"no employee with id {cmd['emp_id']}")
    _require(shift_hours(cmd["start_time"], cmd["end_time"]) > 0,
                         "shift must have a positive duration")
    return [ev.shift_assigned(emp_id=cmd["emp_id"], shift_name=cmd["shift_name"],
                              start_time=cmd["start_time"], end_time=cmd["end_time"])]


def _sell(state, cmd):
    book = state["books"].get(cmd["isbn"])
    _require(book is not None, f"no book with isbn {cmd['isbn']}")
    _require(cmd["quantity"] > 0, "sale quantity must be positive")
    _require(_available(book) >= cmd["quantity"],
                        f"only {_available(book)} copies of {cmd['isbn']} available")
    employee = state["employees"].get(cmd["employee_id"])
    _require(employee is not None, f"no employee with id {cmd['employee_id']}")

    cap = config.discount_cap(employee["rank"])
    discount = max(0.0, min(cmd["discount"], cap))
    return [ev.sale_completed(isbn=cmd["isbn"], employee_id=cmd["employee_id"],
                              quantity=cmd["quantity"], unit_price=book["price"],
                              discount=discount)]


def _return_sale(state, cmd):
    seq = cmd["transaction_seq"]
    sale = state["sales"].get(seq)
    _require(sale is not None, f"no transaction {seq}")
    _require(not sale["returned"], f"transaction {seq} was already returned")
    return [ev.sale_returned(transaction_seq=seq, isbn=sale["isbn"],
                             employee_id=sale["employee_id"],
                             quantity=sale["quantity"])]


def _reserve(state, cmd):
    book = state["books"].get(cmd["isbn"])
    _require(book is not None, f"no book with isbn {cmd['isbn']}")
    _require(cmd["quantity"] > 0, "reservation quantity must be positive")
    _require(_available(book) >= cmd["quantity"],
                        f"only {_available(book)} copies of {cmd['isbn']} available")
    _require(cmd["employee_id"] in state["employees"],
             f"no employee with id {cmd['employee_id']}")
    return [ev.book_reserved(isbn=cmd["isbn"], employee_id=cmd["employee_id"],
                             quantity=cmd["quantity"])]


def _release_reservation(state, cmd):
    book = state["books"].get(cmd["isbn"])
    _require(book is not None, f"no book with isbn {cmd['isbn']}")
    _require(cmd["quantity"] > 0, "reservation quantity must be positive")
    _require(book["reserved"] >= cmd["quantity"],
             f"only {book['reserved']} copies of {cmd['isbn']} are reserved")
    return [ev.reservation_released(isbn=cmd["isbn"],
                                    employee_id=cmd["employee_id"],
                                    quantity=cmd["quantity"])]


def _add_supplier(state, cmd):
    _require(cmd["supplier_id"] not in state["suppliers"],
             f"supplier {cmd['supplier_id']} is already registered")
    return [ev.supplier_added(supplier_id=cmd["supplier_id"], name=cmd["name"],
                              contact_email=cmd["contact_email"],
                              phone=cmd["phone"], rating=cmd["rating"])]


def _supplier_carries(state, cmd):
    _require(cmd["supplier_id"] in state["suppliers"],
             f"no supplier with id {cmd['supplier_id']}")
    return [ev.supplier_carries_book(supplier_id=cmd["supplier_id"],
                                     isbn=cmd["isbn"], price=cmd["price"])]


def _find_supplier(state, cmd):
    """Use the given supplier, else the one on the book record."""
    sid = cmd.get("supplier_id") or state["books"][cmd["isbn"]].get("supplier_id")
    _require(sid is not None, f"no supplier known for {cmd['isbn']}")
    _require(sid in state["suppliers"], f"no supplier with id {sid}")
    return sid


def _place_order(state, cmd):
    _require(cmd["isbn"] in state["books"], f"no book with isbn {cmd['isbn']}")
    _require(cmd["quantity"] > 0, "order quantity must be positive")
    sid = _find_supplier(state, cmd)
    return [ev.order_placed(isbn=cmd["isbn"], quantity=cmd["quantity"],
                            supplier_id=sid, urgent=cmd["urgent"])]


def _receive_order(state, cmd):
    seq = cmd["order_seq"]
    order = state["orders"].get(seq)
    _require(order is not None, f"no order {seq}")
    _require(order["status"] == "pending", f"order {seq} is already {order['status']}")
    return [ev.order_received(seq)]


_HANDLERS = {
    "AddBook": _add_book,
    "Restock": _restock,
    "RemoveBook": _remove_book,
    "Hire": _hire,
    "Fire": _fire,
    "Promote": _promote,
    "AssignShift": _assign_shift,
    "Sell": _sell,
    "ReturnSale": _return_sale,
    "Reserve": _reserve,
    "ReleaseReservation": _release_reservation,
    "AddSupplier": _add_supplier,
    "SupplierCarries": _supplier_carries,
    "PlaceOrder": _place_order,
    "ReceiveOrder": _receive_order,
}


def handle(state, cmd):
    """Decide which events a command deserves. Pure: writes nothing itself."""
    handler = _HANDLERS.get(cmd.get("type"))
    if handler is None:
        raise Rejection(f"unknown command: {cmd.get('type')}")
    return handler(state, cmd)
