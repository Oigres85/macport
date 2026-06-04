#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robot dati per "Catena Macro -> Portafoglio".
Scarica quote da Stooq (gratis, senza chiave), calcola lo stato dei 6 driver macro
e la matrice di trasmissione sui titoli, e salva tutto in data.json.
Gira su GitHub Actions ogni ora durante i mercati. Nessuna dipendenza esterna: solo stdlib.
"""

import json, urllib.request, datetime, sys

# ---- simboli Stooq ----
# driver macro
DRIVERS_SYM = {
    "US10Y":    "10usy.b",   # rendimento Treasury 10 anni
    "PETROLIO": "cl.f",      # WTI crude futures
    "BITCOIN":  "btcusd",    # bitcoin
    "EUR/USD":  "eurusd",    # cambio
    "VIX":      "^vix",      # volatilita CBOE
    "TAIWAN / SEMI": "smh.us" # proxy: ETF semiconduttori (catena TSMC/AI)
}
# i tuoi 8 titoli
TITOLI_SYM = {
    "NVDA":"nvda.us","AMD":"amd.us","MU":"mu.us","INTC":"intc.us",
    "TSLA":"tsla.us","MSTR":"mstr.us","RGTI":"rgti.us","ARBE":"arbe.us"
}
SETT = {"NVDA":"SEMI","AMD":"SEMI","MU":"SEMI","INTC":"SEMI",
        "TSLA":"AUTO","MSTR":"CRYPTO","RGTI":"QUANTUM","ARBE":"RADAR"}
BETA = {"NVDA":1.45,"AMD":2.00,"MU":1.50,"INTC":1.10,
        "TSLA":2.00,"MSTR":2.42,"RGTI":3.00,"ARBE":2.00}

# ---- esposizione STRUTTURALE titolo->driver (segno+intensita, -2..+2) ----
# indica come il titolo reagisce quando il driver e in stato FAVOREVOLE.
# Il segno netto del giorno = esposizione * direzione_attuale_driver.
EXPO = {
  "NVDA":{"US10Y":2,"PETROLIO":1,"BITCOIN":0,"EUR/USD":1,"VIX":1,"TAIWAN / SEMI":2},
  "AMD": {"US10Y":1,"PETROLIO":1,"BITCOIN":0,"EUR/USD":1,"VIX":2,"TAIWAN / SEMI":2},
  "MU":  {"US10Y":2,"PETROLIO":1,"BITCOIN":0,"EUR/USD":1,"VIX":1,"TAIWAN / SEMI":2},
  "INTC":{"US10Y":1,"PETROLIO":1,"BITCOIN":0,"EUR/USD":1,"VIX":1,"TAIWAN / SEMI":1},
  "TSLA":{"US10Y":1,"PETROLIO":2,"BITCOIN":0,"EUR/USD":1,"VIX":2,"TAIWAN / SEMI":0},
  "MSTR":{"US10Y":1,"PETROLIO":0,"BITCOIN":2,"EUR/USD":1,"VIX":2,"TAIWAN / SEMI":0},
  "RGTI":{"US10Y":2,"PETROLIO":1,"BITCOIN":0,"EUR/USD":1,"VIX":2,"TAIWAN / SEMI":1},
  "ARBE":{"US10Y":1,"PETROLIO":0,"BITCOIN":0,"EUR/USD":1,"VIX":2,"TAIWAN / SEMI":0},
}

STOOQ = "https://stooq.com/q/l/?s={}&f=sd2t2ohlcv&h&e=csv"

def fetch(sym):
    """Ritorna (last, change_pct) o (None,None) se non disponibile."""
    try:
        url = STOOQ.format(sym)
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8","ignore")
        lines = raw.strip().splitlines()
        if len(lines) < 2:
            return None, None
        cols = lines[1].split(",")
        # formato: Symbol,Date,Time,Open,High,Low,Close,Volume
        o = float(cols[3]); c = float(cols[6])
        chg = (c/o - 1.0)*100 if o else 0.0
        return c, chg
    except Exception as e:
        sys.stderr.write("warn %s: %s\n" % (sym, e))
        return None, None

def direction(name, last, chg):
    """Ritorna (pos, stato, dsign).
    pos = posizione sulla barra FAVOREVOLE(0,sinistra,verde) -> AVVERSO(100,destra,rosso),
    SEMPRE coerente con lo stato/colore. dsign=+1 favorevole ai growth, -1 avverso, 0 neutro."""
    if last is None:
        return 50, "n.d.", 0
    if name == "US10Y":
        fav = last <= 4.5
        return (28 if fav else 75), ("FAVOREVOLE" if fav else "AVVERSO"), (1 if fav else -1)
    if name == "PETROLIO":
        adv = last >= 85
        return (75 if adv else 28), ("AVVERSO" if adv else "FAVOREVOLE"), (-1 if adv else 1)
    if name == "BITCOIN":
        adv = last < 72000
        return (80 if adv else 28), ("AVVERSO" if adv else "FAVOREVOLE"), (-1 if adv else 1)
    if name == "EUR/USD":
        adv = last > 1.15
        return (60 if adv else 45), ("AVVERSO LIEVE" if adv else "NEUTRO"), (-1 if adv else 0)
    if name == "VIX":
        if last < 18:  return 35, "FAVOREVOLE (fragile)", 1
        if last < 28:  return 65, "ALLERTA", -1
        return 90, "CAPITOLAZIONE", -1
    if name == "TAIWAN / SEMI":
        fav = (chg is None or chg >= -1)
        return (25 if fav else 60), ("FAVOREVOLE" if fav else "MONITORARE"), (1 if fav else -1)
    return 50, "n.d.", 0

def main():
    drivers = []
    dir_sign = {}
    for name, sym in DRIVERS_SYM.items():
        last, chg = fetch(sym)
        pos, stato, dsign = direction(name, last, chg)
        dir_sign[name] = dsign
        if name == "BITCOIN":   val = ("$%.1fk" % (last/1000)) if last else "n.d."
        elif name == "US10Y":   val = ("%.2f%%" % last) if last else "n.d."
        elif name == "EUR/USD": val = ("%.3f" % last) if last else "n.d."
        elif name == "PETROLIO":val = ("$%.0f" % last) if last else "n.d."
        elif name == "VIX":     val = ("%.1f" % last) if last else "n.d."
        else:                   val = (("%+.1f%%" % chg) if chg is not None else "n.d.")
        drivers.append({"k":name,"val":val,"pos":round(pos),"stato":stato,
                        "chg":(round(chg,1) if chg is not None else None),
                        "fresh": last is not None})

    titoli = []
    for t, sym in TITOLI_SYM.items():
        last, chg = fetch(sym)
        net_exp = {}
        for dname in DRIVERS_SYM:
            # effetto netto oggi = esposizione strutturale * direzione driver, limitato a [-2,2]
            e = EXPO[t][dname] * dir_sign.get(dname, 0)
            e = max(-2, min(2, e))
            net_exp[dname] = e
        titoli.append({"t":t,"sec":SETT[t],"beta":BETA[t],
                        "chg":(round(chg,1) if chg is not None else None),
                        "fresh": last is not None, "exp":net_exp})

    out = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "drivers": drivers,
        "titoli": titoli
    }
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("data.json scritto:", out["updated"])
    print(json.dumps(out, ensure_ascii=False)[:400])

if __name__ == "__main__":
    main()
