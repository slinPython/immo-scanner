"""
Immo-Scanner Notifier - Slack + Log-basierte Benachrichtigungen
"""
import json
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
if SLACK_WEBHOOK_URL and not SLACK_WEBHOOK_URL.startswith("http"):
    SLACK_WEBHOOK_URL = "https://" + SLACK_WEBHOOK_URL
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#immo-scanner")


def _build_slack_message(listings):
    """Erstellt eine formatierte Slack-Nachricht fuer neue Listings."""
    top5 = sorted(listings, key=lambda x: x.get('score', 0), reverse=True)[:5]
    heute = datetime.now().strftime('%d.%m.%Y')

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":house: Immo-Scanner: {len(listings)} neue Objekte ({heute})"
            }
        },
        {"type": "divider"}
    ]

    for i, l in enumerate(top5, 1):
        preis = l.get('price', 0) or 0
        preis_k = int(preis / 1000)
        zimmer = l.get('rooms', '?')
        rn = l.get('rendite_normal', 0) or 0
        rw = l.get('rendite_wg', 0) or 0
        sc = l.get('score', 0) or 0
        url = l.get('url', '')
        title = l.get('title', 'Ohne Titel')
        address = l.get('address', '')

        text = (
            f"*{i}. <{url}|{title}>*\n"
            f":round_pushpin: {address}\n"
            f":euro: {preis_k}k | :door: {zimmer} Zi | "
            f"NV: {rn:.1f}% | WG: {rw:.1f}% | Score: {sc}"
        )

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text}
        })

    if len(listings) > 5:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_+ {len(listings) - 5} weitere Objekte_"}
            ]
        })

    return {"blocks": blocks}


def _send_slack(listings):
    """Sendet die Nachricht an Slack via Bot Token (bevorzugt) oder Webhook."""
    if not SLACK_BOT_TOKEN and not SLACK_WEBHOOK_URL:
        logger.warning("Weder SLACK_BOT_TOKEN noch SLACK_WEBHOOK_URL gesetzt - Slack uebersprungen")
        return False

    payload = _build_slack_message(listings)

    try:
        if SLACK_BOT_TOKEN:
            # Bevorzugt: Slack Web API mit explizitem Channel
            payload["channel"] = SLACK_CHANNEL
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                timeout=15
            )
            data = resp.json()
            if data.get("ok"):
                logger.info(f"Slack ({SLACK_CHANNEL}): {len(listings)} Objekte erfolgreich gesendet")
                return True
            else:
                logger.error(f"Slack API Fehler: {data.get('error', 'unbekannt')}")
                return False
        else:
            # Fallback: Webhook
            resp = requests.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=15
            )
            if resp.status_code == 200:
                logger.info(f"Slack: {len(listings)} Objekte erfolgreich gesendet")
                return True
            else:
                logger.error(f"Slack Fehler: {resp.status_code} - {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Slack Benachrichtigung fehlgeschlagen: {e}")
        return False


def notify(listings, config, dry_run=False):
    """Benachrichtigung ueber neue Listings (Slack + Log)."""
    if not listings:
        logger.info(f"[{datetime.now().strftime('%d.%m.%Y')}] Keine neuen interessanten Objekte.")
        return True

    if dry_run:
        logger.info(f"[DRY-RUN] Wuerde {len(listings)} Objekte melden")
        return True

    # Slack-Nachricht senden
    _send_slack(listings)

    # Log-Ausgabe (wie bisher)
    top5 = sorted(listings, key=lambda x: x.get('score', 0), reverse=True)[:5]

    logger.info(f"=== {len(listings)} neue interessante Objekte ===")
    for i, l in enumerate(top5, 1):
        preis_k = int((l.get('price', 0) or 0) / 1000)
        rn = l.get('rendite_normal', 0) or 0
        rw = l.get('rendite_wg', 0) or 0
        sc = l.get('score', 0) or 0
        logger.info(
            f"  {i}. {l.get('rooms', '?')} Zi {preis_k}k | "
            f"NV:{rn:.1f}% WG:{rw:.1f}% | Score:{sc}"
        )

    if len(listings) > 5:
        logger.info(f"  + {len(listings) - 5} weitere")

    return True
