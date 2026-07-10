"""Tax helpers."""


def apply_tax(price: float, percent: float) -> float:
    """Return the price after adding percentage tax."""
    return price * (1 + percent / 100)
