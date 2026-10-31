"""
Core Monetary & Financial Precision Engine.
Guarantees exact integer minor-unit arithmetic, strict currency consistency,
and ROUND_HALF_UP commercial rounding to eliminate floating-point errors.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

CENT = Decimal('0.01')

class CurrencyMismatchError(ValueError):
    pass

class Money:
    __slots__ = ('_minor_units', '_currency')

    def __init__(self, minor_units: int, currency: str = "USD"):
        if not isinstance(minor_units, int):
            raise TypeError(f"minor_units must be an int, got {type(minor_units).__name__}")
        self._minor_units = minor_units
        self._currency = currency.upper()

    @property
    def minor_units(self) -> int:
        return self._minor_units

    @property
    def currency(self) -> str:
        return self._currency

    @classmethod
    def from_decimal(cls, amount: Union[Decimal, str], currency: str = "USD") -> "Money":
        d = Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP)
        return cls(int(d * 100), currency)

    @classmethod
    def from_minor_units(cls, minor_units: int, currency: str = "USD") -> "Money":
        return cls(int(minor_units), currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> "Money":
        return cls(0, currency)

    def to_decimal(self) -> Decimal:
        return (Decimal(self._minor_units) / Decimal(100)).quantize(CENT)

    def to_formatted_string(self) -> str:
        return f"{self.to_decimal():.2f} {self._currency}"

    def __repr__(self) -> str:
        return f"Money({self._minor_units} minor units, {self._currency})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self._minor_units == other._minor_units and self._currency == other._currency

    def __lt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._minor_units < other._minor_units

    def __le__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._minor_units <= other._minor_units

    def __gt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._minor_units > other._minor_units

    def __ge__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._minor_units >= other._minor_units

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self._minor_units + other._minor_units, self._currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self._minor_units - other._minor_units, self._currency)

    def __mul__(self, factor: Union[int, Decimal, float]) -> "Money":
        d_factor = Decimal(str(factor))
        calculated = (Decimal(self._minor_units) * d_factor).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return Money(int(calculated), self._currency)

    def apply_basis_points(self, basis_points: int) -> "Money":
        """Applies basis points (1 bp = 0.01% = 0.0001). 1000 bp = 10%."""
        if not isinstance(basis_points, int):
            raise TypeError("basis_points must be an integer")
        d_amount = Decimal(self._minor_units)
        d_rate = Decimal(basis_points) / Decimal(10000)
        calc_minor = (d_amount * d_rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return Money(int(calc_minor), self._currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Cannot compare Money with {type(other).__name__}")
        if self._currency != other._currency:
            raise CurrencyMismatchError(f"Currency mismatch: {self._currency} != {other._currency}")