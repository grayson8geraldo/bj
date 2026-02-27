"""Tests for blackjack strategy engine."""

import unittest
from blackjack.cards import hand_value, is_soft, is_pair, is_blackjack, Shoe
from blackjack.counting import CardCounter
from blackjack.strategy import basic_strategy, get_action, should_take_insurance
from blackjack.betting import player_edge, bet_ramp, kelly_bet


class TestHandValue(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(hand_value(["5", "K"]), 15)

    def test_ace_high(self):
        self.assertEqual(hand_value(["A", "7"]), 18)

    def test_ace_low(self):
        self.assertEqual(hand_value(["A", "7", "8"]), 16)

    def test_double_ace(self):
        self.assertEqual(hand_value(["A", "A"]), 12)

    def test_blackjack(self):
        self.assertEqual(hand_value(["A", "K"]), 21)
        self.assertTrue(is_blackjack(["A", "K"]))
        self.assertTrue(is_blackjack(["10", "A"]))
        self.assertFalse(is_blackjack(["5", "6", "10"]))

    def test_soft(self):
        self.assertTrue(is_soft(["A", "6"]))
        self.assertFalse(is_soft(["A", "6", "8"]))

    def test_pair(self):
        self.assertTrue(is_pair(["8", "8"]))
        self.assertTrue(is_pair(["K", "Q"]))  # both value 10
        self.assertFalse(is_pair(["8", "9"]))


class TestBasicStrategy(unittest.TestCase):
    def test_hard_16_vs_10_hit(self):
        # Basic strategy: 16 vs 10 = Surrender (or hit)
        action = basic_strategy(["10", "6"], "10", can_surrender=False)
        self.assertEqual(action, "H")

    def test_hard_16_vs_10_surrender(self):
        action = basic_strategy(["10", "6"], "10", can_surrender=True)
        self.assertEqual(action, "R")

    def test_hard_11_double(self):
        action = basic_strategy(["5", "6"], "7")
        self.assertEqual(action, "D")

    def test_hard_11_no_double(self):
        action = basic_strategy(["5", "6"], "7", can_double=False)
        self.assertEqual(action, "H")

    def test_soft_18_vs_6(self):
        action = basic_strategy(["A", "7"], "6")
        self.assertEqual(action, "D")

    def test_soft_18_vs_9(self):
        action = basic_strategy(["A", "7"], "9")
        self.assertEqual(action, "H")

    def test_pair_88_vs_10(self):
        action = basic_strategy(["8", "8"], "10")
        self.assertEqual(action, "P")

    def test_pair_aa_always_split(self):
        action = basic_strategy(["A", "A"], "A")
        self.assertEqual(action, "P")

    def test_pair_10s_never_split(self):
        action = basic_strategy(["K", "Q"], "6")
        self.assertEqual(action, "S")

    def test_hard_12_vs_4_stand(self):
        action = basic_strategy(["10", "2"], "4")
        self.assertEqual(action, "S")

    def test_hard_12_vs_2_hit(self):
        action = basic_strategy(["10", "2"], "2")
        self.assertEqual(action, "H")


class TestDeviations(unittest.TestCase):
    def test_16_vs_10_stand_high_count(self):
        action, reason = get_action(["10", "6"], "10", true_count=1.0)
        self.assertEqual(action, "S")
        self.assertEqual(reason, "deviation")

    def test_16_vs_10_hit_negative_count(self):
        action, reason = get_action(["10", "6"], "10", true_count=-2.0)
        self.assertEqual(action, "H")
        self.assertEqual(reason, "deviation")

    def test_insurance_positive(self):
        self.assertTrue(should_take_insurance(3.0))
        self.assertTrue(should_take_insurance(5.0))

    def test_insurance_negative(self):
        self.assertFalse(should_take_insurance(2.0))
        self.assertFalse(should_take_insurance(-1.0))

    def test_15_vs_10_stand_high_tc(self):
        action, reason = get_action(
            ["10", "5"], "10", true_count=5.0, can_surrender=False
        )
        self.assertEqual(action, "S")

    def test_12_vs_3_stand_at_tc2(self):
        action, reason = get_action(["10", "2"], "3", true_count=3.0)
        self.assertEqual(action, "S")
        self.assertEqual(reason, "deviation")


class TestCounting(unittest.TestCase):
    def test_hilo_basic(self):
        shoe = Shoe(8)
        counter = CardCounter(shoe)
        # Low cards = +1
        counter.count_cards(["2", "3", "4", "5", "6"])
        self.assertEqual(counter.rc, 5)
        # High cards = -1
        counter.count_cards(["10", "J", "Q", "K", "A"])
        self.assertEqual(counter.rc, 0)

    def test_true_count(self):
        shoe = Shoe(8)
        counter = CardCounter(shoe)
        # 8 decks = 416 cards. Count 10 low cards.
        for _ in range(10):
            counter.count_card("5")
        # RC = 10, decks remaining ≈ (416-10)/52 ≈ 7.81
        self.assertAlmostEqual(counter.tc, 10 / ((416 - 10) / 52), places=1)


class TestBetting(unittest.TestCase):
    def test_negative_edge_min_bet(self):
        bet = bet_ramp(-1.0, min_bet=10.0)
        self.assertEqual(bet, 10.0)

    def test_high_count_max_spread(self):
        bet = bet_ramp(5.0, min_bet=10.0, spread=12.0)
        self.assertEqual(bet, 120.0)

    def test_kelly_negative_edge(self):
        bet = kelly_bet(-1.0, bankroll=10000.0, min_bet=10.0)
        self.assertEqual(bet, 10.0)

    def test_player_edge_calculation(self):
        # TC 0: edge = 0*0.005 - 0.0043 = -0.0043
        self.assertAlmostEqual(player_edge(0), -0.0043)
        # TC 1: edge = 0.005 - 0.0043 = 0.0007
        self.assertAlmostEqual(player_edge(1), 0.0007)
        # TC 2: edge = 0.01 - 0.0043 = 0.0057
        self.assertAlmostEqual(player_edge(2), 0.0057)


if __name__ == "__main__":
    unittest.main()
