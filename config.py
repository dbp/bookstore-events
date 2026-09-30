"""Business constants shared by the core and the views."""

TAX_RATE = 0.075
COMMISSION_RATE = 0.08
LOW_STOCK_THRESHOLD = 5
OPENING_HOUR = 8
CLOSING_HOUR = 18

RANK_DISCOUNT_CAPS = {
    "cashier": 0.05,
    "senior_cashier": 0.10,
    "shift_lead": 0.15,
    "manager": 0.25,
}


def discount_cap(rank):
    """Maximum discount an employee of this rank may apply."""
    return RANK_DISCOUNT_CAPS.get(rank, 0.0)


def format_currency(amount):
    return f"${amount:,.2f}"
