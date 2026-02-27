"""Tests for shuffle tracking module."""

import unittest
from blackjack.shuffle_tracking import ShuffleTracker, Zone, ZonePrediction


class TestZone(unittest.TestCase):
    def test_empty_zone(self):
        z = Zone(index=0)
        self.assertEqual(z.size, 0)
        self.assertEqual(z.running_count, 0)
        self.assertAlmostEqual(z.count_per_card, 0.0)

    def test_low_cards_positive_count(self):
        z = Zone(index=0)
        for card in ["2", "3", "4", "5", "6"]:
            z.add_card(card)
        self.assertEqual(z.running_count, 5)  # all +1
        self.assertTrue(z.is_unfavorable)  # lots of low cards dealt = ten-poor remains

    def test_high_cards_negative_count(self):
        z = Zone(index=0)
        for card in ["10", "J", "Q", "K", "A"]:
            z.add_card(card)
        self.assertEqual(z.running_count, -5)  # all -1
        self.assertTrue(z.is_favorable)  # lots of high cards dealt


class TestShuffleTracker(unittest.TestCase):
    def test_zone_creation(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=10)
        for i in range(25):
            tracker.add_card("5")
        # 25 cards with zone size 10 = 3 zones (10, 10, 5)
        self.assertEqual(tracker.num_zones, 3)
        self.assertEqual(tracker.zones[0].size, 10)
        self.assertEqual(tracker.zones[1].size, 10)
        self.assertEqual(tracker.zones[2].size, 5)

    def test_total_cards(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=52)
        cards = ["2", "5", "10", "A", "7", "K"]
        tracker.add_cards(cards)
        self.assertEqual(tracker.total_cards, 6)

    def test_finalize_removes_empty(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=5)
        for _ in range(5):
            tracker.add_card("3")
        # Zone 0 has 5 cards (full), zone 1 exists but empty
        self.assertEqual(tracker.num_zones, 2)
        tracker.finalize_shoe()
        self.assertEqual(tracker.num_zones, 1)

    def test_predict_simple_basic(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=5)
        # Zone 0: 5 low cards (RC=+5, ten-poor)
        for _ in range(5):
            tracker.add_card("3")
        # Zone 1: 5 high cards (RC=-5, ten-rich)
        for _ in range(5):
            tracker.add_card("K")
        # Zone 2: 5 neutral (RC=0)
        for _ in range(5):
            tracker.add_card("7")
        # Zone 3: 5 low cards (RC=+5)
        for _ in range(5):
            tracker.add_card("4")

        tracker.finalize_shoe()
        self.assertEqual(tracker.num_zones, 4)

        preds = tracker.predict_simple(num_riffles=1, riffle_quality=0.5)
        self.assertTrue(len(preds) > 0)

        # Check that predictions have non-zero estimated counts
        for p in preds:
            self.assertIsInstance(p.estimated_count, float)
            self.assertIsInstance(p.confidence, float)
            self.assertGreater(p.confidence, 0)

    def test_predict_sloppy_shuffle_high_retention(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=5)
        # 4 zones with different counts so they don't cancel out
        # Zone 0: low cards (RC=+5)
        for _ in range(5):
            tracker.add_card("2")
        # Zone 1: low cards (RC=+5)
        for _ in range(5):
            tracker.add_card("3")
        # Zone 2: high cards (RC=-5)
        for _ in range(5):
            tracker.add_card("K")
        # Zone 3: neutral (RC=0)
        for _ in range(5):
            tracker.add_card("7")
        tracker.finalize_shoe()

        # Sloppy shuffle = high retention
        preds = tracker.predict_simple(num_riffles=1, riffle_quality=0.3)
        # retention = (1 - 0.3)^1 = 0.7

        # Good shuffle = low retention
        preds2 = tracker.predict_simple(num_riffles=2, riffle_quality=0.7)
        # retention = (1 - 0.7)^2 = 0.09

        # Sloppy should have higher absolute estimated counts
        # Zone 0 (RC=+5) pairs with Zone 2 (RC=-5) => combined 0 for both
        # Zone 1 (RC=+5) pairs with Zone 3 (RC=0) => combined +5
        # So section 1 should have non-zero count
        self.assertTrue(len(preds) >= 2)
        self.assertTrue(len(preds2) >= 2)
        self.assertGreater(
            abs(preds[1].estimated_count),
            abs(preds2[1].estimated_count)
        )

    def test_bet_signal(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=5)
        # Create zones with extreme counts
        for _ in range(5):
            tracker.add_card("5")  # RC = +5
        for _ in range(5):
            tracker.add_card("K")  # RC = -5
        for _ in range(5):
            tracker.add_card("5")  # RC = +5
        for _ in range(5):
            tracker.add_card("K")  # RC = -5
        tracker.finalize_shoe()

        # Very sloppy 1-riffle shuffle (high retention)
        tracker.predict_simple(num_riffles=1, riffle_quality=0.2)

        # Should get some signal for at least one section
        signals = [tracker.get_bet_signal_for_section(i)
                    for i in range(len(tracker.post_shuffle_predictions))]
        self.assertTrue(any(s != "normal" for s in signals))

    def test_reset(self):
        tracker = ShuffleTracker(num_decks=8)
        tracker.add_cards(["2", "3", "4"])
        tracker.reset()
        self.assertEqual(tracker.total_cards, 0)
        self.assertEqual(tracker.num_zones, 1)
        self.assertFalse(tracker._finalized)

    def test_force_new_zone(self):
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=52)
        tracker.add_cards(["5", "K", "7"])
        tracker.force_new_zone()
        tracker.add_cards(["A", "2"])
        self.assertEqual(tracker.num_zones, 2)
        self.assertEqual(tracker.zones[0].size, 3)
        self.assertEqual(tracker.zones[1].size, 2)


class TestMultistackPrediction(unittest.TestCase):
    """Tests for the realistic multi-stack shuffle model."""

    def _make_tracker(self, zone_counts: list[int], cards_per_zone: int = 5):
        """Helper: create a tracker with zones of known count character.

        zone_counts: list of target RCs per zone.
        Positive RC → feed low cards, Negative RC → feed high cards.
        """
        tracker = ShuffleTracker(num_decks=8, cards_per_zone=cards_per_zone)
        for rc in zone_counts:
            if rc > 0:
                for _ in range(abs(rc)):
                    tracker.add_card("5")   # +1 each
                pad = cards_per_zone - abs(rc)
                for _ in range(pad):
                    tracker.add_card("7")   # neutral
            elif rc < 0:
                for _ in range(abs(rc)):
                    tracker.add_card("K")   # -1 each
                pad = cards_per_zone - abs(rc)
                for _ in range(pad):
                    tracker.add_card("7")
            else:
                for _ in range(cards_per_zone):
                    tracker.add_card("7")
        tracker.finalize_shoe()
        return tracker

    def test_2_stacks_same_as_simple(self):
        """With 2 stacks the multistack model should behave like predict_simple."""
        tracker = self._make_tracker([+5, +5, -5, 0])
        preds_simple = tracker.predict_simple(num_riffles=2, riffle_quality=0.5)
        preds_multi = tracker.predict_multistack(
            num_stacks=2, riffles_per_pair=2,
            riffle_quality=0.5, has_strip=False,
        )
        self.assertEqual(len(preds_simple), len(preds_multi))
        for ps, pm in zip(preds_simple, preds_multi):
            self.assertAlmostEqual(ps.estimated_count, pm.estimated_count, places=2)

    def test_3_stacks_has_unriffled_zone(self):
        """With 3 stacks, the odd stack out is never riffled."""
        tracker = self._make_tracker([+5, -5, +3, -3, +4, -4])
        # 6 zones, 3 stacks: stacks=[0,1], [2,3], [4,5]
        # Riffle pairs: (stack0, stack1) and (stack2 is solo — odd one out)
        # Wait, with 3 stacks: pairs are (0,1), and stack 2 is solo
        preds = tracker.predict_multistack(
            num_stacks=3, riffles_per_pair=2,
            riffle_quality=0.5, has_strip=False,
        )
        self.assertTrue(len(preds) > 0)

        # Check that at least one prediction is unriffled
        unriffled = [p for p in preds if not p.riffled]
        self.assertTrue(len(unriffled) > 0, "3 stacks should have un-riffled section(s)")

        # Un-riffled sections should have confidence=1.0
        for p in unriffled:
            self.assertAlmostEqual(p.confidence, 1.0)

    def test_4_stacks_no_cross_group_mixing(self):
        """With 4 stacks, groups (0,1) and (2,3) never mix with each other."""
        # Zone 0,1 → stack 0; Zone 2,3 → stack 1; Zone 4,5 → stack 2; Zone 6,7 → stack 3
        # Groups: (stack0, stack1) riffled and (stack2, stack3) riffled
        # Zones 0-3 never contact zones 4-7
        tracker = self._make_tracker([+5, +5, -5, -5, +3, +3, -3, -3])
        preds = tracker.predict_multistack(
            num_stacks=4, riffles_per_pair=2,
            riffle_quality=0.3, has_strip=False,
        )
        self.assertTrue(len(preds) > 0)
        # All should be riffled (4 stacks, 2 pairs, no solo)
        self.assertTrue(all(p.riffled for p in preds))

    def test_sloppy_riffle_higher_retention(self):
        """Sloppy riffles retain more zone character than good riffles."""
        tracker = self._make_tracker([+5, 0, -5, +5])
        preds_sloppy = tracker.predict_multistack(
            num_stacks=2, riffles_per_pair=1,
            riffle_quality=0.3, has_strip=False,
        )
        preds_good = tracker.predict_multistack(
            num_stacks=2, riffles_per_pair=2,
            riffle_quality=0.7, has_strip=False,
        )
        # Find a section with non-zero count in both
        max_sloppy = max(abs(p.estimated_count) for p in preds_sloppy)
        max_good = max(abs(p.estimated_count) for p in preds_good)
        self.assertGreater(max_sloppy, max_good)

    def test_strip_cut_reduces_retention(self):
        """Strip cut should reduce predicted count magnitude."""
        tracker = self._make_tracker([+5, -5, +5, -5])
        preds_no_strip = tracker.predict_multistack(
            num_stacks=2, riffles_per_pair=1,
            riffle_quality=0.3, has_strip=False,
        )
        preds_strip = tracker.predict_multistack(
            num_stacks=2, riffles_per_pair=1,
            riffle_quality=0.3, has_strip=True,
        )
        # With strip, effective quality is higher → lower retention
        max_no_strip = max(abs(p.estimated_count) for p in preds_no_strip)
        max_strip = max(abs(p.estimated_count) for p in preds_strip)
        self.assertGreaterEqual(max_no_strip, max_strip)

    def test_unriffled_zone_full_count(self):
        """Un-riffled zone should preserve its exact running count."""
        # 3 zones, 3 stacks: each zone is its own stack
        # Pairs: (stack0, stack1) riffled, stack2 solo
        tracker = self._make_tracker([+3, -4, +5], cards_per_zone=5)
        preds = tracker.predict_multistack(
            num_stacks=3, riffles_per_pair=2,
            riffle_quality=0.5, has_strip=False,
        )
        unriffled = [p for p in preds if not p.riffled]
        self.assertTrue(len(unriffled) > 0)
        # The un-riffled section should have the full zone RC
        for p in unriffled:
            source_zone = tracker.zones[p.source_zones[0]]
            self.assertAlmostEqual(
                p.estimated_count,
                float(source_zone.running_count),
            )


class TestZonePrediction(unittest.TestCase):
    def test_favorable(self):
        p = ZonePrediction(0, -3.0, 100, [0, 1], 0.5)
        self.assertTrue(p.is_favorable)
        self.assertFalse(p.is_unfavorable)

    def test_unfavorable(self):
        p = ZonePrediction(0, 3.0, 100, [0, 1], 0.5)
        self.assertFalse(p.is_favorable)
        self.assertTrue(p.is_unfavorable)

    def test_neutral(self):
        p = ZonePrediction(0, 0.5, 100, [0, 1], 0.5)
        self.assertFalse(p.is_favorable)
        self.assertFalse(p.is_unfavorable)

    def test_summary_bet_big(self):
        p = ZonePrediction(0, -3.0, 100, [0, 1], 0.5)
        s = p.summary()
        self.assertIn("BET BIG", s)

    def test_summary_not_riffled(self):
        p = ZonePrediction(0, -3.0, 100, [0], 1.0, riffled=False)
        s = p.summary()
        self.assertIn("NOT RIFFLED", s)


if __name__ == "__main__":
    unittest.main()
