"""Order pricing helpers."""


def apply_discount(price: float, percent: float) -> float:
    """Return the price after applying a percentage discount."""
    return price * (1 + percent / 100)


def clamp_price(price: float, floor: float = 0.0) -> float:
    """Never let a discounted price go below the floor."""
    return max(price, floor)
