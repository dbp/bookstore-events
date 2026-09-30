"""The one mutable thing: an append-only log of events.

Every question in this program is answered by folding over the log, and the only
way to change any answer is to append facts to this list. Commands are validated
by the pure core before anything is written, so a rejected command leaves no
trace. Events get their sequence number and timestamp here, at the moment they
become facts — that is the only place the clock is read.

Readers get tuples, never the internal list, so nothing outside this class can
append to it.
"""

import datetime

import core
import views


class EventLog:
    """Append-only event store."""

    def __init__(self):
        self._events = []

    # ── Writing ───────────────────────────────────────────────────────────

    def dispatch(self, cmd):
        """Run a command past the core; append its events if accepted.

        Returns {"ok": True, "events": [...]} or {"ok": False, "error": reason}.
        """
        try:
            new_events = core.handle(self.state(), cmd)
        except core.Rejection as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "events": self._append(new_events)}

    def _append(self, new_events):
        """Stamp and append. Returns immutable copies of what was written."""
        stamped = []
        for event in new_events:
            fact = dict(event)
            fact["seq"] = len(self._events) + 1
            fact["at"] = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
            self._events.append(fact)
            stamped.append(dict(fact))
        return tuple(stamped)

    # ── Reading ───────────────────────────────────────────────────────────

    def events(self):
        """The whole log, oldest first."""
        return tuple(dict(e) for e in self._events)

    def state(self):
        """Fold the entire log into the current snapshot."""
        return core.fold(self.events())

    def count(self):
        return len(self._events)

    def __len__(self):
        return len(self._events)


class Bookstore:
    """The log plus the questions worth asking of it.

    This is not a manager class with fields; it is a log with shortcuts. Nothing
    here stores derived data — every method folds on demand.
    """

    def __init__(self):
        self.log = EventLog()

    # ── Sending commands ──────────────────────────────────────────────────

    def send(self, cmd):
        return self.log.dispatch(cmd)

    def must(self, cmd):
        """Send a command and insist it is accepted; returns the new events."""
        result = self.log.dispatch(cmd)
        if not result["ok"]:
            raise AssertionError(f"command rejected: {result['error']}")
        return result["events"]

    # ── Asking questions ──────────────────────────────────────────────────

    def events(self):
        return self.log.events()

    def state(self):
        return self.log.state()

    def stock(self):
        return views.stock_view(self.events())

    def book(self, isbn):
        for item in views.stock_view(self.events()):
            if item["isbn"] == isbn:
                return item
        return None

    def employees(self):
        return views.employee_view(self.events())

    def sales(self):
        return views.sales_view(self.events())

    def orders(self):
        return views.orders_view(self.events())

    def report(self, kind="daily"):
        if kind == "daily":
            return views.daily_report(self.events())
        if kind == "inventory":
            return views.inventory_report(self.events())
        if kind == "employees":
            return views.employee_report(self.events())
        raise ValueError(f"no such report: {kind}")
