"""Shuffle Tracking for hand-shuffled shoes.

When a dealer uses riffle shuffles, cards are not fully randomized.
Zones of high/low count cards maintain partial structure through the shuffle.

Technique:
1. Divide the dealt shoe into ZONES (segments of ~1 deck each)
2. Track the running count of EACH zone separately
3. Observe the dealer's shuffle routine (how zones are interleaved)
4. After the shuffle, predict which sections of the new shoe are
   "ten-rich" (favorable) or "ten-poor" (unfavorable)
5. Bet big when playing through a predicted favorable zone

This module implements zone tracking and riffle shuffle mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from .counting import HI_LO


@dataclass
class Zone:
    """A segment of the shoe during play."""
    index: int
    cards: list[str] = field(default_factory=list)
    running_count: int = 0

    @property
    def size(self) -> int:
        return len(self.cards)

    @property
    def count_per_card(self) -> float:
        """Count density — how rich/poor this zone is."""
        if self.size == 0:
            return 0.0
        return self.running_count / self.size

    def add_card(self, card: str):
        self.cards.append(card)
        self.running_count += HI_LO.get(card, 0)

    @property
    def is_favorable(self) -> bool:
        """Negative RC = lots of high cards were dealt FROM this zone.
        But for shuffle tracking we care about what REMAINS after
        these cards mixed — a zone that was very negative means
        it had lots of high cards, which after riffle will still
        partially cluster."""
        return self.running_count < -2

    @property
    def is_unfavorable(self) -> bool:
        return self.running_count > 2

    def summary(self) -> str:
        rc = self.running_count
        density = self.count_per_card
        if rc < -2:
            quality = "TEN-RICH"
        elif rc > 2:
            quality = "ten-poor"
        else:
            quality = "neutral"
        return (f"Zone {self.index}: {self.size:3d} cards | "
                f"RC={rc:+3d} | density={density:+.2f} | {quality}")


class RiffleModel:
    """Models a single riffle shuffle interleave.

    A riffle takes two halves and interleaves them.
    The 'quality' parameter controls how perfect the riffle is:
    - quality=1.0: perfect alternating (one from each half) — most mixing
    - quality=0.5: average hand riffle — clumps of 1-3 cards
    - quality=0.3: sloppy riffle — clumps of 2-5 cards stay together

    For prediction, we model that after a riffle, adjacent zones
    from the two halves become interleaved but partially retain
    their character.
    """

    def __init__(self, quality: float = 0.5):
        self.quality = min(max(quality, 0.0), 1.0)

    @property
    def retention(self) -> float:
        """How much of the original zone character is retained.

        Lower quality riffle = higher retention of zone structure.
        """
        return 1.0 - self.quality


@dataclass
class ShuffleStep:
    """One step in the dealer's shuffle procedure.

    type: 'riffle', 'strip', or 'cut'
    For riffle: top_zones and bottom_zones are merged
    For strip: zones are reordered
    For cut: the cut point shifts zone order
    """
    step_type: str  # 'riffle', 'strip', 'cut'
    # Which zone indices are in top half vs bottom half (for riffle)
    top_zones: list[int] = field(default_factory=list)
    bottom_zones: list[int] = field(default_factory=list)
    # For strip/cut
    details: str = ""


class ShuffleTracker:
    """Main shuffle tracking engine.

    Tracks cards dealt in zones, then maps zones through the
    observed shuffle procedure to predict favorable/unfavorable
    sections of the new shoe.
    """

    def __init__(self, num_decks: int = 8, cards_per_zone: int = 52):
        self.num_decks = num_decks
        self.cards_per_zone = cards_per_zone  # ~1 deck per zone
        self.zones: list[Zone] = [Zone(index=0)]
        self.current_zone_index = 0
        self.total_cards = 0
        self.shuffle_procedure: list[ShuffleStep] = []
        self.post_shuffle_predictions: list[ZonePrediction] = []
        self._finalized = False

    @property
    def current_zone(self) -> Zone:
        return self.zones[self.current_zone_index]

    @property
    def num_zones(self) -> int:
        return len(self.zones)

    def add_card(self, card: str):
        """Add a card to the current zone."""
        if self._finalized:
            return
        self.current_zone.add_card(card)
        self.total_cards += 1

        # Start a new zone when current one fills up
        if self.current_zone.size >= self.cards_per_zone:
            new_zone = Zone(index=self.current_zone_index + 1)
            self.zones.append(new_zone)
            self.current_zone_index += 1

    def add_cards(self, cards: list[str]):
        for c in cards:
            self.add_card(c)

    def force_new_zone(self):
        """Manually mark start of a new zone (e.g. new round boundary)."""
        if self._finalized:
            return
        if self.current_zone.size > 0:
            new_zone = Zone(index=self.current_zone_index + 1)
            self.zones.append(new_zone)
            self.current_zone_index += 1

    def finalize_shoe(self):
        """Mark the shoe as complete, ready for shuffle analysis."""
        # Remove empty trailing zone
        if self.zones and self.zones[-1].size == 0:
            self.zones.pop()
        self._finalized = True

    def get_zone_summary(self) -> list[str]:
        """Get summary of all zones."""
        lines = []
        for z in self.zones:
            lines.append(z.summary())
        return lines

    # ── Shuffle procedure recording ─────────────────────

    def record_riffle(self, top_zone_indices: list[int],
                      bottom_zone_indices: list[int]):
        """Record a riffle step: top half zones interleaved with bottom half."""
        step = ShuffleStep(
            step_type="riffle",
            top_zones=top_zone_indices,
            bottom_zones=bottom_zone_indices,
        )
        self.shuffle_procedure.append(step)

    def record_strip(self, details: str = ""):
        """Record a strip cut (taking small packets from top to bottom)."""
        step = ShuffleStep(step_type="strip", details=details)
        self.shuffle_procedure.append(step)

    def record_cut(self, details: str = ""):
        """Record a cut."""
        step = ShuffleStep(step_type="cut", details=details)
        self.shuffle_procedure.append(step)

    # ── Simple prediction model ──────────────────────────
    # For practical use: map zone counts through a standard
    # riffle-riffle-strip-cut procedure

    def predict_simple(self, num_riffles: int = 2,
                       riffle_quality: float = 0.5) -> list["ZonePrediction"]:
        """Generate predictions for the new shoe using a simple model.

        Assumes a standard shuffle: the discard tray is split roughly
        in half, riffled together N times, then stripped and cut.

        After each riffle, zone character is retained by (1-quality) factor.
        After N riffles: retention = (1-quality)^N

        Args:
            num_riffles: Number of riffle passes (typically 1-3).
            riffle_quality: 0.0 (no mixing) to 1.0 (perfect). 0.5 is average.

        Returns:
            List of predictions for sections of the new shoe.
        """
        if not self.zones:
            return []

        model = RiffleModel(riffle_quality)
        retention = model.retention ** num_riffles

        n = len(self.zones)
        if n < 2:
            return []

        # Split zones into top/bottom halves (as they sit in discard tray)
        # Discard tray: zone 0 is at bottom (dealt first), zone N at top
        mid = n // 2
        bottom_half = self.zones[:mid]   # zones 0..mid-1
        top_half = self.zones[mid:]      # zones mid..N-1

        # After riffle: top and bottom interleave
        # The resulting shoe sections inherit blended counts
        predictions = []

        # Model: new shoe has sections where adjacent top/bottom zones merged
        # Each pair creates a section in the new shoe
        max_pairs = min(len(top_half), len(bottom_half))

        for i in range(max_pairs):
            tz = top_half[i]
            bz = bottom_half[i]

            # Blended count after interleaving
            combined_rc = (tz.running_count + bz.running_count)
            combined_size = tz.size + bz.size

            # Apply retention factor — only partial structure survives
            effective_rc = combined_rc * retention

            pred = ZonePrediction(
                section_index=i,
                estimated_count=effective_rc,
                estimated_cards=combined_size,
                source_zones=[tz.index, bz.index],
                confidence=retention,
            )
            predictions.append(pred)

        # Handle leftover zone if odd number
        if len(top_half) > len(bottom_half):
            extra = top_half[-1]
            pred = ZonePrediction(
                section_index=max_pairs,
                estimated_count=extra.running_count * retention,
                estimated_cards=extra.size,
                source_zones=[extra.index],
                confidence=retention * 0.7,  # lower confidence for unmixed zone
            )
            predictions.append(pred)
        elif len(bottom_half) > len(top_half):
            extra = bottom_half[-1]
            pred = ZonePrediction(
                section_index=max_pairs,
                estimated_count=extra.running_count * retention,
                estimated_cards=extra.size,
                source_zones=[extra.index],
                confidence=retention * 0.7,
            )
            predictions.append(pred)

        self.post_shuffle_predictions = predictions
        return predictions

    def get_bet_signal_for_section(self, section_index: int) -> str:
        """Get bet recommendation for a predicted section.

        Returns: 'big' (favorable), 'min' (unfavorable), 'normal'
        """
        if section_index >= len(self.post_shuffle_predictions):
            return "normal"

        pred = self.post_shuffle_predictions[section_index]
        if pred.estimated_count < -1.5 and pred.confidence > 0.15:
            return "big"      # predicted ten-rich section
        elif pred.estimated_count > 1.5 and pred.confidence > 0.15:
            return "min"      # predicted ten-poor section
        return "normal"

    def reset(self):
        """Reset for a new shoe."""
        self.zones = [Zone(index=0)]
        self.current_zone_index = 0
        self.total_cards = 0
        self.shuffle_procedure = []
        self.post_shuffle_predictions = []
        self._finalized = False


@dataclass
class ZonePrediction:
    """Prediction for a section of the post-shuffle shoe."""
    section_index: int
    estimated_count: float      # expected running count character
    estimated_cards: int        # approximate cards in this section
    source_zones: list[int]     # which original zones contributed
    confidence: float           # 0.0 to 1.0

    @property
    def is_favorable(self) -> bool:
        """Negative estimated count = ten-rich = favorable for player."""
        return self.estimated_count < -1.5

    @property
    def is_unfavorable(self) -> bool:
        return self.estimated_count > 1.5

    def summary(self) -> str:
        ec = self.estimated_count
        if ec < -2:
            signal = ">>> BET BIG <<<"
        elif ec < -1:
            signal = "> Favorable"
        elif ec > 2:
            signal = "--- Bet min ---"
        elif ec > 1:
            signal = "- Unfavorable"
        else:
            signal = "  Neutral"
        return (
            f"Section {self.section_index}: "
            f"est.count={ec:+.1f} | "
            f"~{self.estimated_cards} cards | "
            f"conf={self.confidence:.0%} | "
            f"{signal}"
        )
