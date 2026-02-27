"""Card counting systems for blackjack."""

from __future__ import annotations

from .cards import Shoe

# Hi-Lo count values
HI_LO: dict[str, int] = {
    "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,   # low cards: +1
    "7": 0, "8": 0, "9": 0,                      # neutral: 0
    "10": -1, "J": -1, "Q": -1, "K": -1, "A": -1,  # high cards: -1
}

# Omega II (more accurate, harder to use)
OMEGA_II: dict[str, int] = {
    "2": 1, "3": 1, "4": 2, "5": 2, "6": 2,
    "7": 1, "8": 0, "9": -1,
    "10": -2, "J": -2, "Q": -2, "K": -2, "A": 0,
}

# Zen Count
ZEN: dict[str, int] = {
    "2": 1, "3": 1, "4": 2, "5": 2, "6": 2,
    "7": 1, "8": 0, "9": 0,
    "10": -2, "J": -2, "Q": -2, "K": -2, "A": -1,
}


class CardCounter:
    """Multi-system card counter tied to a shoe."""

    def __init__(self, shoe: Shoe):
        self.shoe = shoe
        self.running_count_hilo = 0
        self.running_count_omega = 0
        self.running_count_zen = 0
        # Side count of aces (important for insurance & play decisions)
        self.aces_seen = 0

    def count_card(self, card: str):
        """Update all counts when a card is seen."""
        self.shoe.card_seen(card)
        self.running_count_hilo += HI_LO.get(card, 0)
        self.running_count_omega += OMEGA_II.get(card, 0)
        self.running_count_zen += ZEN.get(card, 0)
        if card == "A":
            self.aces_seen += 1

    def count_cards(self, cards: list[str]):
        """Count multiple cards."""
        for c in cards:
            self.count_card(c)

    @property
    def true_count_hilo(self) -> float:
        """Hi-Lo true count = running count / decks remaining."""
        return self.running_count_hilo / self.shoe.decks_remaining

    @property
    def true_count_omega(self) -> float:
        """Omega II true count."""
        return self.running_count_omega / self.shoe.decks_remaining

    @property
    def true_count_zen(self) -> float:
        """Zen true count."""
        return self.running_count_zen / self.shoe.decks_remaining

    # Convenience alias — primary system is Hi-Lo
    @property
    def tc(self) -> float:
        return self.true_count_hilo

    @property
    def rc(self) -> int:
        return self.running_count_hilo

    @property
    def expected_aces_remaining(self) -> float:
        """How many aces we'd expect to remain vs actual."""
        total_aces = self.shoe.num_decks * 4
        remaining = total_aces - self.aces_seen
        return remaining

    @property
    def ace_richness(self) -> float:
        """Ratio of actual aces remaining vs expected proportion.

        > 1.0 means the remaining shoe is ace-rich.
        """
        cards_rem = self.shoe.cards_remaining
        if cards_rem == 0:
            return 1.0
        expected = cards_rem * (4 / 52)  # expected aces per card remaining
        actual = self.expected_aces_remaining
        if expected == 0:
            return 1.0
        return actual / expected

    def reset(self):
        """Reset for a new shoe."""
        self.shoe.reset()
        self.running_count_hilo = 0
        self.running_count_omega = 0
        self.running_count_zen = 0
        self.aces_seen = 0
