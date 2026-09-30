"""Commands we send, and events we record.

A *command* is a request to do something (`sell`). It may be refused, and a
refused request is written nowhere.

An *event* is a fact about something that already happened (`sale_completed`).
Events are all this system remembers, so every answer must be computable from
them. They never share a name with the command that produced one: requests are
imperative, facts are past tense.

Two rules hold throughout this file:

  * Every shape is defined exactly once, by a signature. A missing or misspelt
    field fails at the call site, not three files and one fold later.
  * Events carry no derived numbers. A sale records unit price, quantity and the
    discount rate actually granted; every total anyone reports is arithmetic over
    those. Nothing stores what it could have calculated.

A command may hold values that must never reach the log. `sell(discount=0.90)`
asks for ninety percent off; a cashier's event says five, and ninety appears
nowhere, because ninety was never true.
"""


def _request(kind, **fields):
    """Build a command dict."""
    out = {"type": kind}
    out.update(fields)
    return out


# ── Commands ────────────────────────────────────────────────────────────────

def add_book(isbn, title, author, price, quantity=0, supplier_id=None):
    return _request("AddBook", isbn=isbn, title=title, author=author,
                    price=price, quantity=quantity, supplier_id=supplier_id)


def restock(isbn, quantity):
    return _request("Restock", isbn=isbn, quantity=quantity)


def remove_book(isbn):
    return _request("RemoveBook", isbn=isbn)


def hire(emp_id, name, rank="cashier", hourly_rate=12.0):
    return _request("Hire", emp_id=emp_id, name=name, rank=rank,
                    hourly_rate=hourly_rate)


def fire(emp_id):
    return _request("Fire", emp_id=emp_id)


def promote(emp_id, new_rank):
    return _request("Promote", emp_id=emp_id, new_rank=new_rank)


def assign_shift(emp_id, shift_name, start_time, end_time):
    return _request("AssignShift", emp_id=emp_id, shift_name=shift_name,
                    start_time=start_time, end_time=end_time)


def sell(employee_id, isbn, quantity=1, discount=0.0):
    """Ask for a sale. `discount` is a request, not a fact: the core caps it by
    rank and records only what was granted."""
    return _request("Sell", employee_id=employee_id, isbn=isbn,
                    quantity=quantity, discount=discount)


def return_sale(transaction_seq):
    return _request("ReturnSale", transaction_seq=transaction_seq)


def reserve(isbn, employee_id, quantity=1):
    return _request("Reserve", isbn=isbn, employee_id=employee_id,
                    quantity=quantity)


def release_reservation(isbn, employee_id, quantity=1):
    return _request("ReleaseReservation", isbn=isbn, employee_id=employee_id,
                    quantity=quantity)


def add_supplier(supplier_id, name, contact_email, phone=None, rating=5.0):
    return _request("AddSupplier", supplier_id=supplier_id, name=name,
                    contact_email=contact_email, phone=phone, rating=rating)


def supplier_carries(supplier_id, isbn, price):
    return _request("SupplierCarries", supplier_id=supplier_id, isbn=isbn,
                    price=price)


def place_order(isbn, quantity, urgent=False, supplier_id=None):
    return _request("PlaceOrder", isbn=isbn, quantity=quantity, urgent=urgent,
                    supplier_id=supplier_id)


def receive_order(order_seq):
    return _request("ReceiveOrder", order_seq=order_seq)


# ── Events: the facts the log can contain ───────────────────────────────────
#
# Every event's shape is defined exactly once, by the signature of its
# constructor below. The core and the views only ever read fields; they never
# decide what a fact looks like. A missing or misspelt field is a TypeError at
# the moment the core tries to record it, not a KeyError in some later fold.
# Events carry no derived numbers: a sale records unit price, quantity and
# discount rate, and every total anyone reports is arithmetic over those three.

BOOK_ADDED = "BookAdded"
BOOK_REMOVED = "BookRemoved"
STOCK_ADJUSTED = "StockAdjusted"
EMPLOYEE_HIRED = "EmployeeHired"
EMPLOYEE_FIRED = "EmployeeFired"
EMPLOYEE_PROMOTED = "EmployeePromoted"
SHIFT_ASSIGNED = "ShiftAssigned"
SALE_COMPLETED = "SaleCompleted"
SALE_RETURNED = "SaleReturned"
BOOK_RESERVED = "BookReserved"
RESERVATION_RELEASED = "ReservationReleased"
SUPPLIER_ADDED = "SupplierAdded"
SUPPLIER_CARRIES = "SupplierCarriesBook"
ORDER_PLACED = "OrderPlaced"
ORDER_RECEIVED = "OrderReceived"


def _fact(kind, **fields):
    out = {"type": kind}
    out.update(fields)
    return out


def book_added(isbn, title, author, price, quantity, supplier_id=None):
    return _fact(BOOK_ADDED, isbn=isbn, title=title, author=author, price=price,
                 quantity=quantity, supplier_id=supplier_id)


def book_removed(isbn):
    return _fact(BOOK_REMOVED, isbn=isbn)


def stock_adjusted(isbn, delta):
    return _fact(STOCK_ADJUSTED, isbn=isbn, delta=delta)


def employee_hired(emp_id, name, rank, hourly_rate):
    return _fact(EMPLOYEE_HIRED, emp_id=emp_id, name=name, rank=rank,
                 hourly_rate=hourly_rate)


def employee_fired(emp_id):
    return _fact(EMPLOYEE_FIRED, emp_id=emp_id)


def employee_promoted(emp_id, new_rank):
    return _fact(EMPLOYEE_PROMOTED, emp_id=emp_id, new_rank=new_rank)


def shift_assigned(emp_id, shift_name, start_time, end_time):
    return _fact(SHIFT_ASSIGNED, emp_id=emp_id, shift_name=shift_name,
                 start_time=start_time, end_time=end_time)


def sale_completed(isbn, employee_id, quantity, unit_price, discount):
    """Copies left the shelf. `unit_price` is the price at that moment, and
    `discount` is the rate actually granted, which may be less than asked."""
    return _fact(SALE_COMPLETED, isbn=isbn, employee_id=employee_id,
                 quantity=quantity, unit_price=unit_price, discount=discount)


def sale_returned(transaction_seq, isbn, employee_id, quantity):
    """Copies came back. Denormalised from the sale it names so that no view
    has to go hunting for the original to know what was returned."""
    return _fact(SALE_RETURNED, transaction_seq=transaction_seq, isbn=isbn,
                 employee_id=employee_id, quantity=quantity)


def book_reserved(isbn, employee_id, quantity):
    return _fact(BOOK_RESERVED, isbn=isbn, employee_id=employee_id,
                 quantity=quantity)


def reservation_released(isbn, employee_id, quantity):
    return _fact(RESERVATION_RELEASED, isbn=isbn, employee_id=employee_id,
                 quantity=quantity)


def supplier_added(supplier_id, name, contact_email, phone=None, rating=5.0):
    return _fact(SUPPLIER_ADDED, supplier_id=supplier_id, name=name,
                 contact_email=contact_email, phone=phone, rating=rating)


def supplier_carries_book(supplier_id, isbn, price):
    return _fact(SUPPLIER_CARRIES, supplier_id=supplier_id, isbn=isbn, price=price)


def order_placed(isbn, quantity, supplier_id, urgent):
    return _fact(ORDER_PLACED, isbn=isbn, quantity=quantity,
                 supplier_id=supplier_id, urgent=urgent)


def order_received(order_seq):
    return _fact(ORDER_RECEIVED, order_seq=order_seq)
