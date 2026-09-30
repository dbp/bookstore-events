"""Commands we send, and events we record. Both are plain immutable-ish dicts.

A *command* is a request to do something ("Sell"). A command may be rejected;
nothing is written down when it is.

An *event* is a fact about something that already happened ("SaleCompleted").
Events are the only thing the system remembers, so every answer must be
computable from them. Commands and events never share a name: commands are
imperative requests, events are past-tense facts.
"""


def command(kind, **fields):
    """Build a command dict."""
    out = {"type": kind}
    out.update(fields)
    return out


# ── Commands ────────────────────────────────────────────────────────────────

def add_book(isbn, title, author, price, quantity=0, supplier_id=None):
    return command("AddBook", isbn=isbn, title=title, author=author,
                   price=price, quantity=quantity, supplier_id=supplier_id)


def restock(isbn, quantity):
    return command("Restock", isbn=isbn, quantity=quantity)


def remove_book(isbn):
    return command("RemoveBook", isbn=isbn)


def hire(emp_id, name, rank="cashier", hourly_rate=12.0):
    return command("Hire", emp_id=emp_id, name=name, rank=rank,
                   hourly_rate=hourly_rate)


def fire(emp_id):
    return command("Fire", emp_id=emp_id)


def promote(emp_id, new_rank):
    return command("Promote", emp_id=emp_id, new_rank=new_rank)


def assign_shift(emp_id, shift_name, start_time, end_time):
    return command("AssignShift", emp_id=emp_id, shift_name=shift_name,
                   start_time=start_time, end_time=end_time)


def sell(employee_id, isbn, quantity=1, discount=0.0):
    return command("Sell", employee_id=employee_id, isbn=isbn,
                   quantity=quantity, discount=discount)


def return_sale(transaction_seq):
    return command("ReturnSale", transaction_seq=transaction_seq)


def reserve(isbn, employee_id, quantity=1):
    return command("Reserve", isbn=isbn, employee_id=employee_id,
                   quantity=quantity)


def release_reservation(isbn, employee_id, quantity=1):
    return command("ReleaseReservation", isbn=isbn, employee_id=employee_id,
                   quantity=quantity)


def add_supplier(supplier_id, name, contact_email, phone=None, rating=5.0):
    return command("AddSupplier", supplier_id=supplier_id, name=name,
                   contact_email=contact_email, phone=phone, rating=rating)


def supplier_carries(supplier_id, isbn, price):
    return command("SupplierCarries", supplier_id=supplier_id, isbn=isbn,
                   price=price)


def place_order(isbn, quantity, urgent=False, supplier_id=None):
    return command("PlaceOrder", isbn=isbn, quantity=quantity, urgent=urgent,
                   supplier_id=supplier_id)


def receive_order(order_seq):
    return command("ReceiveOrder", order_seq=order_seq)


# ── Event constructors (used by the core when a command is accepted) ─────────

def event(kind, **fields):
    """Build an event dict. The store stamps seq and at on append."""
    out = {"type": kind}
    out.update(fields)
    return out


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
