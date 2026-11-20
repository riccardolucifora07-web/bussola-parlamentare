"""Estrazione dei dati della Camera dei deputati da https://dati.camera.it/sparql
(ontologia OCD, http://dati.camera.it/ocd/). Licenza dei dati: CC BY-SA 4.0."""
import re

from comune import INIZIO_LEG, codice_camera, data_iso, date_in_testo, nome_gruppo, nome_locale, nome_proprio, pulisci_nome_gruppo

ENDPOINT = "https://dati.camera.it/sparql"
LEG = "http://dati.camera.it/ocd/legislatura.rdf/repubblica_19"


def membri(ep):
    righe = ep.query_tutto(f"""# q:camera_deputati
SELECT DISTINCT ?d ?nome ?cognome ?genere ?m ?inizio ?fine WHERE {{
  ?d a ocd:deputato ; ocd:rif_leg <{LEG}> ; foaf:firstName ?nome ; foaf:surname ?cognome .
  OPTIONAL {{ ?d foaf:gender ?genere }}
  OPTIONAL {{ ?d ocd:rif_mandatoCamera ?m .
             OPTIONAL {{ ?m ocd:startDate ?inizio }}
             OPTIONAL {{ ?m ocd:endDate ?fine }} }}
}}""", "?d ?m")
    out = {}
    for r in righe:
        d = out.setdefault(r["d"], {
            "id": r["d"], "nome": nome_proprio(r.get("nome")), "cognome": nome_proprio(r.get("cognome")),
            "sesso": (r.get("genere") or "")[:1].upper(), "mandati": [],
        })
        if r.get("m"):
            per = [data_iso(r.get("inizio")) or INIZIO_LEG, data_iso(r.get("fine"))]
            if per not in d["mandati"]:
                d["mandati"].append(per)
    for d in out.values():
        if not d["mandati"]:
            d["mandati"] = [[INIZIO_LEG, None]]
        d["mandati"].sort(key=lambda p: p[0])
    return out


def adesioni(ep):
    righe = ep.query_tutto(f"""# q:camera_adesioni
SELECT DISTINCT ?d ?a ?g ?inizio ?fine ?etichetta WHERE {{
  ?d a ocd:deputato ; ocd:rif_leg <{LEG}> ; ocd:aderisce ?a .
  ?a ocd:rif_gruppoParlamentare ?g .
  OPTIONAL {{ ?a ocd:startDate ?inizio }}
  OPTIONAL {{ ?a ocd:endDate ?fine }}
  OPTIONAL {{ ?a rdfs:label ?etichetta }}
}}""", "?d ?a")
    out = []
    for r in righe:
        da, a = data_iso(r.get("inizio")), data_iso(r.get("fine"))
        if not da:  # ripiego: date nell'etichetta, es. "FDI (dal 13.10.2022 al 02.05.2024)"
            dt = date_in_testo(r.get("etichetta"))
            if dt:
                da = dt[0]
                if len(dt) > 1 and not a:
                    a = dt[1]
        out.append({"id": r["d"], "g": r["g"], "da": da, "a": a, "carica": None})
    return out


def gruppi(ep):
    righe = ep.query_tutto(f"""# q:camera_gruppi
SELECT DISTINCT ?g ?sigla ?nome ?etichetta WHERE {{
  ?d a ocd:deputato ; ocd:rif_leg <{LEG}> ; ocd:aderisce ?a .
  ?a ocd:rif_gruppoParlamentare ?g .
  OPTIONAL {{ ?g dcterms:alternative ?sigla }}
  OPTIONAL {{ ?g dc:title ?nome }}
  OPTIONAL {{ ?g rdfs:label ?etichetta }}
}}""", "?g")
    out = {}
    for r in righe:
        g = out.setdefault(r["g"], {"sigla": "", "nome": ""})
        sig = pulisci_nome_gruppo(r.get("sigla"))
        nom = pulisci_nome_gruppo(r.get("nome") or r.get("etichetta"))
        if sig and len(sig) > len(g["sigla"]):
            g["sigla"] = sig
        if nom and len(nom) > len(g["nome"]):
            g["nome"] = nom
    for uri, g in out.items():
        if not g["nome"]:
            g["nome"] = g["sigla"] or nome_locale(uri)
        g["nome"] = nome_gruppo(g["nome"])
    return out


def incarichi_gruppo(ep):
    """Presidenti dei gruppi (capigruppo), se pubblicati. Facoltativo: in caso di errore restituisce []."""
    righe = ep.query_tutto(f"""# q:camera_incarichi
SELECT DISTINCT ?d ?i ?g ?p ?o WHERE {{
  ?d a ocd:deputato ; ocd:rif_leg <{LEG}> ; ocd:rif_incarico ?i .
  ?i ocd:rif_gruppoParlamentare ?g ; ?p ?o .
  FILTER (isLiteral(?o))
}}""", "?d ?i ?p")
    per_inc = {}
    for r in righe:
        x = per_inc.setdefault(r["i"], {"id": r["d"], "g": r["g"], "testi": [], "da": None, "a": None})
        p = nome_locale(r["p"])
        if p == "startDate":
            x["da"] = data_iso(r["o"])
        elif p == "endDate":
            x["a"] = data_iso(r["o"])
        else:
            x["testi"].append(str(r["o"]))
    out = []
    for x in per_inc.values():
        t = " ".join(x["testi"]).upper()
        if "PRESIDENTE" in t and not re.search(r"VICE\s*-?\s*PRESIDENTE", t):
            out.append({"id": x["id"], "g": x["g"], "da": x["da"], "a": x["a"]})
    return out


def giorni(ep):
    righe = ep.query(f"""# q:camera_giorni
SELECT DISTINCT ?data WHERE {{
  ?v a ocd:votazione ; dc:date ?data .
  FILTER (regex(str(?data), "^20(2[2-9]|[3-9][0-9])"))
}}""")
    out = sorted({data_iso(r["data"]) for r in righe if data_iso(r.get("data"))})
    return [g for g in out if g >= INIZIO_LEG]


def _filtro_giorno(giorno):
    # la data è pubblicata come letterale semplice "20261119": il confronto diretto usa
    # l'indice dell'endpoint (meno di un secondo), mentre un FILTER su str() lo scorre tutto
    return f'?v a ocd:votazione ; dc:date "{giorno.replace("-", "")}" .'


def votazioni_giorno(ep, giorno):
    """Tutte le votazioni di un giorno, con il voto di ogni deputato.
    Le richieste sono a lotti di votazioni (VALUES): l'endpoint dà al massimo 10.000 righe."""
    uris = sorted({r["v"] for r in ep.query(f"""# q:camera_lista giorno={giorno}
SELECT ?v WHERE {{ {_filtro_giorno(giorno)} }}""")})
    righe = ep.query_lotti(f"""# q:camera_votazioni giorno={giorno}
SELECT ?v ?p ?o WHERE {{ VALUES ?v {{ %VALORI% }} ?v ?p ?o . }}""", uris, 40)
    vot = {}
    for r in righe:
        v = vot.setdefault(r["v"], {"id": r["v"], "d": giorno, "prop": {}})
        p = nome_locale(r["p"])
        v["prop"].setdefault(p, [])
        if r["o"] not in v["prop"][p]:
            v["prop"][p].append(r["o"])

    # titoli degli atti collegati (facoltativo)
    titoli_atti = {}
    try:
        for r in ep.query(f"""# q:camera_atti giorno={giorno}
SELECT DISTINCT ?v ?atto ?titolo WHERE {{
  {_filtro_giorno(giorno)}
  ?v ?p ?atto . ?atto a ocd:atto ; dc:title ?titolo .
}}"""):
            titoli_atti.setdefault(r["v"], [])
            if r["titolo"] not in titoli_atti[r["v"]]:
                titoli_atti[r["v"]].append(r["titolo"])
    except Exception as e:  # noqa: BLE001
        ep.log(f"  [camera] titoli degli atti non disponibili per {giorno}: {e}")

    # voti individuali: circa 400 righe per votazione, quindi lotti da 20
    voti = {}
    righe_voti = ep.query_lotti(f"""# q:camera_voti giorno={giorno}
SELECT ?v ?dep ?espr WHERE {{ VALUES ?v {{ %VALORI% }} ?voto ocd:rif_votazione ?v ; ocd:rif_deputato ?dep ; dc:type ?espr . }}""", uris, 20)
    sconosciute = set()
    for r in righe_voti:
        c = codice_camera(r.get("espr"))
        if c == "?":
            sconosciute.add(r.get("espr"))
        voti.setdefault(r["v"], {})[r["dep"]] = c
    if sconosciute:
        ep.log(f"  [camera] espressioni di voto non riconosciute: {sorted(map(str, sconosciute))}")

    out = []
    for uri, v in vot.items():
        p = v["prop"]
        uno = lambda k: (p.get(k) or [None])[0]  # noqa: E731
        testo = lambda k: " · ".join(str(x) for x in p.get(k, []) if x)  # noqa: E731
        seduta = uno("rif_seduta")
        num = _numero(uno("numeroVotazione") or uno("numero") or uno("identifier"), seduta)
        descr = testo("description") or testo("label")
        titolo = re.sub(r"^\s*Votazione\s*(finale)?\s*", "", testo("title"), flags=re.I).strip()
        if titolo and titolo.lower() in descr.lower():
            titolo = ""
        link = next((str(x) for x in p.get("relation", []) if str(x).startswith("http")), None)
        out.append({
            "id": uri,
            "d": giorno,
            "n": num,
            "seduta": nome_locale(seduta) if seduta else None,
            "t": " · ".join(titoli_atti.get(uri, [])) or titolo,
            "o": descr,
            "tipo": " ".join(str(x) for x in p.get("type", []) if x and not str(x).startswith("http")),
            "esito": _bool(uno("approvato")),
            "finale": bool(_bool(uno("votazioneFinale"))),
            "segreta": bool(_bool(uno("votazioneSegreta"))),
            "fiducia": bool(_bool(uno("richiestaFiducia"))),
            "numero_legale": False,
            "tot": {k: _int(uno(k)) for k in ("presenti", "votanti", "favorevoli", "contrari", "astenuti", "maggioranza")},
            "voti": voti.get(uri, {}),
            "url": link or uri,
        })
    out.sort(key=lambda x: (x["n"] is None, x["n"] or 0, x["id"]))
    return out


def _numero(identificativo, seduta):
    """dc:identifier è seduta*1000 + numero (es. 747001 = seduta 747, votazione 1)."""
    try:
        ident = int(re.sub(r"\D", "", str(identificativo)))
    except (TypeError, ValueError):
        return None
    m = re.search(r"_(\d+)$", str(seduta or ""))
    if m:
        n = ident - int(m.group(1)) * 1000
        if 0 < n < 100000:
            return n
    return ident % 1000 or None


def _bool(x):
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in ("1", "true", "si", "sì", "approvato", "approvata"):
        return True
    if s in ("0", "false", "no", "respinto", "respinta"):
        return False
    return None


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
