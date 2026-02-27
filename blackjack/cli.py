"""Interactive CLI advisor for live blackjack play.

Usage: python -m blackjack.cli
"""

from __future__ import annotations

import sys
import os

from .cards import Shoe, hand_value, is_soft, is_pair, is_blackjack, RANK_VALUES, RANKS
from .counting import CardCounter
from .strategy import (
    get_action, should_take_insurance, ACTION_NAMES, basic_strategy
)
from .betting import BetAdvisor, player_edge, wonging_signal


# ─── ANSI colors ─────────────────────────────────────────
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def color_action(action: str) -> str:
    """Colorize an action for display."""
    colors = {
        "H": YELLOW,
        "S": GREEN,
        "D": MAGENTA,
        "P": CYAN,
        "R": RED,
    }
    name = ACTION_NAMES.get(action, action)
    c = colors.get(action, "")
    return f"{c}{BOLD}{name}{RESET}"


def color_tc(tc: float) -> str:
    """Colorize true count."""
    if tc >= 3:
        return f"{GREEN}{BOLD}{tc:+.1f}{RESET}"
    elif tc >= 1:
        return f"{GREEN}{tc:+.1f}{RESET}"
    elif tc >= 0:
        return f"{YELLOW}{tc:+.1f}{RESET}"
    elif tc >= -2:
        return f"{RED}{tc:+.1f}{RESET}"
    else:
        return f"{RED}{BOLD}{tc:+.1f}{RESET}"


def parse_card(s: str) -> str | None:
    """Parse a card input string to a standard rank.

    Accepts: 2-10, J, Q, K, A (case insensitive), T=10
    """
    s = s.strip().upper()
    if s == "T":
        return "10"
    if s in RANK_VALUES:
        return s
    # Handle "10" already in RANK_VALUES
    return None


def parse_cards(s: str) -> list[str] | None:
    """Parse multiple cards from a comma/space separated string."""
    # Split on any combination of commas, spaces
    parts = s.replace(",", " ").split()
    cards = []
    for p in parts:
        c = parse_card(p)
        if c is None:
            return None
        cards.append(c)
    return cards


def print_header():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  BLACKJACK ADVISOR — 8 Deck, S17{RESET}")
    print(f"{BOLD}{CYAN}  Hi-Lo Count | Illustrious 18 | Kelly Criterion{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


def print_help():
    print(f"""
{BOLD}Card Input:{RESET}
  Cards: 2-9, T/10, J, Q, K, A  (case insensitive)
  Multiple: separate with spaces or commas (e.g., "5 K" or "A,7")

{BOLD}Commands:{RESET}
  {CYAN}n/new{RESET}      — New hand (enter player cards + dealer upcard)
  {CYAN}c/count{RESET}    — Enter cards seen (burned, other players' cards, etc.)
  {CYAN}h/hit{RESET}      — Player took a hit (enter the new card)
  {CYAN}r/result{RESET}   — Record hand result (win/loss/push amount)
  {CYAN}s/status{RESET}   — Show current count and session stats
  {CYAN}shoe{RESET}       — Reset shoe (new shuffle)
  {CYAN}b/bet{RESET}      — Show recommended bet
  {CYAN}w/wong{RESET}     — Wong in/out signal
  {CYAN}i/insurance{RESET}— Should I take insurance?
  {CYAN}stats{RESET}      — Detailed session statistics
  {CYAN}help{RESET}       — Show this help
  {CYAN}q/quit{RESET}     — Exit
""")


def prompt(msg: str = "") -> str:
    try:
        return input(f"{DIM}>{RESET} {msg}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def main():
    print_header()

    # Setup
    num_decks = 8
    shoe = Shoe(num_decks)
    counter = CardCounter(shoe)

    # Get bankroll
    print(f"{BOLD}Session Setup:{RESET}")
    br_input = prompt("Bankroll (default $1000): ")
    bankroll = float(br_input) if br_input else 1000.0

    min_input = prompt("Min bet (default $10): ")
    min_bet = float(min_input) if min_input else 10.0

    max_input = prompt("Max bet (default $500): ")
    max_bet = float(max_input) if max_input else 500.0

    advisor = BetAdvisor(bankroll, min_bet, max_bet)

    print(f"\n{GREEN}Ready! Type 'help' for commands.{RESET}")
    print(f"{DIM}Shoe: {num_decks} decks | Bankroll: ${bankroll:,.0f} | "
          f"Spread: 1-{advisor.spread:.0f}{RESET}\n")

    current_player_cards: list[str] = []
    current_dealer_up: str = ""
    in_hand = False

    while True:
        # Show count in prompt
        tc = counter.tc
        rc = counter.rc
        pen = shoe.penetration
        edge = player_edge(tc)

        status = (
            f"{DIM}[RC:{rc:+d} TC:{color_tc(tc)} "
            f"Pen:{pen:.0%} Edge:{edge:+.2%}]{RESET} "
        )
        sys.stdout.write(status)
        cmd = prompt()

        if not cmd:
            continue

        cmd_lower = cmd.lower().split()[0]
        args = cmd[len(cmd_lower):].strip()

        # ── New hand ──
        if cmd_lower in ("n", "new"):
            if not args:
                p = prompt("Your cards (e.g. 'A 7'): ")
                d = prompt("Dealer upcard (e.g. '6'): ")
            else:
                parts = args.split("/")
                if len(parts) == 2:
                    p, d = parts[0].strip(), parts[1].strip()
                else:
                    p = args
                    d = prompt("Dealer upcard: ")

            player = parse_cards(p)
            dealer = parse_card(d)

            if player is None or dealer is None:
                print(f"{RED}Invalid card input. Use: 2-9, T/10, J, Q, K, A{RESET}")
                continue

            current_player_cards = player
            current_dealer_up = dealer
            in_hand = True

            # Count all visible cards
            counter.count_cards(player)
            counter.count_card(dealer)

            # Update TC after counting
            tc = counter.tc

            # Check for blackjack
            if is_blackjack(player):
                print(f"\n  {GREEN}{BOLD}*** BLACKJACK! ***{RESET}")
                in_hand = False
                continue

            # Check insurance
            if dealer == "A":
                ins = should_take_insurance(tc)
                if ins:
                    print(f"\n  {MAGENTA}{BOLD}>>> TAKE INSURANCE (TC={tc:+.1f} >= +3) <<<{RESET}")
                else:
                    print(f"\n  {DIM}Insurance: NO (TC={tc:+.1f} < +3){RESET}")

            # Get advice
            val = hand_value(player)
            soft = is_soft(player)
            hand_desc = f"{'Soft ' if soft else ''}{val}"

            can_double = len(player) == 2
            can_split = is_pair(player) and len(player) == 2
            can_surrender = len(player) == 2

            action, reason = get_action(
                player, dealer, tc,
                can_double=can_double,
                can_surrender=can_surrender,
                can_split=can_split,
            )

            reason_str = f" {DIM}({reason}){RESET}" if reason == "deviation" else ""

            print(f"\n  Hand: {BOLD}{hand_desc}{RESET} vs Dealer {BOLD}{dealer}{RESET}")
            print(f"  Action: {color_action(action)}{reason_str}")

            # If deviation, also show basic strategy for reference
            if reason == "deviation":
                bs = basic_strategy(player, dealer, can_double, can_surrender, can_split)
                print(f"  {DIM}(Basic strategy would be: {ACTION_NAMES.get(bs, bs)}){RESET}")

            print()

        # ── Hit (new card drawn) ──
        elif cmd_lower in ("h", "hit"):
            if not in_hand:
                print(f"{YELLOW}No active hand. Use 'n' to start a new hand.{RESET}")
                continue

            card_str = args or prompt("Card drawn: ")
            card = parse_card(card_str)
            if card is None:
                print(f"{RED}Invalid card.{RESET}")
                continue

            current_player_cards.append(card)
            counter.count_card(card)
            tc = counter.tc

            val = hand_value(current_player_cards)
            soft = is_soft(current_player_cards)
            hand_desc = f"{'Soft ' if soft else ''}{val}"

            if val > 21:
                print(f"\n  {RED}{BOLD}BUST — {val}{RESET}")
                in_hand = False
                continue

            if val == 21:
                print(f"\n  {GREEN}{BOLD}21! Stand.{RESET}")
                in_hand = False
                continue

            # Can't double/split/surrender after hitting
            action, reason = get_action(
                current_player_cards, current_dealer_up, tc,
                can_double=False, can_surrender=False, can_split=False,
            )
            reason_str = f" {DIM}({reason}){RESET}" if reason == "deviation" else ""

            print(f"\n  Hand: {BOLD}{hand_desc}{RESET} vs Dealer {BOLD}{current_dealer_up}{RESET}")
            print(f"  Action: {color_action(action)}{reason_str}")
            print()

        # ── Count additional cards ──
        elif cmd_lower in ("c", "count"):
            card_str = args or prompt("Cards seen (e.g. '5 K 3 7'): ")
            cards = parse_cards(card_str)
            if cards is None:
                print(f"{RED}Invalid cards.{RESET}")
                continue
            counter.count_cards(cards)
            print(f"  {DIM}Counted {len(cards)} cards.{RESET}")

        # ── Record result ──
        elif cmd_lower in ("r", "result"):
            amount_str = args or prompt("Net result (e.g. '+10', '-25', '0' for push): ")
            try:
                amount = float(amount_str.replace("$", "").replace(",", ""))
            except ValueError:
                print(f"{RED}Invalid amount.{RESET}")
                continue
            advisor.record_result(amount)
            in_hand = False
            color = GREEN if amount > 0 else (RED if amount < 0 else YELLOW)
            print(f"  {color}Result: ${amount:+,.0f} | Bankroll: ${advisor.bankroll:,.0f}{RESET}")

            if advisor.should_leave:
                print(f"\n  {RED}{BOLD}⚠ STOP LOSS HIT — Consider leaving!{RESET}")
            elif advisor.hit_win_goal:
                print(f"\n  {GREEN}{BOLD}✓ WIN GOAL reached — Consider locking profits!{RESET}")

        # ── Count dealer cards at end of hand ──
        elif cmd_lower in ("d", "dealer"):
            card_str = args or prompt("Dealer's revealed cards: ")
            cards = parse_cards(card_str)
            if cards is None:
                print(f"{RED}Invalid cards.{RESET}")
                continue
            counter.count_cards(cards)
            print(f"  {DIM}Counted dealer cards.{RESET}")

        # ── Status ──
        elif cmd_lower in ("s", "status"):
            tc = counter.tc
            print(f"\n  {BOLD}Count:{RESET}")
            print(f"    Running Count: {rc:+d}")
            print(f"    True Count:    {color_tc(tc)}")
            print(f"    Decks Left:    {shoe.decks_remaining:.1f}")
            print(f"    Penetration:   {shoe.penetration:.0%}")
            print(f"    Cards Seen:    {shoe.cards_seen}/{shoe.total_cards}")
            print(f"\n  {BOLD}Edge & Bet:{RESET}")
            edge = player_edge(tc)
            bet = advisor.recommend_bet_simple(tc)
            print(f"    Player Edge:   {edge:+.2%}")
            print(f"    Recommended:   ${bet:,.0f}")
            wong = wonging_signal(tc)
            wong_colors = {"play": GREEN, "sit_out": YELLOW, "leave": RED}
            print(f"    Wong Signal:   {wong_colors[wong]}{wong.upper()}{RESET}")
            print()

        # ── Bet recommendation ──
        elif cmd_lower in ("b", "bet"):
            tc = counter.tc
            bet_simple = advisor.recommend_bet_simple(tc)
            bet_kelly = advisor.recommend_bet(tc)
            edge = player_edge(tc)
            print(f"\n  {BOLD}Bet Recommendation:{RESET}")
            print(f"    True Count:   {color_tc(tc)}")
            print(f"    Player Edge:  {edge:+.2%}")
            print(f"    Ramp Bet:     {BOLD}${bet_simple:,.0f}{RESET}")
            print(f"    Kelly Bet:    ${bet_kelly:,.0f}")
            print(f"    {DIM}(Ramp is simpler for live play){RESET}")
            print()

        # ── Wong signal ──
        elif cmd_lower in ("w", "wong"):
            tc = counter.tc
            signal = wonging_signal(tc)
            colors = {"play": GREEN, "sit_out": YELLOW, "leave": RED}
            msgs = {
                "play": "PLAY — You have an edge!",
                "sit_out": "SIT OUT — Marginal, wait for better count",
                "leave": "LEAVE — House has the edge",
            }
            print(f"\n  {colors[signal]}{BOLD}{msgs[signal]}{RESET} (TC={tc:+.1f})\n")

        # ── Insurance ──
        elif cmd_lower in ("i", "insurance"):
            tc = counter.tc
            ins = should_take_insurance(tc)
            if ins:
                print(f"\n  {GREEN}{BOLD}YES — Take Insurance (TC={tc:+.1f} >= +3){RESET}\n")
            else:
                print(f"\n  {RED}NO — Skip Insurance (TC={tc:+.1f} < +3){RESET}\n")

        # ── New shoe ──
        elif cmd_lower == "shoe":
            counter.reset()
            in_hand = False
            print(f"\n  {CYAN}Shoe reset — new shuffle.{RESET}\n")

        # ── Detailed stats ──
        elif cmd_lower == "stats":
            print(f"\n  {BOLD}Session Statistics:{RESET}")
            print(f"    Hands Played:   {advisor.hands_played}")
            print(f"    Won:            {advisor.hands_won}")
            print(f"    Lost:           {advisor.hands_lost}")
            print(f"    Pushed:         {advisor.hands_pushed}")
            if advisor.hands_played > 0:
                print(f"    Win Rate:       {advisor.win_rate:.1%}")
            print(f"    Net Profit:     ${advisor.net_profit:+,.0f}")
            print(f"    Bankroll:       ${advisor.bankroll:,.0f}")
            print(f"    Peak Bankroll:  ${advisor.peak_bankroll:,.0f}")
            print(f"    Stop Loss at:   ${advisor.initial_bankroll - advisor.stop_loss:,.0f}")
            print(f"    Win Goal at:    ${advisor.initial_bankroll + advisor.win_goal:,.0f}")
            print()

        # ── Help ──
        elif cmd_lower == "help":
            print_help()

        # ── Quit ──
        elif cmd_lower in ("q", "quit", "exit"):
            print(f"\n{BOLD}Final stats:{RESET}")
            print(f"  Hands: {advisor.hands_played} | "
                  f"Net: ${advisor.net_profit:+,.0f} | "
                  f"Bankroll: ${advisor.bankroll:,.0f}")
            print(f"\n{DIM}Good luck!{RESET}\n")
            break

        # ── Quick card input — just type the card rank ──
        else:
            # Try to parse as cards to count
            cards = parse_cards(cmd)
            if cards is not None:
                counter.count_cards(cards)
                tc = counter.tc
                print(f"  {DIM}Counted: {' '.join(cards)} | "
                      f"RC={counter.rc:+d} TC={tc:+.1f}{RESET}")
            else:
                print(f"{RED}Unknown command. Type 'help' for help.{RESET}")


if __name__ == "__main__":
    main()
