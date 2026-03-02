"""
Immo-Scanner Notifier - Log-basierte Benachrichtigungen
Twilio wurde entfernt. Benachrichtigungen laufen ueber die PWA (Browser-Notifications).
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def notify(listings, config, dry_run=False):
    """Log-basierte Benachrichtigung ueber neue Listings."""
    if not listings:
        logger.info(f"[{datetime.now().strftime('%d.%m.%Y')}] Keine neuen interessanten Objekte.")
        return True

    if dry_run:
        logger.info(f"[DRY-RUN] Wuerde {len(listings)} Objekte melden")
        return True

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
