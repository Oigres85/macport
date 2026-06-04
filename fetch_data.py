#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robot dati per "Catena Macro -> Portafoglio".
Scarica quote da Stooq + news da Google News RSS (entrambi gratis, senza chiave).
Calcola stato dei 6 driver macro, matrice di trasmissione sui titoli, e raccoglie le news.
Salva tutto in data.json. Gira su GitHub Actions. Solo stdlib Python.
"""

import json, urllib.request, urllib.parse, datetime, sys, re
import xml.etree.ElementTree as ET

# ---- simboli Stooq ----
DRIVERS_SYM = {
    "US10Y":    "ief.us",    # proxy: ETF Treasury 7-10a (sale quando i rendimenti scendono)
    "PETROLIO": "cl.f",      # WTI crude futures
    "BITCOIN":  "btcusd",    # bitcoin
    "EUR/USD":  "eurusd",    # cambio
    "VIX":      "vixy.us",   # proxy: ETF VIX short-term
    "TAIWAN / SEMI": "smh.us" # proxy: ETF semiconduttori (catena TSMC/AI)
}
TITOLI_SYM = {
    "NVDA":"nvda.us","AMD":"amd.us","MU":"mu.us","INTC":"intc.us",
    "TSLA":"tsla.us","MSTR":"mstr.us","RGTI":"rgti.us","ARBE":"arbe.us"
}
SETT = {"NVDA":"SEMI","AMD":"SEMI","MU":"SEMI","INTC":"SEMI",
        "TSLA":"AUTO","MSTR":"CRYPTO","RGTI":"QUANTUM","ARBE":"RADAR"}
BETA = {"NVDA":1.45,"AMD":2.00,"MU":1.50,"INTC":1.10,
        "TSLA":2.00,"MSTR":2.42,"RGTI":3.00,"ARBE":2.00}
# nome esteso per la ricerca news
NOME = {"NVDA":"Nvidia","AMD":"AMD","MU":"Micron","INTC":"Intel",
        "TSLA":"Tesla","MSTR":"MicroStrategy","RGTI":"Rigetti","ARBE":"Arbe Robotics"}

# ---- GIUDIZIO CIO per titolo (costante, si aggiorna qui quando cambia la tesi) ----
GIUDIZIO = {
  "NVDA":{"dir":"CORE","hz":"LUNGO","conv":"alta"},
  "AMD": {"dir":"TRIM","hz":"MEDIO","conv":"media"},
  "MU":  {"dir":"HOLD","hz":"MEDIO","conv":"media"},
  "INTC":{"dir":"HOLD-STOP","hz":"BREVE","conv":"bassa"},
  "TSLA":{"dir":"HOLD","hz":"MEDIO","conv":"media"},
  "MSTR":{"dir":"HOLD-STOP","hz":"BREVE","conv":"bassa"},
  "RGTI":{"dir":"HOLD-STOP","hz":"BREVE","conv":"bassa"},
  "ARBE":{"dir":"SELL","hz":"BREVISSIMO","conv":"bassa"},
}

# ---- esposizione STRUTTURALE titolo->driver (come reagisce se il driver e FAVOREVOLE) ----
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

def stop_pct(beta):
    if beta <= 1.2: return 14
    if beta <= 1.6: return 18
    if beta <= 2.1: return 23
    if beta <= 2.6: return 29
    return 34

STOOQ = "https://stooq.com/q/l/?s={}&f=sd2t2ohlcv&h&e=csv"

def fetch(sym):
    """Ritorna (last, change_pct, volume) o (None,None,None)."""
    try:
        req = urllib.request.Request(STOOQ.format(sym), headers={"User-Agent":"Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8","ignore")
        lines = raw.strip().splitlines()
        if len(lines) < 2: return None, None, None
        cols = lines[1].split(",")
        o = float(cols[3]); c = float(cols[6])
        vol = None
        try: vol = float(cols[7])
        except: pass
        chg = (c/o - 1.0)*100 if o else 0.0
        return c, chg, vol
    except Exception as e:
        sys.stderr.write("warn quote %s: %s\n" % (sym, e))
        return None, None, None

def news_for(query, n=2):
    """News fresche da Google News RSS (gratis, no chiave). Ritorna lista di dict."""
    out = []
    try:
        q = urllib.parse.quote(query)
        url = "https://news.google.com/rss/search?q=%s&hl=it&gl=IT&ceid=IT:it" % q
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read()
        root = ET.fromstring(raw)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            src_el = item.find("source")
            src = (src_el.text.strip() if src_el is not None and src_el.text else "")
            # togli " - Fonte" dal titolo se presente
            if src and title.endswith(" - " + src):
                title = title[:-(len(src)+3)]
            # data compatta
            when = ""
            try:
                dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                when = dt.strftime("%d/%m %H:%M")
            except: when = pub[:16]
            out.append({"t":title, "src":src, "link":link, "when":when})
            if len(out) >= n: break
    except Exception as e:
        sys.stderr.write("warn news %s: %s\n" % (query, e))
    return out

def direction(name, last, chg):
    if last is None: return 50, "n.d.", 0
    if name == "US10Y":
        fav = (chg is None) or (chg >= 0)
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
        if chg is None: return 35, "n.d.", 0
        if chg <= 0:    return 32, "FAVOREVOLE (vol calo)", 1
        if chg < 10:    return 60, "VOL IN SALITA", -1
        return 85, "ALLERTA VOL", -1
    if name == "TAIWAN / SEMI":
        fav = (chg is None or chg >= -1)
        return (25 if fav else 60), ("FAVOREVOLE" if fav else "MONITORARE"), (1 if fav else -1)
    return 50, "n.d.", 0

def main():
    drivers = []
    dir_sign = {}
    for name, sym in DRIVERS_SYM.items():
        last, chg, vol = fetch(sym)
        pos, stato, dsign = direction(name, last, chg)
        dir_sign[name] = dsign
        if name == "BITCOIN":   val = ("$%.1fk" % (last/1000)) if last else "n.d."
        elif name == "US10Y":   val = (("rend. \u2193" if (chg is not None and chg>=0) else "rend. \u2191")) if last else "n.d."
        elif name == "EUR/USD": val = ("%.3f" % last) if last else "n.d."
        elif name == "PETROLIO":val = ("$%.0f" % last) if last else "n.d."
        elif name == "VIX":     val = (("vol %+.1f%%" % chg)) if (last and chg is not None) else "n.d."
        else:                   val = (("%+.1f%%" % chg) if chg is not None else "n.d.")
        drivers.append({"k":name,"val":val,"pos":round(pos),"stato":stato,
                        "chg":(round(chg,1) if chg is not None else None),"fresh": last is not None})

    titoli = []
    for t, sym in TITOLI_SYM.items():
        last, chg, vol = fetch(sym)
        net_exp = {}
        for dname in DRIVERS_SYM:
            e = max(-2, min(2, EXPO[t][dname] * dir_sign.get(dname, 0)))
            net_exp[dname] = e
        g = GIUDIZIO[t]
        titoli.append({"t":t,"sec":SETT[t],"beta":BETA[t],
                        "dir":g["dir"],"hz":g["hz"],"conv":g["conv"],"stoppct":stop_pct(BETA[t]),
                        "px":(round(last,2) if last else None),
                        "chg":(round(chg,1) if chg is not None else None),
                        "vol":(int(vol) if vol else None),
                        "fresh": last is not None, "exp":net_exp})

    # ---- NEWS: 1 macro + i 3 titoli col movimento maggiore del giorno ----
    news = {"macro":news_for("Wall Street borsa mercati Federal Reserve", 3), "titoli":{}}
    movers = sorted([x for x in titoli if x["chg"] is not None], key=lambda x: abs(x["chg"]), reverse=True)[:3]
    for m in movers:
        news["titoli"][m["t"]] = news_for(NOME[m["t"]] + " azioni", 2)

    out = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "drivers": drivers, "titoli": titoli, "news": news
    }
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("data.json scritto:", out["updated"])

if __name__ == "__main__":
    main()
