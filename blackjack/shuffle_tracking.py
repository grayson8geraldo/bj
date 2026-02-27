"""Shuffle Tracking for hand-shuffled 6/8-deck shoes.

When a dealer hand-shuffles a multi-deck shoe with riffle shuffles,
cards are NOT fully randomized.  A dealer cannot riffle 416 cards
at once — they split the discard tray into 2–4 stacks, riffle pairs
of stacks together, and reassemble.  This means:

  • Zones within the same riffle group are partially mixed
  • Zones in DIFFERENT groups that never contact each other
    retain 100% of their count character

Technique:
1. Divide the dealt shoe into ZONES (segments of ~1 deck each)
2. Track the running count of EACH zone separately
3. Observe the dealer's shuffle routine:
   - How many stacks?  Which zones go into which stack?
   - How many riffles per pair?  How sloppy?
4. Map zones through the shuffle to predict which sections of
   the new shoe are ten-rich (favorable) or ten-poor (unfavorable)
5. Bet big when playing through a predicted favorable section

This module implements zone tracking and realistic multi-stack
riffle shuffle mapping.
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

    # ── Prediction models ──────────────────────────────────

    def predict_simple(self, num_riffles: int = 2,
                       riffle_quality: float = 0.5) -> list["ZonePrediction"]:
        """Simple model — splits all zones in half and riffles once.

        Kept for backward compatibility and small-shoe scenarios.
        For 6/8-deck hand shuffles use predict_multistack().
        """
        if not self.zones or len(self.zones) < 2:
            return []
        mid = len(self.zones) // 2
        groups = [
            (list(range(mid)), list(range(mid, len(self.zones)))),
        ]
        return self._predict_from_groups(groups, num_riffles, riffle_quality)

    def predict_multistack(
        self,
        num_stacks: int = 2,
        riffles_per_pair: int = 2,
        riffle_quality: float = 0.5,
        has_strip: bool = True,
    ) -> list["ZonePrediction"]:
        """Realistic model for hand-shuffled 6/8-deck shoes.

        The dealer splits the discard tray into `num_stacks` stacks
        (~1-2 decks each), then riffles adjacent pairs together.

        Key insight: zones in stacks that are NEVER riffled together
        retain 100% of their count character — only riffled pairs mix.

        Procedure modeled:
            1. Discard tray split into num_stacks stacks
               Stack 0 = bottom (zones dealt first)
               Stack K = top   (zones dealt last)
            2. Adjacent pairs riffled: (0,1), (2,3), ...
               If odd number of stacks, the last stack is un-riffled
            3. Optional strip cut (reduces retention by ~20%)
            4. Cut card placed

        Args:
            num_stacks:      How many piles the dealer splits into (2-4)
            riffles_per_pair: Riffles per pair (typically 1-3)
            riffle_quality:  0.0 (sloppy) to 1.0 (perfect). 0.3-0.5 typical.
            has_strip:       Did the dealer do a strip cut after riffling?

        Returns:
            Predictions for each section of the new shoe.
        """
        if not self.zones or len(self.zones) < 2:
            return []

        n = len(self.zones)
        num_stacks = max(2, min(num_stacks, n))  # clamp

        # ── Split zones into stacks ──
        # Distribute zones as evenly as possible across stacks
        stacks: list[list[int]] = [[] for _ in range(num_stacks)]
        for i, zone in enumerate(self.zones):
            stack_idx = min(i * num_stacks // n, num_stacks - 1)
            stacks[stack_idx].append(zone.index)

        # ── Pair adjacent stacks for riffling ──
        # (0,1), (2,3), ... — zones across non-adjacent stacks NEVER mix
        groups: list[tuple[list[int], list[int]]] = []
        i = 0
        while i < len(stacks) - 1:
            groups.append((stacks[i], stacks[i + 1]))
            i += 2
        # Odd stack out — never riffled, full retention
        if len(stacks) % 2 == 1:
            groups.append((stacks[-1], []))  # solo group

        # Strip cut reduces retention by ~20%
        quality = riffle_quality
        if has_strip:
            quality = min(quality + 0.1, 1.0)

        return self._predict_from_groups(groups, riffles_per_pair, quality)

    def _predict_from_groups(
        self,
        groups: list[tuple[list[int], list[int]]],
        num_riffles: int,
        riffle_quality: float,
    ) -> list["ZonePrediction"]:
        """Core prediction engine: map riffle groups to predictions.

        Each group is a pair of zone-index lists that get riffled together.
        Within a group, zone counts blend with retention factor.
        Solo groups (second list empty) pass through with full retention.
        """
        model = RiffleModel(riffle_quality)
        retention = model.retention ** num_riffles
        predictions: list[ZonePrediction] = []
        section_idx = 0

        for left_indices, right_indices in groups:
            left_zones = [self.zones[i] for i in left_indices]
            right_zones = [self.zones[i] for i in right_indices]

            if not right_zones:
                # ── Solo group: no riffle partner → full retention ──
                for z in left_zones:
                    pred = ZonePrediction(
                        section_index=section_idx,
                        estimated_count=float(z.running_count),
                        estimated_cards=z.size,
                        source_zones=[z.index],
                        confidence=1.0,
                        riffled=False,
                    )
                    predictions.append(pred)
                    section_idx += 1
                continue

            # ── Riffled pair: interleave left and right zones ──
            # Model: corresponding zones from left & right stacks merge.
            # Any leftover zones in the longer stack are partially mixed
            # (they get shuffled into the tail of the shorter stack's last zone).
            max_pairs = min(len(left_zones), len(right_zones))

            for i in range(max_pairs):
                lz = left_zones[i]
                rz = right_zones[i]

                combined_rc = lz.running_count + rz.running_count
                combined_size = lz.size + rz.size
                effective_rc = combined_rc * retention

                pred = ZonePrediction(
                    section_index=section_idx,
                    estimated_count=effective_rc,
                    estimated_cards=combined_size,
                    source_zones=[lz.index, rz.index],
                    confidence=retention,
                    riffled=True,
                )
                predictions.append(pred)
                section_idx += 1

            # Leftover zones from the longer stack
            longer = (left_zones[max_pairs:] if len(left_zones) > max_pairs
                      else right_zones[max_pairs:])
            for z in longer:
                # Partially mixed with the tail of the riffle
                effective_rc = z.running_count * retention
                pred = ZonePrediction(
                    section_index=section_idx,
                    estimated_count=effective_rc,
                    estimated_cards=z.size,
                    source_zones=[z.index],
                    confidence=retention * 0.8,
                    riffled=True,
                )
                predictions.append(pred)
                section_idx += 1

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
    riffled: bool = True        # False = this zone was never riffled (full retention)

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
        riffle_tag = "" if self.riffled else " [NOT RIFFLED]"
        return (
            f"Section {self.section_index}: "
            f"est.count={ec:+.1f} | "
            f"~{self.estimated_cards} cards | "
            f"conf={self.confidence:.0%} | "
            f"{signal}{riffle_tag}"
        )
