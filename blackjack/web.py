"""Web interface for the Blackjack Advisor.

Mobile-friendly single-page app for live play at the table.
Run with: python -m blackjack.web
"""

from __future__ import annotations

import uuid
from flask import Flask, request, jsonify, send_from_directory
import os

from .cards import Shoe, hand_value, is_soft, is_pair, is_blackjack
from .counting import CardCounter
from .strategy import get_action, should_take_insurance, ACTION_NAMES, basic_strategy
from .betting import BetAdvisor, player_edge, wonging_signal
from .shuffle_tracking import ShuffleTracker

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))

# ── Session state ────────────────────────────────────────
# In-memory sessions (single-user tool, no DB needed)
sessions: dict[str, dict] = {}


def get_or_create_session(sid: str | None = None) -> tuple[str, dict]:
    if sid and sid in sessions:
        return sid, sessions[sid]
    sid = sid or uuid.uuid4().hex[:12]
    num_decks = 8
    shoe = Shoe(num_decks)
    counter = CardCounter(shoe)
    advisor = BetAdvisor(1000.0, 10.0, 500.0)
    tracker = ShuffleTracker(num_decks=num_decks, cards_per_zone=52)
    sessions[sid] = {
        "shoe": shoe,
        "counter": counter,
        "advisor": advisor,
        "tracker": tracker,
        "num_decks": num_decks,
        "player_cards": [],
        "dealer_up": "",
        "in_hand": False,
        "predictions_active": False,
        "current_section": 0,
        "cards_in_section": 0,
    }
    return sid, sessions[sid]


def track_cards(s: dict, cards: list[str]):
    s["counter"].count_cards(cards)
    s["tracker"].add_cards(cards)
    if s["predictions_active"]:
        s["cards_in_section"] += len(cards)


def track_card(s: dict, card: str):
    s["counter"].count_card(card)
    s["tracker"].add_card(card)
    if s["predictions_active"]:
        s["cards_in_section"] += 1


def state_snapshot(s: dict) -> dict:
    counter = s["counter"]
    shoe = s["shoe"]
    advisor = s["advisor"]
    tracker = s["tracker"]
    tc = counter.tc
    rc = counter.rc
    edge = player_edge(tc)
    wong = wonging_signal(tc)
    bet_ramp = advisor.recommend_bet_simple(tc)
    bet_kelly = advisor.recommend_bet(tc)

    snap = {
        "rc": rc,
        "tc": round(tc, 1),
        "edge": round(edge * 100, 2),
        "penetration": round(shoe.penetration * 100, 0),
        "decks_remaining": round(shoe.decks_remaining, 1),
        "cards_seen": shoe.cards_seen,
        "total_cards": shoe.total_cards,
        "wong": wong,
        "bet_ramp": round(bet_ramp, 0),
        "bet_kelly": round(bet_kelly, 0),
        "bankroll": round(advisor.bankroll, 0),
        "net_profit": round(advisor.net_profit, 0),
        "hands_played": advisor.hands_played,
        "hands_won": advisor.hands_won,
        "hands_lost": advisor.hands_lost,
        "hands_pushed": advisor.hands_pushed,
        "in_hand": s["in_hand"],
        "player_cards": s["player_cards"][:],
        "dealer_up": s["dealer_up"],
        "predictions_active": s["predictions_active"],
        "current_section": s["current_section"],
        "cards_in_section": s["cards_in_section"],
        "should_leave": advisor.should_leave,
        "hit_win_goal": advisor.hit_win_goal,
        "num_zones": tracker.num_zones,
    }

    # Shuffle tracking predictions
    if s["predictions_active"] and tracker.post_shuffle_predictions:
        preds = []
        for p in tracker.post_shuffle_predictions:
            preds.append({
                "section": p.section_index,
                "est_count": round(p.estimated_count, 1),
                "est_cards": p.estimated_cards,
                "confidence": round(p.confidence * 100, 0),
                "favorable": p.is_favorable,
                "unfavorable": p.is_unfavorable,
                "riffled": p.riffled,
            })
        snap["predictions"] = preds
        signal = tracker.get_bet_signal_for_section(s["current_section"])
        snap["section_signal"] = signal
    else:
        snap["predictions"] = []
        snap["section_signal"] = "normal"

    return snap


# ── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/init", methods=["POST"])
def api_init():
    data = request.json or {}
    sid, s = get_or_create_session()
    bankroll = float(data.get("bankroll", 1000))
    min_bet = float(data.get("min_bet", 10))
    max_bet = float(data.get("max_bet", 500))
    s["advisor"] = BetAdvisor(bankroll, min_bet, max_bet)
    return jsonify({"sid": sid, "state": state_snapshot(s)})


@app.route("/api/state", methods=["GET"])
def api_state():
    sid = request.args.get("sid", "")
    sid, s = get_or_create_session(sid)
    return jsonify({"sid": sid, "state": state_snapshot(s)})


@app.route("/api/new_hand", methods=["POST"])
def api_new_hand():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)

    player_cards = data.get("player_cards", [])
    dealer_up = data.get("dealer_up", "")

    if not player_cards or not dealer_up:
        return jsonify({"error": "Need player_cards and dealer_up"}), 400

    other_cards = data.get("other_cards", [])

    s["player_cards"] = player_cards
    s["dealer_up"] = dealer_up
    s["in_hand"] = True

    track_cards(s, player_cards)
    track_card(s, dealer_up)
    if other_cards:
        track_cards(s, other_cards)

    tc = s["counter"].tc
    result = {"sid": sid}

    # Blackjack?
    if is_blackjack(player_cards):
        result["blackjack"] = True
        s["in_hand"] = False
        result["state"] = state_snapshot(s)
        return jsonify(result)

    # Insurance?
    if dealer_up == "A":
        result["insurance"] = should_take_insurance(tc)

    # Action
    action, reason = get_action(
        player_cards, dealer_up, tc,
        can_double=len(player_cards) == 2,
        can_surrender=len(player_cards) == 2,
        can_split=is_pair(player_cards) and len(player_cards) == 2,
    )

    val = hand_value(player_cards)
    soft = is_soft(player_cards)

    result["action"] = action
    result["action_name"] = ACTION_NAMES.get(action, action)
    result["reason"] = reason
    result["hand_value"] = val
    result["is_soft"] = soft

    if reason == "deviation":
        bs = basic_strategy(
            player_cards, dealer_up,
            can_double=len(player_cards) == 2,
            can_surrender=len(player_cards) == 2,
            can_split=is_pair(player_cards) and len(player_cards) == 2,
        )
        result["basic_would_be"] = ACTION_NAMES.get(bs, bs)

    result["state"] = state_snapshot(s)
    return jsonify(result)


@app.route("/api/hit", methods=["POST"])
def api_hit():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)
    card = data.get("card", "")

    if not s["in_hand"]:
        return jsonify({"error": "No active hand"}), 400
    if not card:
        return jsonify({"error": "Need card"}), 400

    s["player_cards"].append(card)
    track_card(s, card)
    tc = s["counter"].tc

    val = hand_value(s["player_cards"])
    soft = is_soft(s["player_cards"])
    result = {"sid": sid, "hand_value": val, "is_soft": soft}

    if val > 21:
        result["bust"] = True
        s["in_hand"] = False
    elif val == 21:
        result["twenty_one"] = True
        s["in_hand"] = False
    else:
        action, reason = get_action(
            s["player_cards"], s["dealer_up"], tc,
            can_double=False, can_surrender=False, can_split=False,
        )
        result["action"] = action
        result["action_name"] = ACTION_NAMES.get(action, action)
        result["reason"] = reason

    result["state"] = state_snapshot(s)
    return jsonify(result)


@app.route("/api/count", methods=["POST"])
def api_count():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)
    cards = data.get("cards", [])
    if not cards:
        return jsonify({"error": "Need cards"}), 400
    track_cards(s, cards)
    return jsonify({"sid": sid, "counted": len(cards), "state": state_snapshot(s)})


@app.route("/api/result", methods=["POST"])
def api_result():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)
    amount = float(data.get("amount", 0))
    s["advisor"].record_result(amount)
    s["in_hand"] = False
    return jsonify({"sid": sid, "state": state_snapshot(s)})


@app.route("/api/shoe_reset", methods=["POST"])
def api_shoe_reset():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)
    s["counter"].reset()
    s["tracker"].reset()
    s["predictions_active"] = False
    s["current_section"] = 0
    s["cards_in_section"] = 0
    s["in_hand"] = False
    s["player_cards"] = []
    s["dealer_up"] = ""
    return jsonify({"sid": sid, "state": state_snapshot(s)})


@app.route("/api/zones", methods=["GET"])
def api_zones():
    sid = request.args.get("sid", "")
    sid, s = get_or_create_session(sid)
    tracker = s["tracker"]
    zones = []
    for z in tracker.zones:
        if z.size > 0:
            zones.append({
                "index": z.index,
                "size": z.size,
                "rc": z.running_count,
                "density": round(z.count_per_card, 2),
                "favorable": z.is_favorable,
                "unfavorable": z.is_unfavorable,
            })
    return jsonify({"sid": sid, "zones": zones, "total_cards": tracker.total_cards})


@app.route("/api/shuffle", methods=["POST"])
def api_shuffle():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)
    tracker = s["tracker"]

    num_stacks = int(data.get("num_stacks", 2))
    riffles = int(data.get("riffles", 2))
    quality_str = data.get("quality", "sloppy")
    has_strip = data.get("has_strip", True)

    quality_map = {"sloppy": 0.3, "average": 0.5, "good": 0.7}
    quality = quality_map.get(quality_str, 0.3)

    tracker.finalize_shoe()

    # Zones summary before prediction
    zones_before = []
    for z in tracker.zones:
        if z.size > 0:
            zones_before.append({
                "index": z.index, "size": z.size,
                "rc": z.running_count, "favorable": z.is_favorable,
                "unfavorable": z.is_unfavorable,
            })

    preds = tracker.predict_multistack(
        num_stacks=num_stacks,
        riffles_per_pair=riffles,
        riffle_quality=quality,
        has_strip=has_strip,
    )

    # Reset for new shoe
    s["counter"].reset()
    new_tracker = ShuffleTracker(num_decks=s["num_decks"], cards_per_zone=52)
    new_tracker.post_shuffle_predictions = preds
    s["tracker"] = new_tracker
    s["predictions_active"] = True
    s["current_section"] = 0
    s["cards_in_section"] = 0
    s["in_hand"] = False
    s["player_cards"] = []
    s["dealer_up"] = ""

    eff_quality = min(quality + (0.1 if has_strip else 0), 1.0)
    retention = (1 - eff_quality) ** riffles

    predictions = []
    for p in preds:
        predictions.append({
            "section": p.section_index,
            "est_count": round(p.estimated_count, 1),
            "est_cards": p.estimated_cards,
            "confidence": round(p.confidence * 100, 0),
            "favorable": p.is_favorable,
            "unfavorable": p.is_unfavorable,
            "riffled": p.riffled,
        })

    return jsonify({
        "sid": sid,
        "zones_before": zones_before,
        "predictions": predictions,
        "retention": round(retention * 100, 0),
        "state": state_snapshot(s),
    })


@app.route("/api/next_section", methods=["POST"])
def api_next_section():
    data = request.json or {}
    sid = data.get("sid", "")
    sid, s = get_or_create_session(sid)

    if not s["predictions_active"]:
        return jsonify({"error": "No predictions active"}), 400

    s["current_section"] += 1
    s["cards_in_section"] = 0
    tracker = s["tracker"]
    preds = tracker.post_shuffle_predictions

    if s["current_section"] >= len(preds):
        s["predictions_active"] = False

    return jsonify({"sid": sid, "state": state_snapshot(s)})


def main():
    print("\n  Blackjack Advisor — Web Interface")
    print("  Open http://localhost:5050 in your browser\n")
    app.run(host="0.0.0.0", port=5050, debug=False)


if __name__ == "__main__":
    main()
