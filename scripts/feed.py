"""Avvisi per tema: feed RSS con le novità di ogni tema.

Chi segue un tema (per esempio "Energia") riceve nel proprio lettore di notizie, in
Outlook, in Slack o in Teams le nuove proposte di legge, i cambi di stato (approvata,
è legge...) e i voti finali e di fiducia su quel tema. Un feed per tema più uno con tutto."""
import datetime as dt
import email.utils
import os
from xml.sax.saxutils import escape

from comune import leggi_json

GIORNI = 120   # novità degli ultimi 4 mesi
MAX_VOCI = 60
SITO = os.environ.get("BUSSOLA_SITO", "https://riccardolucifora07-web.github.io/bussola-parlamentare/")
RAMO = {"C": "Camera", "S": "Senato"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]
POS = {"F": "sì", "C": "no", "A": "astenuto", "D": "diviso"}


def data_it(d):
    try:
        x = dt.date.fromisoformat(d[:10])
        return f"{x.day} {MESI[x.month - 1]} {x.year}"
    except (TypeError, ValueError):
        return d or ""


def rfc822(d):
    try:
        x = dt.date.fromisoformat(d[:10])
    except (TypeError, ValueError):
        x = dt.date.today()
    return email.utils.format_datetime(dt.datetime(x.year, x.month, x.day, 12, 0, tzinfo=dt.timezone.utc))


def fase_lunga(f):
    r, _, n = f.partition(".")
    return f"{'Atto Camera' if r == 'C' else 'Atto Senato'} n. {n}"


def eventi_leggi(leggi):
    ev = []
    for x in leggi:
        titolo = x["tb"] or x["t"]
        prima, ultima = x["fasi"][0], x["fasi"][-1]
        chi = f" Presentato da: {x['chi']}." if x.get("chi") else ""
        ev.append({"d": x["dp"], "temi": x["temi"], "guid": f"pres-{x['id']}", "link": f"#leggi/{x['id']}",
                   "gov": x.get("ini") == "Governo",
                   "t": f"Nuova proposta di legge: {titolo}",
                   "desc": f"{fase_lunga(prima['f'])}, presentato il {data_it(x['dp'])}.{chi} {x['t']}"})
        if ultima["ds"] and (ultima["ds"] != x["dp"] or len(x["fasi"]) > 1) and ultima["st"] != "presentato":
            ev.append({"d": ultima["ds"], "temi": x["temi"], "guid": f"stato-{x['id']}-{ultima['f']}-{ultima['ds']}",
                       "link": f"#leggi/{x['id']}", "t": f"{titolo}: {ultima['s']}",
                       "desc": f"{fase_lunga(ultima['f'])} ({RAMO.get(ultima['f'][:1], '')}), {data_it(ultima['ds'])}: {ultima['s']}. {x['t']}"})
    return ev


def eventi_voti(dati_dir, legge_di_fase):
    ev = []
    for ramo, sigla in (("camera", "C"), ("senato", "S")):
        I = leggi_json(os.path.join(dati_dir, ramo, "indice.json"))
        M = leggi_json(os.path.join(dati_dir, ramo, "membri.json"))
        if not I or not M:
            continue
        campi = I["campi"]
        k = {c: i for i, c in enumerate(campi)}
        nomi = [(M["gruppi"].get(g) or {}).get("breve") or g for g in I["gruppi"]]
        for r in I["righe"]:
            if r[k["categoria"]] not in ("finale", "fiducia"):
                continue
            atto = r[k["atto"]] if "atto" in k else None
            temi = [t for t in (r[k["temi"]] if "temi" in k else "").split(",") if t]
            idl = legge_di_fase.get(f"{sigla}.{atto}") if atto else None
            uff = r[k["ufficiali_FCA"]] or [None, None, None]
            F, C, A = [u if u is not None else r[k[x]] for u, x in zip(uff, "FCA")]
            esito = {1: "approvata", 0: "respinta"}.get(r[k["esito"]], "")
            pos = ", ".join(f"{n} {POS[c]}" for n, c in zip(nomi, r[k["posizioni"]] or "") if c in POS)
            tipo = "Voto di fiducia" if r[k["categoria"]] == "fiducia" else "Voto finale"
            titolo = r[k["titolo"]] or r[k["oggetto"]]
            ev.append({"d": r[k["data"]], "temi": temi, "guid": f"voto-{ramo}-{r[k['id']]}",
                       "link": f"#leggi/{idl}" if idl else "#voti",
                       "t": f"{RAMO[sigla]}, {tipo.lower()}: {titolo}" + (f" ({esito})" if esito else ""),
                       "desc": f"{RAMO[sigla]}, {data_it(r[k['data']])}. {tipo}{', ' + esito if esito else ''}: "
                               f"{F} sì, {C} no, {A} astenuti. Posizione dei gruppi: {pos or 'non disponibile'}."})
    return ev


def rss(titolo, descrizione, pagina, nome_file, voci, oggi):
    righe = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(titolo)}</title>",
        f"<link>{escape(SITO + pagina)}</link>",
        f"<description>{escape(descrizione)}</description>",
        "<language>it-it</language>",
        f"<lastBuildDate>{rfc822(oggi)}</lastBuildDate>",
        f'<atom:link href="{escape(SITO + "data/feed/" + nome_file)}" rel="self" type="application/rss+xml"/>',
    ]
    for v in voci:
        righe += ["<item>", f"<title>{escape(v['t'])}</title>", f"<link>{escape(SITO + v['link'])}</link>",
                  f'<guid isPermaLink="false">{escape(v["guid"])}</guid>', f"<pubDate>{rfc822(v['d'])}</pubDate>",
                  f"<description>{escape(v['desc'])}</description>", "</item>"]
    righe += ["</channel>", "</rss>", ""]
    return "\n".join(righe)


def scrivi(dati_dir, leggi, temi_elenco, oggi=None):
    """Scrive data/feed/<tema>.xml e data/feed/tutto.xml; restituisce il numero di feed."""
    oggi = oggi or dt.date.today().isoformat()
    limite = (dt.date.fromisoformat(oggi) - dt.timedelta(days=GIORNI)).isoformat()
    legge_di_fase = {f["f"]: x["id"] for x in leggi for f in x["fasi"]}
    tutti = [e for e in eventi_leggi(leggi) + eventi_voti(dati_dir, legge_di_fase) if e["d"] and limite <= e["d"] <= oggi]
    tutti.sort(key=lambda e: (e["d"], e["guid"]), reverse=True)
    cart = os.path.join(dati_dir, "feed")
    os.makedirs(cart, exist_ok=True)
    scritti = 0
    for t in temi_elenco:
        voci = [e for e in tutti if t["codice"] in e["temi"]][:MAX_VOCI]
        testo = rss(f"Bussola Parlamentare · {t['nome']}",
                    f"Nuove proposte di legge, leggi approvate e voti finali in Parlamento sul tema {t['nome']}.",
                    f"#temi/{t['codice']}", f"{t['codice']}.xml", voci, oggi)
        with open(os.path.join(cart, f"{t['codice']}.xml"), "w", encoding="utf-8") as f:
            f.write(testo)
        scritti += 1
    voci = [e for e in tutti if not e["guid"].startswith("pres-") or e.get("gov")][:MAX_VOCI]
    with open(os.path.join(cart, "tutto.xml"), "w", encoding="utf-8") as f:
        f.write(rss("Bussola Parlamentare · tutte le novità",
                    "Leggi approvate, voti finali e di fiducia e nuovi disegni di legge del Governo, da Camera e Senato.",
                    "#temi", "tutto.xml", voci, oggi))
    return scritti + 1
