"""One clock for social and financial events (system brief §7.2, agent-world HANDOFF).

A round is 4 simulated hours; the 72 h horizon is 18 rounds. Round r stands at t = 4·r hours from
the world's epoch, the same epoch observations render times from. OASIS keeps its own
``sandbox_clock.time_step``, which stamps every post and action trace, and which ``env.step``
advances once per step (only on a TWITTER-type platform: oasis-seam.md S10/S11) but only after
the step's actions have all run. So step 1 advances both clocks, before any social write of the
round, and the step's own advance is taken back after it (``Clock.settle_step``): every round-r
row reads r, the platform's clock moves once a round, and a mismatch fails the round, so a post is
never stamped in another round than the money it moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from oasis_finance.observation import DEFAULT_EPOCH

from ..finance.models import HORIZON

ROUND_HOURS = 4
HORIZON_HOURS = HORIZON // timedelta(hours=1)
HORIZON_ROUNDS = HORIZON_HOURS // ROUND_HOURS

__all__ = ["HORIZON_HOURS", "HORIZON_ROUNDS", "ROUND_HOURS", "Clock", "ClockDrift"]


class ClockDrift(RuntimeError):
    """The OASIS clock and the round clock disagree: the round fails."""


@dataclass
class Clock:
    """The world's round clock; round 0 is the snapshot, before any round has run."""

    round: int = 0
    epoch: datetime = DEFAULT_EPOCH

    def __post_init__(self) -> None:
        if isinstance(self.round, bool) or not isinstance(self.round, int) or self.round < 0:
            raise ValueError(f"a round is a non-negative integer, not {self.round!r}")
        if self.epoch.tzinfo is None:
            raise ValueError("the clock's epoch carries its zone")

    @property
    def t_hours(self) -> int:
        return self.round * ROUND_HOURS

    @property
    def sim_minute(self) -> int:
        return self.t_hours * 60

    @property
    def now(self) -> datetime:
        return self.at(self.round)

    def at(self, round_: int) -> datetime:
        """The simulated time of round ``round_``."""
        return self.epoch + timedelta(hours=round_ * ROUND_HOURS)

    def advance(self, sandbox_clock: Any = None) -> int:
        """Step 1 of a round: move to the next round, and OASIS's clock with it, and return it."""
        if sandbox_clock is not None:
            self.check(sandbox_clock.time_step)
            sandbox_clock.time_step = self.round + 1
        self.round += 1
        return self.round

    def settle_step(self, sandbox_clock: Any) -> None:
        """After ``env.step``: it advanced OASIS's clock once, which step 1 already did; that
        advance is taken back, so the clock reads this round. Anything else fails the round."""
        if sandbox_clock.time_step != self.round + 1:
            raise ClockDrift(f"OASIS time_step {sandbox_clock.time_step} after the step of round "
                             f"{self.round}: the step did not advance it once")
        sandbox_clock.time_step = self.round

    def check(self, oasis_time_step: int) -> None:
        """The platform's clock reads this round, or the round fails."""
        if oasis_time_step != self.round:
            raise ClockDrift(f"OASIS time_step {oasis_time_step} in round {self.round}")
