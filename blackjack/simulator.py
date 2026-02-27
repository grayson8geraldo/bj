"""Monte Carlo blackjack simulator.

Simulates millions of hands to verify strategy performance with:
- Perfect basic strategy
- Hi-Lo card counting with deviations
- Optimal bet sizing

Usage: python -m blackjack.simulator [--hands N] [--shoes N]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass, field

from .cards import RANKS, RANK_VALUES, hand_value, is_soft, is_pair, is_blackjack
from .counting import CardCounter, HI_LO
from .strategy import get_action, should_take_insurance, basic_strategy
from .betting import player_edge, bet_ramp
from .cards import Shoe


@dataclass
class SimStats:
    """Simulation statistics."""
    hands_played: int = 0
    hands_won: int = 0
    hands_lost: int = 0
    hands_pushed: int = 0
    blackjacks: int = 0
    doubles_won: int = 0
    doubles_lost: int = 0
    splits: int = 0
    surrenders: int = 0
    insurance_taken: int = 0
    insurance_won: int = 0
    total_wagered: float = 0.0
    total_profit: float = 0.0
    peak_bankroll: float = 0.0
    min_bankroll: float = float("inf")
    bankroll_history: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.hands_played == 0:
            return 0.0
        return self.hands_won / self.hands_played

    @property
    def house_edge(self) -> float:
        if self.total_wagered == 0:
            return 0.0
        return -self.total_profit / self.total_wagered

    @property
    def ev_per_hand(self) -> float:
        if self.hands_played == 0:
            return 0.0
        return self.total_profit / self.hands_played


class BlackjackSimulator:
    """Full blackjack shoe simulator."""

    def __init__(
        self,
        num_decks: int = 8,
        penetration: float = 0.50,
        min_bet: float = 10.0,
        spread: float = 12.0,
        bankroll: float = 10000.0,
        use_counting: bool = True,
        use_deviations: bool = True,
        use_bet_spread: bool = True,
    ):
        self.num_decks = num_decks
        self.penetration = penetration  # fraction dealt before reshuffle
        self.min_bet = min_bet
        self.spread = spread
        self.initial_bankroll = bankroll
        self.use_counting = use_counting
        self.use_deviations = use_deviations
        self.use_bet_spread = use_bet_spread

    def _build_shoe(self) -> list[str]:
        """Build and shuffle a shoe."""
        shoe = []
        for _ in range(self.num_decks):
            for rank in RANKS:
                shoe.extend([rank] * 4)
        random.shuffle(shoe)
        return shoe

    def _deal_card(self, shoe_cards: list[str], counter: CardCounter) -> str:
        """Deal one card from shoe and count it."""
        card = shoe_cards.pop()
        counter.count_card(card)
        return card

    def _play_dealer(
        self, shoe_cards: list[str], counter: CardCounter, dealer_cards: list[str]
    ) -> int:
        """Play out dealer hand according to S17 rules."""
        while hand_value(dealer_cards) < 17:
            dealer_cards.append(self._deal_card(shoe_cards, counter))
        return hand_value(dealer_cards)

    def _play_hand(
        self,
        shoe_cards: list[str],
        counter: CardCounter,
        player_cards: list[str],
        dealer_up: str,
        tc: float,
        can_split: bool = True,
        depth: int = 0,
    ) -> list[tuple[list[str], float]]:
        """Play out a single player hand.

        Returns list of (final_cards, bet_multiplier) for each resulting hand.
        bet_multiplier: 1.0 normal, 2.0 doubled, 0.5 surrendered.
        """
        val = hand_value(player_cards)

        # Natural blackjack
        if is_blackjack(player_cards) and depth == 0:
            return [(player_cards, 1.0)]  # BJ payout handled separately

        can_double = len(player_cards) == 2 and len(shoe_cards) > 0
        can_surr = len(player_cards) == 2 and depth == 0
        can_spl = (
            can_split
            and is_pair(player_cards)
            and len(player_cards) == 2
            and depth < 4  # max 4 splits
            and len(shoe_cards) > 2
        )

        action, _ = get_action(
            player_cards, dealer_up, tc,
            can_double=can_double,
            can_surrender=can_surr,
            can_split=can_spl,
            use_deviations=self.use_deviations,
        )

        if action == "R":
            return [(player_cards, 0.5)]

        if action == "P" and can_spl:
            # Split
            results = []
            for card in player_cards:
                new_hand = [card]
                new_card = self._deal_card(shoe_cards, counter)
                new_hand.append(new_card)
                # After splitting aces, only one card
                if card == "A":
                    results.append((new_hand, 1.0))
                else:
                    sub = self._play_hand(
                        shoe_cards, counter, new_hand, dealer_up,
                        counter.tc, can_split=True, depth=depth + 1
                    )
                    results.extend(sub)
            return results

        if action == "D" and can_double:
            new_card = self._deal_card(shoe_cards, counter)
            player_cards.append(new_card)
            return [(player_cards, 2.0)]

        # Hit/Stand loop
        while action == "H" and val < 21 and len(shoe_cards) > 0:
            new_card = self._deal_card(shoe_cards, counter)
            player_cards.append(new_card)
            val = hand_value(player_cards)
            if val >= 21:
                break
            action, _ = get_action(
                player_cards, dealer_up, counter.tc,
                can_double=False, can_surrender=False, can_split=False,
                use_deviations=self.use_deviations,
            )

        return [(player_cards, 1.0)]

    def simulate(self, num_shoes: int = 1000, verbose: bool = False) -> SimStats:
        """Run simulation for given number of shoes."""
        stats = SimStats()
        bankroll = self.initial_bankroll
        stats.peak_bankroll = bankroll
        stats.min_bankroll = bankroll

        cut_card = int(self.num_decks * 52 * self.penetration)

        start_time = time.time()

        for shoe_num in range(num_shoes):
            shoe_cards = self._build_shoe()
            shoe = Shoe(self.num_decks)
            counter = CardCounter(shoe)

            # Deal until cut card
            while len(shoe_cards) > (self.num_decks * 52 - cut_card) and len(shoe_cards) > 10:
                tc = counter.tc if self.use_counting else 0

                # Determine bet
                if self.use_bet_spread and self.use_counting:
                    bet = bet_ramp(tc, self.min_bet, self.spread)
                else:
                    bet = self.min_bet

                # Deal initial cards
                player_cards = [
                    self._deal_card(shoe_cards, counter),
                    self._deal_card(shoe_cards, counter),
                ]
                dealer_cards = [
                    self._deal_card(shoe_cards, counter),
                    self._deal_card(shoe_cards, counter),
                ]
                dealer_up = dealer_cards[0]

                tc = counter.tc  # Update after dealing

                # Insurance
                insurance_profit = 0.0
                if dealer_up == "A" and self.use_counting:
                    if should_take_insurance(tc):
                        ins_bet = bet / 2
                        stats.insurance_taken += 1
                        if hand_value(dealer_cards) == 21:
                            insurance_profit = ins_bet * 2  # pays 2:1
                            stats.insurance_won += 1
                        else:
                            insurance_profit = -ins_bet

                # Check dealer blackjack
                dealer_bj = is_blackjack(dealer_cards)
                player_bj = is_blackjack(player_cards)

                if dealer_bj and player_bj:
                    # Push
                    stats.hands_played += 1
                    stats.hands_pushed += 1
                    bankroll += insurance_profit
                    stats.total_wagered += bet
                    continue
                elif dealer_bj:
                    stats.hands_played += 1
                    stats.hands_lost += 1
                    bankroll -= bet
                    bankroll += insurance_profit
                    stats.total_profit -= bet
                    stats.total_wagered += bet
                    continue
                elif player_bj:
                    # Blackjack pays 3:2
                    win = bet * 1.5
                    stats.hands_played += 1
                    stats.hands_won += 1
                    stats.blackjacks += 1
                    bankroll += win + insurance_profit
                    stats.total_profit += win
                    stats.total_wagered += bet
                    continue

                # Play player hand(s)
                results = self._play_hand(
                    shoe_cards, counter, player_cards, dealer_up, tc
                )

                # Check if all hands busted or surrendered
                all_done = all(
                    hand_value(cards) > 21 or mult == 0.5
                    for cards, mult in results
                )

                if not all_done and len(shoe_cards) > 0:
                    dealer_val = self._play_dealer(shoe_cards, counter, dealer_cards)
                else:
                    dealer_val = hand_value(dealer_cards)

                # Resolve each hand
                for cards, mult in results:
                    hand_bet = bet * mult
                    stats.total_wagered += hand_bet
                    stats.hands_played += 1

                    if mult == 0.5:
                        # Surrender
                        stats.surrenders += 1
                        stats.hands_lost += 1
                        bankroll -= hand_bet
                        stats.total_profit -= hand_bet
                        continue

                    pval = hand_value(cards)

                    if pval > 21:
                        # Bust
                        stats.hands_lost += 1
                        bankroll -= hand_bet
                        stats.total_profit -= hand_bet
                        if mult == 2.0:
                            stats.doubles_lost += 1
                    elif dealer_val > 21:
                        # Dealer bust
                        stats.hands_won += 1
                        bankroll += hand_bet
                        stats.total_profit += hand_bet
                        if mult == 2.0:
                            stats.doubles_won += 1
                    elif pval > dealer_val:
                        stats.hands_won += 1
                        bankroll += hand_bet
                        stats.total_profit += hand_bet
                        if mult == 2.0:
                            stats.doubles_won += 1
                    elif pval < dealer_val:
                        stats.hands_lost += 1
                        bankroll -= hand_bet
                        stats.total_profit -= hand_bet
                        if mult == 2.0:
                            stats.doubles_lost += 1
                    else:
                        stats.hands_pushed += 1

                bankroll += insurance_profit

                stats.peak_bankroll = max(stats.peak_bankroll, bankroll)
                stats.min_bankroll = min(stats.min_bankroll, bankroll)

            # Record bankroll at end of each shoe
            if shoe_num % 100 == 0:
                stats.bankroll_history.append(bankroll)

            # Progress
            if verbose and (shoe_num + 1) % (num_shoes // 10 or 1) == 0:
                elapsed = time.time() - start_time
                pct = (shoe_num + 1) / num_shoes * 100
                print(
                    f"  {pct:5.1f}% | "
                    f"Shoes: {shoe_num + 1:,} | "
                    f"Hands: {stats.hands_played:,} | "
                    f"Profit: ${stats.total_profit:+,.0f} | "
                    f"Bankroll: ${bankroll:,.0f} | "
                    f"Time: {elapsed:.1f}s"
                )

        stats.bankroll_history.append(bankroll)
        return stats


def print_results(stats: SimStats, label: str = ""):
    """Print formatted simulation results."""
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

    print(f"\n  Hands played:    {stats.hands_played:>12,}")
    print(f"  Hands won:       {stats.hands_won:>12,}  ({stats.win_rate:.2%})")
    print(f"  Hands lost:      {stats.hands_lost:>12,}")
    print(f"  Hands pushed:    {stats.hands_pushed:>12,}")
    print(f"  Blackjacks:      {stats.blackjacks:>12,}")
    print(f"  Doubles won:     {stats.doubles_won:>12,}")
    print(f"  Doubles lost:    {stats.doubles_lost:>12,}")
    print(f"  Surrenders:      {stats.surrenders:>12,}")
    print(f"  Insurance taken: {stats.insurance_taken:>12,}")
    print(f"  Insurance won:   {stats.insurance_won:>12,}")
    print(f"\n  Total wagered:   ${stats.total_wagered:>14,.0f}")
    sign = "+" if stats.total_profit >= 0 else ""
    print(f"  Total profit:    $ {sign}{stats.total_profit:>12,.0f}")
    print(f"  House edge:      {stats.house_edge:>14.4%}")
    ev_sign = "+" if stats.ev_per_hand >= 0 else ""
    print(f"  EV per hand:     $ {ev_sign}{stats.ev_per_hand:>12.4f}")
    print(f"\n  Peak bankroll:   ${stats.peak_bankroll:>14,.0f}")
    print(f"  Min bankroll:    ${stats.min_bankroll:>14,.0f}")
    print(f"  Final bankroll:  ${stats.bankroll_history[-1] if stats.bankroll_history else 0:>14,.0f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Blackjack Strategy Simulator")
    parser.add_argument("--shoes", type=int, default=10000,
                        help="Number of shoes to simulate (default: 10000)")
    parser.add_argument("--decks", type=int, default=8,
                        help="Number of decks (default: 8)")
    parser.add_argument("--penetration", type=float, default=0.50,
                        help="Deck penetration 0.0-1.0 (default: 0.50)")
    parser.add_argument("--min-bet", type=float, default=10.0,
                        help="Minimum bet (default: 10)")
    parser.add_argument("--spread", type=float, default=12.0,
                        help="Bet spread (default: 12)")
    parser.add_argument("--bankroll", type=float, default=10000.0,
                        help="Starting bankroll (default: 10000)")
    parser.add_argument("--compare", action="store_true",
                        help="Compare basic vs counting strategies")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  BLACKJACK STRATEGY SIMULATOR")
    print("  Monte Carlo Simulation Engine")
    print("=" * 60)
    print(f"\n  Config: {args.decks} decks, {args.penetration:.0%} penetration, "
          f"${args.min_bet:.0f} min bet, 1:{args.spread:.0f} spread")
    print(f"  Bankroll: ${args.bankroll:,.0f}")

    if args.compare:
        # Compare all strategy levels
        configs = [
            ("Basic Strategy Only (flat bet)", False, False, False),
            ("Basic + Counting (flat bet)", True, False, False),
            ("Basic + Counting + Deviations", True, True, False),
            ("Full: Count + Deviations + Bet Spread", True, True, True),
        ]

        for label, counting, devs, betting in configs:
            sim = BlackjackSimulator(
                num_decks=args.decks,
                penetration=args.penetration,
                min_bet=args.min_bet,
                spread=args.spread,
                bankroll=args.bankroll,
                use_counting=counting,
                use_deviations=devs,
                use_bet_spread=betting,
            )
            print(f"\n  Simulating: {label} ...")
            stats = sim.simulate(args.shoes, args.verbose)
            print_results(stats, label)

    else:
        sim = BlackjackSimulator(
            num_decks=args.decks,
            penetration=args.penetration,
            min_bet=args.min_bet,
            spread=args.spread,
            bankroll=args.bankroll,
        )
        print(f"\n  Simulating {args.shoes:,} shoes ...\n")
        stats = sim.simulate(args.shoes, args.verbose)
        print_results(stats, "Full Strategy: Count + Deviations + Bet Spread")


if __name__ == "__main__":
    main()
