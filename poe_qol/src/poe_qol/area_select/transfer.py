"""Transfer interface + the manual (highlight-only) strategy.

The selection system hands a ``TransferPlan`` (grid + ordered slots) to
a ``TransferStrategy``. Strategies report back through a
``TransferListener``. Two strategies exist:

* ``ManualTransfer`` (here): sends NO input. The overlay keeps the
  selected slots highlighted, and each slot is ticked off when the
  player Ctrl-clicks it themselves. One click = one game action, so it
  stays inside GGG's macro rules.
* ``ExperimentalCtrlClickTransfer`` (``poe_qol/experimental/``):
  Ctrl-clicks every slot for the player. Many game actions per gesture,
  so it is NOT GGG-compliant. It is imported only when selected.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Protocol

from .grid import GridGeometry, Slot


def order_slots(slots: Iterable[Slot], order: str = "column_serpentine") -> list[Slot]:
    """``row_major``: left-to-right, top-to-bottom.
    ``column_serpentine``: down the first column, up the next, ...
    (shortest cursor path for column-shaped selections)."""
    s = sorted(set(slots))
    if order == "row_major":
        return s
    cols = sorted({c for _, c in s})
    out: list[Slot] = []
    for i, c in enumerate(cols):
        col = sorted((sl for sl in s if sl[1] == c), reverse=bool(i % 2))
        out.extend(col)
    return out


@dataclass(frozen=True)
class TransferPlan:
    grid: str                     # config namespace, e.g. macros.inventory_dump
    geometry: GridGeometry
    slots: tuple[Slot, ...]       # in transfer order

    def points(self) -> list[tuple[int, int]]:
        """Screen coordinates (slot centres) in transfer order."""
        return [tuple(int(round(v)) for v in self.geometry.slot_center(s))
                for s in self.slots]  # type: ignore[misc]


class TransferListener(Protocol):
    def on_progress(self, done: int, total: int,
                    remaining: tuple[Slot, ...]) -> None: ...
    def on_finished(self, status: str, message: str) -> None: ...
    # status: "done" | "cancelled" | "aborted" | "error"


class TransferStrategy(ABC):
    MODE: str = ""
    GGG_COMPLIANT: bool = False
    DESCRIPTION: str = ""

    @property
    @abstractmethod
    def active(self) -> bool: ...

    @abstractmethod
    def start(self, plan: TransferPlan, listener: TransferListener) -> None: ...

    @abstractmethod
    def cancel(self, reason: str) -> None: ...

    def user_clicked(self, x: int, y: int, modifiers: frozenset[str]) -> None:
        """A real (not injected) left click the game received."""

    def user_moved(self, x: int, y: int) -> None:
        """A real (not injected) mouse move. May be called from the
        hook thread: must be cheap and thread-safe."""


class ManualTransfer(TransferStrategy):
    MODE = "manual"
    GGG_COMPLIANT = True
    DESCRIPTION = ("Highlights the selected slots; you Ctrl-click each one "
                   "yourself. Sends no input.")

    def __init__(self) -> None:
        self._plan: TransferPlan | None = None
        self._remaining: list[Slot] = []
        self._listener: TransferListener | None = None

    @property
    def active(self) -> bool:
        return self._plan is not None

    def start(self, plan: TransferPlan, listener: TransferListener) -> None:
        self._plan = plan
        self._remaining = list(plan.slots)
        self._listener = listener
        listener.on_progress(0, len(plan.slots), tuple(self._remaining))

    def user_clicked(self, x: int, y: int, modifiers: frozenset[str]) -> None:
        if self._plan is None or "ctrl" not in modifiers:
            return
        slot = self._plan.geometry.slot_at(x, y)
        if slot is None or slot not in self._remaining:
            return
        self._remaining.remove(slot)
        total = len(self._plan.slots)
        listener = self._listener
        assert listener is not None
        listener.on_progress(total - len(self._remaining), total,
                             tuple(self._remaining))
        if not self._remaining:
            self._finish("done", f"All {total} slots clicked")

    def cancel(self, reason: str) -> None:
        if self._plan is not None:
            self._finish("cancelled", reason)

    def _finish(self, status: str, message: str) -> None:
        listener = self._listener
        self._plan = None
        self._remaining = []
        self._listener = None
        if listener is not None:
            listener.on_finished(status, message)
