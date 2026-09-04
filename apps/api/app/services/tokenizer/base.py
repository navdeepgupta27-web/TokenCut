"""Tokenizer abstraction.

One rule governs every implementation in this package: a tokenizer returns
what it actually knows, tagged with how it knows it. It never guesses and
labels the guess as exact, and it never synthesises token offsets it cannot
derive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.schemas import CountSource


@dataclass(frozen=True, slots=True)
class CountResult:
    model: str
    tokens: int | None
    source: CountSource
    encoding: str | None = None
    offsets: list[tuple[int, int]] | None = None
    includes_message_overhead: bool = False
    estimate_error_p90: float | None = None
    calibrated: bool | None = None
    note: str | None = None

    @classmethod
    def unavailable(cls, model: str, reason: str) -> CountResult:
        return cls(
            model=model,
            tokens=None,
            source=CountSource.UNAVAILABLE,
            note=reason,
        )


@runtime_checkable
class Tokenizer(Protocol):
    provider: str

    @property
    def supports_offsets(self) -> bool: ...

    @property
    def is_local(self) -> bool:
        """True when counting requires no network call and no credential."""

    def available(self) -> tuple[bool, str | None]:
        """(usable, reason_if_not). Missing credentials are not an error."""

    async def count(
        self, text: str, model: str, *, want_offsets: bool = False
    ) -> CountResult: ...


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Static, price-free metadata about a model.

    Deliberately separate from the pricing catalog: a model can be perfectly
    countable while its price is unverified, and the two facts have different
    review cycles.
    """

    id: str
    provider: str
    display_name: str
    tokenizer: str
    context_window: int | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    note: str | None = None
