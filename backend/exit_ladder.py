"""
EXIT LADDER — shared state machine for both pump.fun bonding-curve sniper AND
graduation sniper. Pure logic, no I/O. Testable in isolation.

Milestone schema per position:
  [(mult, pct_of_remaining_to_sell, trailing_floor_mult_after), ...]

Config string format (env var): "mult:pct:floor,mult:pct:floor,..."
  Example:  "5:80:5,20:50:10,100:100:50"
    - At 5x price, sell 80% of remaining tokens, set trailing floor to 5x
    - At 20x price, sell 50% of remaining (=10% of original), floor moves to 10x
    - At 100x price, sell 100% of remaining, position closed

Ratchet rule: floor only moves UP as milestones are hit — never down.
Trailing floor arms only after peak-after-milestone exceeds milestone × 1.05,
so a sell impacting the pool price doesn't immediately re-trigger.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LadderActionType(str, Enum):
    HOLD = "hold"
    SELL_PARTIAL = "sell_partial"     # sell pct of remaining (milestone hit)
    SELL_ALL = "sell_all"             # rug_stop / trailing_floor / time_limit


@dataclass
class Milestone:
    mult: float
    sell_pct_of_remaining: float   # 0-100
    floor_after: float             # trailing floor in multiples-of-entry


@dataclass
class LadderAction:
    type: LadderActionType
    sell_pct: float                # pct of CURRENT holdings to sell
    reason: str
    milestone_index: Optional[int] = None


@dataclass
class LadderState:
    """Per-position state. Mutated by evaluate()."""
    milestones_hit: List[int] = field(default_factory=list)
    current_floor: Optional[float] = None          # None until first milestone hit
    floor_armed: bool = False                      # true only after peak > floor × 1.05
    peak_ratio: float = 1.0                        # tracked ATH multiple


def parse_ladder(cfg_str: str) -> List[Milestone]:
    """Parse '5:80:5,20:50:10,100:100:50' into Milestone list. Skips malformed
    entries. Sorted ascending by mult. floor_after may be 0 (no trailing floor,
    used for moonbag stages)."""
    out: List[Milestone] = []
    if not cfg_str:
        return out
    for chunk in cfg_str.split(","):
        parts = chunk.strip().split(":")
        if len(parts) != 3:
            continue
        try:
            m = Milestone(
                mult=float(parts[0]),
                sell_pct_of_remaining=float(parts[1]),
                floor_after=float(parts[2]),
            )
            if m.mult > 0 and 0 < m.sell_pct_of_remaining <= 100 and m.floor_after >= 0:
                out.append(m)
        except Exception:
            continue
    out.sort(key=lambda x: x.mult)
    return out


def evaluate_ladder(
    ratio: float,
    milestones: List[Milestone],
    state: LadderState,
    rug_stop_mult: float = 0.5,
    floor_arm_bonus_pct: float = 5.0,
    hold_expired: bool = False,
) -> LadderAction:
    """Given current price ratio and mutable ladder state, decide next action.
    Mutates state.peak_ratio, state.floor_armed as needed. Milestone hits are
    NOT recorded here — caller records them AFTER successful sell (so a failed
    sell doesn't advance state)."""
    # Update peak
    if ratio > state.peak_ratio:
        state.peak_ratio = ratio

    # Time-limit override (caller sets hold_expired externally)
    if hold_expired:
        return LadderAction(LadderActionType.SELL_ALL, 100.0, "time_limit")

    # Rug stop — only active before any milestone hit
    if not state.milestones_hit and ratio <= rug_stop_mult:
        return LadderAction(LadderActionType.SELL_ALL, 100.0, f"rug_stop ({ratio:.2f}x)")

    # Arm the trailing floor when peak has cleared the CURRENT FLOOR by the arm bonus.
    # A floor of 0 means "no trailing floor" (used for moonbag stages).
    if state.current_floor is not None and state.current_floor > 0 and not state.floor_armed:
        if state.peak_ratio >= state.current_floor * (1 + floor_arm_bonus_pct / 100.0):
            state.floor_armed = True

    # Trailing floor exit — only if floor is set AND > 0 AND armed
    if (state.current_floor is not None and state.current_floor > 0
            and state.floor_armed and ratio <= state.current_floor):
        return LadderAction(
            LadderActionType.SELL_ALL, 100.0,
            f"trailing_floor ({state.current_floor:.1f} from peak {state.peak_ratio:.1f})"
        )

    # Milestone advance: find the LOWEST not-yet-hit milestone that ratio has crossed
    for i, m in enumerate(milestones):
        if i in state.milestones_hit:
            continue
        if ratio >= m.mult:
            return LadderAction(
                LadderActionType.SELL_PARTIAL,
                m.sell_pct_of_remaining,
                f"milestone_{m.mult:.0f}x_sell_{m.sell_pct_of_remaining:.0f}pct",
                milestone_index=i,
            )
        else:
            break   # milestones sorted ascending; no higher can be hit if this one isn't

    return LadderAction(LadderActionType.HOLD, 0.0, "hold")


def record_milestone_hit(
    state: LadderState,
    milestones: List[Milestone],
    milestone_index: int,
) -> None:
    """Call AFTER the partial sell tx confirms so we don't advance on failed sells.
    Ratchets floor upward and does NOT reset floor_armed if the previous floor was
    already armed — a new higher floor is auto-armed since peak has by definition
    already reached the milestone that just fired."""
    if milestone_index in state.milestones_hit:
        return
    state.milestones_hit.append(milestone_index)
    m = milestones[milestone_index]
    if state.current_floor is None or m.floor_after > state.current_floor:
        state.current_floor = m.floor_after
        # Do NOT clear floor_armed. evaluate_ladder will re-check on next tick
        # against the NEW floor; peak_ratio is already >= milestone.mult > new floor,
        # so arming happens on the very next evaluate call automatically.


DEFAULT_LADDER_CFG = "5:80:5,20:50:10,100:100:50"
DEFAULT_RUG_STOP = 0.5
