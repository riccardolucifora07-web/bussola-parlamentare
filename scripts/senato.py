"""Estrazione dei dati del Senato della Repubblica da https://dati.senato.it/sparql
(ontologia OSR, http://dati.senato.it/osr/). Licenza dei dati: CC BY 3.0.

Note sull'endpoint (Virtuoso): niente BIND/SAMPLE e niente confronti tra date
tipizzate, per cui si filtra per seduta e non per data."""
import re

from comune import INIZIO_LEG, data_iso, nome_gruppo, nome_locale, nome_proprio, pulisci_nome_gruppo

ENDPOINT = "https://dati.senato.it/sparql"
LEG = 19

CODICI = {
    "favorevole": "F", "contrario": "C", "astenuto": "A", "votante": "V",
    "presenteNonVotante": "N", "richiedenteNonVotante": "N",
    "inCongedoMissione": "M", "presidente": "P",
}


def _mandati_da_righe(righe):
    out = {}
    for r in righe:
        s = out.setdefault(r["s"], {
            "id": r["s"], "nome": nome_proprio(r.get("nome")), "cognome": nome_proprio(r.get("cognome")),
            "sesso": "", "mandati": [], "tipo": "",
        })
        if r.get("tipo") and not s["tipo"]:
            s["tipo"] = str(r["tipo"])
        da, a = data_iso(r.get("inizio")), data_iso(r.get("fine"))
        if a and a < INIZIO_LEG:
            continue  # mandato chiuso prima della XIX legislatura
        per = [max(da or INIZIO_LEG, INIZIO_LEG), a]
        if per not in s["mandati"]:
            s["mandati"].append(per)
    return out


def membri(ep):
    righe = ep.query_tutto(f"""# q:senato_senatori
SELECT DISTINCT ?s ?nome ?cognome ?m ?inizio ?fine ?tipo WHERE {{
  ?s a osr:Senatore ; foaf:firstName ?nome ; foaf:lastName ?cognome ; osr:mandato ?m .
  ?m osr:legislatura {LEG} .
  OPTIONAL {{ ?m osr:inizio ?inizio }}
  OPTIONAL {{ ?m osr:fine ?fine }}
  OPTIONAL {{ ?m osr:tipoMandato ?tipo }}
}}""", "?s ?m")
    out = _mandati_da_righe(righe)
    for s in out.values():
        if not s["mandati"]:
            s["mandati"] = [[INIZIO_LEG, None]]
        s["mandati"].sort(key=lambda p: p[0])
    return out


def membri_extra(ep, uris):
    """Senatori che votano nella XIX legislatura ma senza mandato legato a essa
    (tipicamente i senatori a vita): si leggono tutti i loro mandati."""
    out = {}
    for uri in sorted(uris):
        righe = ep.query(f"""# q:senato_senatore_extra
SELECT DISTINCT ?nome ?cognome ?m ?inizio ?fine ?tipo WHERE {{
  <{uri}> foaf:firstName ?nome ; foaf:lastName ?cognome .
  OPTIONAL {{ <{uri}> osr:mandato ?m .
             OPTIONAL {{ ?m osr:inizio ?inizio }}
             OPTIONAL {{ ?m osr:fine ?fine }}
             OPTIONAL {{ ?m osr:tipoMandato ?tipo }} }}
}}""")
        for r in righe:
            r["s"] = uri
        x = _mandati_da_righe(righe).get(uri)
        if x:
            if not x["mandati"]:
                x["mandati"] = [[INIZIO_LEG, None]]
            x["mandati"].sort(key=lambda p: p[0])
            out[uri] = x
    return out


def adesioni(ep):
    righe = ep.query_tutto(f"""# q:senato_adesioni
SELECT DISTINCT ?s ?g ?inizio ?fine ?carica WHERE {{
  ?s ocd:aderisce ?a .
  ?a osr:legislatura {LEG} ; osr:gruppo ?g .
  OPTIONAL {{ ?a osr:inizio ?inizio }}
  OPTIONAL {{ ?a osr:fine ?fine }}
  OPTIONAL {{ ?a osr:carica ?carica }}
}}""", "?s ?g ?inizio")
    return [{"id": r["s"], "g": r["g"], "da": data_iso(r.get("inizio")), "a": data_iso(r.get("fine")),
             "carica": str(r.get("carica") or "")} for r in righe]


def gruppi(ep):
    righe = ep.query_tutto(f"""# q:senato_gruppi
SELECT DISTINCT ?g ?titolo ?inizio ?fine WHERE {{
  ?a osr:legislatura {LEG} ; osr:gruppo ?g .
  ?g osr:denominazione ?den . ?den osr:titolo ?titolo .
  OPTIONAL {{ ?den osr:inizio ?inizio }}
  OPTIONAL {{ ?den osr:fine ?fine }}
}}""", "?g ?inizio")
    per_g = {}
    for r in righe:
        per_g.setdefault(r["g"], []).append((data_iso(r.get("fine")) or "9999", data_iso(r.get("inizio")) or "", r["titolo"]))
    out = {}
    for g, den in per_g.items():
        den.sort()
        nome = pulisci_nome_gruppo(den[-1][2])  # denominazione senza fine o più recente
        out[g] = {"nome": nome_gruppo(nome), "sigla": ""}
    return out


def sedute(ep):
    righe = ep.query(f"""# q:senato_sedute
SELECT DISTINCT ?s ?data ?num WHERE {{
  ?v a osr:Votazione ; osr:legislatura {LEG} ; osr:seduta ?s .
  ?s osr:dataSeduta ?data .
  OPTIONAL {{ ?s osr:numeroSeduta ?num }}
}}""")
    out = {}
    for r in righe:
        d = data_iso(r.get("data"))
        if d and d >= INIZIO_LEG:
            out[r["s"]] = {"uri": r["s"], "d": d, "num": r.get("num")}
    return sorted(out.values(), key=lambda x: (x["d"], str(x["num"]), x["uri"]))


def votazioni_seduta(ep, seduta):
    # l'endpoint del Senato non conosce VALUES e rifiuta le richieste POST:
    # lotti di votazioni con FILTER IN, in GET (circa 350 righe per votazione)
    uris = sorted({r["v"] for r in ep.query(f"""# q:senato_lista seduta={seduta['uri']}
SELECT ?v WHERE {{ ?v a osr:Votazione ; osr:seduta <{seduta['uri']}> . }}""")})
    righe = ep.query_lotti(f"""# q:senato_votazioni seduta={seduta['uri']}
SELECT ?v ?p ?o WHERE {{
  ?v a osr:Votazione ; osr:seduta <{seduta['uri']}> ; ?p ?o .
  FILTER (?v IN (%VALORI%))
  FILTER (?p != osr:presente)
}}""", uris, 20, separatore=", ")
    vot = {}
    for r in righe:
        v = vot.setdefault(r["v"], {"prop": {}, "voti": {}})
        p = nome_locale(r["p"])
        if p in CODICI:
            vecchio = v["voti"].get(r["o"])
            nuovo = CODICI[p]
            # un senatore elencato in più liste: vale il voto espresso
            if vecchio is None or (nuovo in "FCA") or (vecchio not in "FCA" and nuovo == "V"):
                v["voti"][r["o"]] = nuovo
        else:
            v["prop"].setdefault(p, [])
            if r["o"] not in v["prop"][p]:
                v["prop"][p].append(r["o"])

    titoli = {}
    try:
        for r in ep.query(f"""# q:senato_ddl seduta={seduta['uri']}
SELECT DISTINCT ?v ?ddl ?titolo ?breve WHERE {{
  ?v a osr:Votazione ; osr:seduta <{seduta['uri']}> ; osr:oggetto ?og .
  ?og osr:relativoA ?ddl .
  OPTIONAL {{ ?ddl osr:titoloBreve ?breve }}
  OPTIONAL {{ ?ddl osr:titolo ?titolo }}
}}"""):
            t = r.get("breve") or r.get("titolo")
            if t:
                titoli.setdefault(r["v"], [])
                if t not in titoli[r["v"]]:
                    titoli[r["v"]].append(str(t))
    except Exception as e:  # noqa: BLE001
        ep.log(f"  [senato] titoli dei ddl non disponibili per la seduta {seduta['uri']}: {e}")

    out = []
    for uri, v in vot.items():
        p = v["prop"]
        uno = lambda k: (p.get(k) or [None])[0]  # noqa: E731
        etichetta = " · ".join(str(x) for x in p.get("label", []) + p.get("title", []) if x)
        tipo = str(uno("tipoVotazione") or "")
        esito = str(uno("esito") or "").lower()
        segreta = "segret" in tipo.lower() or (any(c == "V" for c in v["voti"].values())
                                               and not any(c in "FCA" for c in v["voti"].values()))
        m = re.search(r"/(\d+)-(\d+)-(\d+)$", uri)
        num = uno("numero")
        if num is None and m:
            num = int(m.group(3))
        out.append({
            "id": uri,
            "d": seduta["d"],
            "n": num if isinstance(num, int) else _int(num),
            "seduta": str(seduta.get("num") or (m.group(2) if m else "")),
            "t": " · ".join(titoli.get(uri, [])),
            "o": etichetta,
            "tipo": tipo,
            "esito": True if esito.startswith("approv") else False if esito.startswith("respin") else None,
            "finale": bool(re.search(r"votazione finale|voto finale|nel suo complesso", etichetta, re.I)),
            "segreta": segreta,
            "fiducia": bool(re.search(r"fiducia", etichetta, re.I)),
            "numero_legale": "numero legale" in tipo.lower(),
            "tot": {
                "presenti": _int(uno("presenti")), "votanti": _int(uno("votanti")),
                "favorevoli": _int(uno("favorevoli")), "contrari": _int(uno("contrari")),
                "astenuti": _int(uno("astenuti")), "maggioranza": _int(uno("maggioranza")),
            },
            "voti": v["voti"],
            "url": re.sub(r"^http://", "https://", uri) + ".html",
        })
    out.sort(key=lambda x: (x["n"] is None, x["n"] or 0))
    return out


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
