"""Optimal bet sizing based on card counting edge estimation.

Uses a combination of:
1. Kelly Criterion for bankroll-optimal bet sizing
2. True count to edge conversion
3. Risk-of-ruin management
"""

from __future__ import annotations

import math


# House edge with perfect basic strategy, 8 deck S17 ≈ 0.43%
BASE_HOUSE_EDGE = 0.0043

# Each point of true count shifts the edge by approximately 0.5%
TC_EDGE_PER_UNIT = 0.005

# Conservative Kelly fraction (full Kelly is too aggressive for most bankrolls)
# Quarter Kelly balances growth with risk of ruin
KELLY_FRACTION = 0.25


def player_edge(true_count: float) -> float:
    """Estimate player's edge given the current true count.

    Positive = player advantage, negative = house advantage.
    """
    return (true_count * TC_EDGE_PER_UNIT) - BASE_HOUSE_EDGE


def kelly_bet(
    true_count: float,
    bankroll: float,
    min_bet: float = 10.0,
    max_bet: float = 500.0,
    spread: float = 12.0,
    kelly_fraction: float = KELLY_FRACTION,
) -> float:
    """Calculate optimal bet size using Kelly Criterion.

    Args:
        true_count: Current Hi-Lo true count.
        bankroll: Current bankroll.
        min_bet: Table minimum bet.
        max_bet: Table maximum (or max you want to bet).
        spread: Maximum bet spread (max_bet / min_bet ratio limit).
        kelly_fraction: Fraction of Kelly to use (0.25 = quarter Kelly).

    Returns:
        Optimal bet amount.
    """
    edge = player_edge(true_count)

    if edge <= 0:
        # No edge — bet the minimum
        return min_bet

    # Kelly formula: f* = edge / variance
    # For blackjack, variance per hand ≈ 1.32
    variance = 1.32
    kelly_optimal = edge / variance
    bet = bankroll * kelly_optimal * kelly_fraction

    # Apply spread limit
    max_spread_bet = min_bet * spread

    # Clamp to table limits and spread
    bet = max(min_bet, min(bet, max_bet, max_spread_bet))

    # Round to nearest chip denomination
    bet = round(bet / 5) * 5
    bet = max(min_bet, bet)

    return bet


def bet_ramp(
    true_count: float,
    min_bet: float = 10.0,
    spread: float = 12.0,
) -> float:
    """Simple true count based bet ramp.

    More practical than pure Kelly for live play — easy to remember.

    TC <= 1: 1 unit (min bet)
    TC  2:   2 units
    TC  3:   4 units
    TC  4:   8 units
    TC  5+:  12 units (max spread)
    """
    tc = round(true_count)

    if tc <= 1:
        units = 1
    elif tc == 2:
        units = 2
    elif tc == 3:
        units = 4
    elif tc == 4:
        units = 8
    else:  # tc >= 5
        units = spread

    bet = min_bet * units
    return bet


def wonging_signal(true_count: float) -> str:
    """Wong in/out signals.

    Wonging = only playing when you have an edge (back-counting).

    Returns: 'play', 'leave', or 'sit_out'
    """
    if true_count >= 2:
        return "play"
    elif true_count >= 1:
        return "sit_out"  # Stay but don't bet (if possible)
    else:
        return "leave"


def risk_of_ruin(bankroll: float, min_bet: float, edge: float) -> float:
    """Estimate risk of ruin (probability of losing entire bankroll).

    Uses simplified formula for even-money bets.
    """
    if edge <= 0:
        return 1.0  # negative edge = will lose eventually
    # Approximate: RoR = ((1 - edge) / (1 + edge))^(bankroll / min_bet)
    ratio = (1 - edge) / (1 + edge)
    units = bankroll / min_bet
    return ratio ** units


def session_stop_loss(bankroll: float, fraction: float = 0.20) -> float:
    """Recommended stop-loss for a session.

    Losing this much in one session means conditions are bad — leave.
    Default: 20% of bankroll.
    """
    return bankroll * fraction


def session_win_goal(bankroll: float, fraction: float = 0.20) -> float:
    """Recommended win goal for a session.

    Locking in profits periodically prevents giving back gains.
    """
    return bankroll * fraction


class BetAdvisor:
    """Stateful bet advisor tracking session results."""

    def __init__(
        self,
        bankroll: float,
        min_bet: float = 10.0,
        max_bet: float = 500.0,
        spread: float = 12.0,
    ):
        self.initial_bankroll = bankroll
        self.bankroll = bankroll
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.spread = spread
        self.hands_played = 0
        self.hands_won = 0
        self.hands_lost = 0
        self.hands_pushed = 0
        self.net_profit = 0.0
        self.peak_bankroll = bankroll
        self.stop_loss = session_stop_loss(bankroll)
        self.win_goal = session_win_goal(bankroll)

    def recommend_bet(self, true_count: float) -> float:
        """Get recommended bet for current conditions."""
        return kelly_bet(
            true_count, self.bankroll,
            self.min_bet, self.max_bet, self.spread
        )

    def recommend_bet_simple(self, true_count: float) -> float:
        """Get bet using the simple ramp (easier for live play)."""
        return bet_ramp(true_count, self.min_bet, self.spread)

    def record_result(self, net: float):
        """Record hand result (positive = win, negative = loss, 0 = push)."""
        self.bankroll += net
        self.net_profit += net
        self.hands_played += 1
        if net > 0:
            self.hands_won += 1
        elif net < 0:
            self.hands_lost += 1
        else:
            self.hands_pushed += 1
        self.peak_bankroll = max(self.peak_bankroll, self.bankroll)

    @property
    def win_rate(self) -> float:
        if self.hands_played == 0:
            return 0.0
        return self.hands_won / self.hands_played

    @property
    def should_leave(self) -> bool:
        """Should the player leave this session?"""
        loss = self.initial_bankroll - self.bankroll
        return loss >= self.stop_loss

    @property
    def hit_win_goal(self) -> bool:
        """Has the player hit their win goal?"""
        return self.net_profit >= self.win_goal

    def status_line(self, true_count: float) -> str:
        """One-line session status."""
        edge = player_edge(true_count)
        bet = self.recommend_bet_simple(true_count)
        return (
            f"BR: ${self.bankroll:,.0f} | "
            f"Net: ${self.net_profit:+,.0f} | "
            f"W/L/P: {self.hands_won}/{self.hands_lost}/{self.hands_pushed} | "
            f"Edge: {edge:+.2%} | "
            f"Bet: ${bet:,.0f}"
        )
