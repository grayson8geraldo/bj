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

    def test_summary(self):
        p = ZonePrediction(0, -3.0, 100, [0, 1], 0.5)
        s = p.summary()
        self.assertIn("BET BIG", s)


if __name__ == "__main__":
    unittest.main()
