#!/usr/bin/env python3
"""Aggiorna i dati della Bussola Parlamentare dai dati aperti di Camera e Senato.

Uso:
  python scripts/aggiorna.py --dati site/data                 # aggiornamento normale
  python scripts/aggiorna.py --dati site/data --ramo camera   # solo la Camera
  python scripts/aggiorna.py --dati site/data --max-minuti 60 # si ferma dopo un'ora e riprende al giro dopo
  python scripts/aggiorna.py --dati site/data --solo-calcoli  # ricalcola gli indicatori senza scaricare

La prima volta scarica l'intera legislatura (alcune ore): se il tempo finisce,
salva quello che ha fatto e al giro successivo riparte da lì.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import camera  # noqa: E402
import senato  # noqa: E402
from calcoli import Calcolo, in_carica, unisci_intervalli  # noqa: E402
from comune import CATEGORIE, categoria, leggi_json, nome_locale, scrivi_json  # noqa: E402
from sparql import Endpoint  # noqa: E402

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVVISI = []


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def avviso(msg):
    AVVISI.append(msg)
    print(f"::warning::{msg}", flush=True)


# ---------- gruppi: regole di attribuzione (config/gruppi.json) ----------
def carica_regole():
    cfg = leggi_json(os.path.join(RADICE, "config", "gruppi.json"), {"regole": []})
    for r in cfg["regole"]:
        r["_rx"] = re.compile(r["cerca"], re.I)
    return cfg["regole"]


def classifica_gruppo(ramo, sigla, nome, regole):
    testo = f"{sigla} {nome}"
    for r in regole:
        if r.get("ramo", "*") in ("*", ramo) and r["_rx"].search(testo):
            return {"chiave": r["chiave"], "breve": r["breve"], "coal": r["coalizione"]}
    breve = sigla or (nome[:22] + "…" if len(nome) > 23 else nome)
    return {"chiave": "altro_" + re.sub(r"\W+", "", breve.lower())[:12], "breve": breve, "coal": "altro"}


def gid_di(uri):
    loc = nome_locale(uri)
    return ("g" + loc) if loc[:1].isdigit() else loc


# ---------- archivio mensile ----------
def file_mese(cart, mese):
    return os.path.join(cart, "votazioni", f"{mese}.json")


def salva_unita(cart, chiave_unita, records):
    """Sostituisce nel file del mese le votazioni di quella unità (giorno o seduta)."""
    per_mese = {}
    for r in records:
        per_mese.setdefault(r["d"][:7], []).append(r)
    mesi = set(per_mese) | {m for m in [chiave_unita.get("mese")] if m}
    for mese in mesi:
        p = file_mese(cart, mese)
        dati = leggi_json(p, {"votazioni": []})
        tenute = [v for v in dati["votazioni"] if v.get("k") != chiave_unita["k"]]
        tenute += per_mese.get(mese, [])
        tenute.sort(key=lambda v: (v["d"], v.get("s") or "", v.get("n") or 0, v["id"]))
        dati["votazioni"] = tenute
        scrivi_json(p, dati)


def costruisci_record(v, k, indice_uri, membri_per_i):
    n = len(membri_per_i)
    codici = ["."] * n
    for i in range(n):
        if in_carica(membri_per_i[i]["mandati"], v["d"]):
            codici[i] = "-"
    for uri, c in v["voti"].items():
        i = indice_uri.get(uri)
        if i is not None:
            codici[i] = c
    testo = " ".join(x for x in (v.get("o"), v.get("t")) if x)
    legale = v.get("numero_legale") or bool(re.search(r"numero legale", testo, re.I))
    cat = categoria(testo, v.get("finale"), v.get("fiducia"), legale)
    flag = ("F" if cat == "finale" or v.get("finale") else "") + ("S" if v.get("segreta") else "") + \
           ("Q" if v.get("fiducia") else "") + ("L" if legale else "")
    t = v.get("tot", {})
    tot = [t.get(x) for x in ("presenti", "votanti", "favorevoli", "contrari", "astenuti", "maggioranza")]
    rec = {
        "id": nome_locale(v["id"]), "k": k, "d": v["d"], "n": v.get("n"), "s": v.get("seduta"),
        "t": (v.get("t") or "").strip(), "o": (v.get("o") or "").strip(), "c": cat, "f": flag,
        "e": None if v.get("esito") is None else int(bool(v["esito"])),
        "tot": tot, "v": "".join(codici).rstrip("."), "u": v.get("url"),
    }
    conta = {x: rec["v"].count(x) for x in "FCA"}
    if not v.get("segreta") and tot[2] is not None and conta["F"] + conta["C"] + conta["A"] > 0:
        diff = [conta["F"] - (tot[2] or 0), conta["C"] - (tot[3] or 0), conta["A"] - (tot[4] or 0)]
        if any(diff):
            rec["chk"] = diff
    return rec


# ---------- anagrafe ----------
def aggiorna_anagrafe(ramo, cart, roster, ades, gruppi_raw, capi, regole):
    prec = leggi_json(os.path.join(cart, "membri.json"), {"membri": [], "gruppi": {}})
    vecchi = {m["id"]: m for m in prec["membri"]}
    indice_uri = {m["id"]: m["i"] for m in prec["membri"]}
    prossimo = max(indice_uri.values(), default=-1) + 1
    for uri in sorted(roster):
        if uri not in indice_uri:
            indice_uri[uri] = prossimo
            prossimo += 1
    per_membro = {}
    for a in ades:
        per_membro.setdefault(a["id"], []).append((gid_di(a["g"]), a["da"], a["a"]))
    capi_m = {}
    for c in capi:
        capi_m.setdefault(c["id"], []).append((gid_di(c["g"]), c["da"], c["a"]))
    membri = [None] * prossimo
    for uri, i in indice_uri.items():
        base = roster.get(uri) or vecchi.get(uri)
        if base is None:
            base = {"id": uri, "nome": "", "cognome": nome_locale(uri), "sesso": "", "mandati": []}
        m = {
            "i": i, "id": uri, "nome": base.get("nome", ""), "cognome": base.get("cognome", ""),
            "sesso": base.get("sesso", ""), "tipo": base.get("tipo", ""),
            "mandati": base.get("mandati", []),
            "adesioni": unisci_intervalli(per_membro[uri]) if uri in per_membro else (vecchi.get(uri, {}).get("adesioni") or []),
            "capo": unisci_intervalli(capi_m[uri]) if uri in capi_m else [],
        }
        membri[i] = m
    gruppi = dict(prec.get("gruppi", {}))
    for uri, g in gruppi_raw.items():
        gid = gid_di(uri)
        info = {"uri": uri, "nome": g["nome"], "sigla": g.get("sigla", "")}
        info.update(classifica_gruppo(ramo, info["sigla"], info["nome"], regole))
        gruppi[gid] = info
    for m in membri:  # gruppi citati nelle adesioni ma senza nome
        for gid, _, _ in m["adesioni"]:
            if gid not in gruppi:
                gruppi[gid] = {"uri": "", "nome": gid, "sigla": "", **classifica_gruppo(ramo, "", gid, regole)}
    return membri, gruppi, indice_uri


def salva_anagrafe(cart, membri, gruppi, extra=None):
    dati = {"membri": membri, "gruppi": gruppi}
    if extra:
        dati.update(extra)
    scrivi_json(os.path.join(cart, "membri.json"), dati)


# ---------- un ramo ----------
def aggiorna_ramo(ramo, dati_dir, scadenza, rifai, endpoint_url, solo_calcoli, regole, pausa):
    mod = camera if ramo == "camera" else senato
    cart = os.path.join(dati_dir, ramo)
    os.makedirs(os.path.join(cart, "votazioni"), exist_ok=True)
    stato = leggi_json(os.path.join(cart, "stato.json"), {"fatti": {}})
    ep = Endpoint(endpoint_url or mod.ENDPOINT, ramo, pausa=pausa, log=lambda *a: log(*a))
    rimaste = 0

    if not solo_calcoli:
        log(f"[{ramo}] anagrafe e gruppi")
        roster = mod.membri(ep)
        ades = mod.adesioni(ep)
        gruppi_raw = mod.gruppi(ep)
        if ramo == "camera":
            try:
                capi = camera.incarichi_gruppo(ep)
            except Exception as e:  # noqa: BLE001
                log(f"[camera] capigruppo non disponibili: {e}")
                capi = []
        else:
            capi = [a for a in ades if a.get("carica", "").strip().lower() == "presidente"]
        if len(roster) < (300 if ramo == "camera" else 150):
            raise RuntimeError(f"anagrafe incompleta: solo {len(roster)} membri")
        # iscritti a un gruppo della legislatura ma senza mandato collegato (senatori a vita)
        senza_mandato = {a["id"] for a in ades} - set(roster)
        if senza_mandato and ramo == "senato":
            roster.update(senato.membri_extra(ep, senza_mandato))
        log(f"[{ramo}] {len(roster)} membri, {len(ades)} adesioni, {len(gruppi_raw)} gruppi, {len(capi)} incarichi di capogruppo")
        membri, gruppi, indice_uri = aggiorna_anagrafe(ramo, cart, roster, ades, gruppi_raw, capi, regole)
        salva_anagrafe(cart, membri, gruppi)

        if ramo == "camera":
            unita = [{"k": g, "d": g, "mese": g[:7]} for g in camera.giorni(ep)]
        else:
            unita = [{"k": nome_locale(s["uri"]), "d": s["d"], "mese": s["d"][:7], "seduta": s} for s in senato.sedute(ep)]
        unita.sort(key=lambda u: (u["d"], u["k"]))
        if not unita:
            raise RuntimeError("nessuna votazione trovata: l'endpoint risponde ma la query non restituisce date; "
                               "controllare scripts/" + ramo + ".py")
        fatti = stato["fatti"]
        recenti = {u["k"] for u in unita[-rifai:]} if rifai else set()
        da_fare = [u for u in unita if u["k"] not in fatti or u["k"] in recenti]
        log(f"[{ramo}] {len(unita)} {'giorni' if ramo == 'camera' else 'sedute'} con votazioni, da scaricare: {len(da_fare)}")

        for n, u in enumerate(da_fare, 1):
            if time.time() > scadenza:
                rimaste = len(da_fare) - n + 1
                avviso(f"{ramo}: tempo esaurito, restano {rimaste} {'giorni' if ramo == 'camera' else 'sedute'}; riprendo al prossimo aggiornamento")
                break
            try:
                vot = camera.votazioni_giorno(ep, u["d"]) if ramo == "camera" else senato.votazioni_seduta(ep, u["seduta"])
            except Exception as e:  # noqa: BLE001
                avviso(f"{ramo}: impossibile scaricare {u['k']} ({e})")
                continue
            ignoti = {uri for v in vot for uri in v["voti"] if uri not in indice_uri}
            if ignoti:
                extra = senato.membri_extra(ep, ignoti) if ramo == "senato" else {}
                for uri in sorted(ignoti):
                    indice_uri[uri] = len(membri)
                    x = extra.get(uri) or {"nome": "", "cognome": nome_locale(uri), "sesso": "", "mandati": []}
                    sue = [(gid_di(a["g"]), a["da"], a["a"]) for a in ades if a["id"] == uri]
                    membri.append({"i": len(membri), "id": uri, "nome": x.get("nome", ""), "cognome": x.get("cognome", ""),
                                   "sesso": x.get("sesso", ""), "tipo": x.get("tipo", ""), "mandati": x.get("mandati", []),
                                   "adesioni": unisci_intervalli(sue), "capo": []})
                log(f"[{ramo}] aggiunti {len(ignoti)} votanti non presenti in anagrafe")
                salva_anagrafe(cart, membri, gruppi)
            records = [costruisci_record(v, u["k"], indice_uri, membri) for v in vot]
            salva_unita(cart, u, records)
            fatti[u["k"]] = {"d": u["d"], "n": len(records)}
            scrivi_json(os.path.join(cart, "stato.json"), stato)
            if n % 10 == 0 or n == len(da_fare):
                log(f"[{ramo}] {n}/{len(da_fare)} · {u['d']} · {len(records)} votazioni · {ep.richieste} richieste")

    # ---- indicatori su tutto l'archivio
    log(f"[{ramo}] calcolo degli indicatori")
    anag = leggi_json(os.path.join(cart, "membri.json"))
    if not anag:
        raise RuntimeError("nessuna anagrafe salvata")
    membri, gruppi = anag["membri"], anag["gruppi"]
    for g in gruppi.values():  # riapplica le regole: si possono correggere senza riscaricare
        g.update(classifica_gruppo(ramo, g.get("sigla", ""), g.get("nome", ""), regole))
    mesi = sorted(glob.glob(os.path.join(cart, "votazioni", "*.json")))
    per_file = [(p, leggi_json(p)["votazioni"]) for p in mesi]
    tutte = [v for _, vs in per_file for v in vs]
    oggi = dt.date.today().isoformat()
    ris = Calcolo(membri, gruppi, tutte, oggi).esegui()
    for p, vs in per_file:
        scrivi_json(p, {"votazioni": vs})
    righe = [[v["id"], v["d"], v.get("n"), v.get("t", "")[:200], v.get("o", "")[:200], v["c"], v["f"],
              v.get("e"), v["v"].count("F"), v["v"].count("C"), v["v"].count("A"), v.get("p", ""),
              v.get("pm", "-"), v.get("tot", [None] * 6)[2:5]] for v in tutte]
    scrivi_json(os.path.join(cart, "indice.json"), {
        "campi": ["id", "data", "numero", "titolo", "oggetto", "categoria", "flag", "esito",
                  "F", "C", "A", "posizioni", "maggioranza", "ufficiali_FCA"],
        "gruppi": ris["ordine"], "righe": righe,
    })
    salva_anagrafe(cart, membri, gruppi)
    scrivi_json(os.path.join(cart, "gruppi.json"), {
        "gruppi": ris["gruppi"], "convergenza": ris["convergenza"], "cambi": ris["cambi"],
    })
    in_c = sum(1 for m in membri if in_carica(m["mandati"], oggi))
    return {
        "votazioni": len(tutte),
        "ultima": max((v["d"] for v in tutte), default=None),
        "prima": min((v["d"] for v in tutte), default=None),
        "membri_in_carica": in_c,
        "membri_totali": len(membri),
        "da_scaricare": rimaste,
        "richieste": ep.richieste,
        "controllo_totali": sum(1 for v in tutte if v.get("chk")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dati", default=os.path.join(RADICE, "site", "data"))
    ap.add_argument("--ramo", choices=["camera", "senato", "tutti"], default="tutti")
    ap.add_argument("--max-minuti", type=float, default=330)
    ap.add_argument("--rifai", type=int, default=5, help="riscarica le ultime N unità (dati pubblicati in ritardo)")
    ap.add_argument("--solo-calcoli", action="store_true")
    ap.add_argument("--pausa", type=float, default=0.35, help="secondi di pausa tra una richiesta e l'altra")
    a = ap.parse_args()

    inizio = time.time()
    regole = carica_regole()
    rami = ["camera", "senato"] if a.ramo == "tutti" else [a.ramo]
    meta_p = os.path.join(a.dati, "meta.json")
    meta = leggi_json(meta_p, {"rami": {}})
    falliti = 0
    for i, ramo in enumerate(rami):
        # il tempo si divide tra i rami rimasti, lasciando 8 minuti per i calcoli finali
        restante = a.max_minuti * 60 - (time.time() - inizio) - 8 * 60 * (len(rami) - i)
        scadenza = time.time() + max(restante / (len(rami) - i), 60)
        url = os.environ.get(f"BUSSOLA_{ramo.upper()}_ENDPOINT")
        AVVISI.clear()
        try:
            ris = aggiorna_ramo(ramo, a.dati, scadenza, a.rifai, url, a.solo_calcoli, regole, a.pausa)
            ris["aggiornato"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            ris["avvisi"] = list(AVVISI)
            meta["rami"][ramo] = ris
            log(f"[{ramo}] fatto: {json.dumps(ris, ensure_ascii=False)}")
        except Exception as e:  # noqa: BLE001
            falliti += 1
            print(f"::error::{ramo}: aggiornamento non riuscito: {e}", flush=True)
            meta["rami"].setdefault(ramo, {})["errore"] = f"{dt.date.today().isoformat()}: {e}"
    meta["aggiornato"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    meta["categorie"] = CATEGORIE
    meta["fonti"] = {
        "camera": {"nome": "Camera dei deputati, dati.camera.it", "url": "https://dati.camera.it/", "licenza": "CC BY-SA 4.0"},
        "senato": {"nome": "Senato della Repubblica, dati.senato.it", "url": "https://dati.senato.it/", "licenza": "CC BY 3.0"},
    }
    scrivi_json(meta_p, meta, compatto=False)
    if falliti == len(rami) and not any(meta["rami"].get(r, {}).get("votazioni") for r in rami):
        sys.exit(1)


if __name__ == "__main__":
    main()
