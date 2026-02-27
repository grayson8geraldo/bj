"""Tests for the web API."""

import unittest
import json
from blackjack.web import app


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def _init(self, bankroll=1000, min_bet=10, max_bet=500):
        r = self.client.post('/api/init', json={
            'bankroll': bankroll, 'min_bet': min_bet, 'max_bet': max_bet,
        })
        data = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertIn('sid', data)
        return data['sid'], data['state']

    def test_init(self):
        sid, state = self._init()
        self.assertTrue(sid)
        self.assertEqual(state['rc'], 0)
        self.assertAlmostEqual(state['tc'], 0.0)
        self.assertEqual(state['bankroll'], 1000)

    def test_state(self):
        sid, _ = self._init()
        r = self.client.get(f'/api/state?sid={sid}')
        data = r.get_json()
        self.assertEqual(data['sid'], sid)
        self.assertEqual(data['state']['rc'], 0)

    def test_new_hand_basic(self):
        sid, _ = self._init()
        r = self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['10', 'J'], 'dealer_up': '6',
        })
        data = r.get_json()
        self.assertEqual(r.status_code, 200)
        # 20 vs 6 should be Stand
        self.assertEqual(data['action'], 'S')
        self.assertEqual(data['state']['in_hand'], True)

    def test_new_hand_blackjack(self):
        sid, _ = self._init()
        r = self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['A', '10'], 'dealer_up': '5',
        })
        data = r.get_json()
        self.assertTrue(data.get('blackjack'))

    def test_new_hand_insurance(self):
        sid, _ = self._init()
        # First push count high to get TC >= 3
        # Count many low cards to raise TC
        low_cards = ['2', '3', '4', '5', '6'] * 10  # 50 low cards = RC +50
        self.client.post('/api/count', json={'sid': sid, 'cards': low_cards})

        r = self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['8', '9'], 'dealer_up': 'A',
        })
        data = r.get_json()
        # TC should be high enough for insurance
        self.assertIn('insurance', data)

    def test_hit(self):
        sid, _ = self._init()
        self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['5', '3'], 'dealer_up': '10',
        })
        r = self.client.post('/api/hit', json={'sid': sid, 'card': '2'})
        data = r.get_json()
        self.assertEqual(data['hand_value'], 10)  # 5+3+2
        self.assertIn('action', data)

    def test_hit_bust(self):
        sid, _ = self._init()
        self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['10', '8'], 'dealer_up': '7',
        })
        r = self.client.post('/api/hit', json={'sid': sid, 'card': 'K'})
        data = r.get_json()
        self.assertTrue(data.get('bust'))
        self.assertFalse(data['state']['in_hand'])

    def test_count(self):
        sid, _ = self._init()
        r = self.client.post('/api/count', json={
            'sid': sid, 'cards': ['5', '6', 'K'],
        })
        data = r.get_json()
        self.assertEqual(data['counted'], 3)
        # 5(+1) + 6(+1) + K(-1) = RC +1
        self.assertEqual(data['state']['rc'], 1)

    def test_result(self):
        sid, _ = self._init()
        r = self.client.post('/api/result', json={'sid': sid, 'amount': 25})
        data = r.get_json()
        self.assertEqual(data['state']['bankroll'], 1025)
        self.assertEqual(data['state']['net_profit'], 25)

    def test_shoe_reset(self):
        sid, _ = self._init()
        self.client.post('/api/count', json={'sid': sid, 'cards': ['5', '6', 'K']})
        r = self.client.post('/api/shoe_reset', json={'sid': sid})
        data = r.get_json()
        self.assertEqual(data['state']['rc'], 0)

    def test_shuffle(self):
        sid, _ = self._init()
        # Feed enough cards to have multiple zones
        cards = (['5'] * 30 + ['K'] * 20 + ['7'] * 10 +
                 ['2'] * 20 + ['Q'] * 30 + ['8'] * 10)
        self.client.post('/api/count', json={'sid': sid, 'cards': cards})

        r = self.client.post('/api/shuffle', json={
            'sid': sid, 'num_stacks': 2, 'riffles': 2,
            'quality': 'sloppy', 'has_strip': True,
        })
        data = r.get_json()
        self.assertIn('predictions', data)
        self.assertTrue(len(data['predictions']) > 0)
        self.assertIn('retention', data)
        # After shuffle, counter should be reset
        self.assertEqual(data['state']['rc'], 0)
        self.assertTrue(data['state']['predictions_active'])

    def test_next_section(self):
        sid, _ = self._init()
        cards = ['5'] * 60 + ['K'] * 60
        self.client.post('/api/count', json={'sid': sid, 'cards': cards})
        self.client.post('/api/shuffle', json={
            'sid': sid, 'num_stacks': 2, 'riffles': 1,
            'quality': 'sloppy', 'has_strip': False,
        })
        r = self.client.post('/api/next_section', json={'sid': sid})
        data = r.get_json()
        self.assertEqual(data['state']['current_section'], 1)

    def test_zones(self):
        sid, _ = self._init()
        cards = ['5'] * 30 + ['K'] * 30
        self.client.post('/api/count', json={'sid': sid, 'cards': cards})
        r = self.client.get(f'/api/zones?sid={sid}')
        data = r.get_json()
        self.assertIn('zones', data)
        self.assertTrue(data['total_cards'] > 0)

    def test_serves_html(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'BJ Advisor', r.data)

    def test_full_flow(self):
        """Full game flow: init → count → hand → hit → result → shoe."""
        sid, _ = self._init(bankroll=500)

        # Count some cards at other spots
        self.client.post('/api/count', json={'sid': sid, 'cards': ['3', '4', '7']})

        # New hand
        r = self.client.post('/api/new_hand', json={
            'sid': sid, 'player_cards': ['10', '6'], 'dealer_up': '10',
        })
        data = r.get_json()
        self.assertIn('action', data)

        # Hit
        r = self.client.post('/api/hit', json={'sid': sid, 'card': '3'})
        data = r.get_json()
        # 10+6+3 = 19
        self.assertEqual(data['hand_value'], 19)

        # Result
        r = self.client.post('/api/result', json={'sid': sid, 'amount': -25})
        data = r.get_json()
        self.assertEqual(data['state']['bankroll'], 475)

        # New shoe
        r = self.client.post('/api/shoe_reset', json={'sid': sid})
        data = r.get_json()
        self.assertEqual(data['state']['rc'], 0)
        # Bankroll should persist across shoe resets
        self.assertEqual(data['state']['bankroll'], 475)


if __name__ == '__main__':
    unittest.main()
