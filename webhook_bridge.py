"""OpenAlgo → Telegram webhook bridge.
Receives order events from OpenAlgo and forwards formatted messages to Telegram.
"""
import os
import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify
import requests

log = logging.getLogger(__name__)
bp = Blueprint("webhook_bridge", __name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
WEBHOOK_SECRET = os.environ.get("OPENALGO_WEBHOOK_SECRET", "")


def _verify(req) -> bool:
    """Verify OpenAlgo webhook signature (HMAC-SHA256 of body)."""
    if not WEBHOOK_SECRET:
        log.warning("OPENALGO_WEBHOOK_SECRET not set — skipping verification")
        return True
    sig = req.headers.get("X-OpenAlgo-Signature", "")
    body = req.get_data()
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def _format(event: dict) -> str:
    """Build a clean HTML message from an order.placed event."""
    symbol = event.get("symbol", "?")
    action = event.get("action", "?")           # BUY / SELL
    qty    = event.get("quantity", "?")
    price  = event.get("price", event.get("avg_price", "?"))
    side   = "LONG 🟢" if action.upper() == "BUY" else "SHORT 🔴"
    return (
        f"📊 <b>SYMBOL</b>\n"
        f"<b>{symbol}</b>\n"
        f"Dir: <b>{action}-{side}</b>\n"
        f"Entry: <b>{price}</b>\n"
        f"Qty: <b>{qty}</b>"
    )


@bp.post("/webhook/order")
def order_received():
    if not _verify(request):
        return jsonify({"error": "invalid signature"}), 401

    event = request.get_json(silent=True) or {}
    log.info("OpenAlgo webhook received: %s", event.get("event") or event)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_ids = [
        cid.strip() for cid in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
        if cid.strip()
    ]
    if not token or not chat_ids:
        return jsonify({"error": "telegram env not set"}), 500

    text = _format(event)
    sent, failed = 0, 0
    for cid in chat_ids:
        r = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
        if r.ok:
            sent += 1
        else:
            failed += 1
            log.error("Telegram error: %s", r.text)

    return jsonify({"sent": sent, "failed": failed}), 200
