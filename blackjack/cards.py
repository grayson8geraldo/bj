"""Card representation and shoe tracking."""

from __future__ import annotations

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

# Blackjack value of each rank (Ace handled separately)
RANK_VALUES: dict[str, int] = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10, "A": 11,
}

# Cards per single deck
CARDS_PER_DECK = 52


def hand_value(cards: list[str]) -> int:
    """Calculate best blackjack hand value.

    Returns the highest value <= 21 if possible, otherwise the bust value.
    """
    total = 0
    aces = 0
    for card in cards:
        v = RANK_VALUES[card]
        total += v
        if card == "A":
            aces += 1
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def is_soft(cards: list[str]) -> bool:
    """Return True if the hand is soft (contains an Ace counted as 11)."""
    total = 0
    aces = 0
    for card in cards:
        v = RANK_VALUES[card]
        total += v
        if card == "A":
            aces += 1
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    # Hand is soft if at least one ace is still counted as 11
    # Recalculate: total without any ace adjustment
    hard_total = sum(RANK_VALUES[c] for c in cards)
    aces_total = sum(1 for c in cards if c == "A")
    # Number of aces reduced
    reduced = 0
    t = hard_total
    while t > 21 and reduced < aces_total:
        t -= 10
        reduced += 1
    return reduced < aces_total and aces_total > 0


def is_pair(cards: list[str]) -> bool:
    """Return True if the hand is a splittable pair."""
    return len(cards) == 2 and RANK_VALUES[cards[0]] == RANK_VALUES[cards[1]]


def is_blackjack(cards: list[str]) -> bool:
    """Return True if the hand is a natural blackjack."""
    return len(cards) == 2 and hand_value(cards) == 21


class Shoe:
    """Tracks a multi-deck shoe for card counting."""

    def __init__(self, num_decks: int = 8):
        self.num_decks = num_decks
        self.reset()

    def reset(self):
        """Reset to a fresh shoe."""
        self.total_cards = self.num_decks * CARDS_PER_DECK
        self.seen: dict[str, int] = {r: 0 for r in RANKS}
        self.cards_seen = 0

    @property
    def cards_remaining(self) -> int:
        return self.total_cards - self.cards_seen

    @property
    def decks_remaining(self) -> float:
        return max(self.cards_remaining / CARDS_PER_DECK, 0.5)

    def card_seen(self, card: str):
        """Register that a card has been seen (dealt)."""
        self.seen[card] = self.seen.get(card, 0) + 1
        self.cards_seen += 1

    def cards_seen_list(self, cards: list[str]):
        """Register multiple cards seen."""
        for c in cards:
            self.card_seen(c)

    def remaining_of(self, rank: str) -> int:
        """How many of a specific rank remain in the shoe."""
        per_deck = 4  # 4 suits
        total = self.num_decks * per_deck
        return total - self.seen.get(rank, 0)

    @property
    def penetration(self) -> float:
        """Fraction of shoe dealt (0.0 to 1.0)."""
        return self.cards_seen / self.total_cards
