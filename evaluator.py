"""
Bierdeckelrechnung nach Immocation-Methode
==========================================

Kernformel: Bruttomietrendite = (Jahreskaltmiete / Kaufpreis) * 100

Deine Kriterien:
- Normalvermietung: mind. 5% Bruttomietrendite
- WG-Vermietung:    mind. 6% Bruttomietrendite
- Max. Kaufpreis:   110.000 EUR pro Zimmer

Kaufnebenkosten BW (ohne Makler): ~7%
Kaufnebenkosten BW (mit Makler):  ~10.57%
"""

import re
import logging

logger = logging.getLogger(__name__)


class BierdeckelEvaluator:
      def __init__(self, config: dict):
                self.config = config
                self.bd = config.get('bierdeckel', {})
                self.scoring = config.get('scoring', {})
                self.bonus_config = config.get('bonus', {})

          # Normalvermietung
                self.miete_normal_qm = self.bd.get('normal', {}).get('rent_per_sqm', 12.0)
                self.min_rendite_normal = self.bd.get('normal', {}).get('min_rendite_pct', 5.0)

          # WG-Vermietung
                self.miete_wg_zimmer = self.bd.get('wg', {}).get('rent_per_room', 420.0)
                self.min_rendite_wg = self.bd.get('wg', {}).get('min_rendite_pct', 6.0)

          # Kaufnebenkosten
                self.nk_ohne_makler = self.bd.get('nebenkosten_ohne_makler_pct', 7.0) / 100
                self.nk_mit_makler = self.bd.get('nebenkosten_mit_makler_pct', 10.57) / 100

          # Kriterien
                self.max_preis_pro_zimmer = config.get('price_per_room_max', 110000)
                self.gute_stadtteile = self.bonus_config.get('guter_stadtteil', [])

      def evaluate(self, listing: dict) -> dict:
                """Fuehrt die komplette Bierdeckelrechnung fuer ein Listing durch."""
                result = listing.copy()

          price = listing.get('price', 0) or 0
        rooms = listing.get('rooms', 0) or 0
        sqm = listing.get('sqm', 0) or 0
        title_lower = (listing.get('title', '') + ' ' + listing.get('description', '')).lower()
        address = listing.get('address', '').lower()

        # --- BIERDECKELRECHNUNG NORMALVERMIETUNG ---
        if price > 0 and sqm > 0:
                      jahreskaltmiete_normal = self.miete_normal_qm * sqm * 12
                      rendite_normal = (jahreskaltmiete_normal / price) * 100
                      kaufpreis_faktor = price / jahreskaltmiete_normal  # z.B. 20 = 5%
            monatliche_miete_normal = self.miete_normal_qm * sqm
elif price > 0 and rooms > 0:
            # Fallback: Schaetze 25 m² pro Zimmer
            sqm_est = rooms * 25
            jahreskaltmiete_normal = self.miete_normal_qm * sqm_est * 12
            rendite_normal = (jahreskaltmiete_normal / price) * 100
            kaufpreis_faktor = price / jahreskaltmiete_normal
            monatliche_miete_normal = self.miete_normal_qm * sqm_est
else:
            rendite_normal = 0
              kaufpreis_faktor = 0
            monatliche_miete_normal = 0

        # --- BIERDECKELRECHNUNG WG-VERMIETUNG ---
        if price > 0 and rooms >= 1:
                      # WG: vermietbare Zimmer = rooms (alle Zimmer)
                      vermietbare_zimmer = max(1, int(rooms))
                      jahreskaltmiete_wg = self.miete_wg_zimmer * vermietbare_zimmer * 12
                      rendite_wg = (jahreskaltmiete_wg / price) * 100
                      monatliche_miete_wg = self.miete_wg_zimmer * vermietbare_zimmer
else:
            rendite_wg = 0
            monatliche_miete_wg = 0

        # --- KAUFPREIS PRO ZIMMER ---
        if rooms > 0 and price > 0:
                      preis_pro_zimmer = price / rooms
else:
            preis_pro_zimmer = 0

        # --- SONDERMERKMALE ---
        leerstand_keywords = ['leerstand', 'leer stehend', 'leerstehend', 'sofort beziehbar',
                                                            'frei ab sofort', 'sofort verfuegbar', 'unbewohnt']
        leerstand = any(kw in title_lower for kw in leerstand_keywords)

        wg_keywords = ['wg', 'wg-geeignet', 'wg geeignet', 'wohngemeinschaft',
                                              'einzelzimmer', 'mehrzimmerwohnung', 'studenten']
        wg_geeignet = rooms >= 2 and any(kw in title_lower for kw in wg_keywords)
        if rooms >= 3:
                      wg_geeignet = True  # Ab 3 Zimmern immer WG-geeignet

        gute_lage = any(stadtteil.lower() in address for stadtteil in self.gute_stadtteile)

        # --- SCORING (0-100 Punkte) ---
        score = 0

        # 1. Rendite Normalvermietung (max 35 Punkte)
        rendite_score_normal = self.scoring.get('rendite_normal', 35)
        if rendite_normal >= self.min_rendite_normal:
                      # Ueber Schwelle: volle Punkte + Bonus fuer Ueberperformance
                      ueber_schwelle = rendite_normal - self.min_rendite_normal
                      score += min(rendite_score_normal, rendite_score_normal * (0.8 + ueber_schwelle * 0.1))
elif rendite_normal > 0:
            # Unter Schwelle: proportional
            ratio = rendite_normal / self.min_rendite_normal
            score += rendite_score_normal * ratio * 0.6

        # 2. Rendite WG-Vermietung (max 25 Punkte)
        rendite_score_wg = self.scoring.get('rendite_wg', 25)
        if rendite_wg >= self.min_rendite_wg:
                      ueber_schwelle = rendite_wg - self.min_rendite_wg
                      score += min(rendite_score_wg, rendite_score_wg * (0.8 + ueber_schwelle * 0.1))
elif rendite_wg > 0:
            ratio = rendite_wg / self.min_rendite_wg
            score += rendite_score_wg * ratio * 0.6

        # 3. Preis pro Zimmer (max 20 Punkte)
        preis_score = self.scoring.get('preis_pro_zimmer', 20)
        if preis_pro_zimmer > 0:
                      if preis_pro_zimmer <= self.max_preis_pro_zimmer:
                                        # Unter Grenze: volle Punkte + Bonus je guenstiger
                                        unterschreitung = (self.max_preis_pro_zimmer - preis_pro_zimmer) / self.max_preis_pro_zimmer
                                        score += min(preis_score, preis_score * (0.7 + unterschreitung * 0.5))
        else:
                # Ueber Grenze: deutliche Abwertung
                          ueberschreitung = preis_pro_zimmer / self.max_preis_pro_zimmer
                score += max(0, preis_score * (1 - ueberschreitung) * 0.3)

        # 4. Gute Lage (max 10 Punkte)
        if gute_lage:
                      score += self.scoring.get('lage', 10)

        # 5. Leerstand Bonus (max 5 Punkte)
        if leerstand:
                      score += self.scoring.get('leerstand', 5)

        # 6. WG-geeignet Bonus (max 5 Punkte)
        if wg_geeignet:
                      score += self.scoring.get('wg_geeignet', 5)

        gesamtscore = min(100, int(score))

        # --- BIERDECKEL ZUSAMMENFASSUNG ---
        bierdeckel_summary = self._create_summary(
                      price, sqm, rooms, rendite_normal, rendite_wg,
                      kaufpreis_faktor, preis_pro_zimmer,
                      monatliche_miete_normal, monatliche_miete_wg,
                      leerstand, wg_geeignet
        )

        result.update({
                      'rendite_normal': round(rendite_normal, 2),
                      'rendite_wg': round(rendite_wg, 2),
                      'kaufpreis_faktor': round(kaufpreis_faktor, 1),
                      'preis_pro_zimmer': round(preis_pro_zimmer, 0),
                      'monatliche_miete_normal': round(monatliche_miete_normal, 0),
                      'monatliche_miete_wg': round(monatliche_miete_wg, 0),
                      'gesamtscore': gesamtscore,
                      'score_normal': round(rendite_normal, 2),
                      'score_wg': round(rendite_wg, 2),
                      'ok_normal': rendite_normal >= self.min_rendite_normal,
                      'ok_wg': rendite_wg >= self.min_rendite_wg,
                      'ok_preis_pro_zimmer': preis_pro_zimmer <= self.max_preis_pro_zimmer if preis_pro_zimmer > 0 else False,
                      'leerstand': leerstand,
                      'wg_geeignet': wg_geeignet,
                      'gute_lage': gute_lage,
                      'bierdeckel_summary': bierdeckel_summary
        })

        logger.debug(f"Bewertet: {listing.get('title', 'N/A')} | "
                                         f"Rendite N:{rendite_normal:.1f}% WG:{rendite_wg:.1f}% | "
                                         f"Score:{gesamtscore}")

        return result

    def _create_summary(self, price, sqm, rooms, rendite_normal, rendite_wg,
                                                kaufpreis_faktor, preis_pro_zimmer,
                                                miete_normal, miete_wg, leerstand, wg_geeignet):
                                                          """Erstellt die Bierdeckel-Zusammenfassung als String."""
                                                          lines = [
                                                              "=== BIERDECKELRECHNUNG (Immocation-Methode) ===",
                                                              f"Kaufpreis:          {price:>10,.0f} EUR",
                                                          ]
                                                          if sqm > 0:
                                                                        lines.append(f"Wohnflaeche:        {sqm:>10.0f} m2")
                                                                    if rooms > 0:
                                                                                  lines.append(f"Zimmer:             {rooms:>10.1f}")
                                                                              if preis_pro_zimmer > 0:
                                                                                            ok = "OK" if preis_pro_zimmer <= self.max_preis_pro_zimmer else "HOCH"
                                                                                            lines.append(f"Preis/Zimmer:       {preis_pro_zimmer:>10,.0f} EUR [{ok}]")

        lines.append("")
        lines.append("--- NORMALVERMIETUNG ---")
        lines.append(f"Miete (kalt):       {miete_normal:>10,.0f} EUR/Monat")
        lines.append(f"Jahreskaltmiete:    {miete_normal*12:>10,.0f} EUR")
        lines.append(f"Kaufpreisfaktor:    {kaufpreis_faktor:>10.1f}x  (Faktor 20 = 5%)")
        ok_normal = "OK (>= 5%)" if rendite_normal >= self.min_rendite_normal else f"NEIN (< 5%)"
        lines.append(f"Bruttomietrendite:  {rendite_normal:>10.2f}% [{ok_normal}]")

        if rooms >= 2:
                      lines.append("")
            lines.append("--- WG-VERMIETUNG ---")
            zimmer_wg = max(1, int(rooms))
            lines.append(f"Zimmer vermietbar:  {zimmer_wg:>10}")
            lines.append(f"Miete/Zimmer:       {self.miete_wg_zimmer:>10,.0f} EUR kalt")
            lines.append(f"Gesamtmiete:        {miete_wg:>10,.0f} EUR/Monat")
            ok_wg = "OK (>= 6%)" if rendite_wg >= self.min_rendite_wg else f"NEIN (< 6%)"
            lines.append(f"Bruttomietrendite:  {rendite_wg:>10.2f}% [{ok_wg}]")

        lines.append("")
        lines.append("--- KAUFNEBENKOSTEN BW ---")
        lines.append(f"Ohne Makler (~7%):  {price * self.nk_ohne_makler:>10,.0f} EUR")
        lines.append(f"Mit Makler (~10.6%): {price * self.nk_mit_makler:>9,.0f} EUR")
        lines.append(f"Gesamtinvest o.M.:  {price * (1 + self.nk_ohne_makler):>10,.0f} EUR")

        if leerstand:
                      lines.append("")
            lines.append("[+] LEERSTAND: Sofort vermietbar - kein Mietausfall")
        if wg_geeignet:
                      lines.append("[+] WG-GEEIGNET: WG-Vermietung moeglich")

        return "\n".join(lines)
