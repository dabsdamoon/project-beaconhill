from fibonacci import fib


def test_fib_base_cases():
    assert fib(0) == 0
    assert fib(1) == 1


def test_fib_small():
    assert fib(5) == 5
    assert fib(10) == 55


def test_fib_medium():
    assert fib(20) == 6765
