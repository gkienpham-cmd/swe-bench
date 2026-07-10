from calc.pricing import apply_discount


def test_ten_percent_off():
    assert apply_discount(200.0, 10) == 180.0


def test_zero_discount_is_identity():
    assert apply_discount(50.0, 0) == 50.0
