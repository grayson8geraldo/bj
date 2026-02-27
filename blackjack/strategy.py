"""Perfect basic strategy for 8-deck, dealer stands on all 17 (S17).

Also includes the Illustrious 18 index plays and Fab 4 surrender deviations
for Hi-Lo true count based decisions.

Action codes:
  H  = Hit
  S  = Stand
  D  = Double (hit if not allowed)
  Ds = Double (stand if not allowed)
  P  = Split
  Ph = Split if DAS allowed, else Hit
  Pd = Split if DAS allowed, else Double
  Rh = Surrender (hit if not allowed)
  Rs = Surrender (stand if not allowed)
  Rp = Surrender (split if not allowed)
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────
# BASIC STRATEGY TABLES — 8 deck, S17, DAS allowed
# Key: player total or hand description
# Value: dict mapping dealer upcard (2–A) to action
# ─────────────────────────────────────────────────────────

# Dealer up card index order: 2,3,4,5,6,7,8,9,10,A
_UP = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]


def _row(actions: str) -> dict[str, str]:
    """Parse a space-separated action row into {upcard: action}."""
    parts = actions.split()
    assert len(parts) == 10, f"Expected 10 actions, got {len(parts)}: {actions}"
    return dict(zip(_UP, parts))


# ── Hard totals ──────────────────────────────────────────
HARD: dict[int, dict[str, str]] = {
    # fmt: off
    5:  _row("H   H   H   H   H   H   H   H   H   H"),
    6:  _row("H   H   H   H   H   H   H   H   H   H"),
    7:  _row("H   H   H   H   H   H   H   H   H   H"),
    8:  _row("H   H   H   H   H   H   H   H   H   H"),
    9:  _row("H   D   D   D   D   H   H   H   H   H"),
    10: _row("D   D   D   D   D   D   D   D   H   H"),
    11: _row("D   D   D   D   D   D   D   D   D   D"),
    12: _row("H   H   S   S   S   H   H   H   H   H"),
    13: _row("S   S   S   S   S   H   H   H   H   H"),
    14: _row("S   S   S   S   S   H   H   H   H   H"),
    15: _row("S   S   S   S   S   H   H   H   Rh  Rh"),
    16: _row("S   S   S   S   S   H   H   Rh  Rh  Rh"),
    17: _row("S   S   S   S   S   S   S   S   S   Rs"),
    18: _row("S   S   S   S   S   S   S   S   S   S"),
    19: _row("S   S   S   S   S   S   S   S   S   S"),
    20: _row("S   S   S   S   S   S   S   S   S   S"),
    21: _row("S   S   S   S   S   S   S   S   S   S"),
    # fmt: on
}

# ── Soft totals (Ace counted as 11) ─────────────────────
SOFT: dict[int, dict[str, str]] = {
    # fmt: off
    13: _row("H   H   H   D   D   H   H   H   H   H"),   # A,2
    14: _row("H   H   H   D   D   H   H   H   H   H"),   # A,3
    15: _row("H   H   D   D   D   H   H   H   H   H"),   # A,4
    16: _row("H   H   D   D   D   H   H   H   H   H"),   # A,5
    17: _row("H   D   D   D   D   H   H   H   H   H"),   # A,6
    18: _row("Ds  Ds  Ds  Ds  Ds  S   S   H   H   H"),   # A,7
    19: _row("S   S   S   S   Ds  S   S   S   S   S"),   # A,8
    20: _row("S   S   S   S   S   S   S   S   S   S"),   # A,9
    21: _row("S   S   S   S   S   S   S   S   S   S"),   # A,10 (BJ handled separately)
    # fmt: on
}

# ── Pair splitting ───────────────────────────────────────
# Key is the card rank in the pair
PAIRS: dict[str, dict[str, str]] = {
    # fmt: off
    "2":  _row("Ph  Ph  P   P   P   P   H   H   H   H"),
    "3":  _row("Ph  Ph  P   P   P   P   H   H   H   H"),
    "4":  _row("H   H   H   Ph  Ph  H   H   H   H   H"),
    "5":  _row("D   D   D   D   D   D   D   D   H   H"),  # Never split 5s
    "6":  _row("Ph  P   P   P   P   H   H   H   H   H"),
    "7":  _row("P   P   P   P   P   P   H   H   H   H"),
    "8":  _row("P   P   P   P   P   P   P   P   P   Rp"),
    "9":  _row("P   P   P   P   P   S   P   P   S   S"),
    "10": _row("S   S   S   S   S   S   S   S   S   S"),  # Never split 10s
    "A":  _row("P   P   P   P   P   P   P   P   P   P"),  # Always split Aces
    # fmt: on
}

# Map face cards to their pair key
_PAIR_KEY = {"J": "10", "Q": "10", "K": "10"}


def _normalize_upcard(card: str) -> str:
    """Normalize dealer upcard for table lookup."""
    if card in ("J", "Q", "K"):
        return "10"
    return card


def basic_strategy(
    player_cards: list[str],
    dealer_upcard: str,
    can_double: bool = True,
    can_surrender: bool = True,
    can_split: bool = True,
    das_allowed: bool = True,
) -> str:
    """Return the optimal basic strategy action.

    Returns one of: 'H', 'S', 'D', 'P', 'R' (surrender).
    """
    from .cards import hand_value, is_soft, is_pair, RANK_VALUES

    up = _normalize_upcard(dealer_upcard)
    total = hand_value(player_cards)

    # Check pair splitting first
    if can_split and is_pair(player_cards) and len(player_cards) == 2:
        pair_key = _PAIR_KEY.get(player_cards[0], player_cards[0])
        if pair_key in PAIRS:
            action = PAIRS[pair_key][up]
            if action == "P":
                return "P"
            elif action == "Ph":
                return "P" if das_allowed else "H"
            elif action == "Pd":
                return "P" if das_allowed else ("D" if can_double else "H")
            elif action == "Rp":
                return "R" if can_surrender else "P"
            # else fall through to hard/soft

    # Check soft hands
    if is_soft(player_cards) and total in SOFT:
        action = SOFT[total][up]
    elif total in HARD:
        action = HARD[total][up]
    else:
        # Fallback: total < 5 always hit
        return "H"

    # Resolve conditional actions
    if action == "D":
        return "D" if can_double else "H"
    elif action == "Ds":
        return "D" if can_double else "S"
    elif action == "Rh":
        return "R" if can_surrender else "H"
    elif action == "Rs":
        return "R" if can_surrender else "S"
    elif action == "Rp":
        return "R" if can_surrender else "P"
    else:
        return action


# ─────────────────────────────────────────────────────────
# ILLUSTRIOUS 18 — True count index deviations
# These are the most profitable deviations from basic strategy
# based on the Hi-Lo true count.
#
# Format: (player_hand_description, dealer_upcard, tc_threshold, action_if_true, action_if_false)
# "If TC >= threshold, do action_if_true; else do action_if_false"
# ─────────────────────────────────────────────────────────

class Deviation:
    """A true-count based deviation from basic strategy."""
    __slots__ = ("desc", "player_total", "is_soft_hand", "is_pair_hand",
                 "dealer_up", "tc_threshold", "action_above", "action_below",
                 "direction")

    def __init__(self, desc: str, player_total: int, dealer_up: str,
                 tc_threshold: float, action_above: str, action_below: str,
                 is_soft: bool = False, is_pair: bool = False,
                 direction: str = ">="):
        self.desc = desc
        self.player_total = player_total
        self.is_soft_hand = is_soft
        self.is_pair_hand = is_pair
        self.dealer_up = dealer_up
        self.tc_threshold = tc_threshold
        self.action_above = action_above
        self.action_below = action_below
        self.direction = direction  # ">=" or "<="


# Illustrious 18 (most valuable count-based plays)
ILLUSTRIOUS_18: list[Deviation] = [
    # 1. Insurance — take at TC >= +3
    Deviation("Insurance", 0, "A", 3, "insure", "no_insure"),

    # 2. 16 vs 10 — Stand at TC >= 0 (instead of hit)
    Deviation("16 vs 10", 16, "10", 0, "S", "H"),

    # 3. 15 vs 10 — Stand at TC >= +4
    Deviation("15 vs 10", 15, "10", 4, "S", "H"),

    # 4. 10,10 vs 5 — Split at TC >= +5
    Deviation("20 vs 5 split", 20, "5", 5, "P", "S", is_pair=True),

    # 5. 10,10 vs 6 — Split at TC >= +4
    Deviation("20 vs 6 split", 20, "6", 4, "P", "S", is_pair=True),

    # 6. 10 vs 10 — Double at TC >= +4
    Deviation("10 vs 10", 10, "10", 4, "D", "H"),

    # 7. 12 vs 3 — Stand at TC >= +2
    Deviation("12 vs 3", 12, "3", 2, "S", "H"),

    # 8. 12 vs 2 — Stand at TC >= +3
    Deviation("12 vs 2", 12, "2", 3, "S", "H"),

    # 9. 11 vs A — Double at TC >= +1
    Deviation("11 vs A", 11, "A", 1, "D", "H"),

    # 10. 9 vs 2 — Double at TC >= +1
    Deviation("9 vs 2", 9, "2", 1, "D", "H"),

    # 11. 10 vs A — Double at TC >= +4
    Deviation("10 vs A", 10, "A", 4, "D", "H"),

    # 12. 9 vs 7 — Double at TC >= +3
    Deviation("9 vs 7", 9, "7", 3, "D", "H"),

    # 13. 16 vs 9 — Stand at TC >= +5
    Deviation("16 vs 9", 16, "9", 5, "S", "H"),

    # 14. 13 vs 2 — Stand at TC >= -1 (hit below)
    Deviation("13 vs 2", 13, "2", -1, "S", "H"),

    # 15. 12 vs 4 — Stand at TC >= 0
    Deviation("12 vs 4", 12, "4", 0, "S", "H"),

    # 16. 12 vs 5 — Stand at TC >= -2
    Deviation("12 vs 5", 12, "5", -2, "S", "H"),

    # 17. 12 vs 6 — Stand at TC >= -1
    Deviation("12 vs 6", 12, "6", -1, "S", "H"),

    # 18. 13 vs 3 — Stand at TC >= -2
    Deviation("13 vs 3", 13, "3", -2, "S", "H"),
]

# Fab 4 surrender deviations
FAB_4_SURRENDER: list[Deviation] = [
    # 1. 14 vs 10 — Surrender at TC >= +3
    Deviation("14 vs 10 surrender", 14, "10", 3, "R", "H"),

    # 2. 15 vs 10 — Surrender at TC >= 0
    Deviation("15 vs 10 surrender", 15, "10", 0, "R", "H"),

    # 3. 15 vs 9 — Surrender at TC >= +2
    Deviation("15 vs 9 surrender", 15, "9", 2, "R", "H"),

    # 4. 15 vs A — Surrender at TC >= +1
    Deviation("15 vs A surrender", 15, "A", 1, "R", "S"),
]

ALL_DEVIATIONS = ILLUSTRIOUS_18 + FAB_4_SURRENDER


def check_deviations(
    player_cards: list[str],
    dealer_upcard: str,
    true_count: float,
    is_pair_hand: bool = False,
) -> str | None:
    """Check if any deviation applies.

    Returns the deviation action if one matches, or None to use basic strategy.
    """
    from .cards import hand_value, is_soft as _is_soft

    total = hand_value(player_cards)
    soft = _is_soft(player_cards)
    up = _normalize_upcard(dealer_upcard)

    for dev in ALL_DEVIATIONS:
        if dev.dealer_up != up:
            continue
        if dev.player_total != total:
            continue
        if dev.is_pair_hand and not is_pair_hand:
            continue
        if dev.is_soft_hand and not soft:
            continue

        if dev.direction == ">=":
            if true_count >= dev.tc_threshold:
                return dev.action_above
            else:
                return dev.action_below
        else:  # "<="
            if true_count <= dev.tc_threshold:
                return dev.action_above
            else:
                return dev.action_below

    return None


def get_action(
    player_cards: list[str],
    dealer_upcard: str,
    true_count: float,
    can_double: bool = True,
    can_surrender: bool = True,
    can_split: bool = True,
    das_allowed: bool = True,
    use_deviations: bool = True,
) -> tuple[str, str]:
    """Get optimal action considering both basic strategy and deviations.

    Returns (action, reason) where reason is 'basic' or 'deviation: ...'.
    """
    from .cards import is_pair as _is_pair

    pair = _is_pair(player_cards) and can_split

    # Check deviations first
    if use_deviations:
        dev_action = check_deviations(player_cards, dealer_upcard, true_count, pair)
        if dev_action is not None:
            # Validate the action is available
            if dev_action == "D" and not can_double:
                dev_action = "H"
            elif dev_action == "R" and not can_surrender:
                dev_action = "H"
            elif dev_action == "P" and not can_split:
                dev_action = "S"
            return dev_action, "deviation"

    # Fall back to basic strategy
    action = basic_strategy(
        player_cards, dealer_upcard, can_double, can_surrender, can_split, das_allowed
    )
    return action, "basic"


def should_take_insurance(true_count: float) -> bool:
    """Insurance is profitable when TC >= +3."""
    return true_count >= 3.0


ACTION_NAMES = {
    "H": "HIT",
    "S": "STAND",
    "D": "DOUBLE DOWN",
    "P": "SPLIT",
    "R": "SURRENDER",
}
