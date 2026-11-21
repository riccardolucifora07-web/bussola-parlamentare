"""Percorso delle leggi della legislatura, dai dati aperti del Senato.

La banca dati del Senato (dati.senato.it) contiene ogni fase di ogni disegno di legge,
anche quelle alla Camera ("C.3133"), collegate da un identificativo comune (idDdl):
così si segue una legge da quando viene presentata a quando diventa legge, passando
da un ramo all'altro. Per ogni fase: stato, date, commissione competente, relatori,
primo firmatario e voci di classificazione ufficiali (TESEO).

Note sull'endpoint del Senato: le stringhe sono tipizzate (si confrontano con str()),
ogni tripla compare due volte (serve DISTINCT), al massimo 10.000 righe per risposta."""
import html
import re

from comune import accenti, nome_locale

LEG = 19
LIMITE = 10000

STATI = {
    "assegnato (no esame)": "assegnato a una commissione, esame non ancora iniziato",
    "da assegn. a commis.": "da assegnare a una commissione",
    "esame in comm.": "in esame in commissione",
    "in relazione": "esame in commissione concluso, in attesa dell'Aula",
    "concluso l'esame": "esame in commissione concluso",
    "all'esame assemblea": "in discussione in Aula",
    "approvato": "approvato",
    "appr. con modificaz": "approvato con modifiche",
    "appr. in t.u.": "approvato in un testo unificato",
    "appr. definit. Legge": "approvato definitivamente: è legge",
    "assorbito": "assorbito in un altro testo",
    "ritirato": "ritirato",
    "respinto": "respinto",
    "D-L decaduto": "decreto-legge decaduto",
    "restit. al Governo": "restituito al Governo",
    "appr. def. non pubbl": "approvato definitivamente, in attesa di pubblicazione",
    "cancellato dall'OdG": "cancellato dall'ordine del giorno",
    "concl. anomala stral": "chiuso per stralcio",
    "rinviato ass.->comm.": "rinviato dall'Aula alla commissione",
}
STADI = {
    "legge": "Approvata definitivamente",
    "approvato": "Approvato da un ramo",
    "aula": "In Aula",
    "commissione": "In commissione",
    "presentato": "Presentato, esame non iniziato",
    "chiuso": "Chiuso senza approvazione",
    "altro": "Altro",
}
INIZIATIVE = {"Governativa": "Governo", "Parlamentare": "Parlamentare", "Regionale": "Regioni",
              "Popolare": "Popolare", "CNEL": "CNEL", "Mista": "Mista"}


def stadio(stato):
    s = (stato or "").lower()
    if "legge" in s or "def" in s:  # "appr. definit. Legge", "appr. def. non pubbl"
        return "legge"
    if s.startswith("appr"):
        return "approvato"
    if "assemblea" in s or "relazione" in s or "concluso" in s:
        return "aula"
    if "esame in comm" in s or "rinviato" in s:
        return "commissione"
    if "assegn" in s:
        return "presentato"
    if any(x in s for x in ("assorbito", "ritirato", "respinto", "decaduto", "restit", "stral", "cancellato")):
        return "chiuso"
    return "altro"


def pulisci(s):
    s = html.unescape(html.unescape(str(s or "")))
    s = re.sub(r"\s+", " ", s).strip()
    return accenti(s)


def senza_titolo(nome):
    """'Sen. Gianni Rosa' -> 'Gianni Rosa'; 'On. Giuseppe Conte' -> 'Giuseppe Conte'."""
    return re.sub(r"^(Sen\.|On\.|Dep\.)\s*", "", pulisci(nome))


def voce_teseo(s):
    s = pulisci(s)
    return accenti(s[:1] + s[1:].lower()) if s.isupper() else s


def commissione(etichetta):
    """'8ª (Ambiente, territorio e lavori pubblici)' -> '8ª Commissione (Ambiente, territorio e lavori pubblici)'."""
    s = pulisci(etichetta)
    if s.lower().startswith("commissioni riunite"):
        s = re.sub(r"\s+\d+\s*ª\s*$", "", s)                  # numero ripetuto in fondo
        return re.sub(r"\)\s+(\d+\s*ª)", r") e \1", s)     # "9ª (...) e 10ª (...)"
    m = re.match(r"^(\d+)\s*[ªa°]?\s*(\(.*\))?\s*$", s)
    if m:
        return f"{m.group(1)}ª Commissione{(' ' + m.group(2)) if m.group(2) else ''}"
    return s


def _filtro_anno(var, anno):
    return f'FILTER (str({var}) >= "{anno}-01-01" && str({var}) < "{anno + 1}-01-01")'


def interroga(ep, modello, nome, anni, var="?dp"):
    """Esegue la query; se la risposta tocca il limite di righe la ripete anno per anno."""
    righe = ep.query(modello.replace("%FILTRO%", ""))
    if len(righe) < LIMITE:
        return righe
    ep.log(f"  [leggi] {nome}: risposta di {len(righe)} righe, la divido per anno")
    out = []
    for a in anni:
        parte = ep.query(modello.replace("%FILTRO%", _filtro_anno(var, a)))
        if len(parte) >= LIMITE:
            raise RuntimeError(f"{nome} {a}: ancora troppe righe ({len(parte)})")
        out += parte
    return out


def _base(r, corpo):
    return f"""?d a osr:Ddl ; osr:legislatura {LEG} ; osr:ramo ?ramo ; osr:dataPresentazione ?dp .
  FILTER (str(?ramo) = "{r}") {corpo}"""


def scarica(ep, oggi_anno):
    """Tutte le fasi di tutti i disegni di legge della legislatura, con i dettagli."""
    anni = list(range(2022, oggi_anno + 1))
    fasi = {}
    for r in ("C", "S"):
        q = f"""# q:leggi_base ramo={r}
SELECT DISTINCT ?d ?f ?id ?titolo ?breve ?stato ?ds ?dp ?nat ?descr ?legge ?prog WHERE {{
  {_base(r, "")} ?d osr:fase ?f ; osr:idDdl ?id ; osr:titolo ?titolo ; osr:statoDdl ?stato .
  OPTIONAL {{ ?d osr:titoloBreve ?breve }} OPTIONAL {{ ?d osr:dataStatoDdl ?ds }} OPTIONAL {{ ?d osr:natura ?nat }}
  OPTIONAL {{ ?d osr:descrIniziativa ?descr }} OPTIONAL {{ ?d osr:numeroLegge ?legge }} OPTIONAL {{ ?d osr:progressivoIter ?prog }}
  %FILTRO%
}}"""
        for x in interroga(ep, q, f"fasi {r}", anni):
            d = str(x["d"])
            if d in fasi:
                continue
            fasi[d] = {"uri": d, "f": str(x["f"]), "r": r, "id": str(x["id"]), "t": pulisci(x.get("titolo")),
                       "tb": pulisci(x.get("breve")), "stato": pulisci(x.get("stato")), "ds": str(x.get("ds") or "")[:10],
                       "dp": str(x.get("dp") or "")[:10], "nat": pulisci(x.get("nat")), "chi": pulisci(x.get("descr")),
                       "legge": str(x.get("legge") or ""), "prog": int(x["prog"]) if str(x.get("prog") or "").isdigit() else 0,
                       "teseo": [], "comm": [], "rel": [], "pf": None, "nf": 0}

        q = f"""# q:leggi_teseo ramo={r}
SELECT DISTINCT ?d ?lab WHERE {{
  {_base(r, "")} ?d osr:classificazione ?c . ?c osr:livello ?l ; dcterms:subject ?s . ?s skos:prefLabel ?lab .
  FILTER (str(?l) = "Generale") %FILTRO%
}}"""
        for x in interroga(ep, q, f"classificazione {r}", anni):
            f = fasi.get(str(x["d"]))
            v = voce_teseo(x.get("lab"))
            if f and v and v not in f["teseo"]:
                f["teseo"].append(v)

        q = f"""# q:leggi_commissioni ramo={r}
SELECT DISTINCT ?d ?lab ?sede ?data WHERE {{
  {_base(r, "")} ?d osr:assegnazione ?a . ?a rdfs:label ?lab ; osr:tipoCommissione ?t .
  OPTIONAL {{ ?a osr:sede ?sede }} OPTIONAL {{ ?a osr:dataAssegnazione ?data }}
  FILTER (str(?t) = "primaria") %FILTRO%
}}"""
        for x in interroga(ep, q, f"commissioni {r}", anni):
            f = fasi.get(str(x["d"]))
            if f:
                c = {"n": commissione(x.get("lab")), "sede": pulisci(x.get("sede")), "d": str(x.get("data") or "")[:10]}
                if not any(y["n"] == c["n"] and y["d"] == c["d"] for y in f["comm"]):
                    f["comm"].append(c)

        q = f"""# q:leggi_relatori ramo={r}
SELECT DISTINCT ?d ?nome ?sen ?dep WHERE {{
  {_base(r, "")} ?d osr:relatore ?x . ?x rdfs:label ?nome .
  OPTIONAL {{ ?x osr:senatore ?sen }} OPTIONAL {{ ?x ocd:rif_deputato ?dep }} %FILTRO%
}}"""
        for x in interroga(ep, q, f"relatori {r}", anni):
            f = fasi.get(str(x["d"]))
            if f:
                n = senza_titolo(x.get("nome"))
                if n and not any(y["n"] == n for y in f["rel"]):
                    f["rel"].append({"n": n, "id": str(x.get("sen") or x.get("dep") or "")})

        q = f"""# q:leggi_firmatari ramo={r}
SELECT DISTINCT ?d ?pres ?tipo ?sen ?dep WHERE {{
  {_base(r, "")} ?d osr:iniziativa ?i . ?i osr:primoFirmatario ?p ; osr:presentatore ?pres .
  OPTIONAL {{ ?i osr:tipoIniziativa ?tipo }} OPTIONAL {{ ?i osr:senatore ?sen }} OPTIONAL {{ ?i ocd:rif_deputato ?dep }}
  FILTER (str(?p) = "1") %FILTRO%
}}"""
        for x in interroga(ep, q, f"firmatari {r}", anni):
            f = fasi.get(str(x["d"]))
            if f and not f["pf"]:
                f["pf"] = {"n": senza_titolo(x.get("pres")), "tipo": pulisci(x.get("tipo")),
                           "id": str(x.get("sen") or x.get("dep") or "")}

        q = f"""# q:leggi_conta_firme ramo={r}
SELECT ?d (COUNT(DISTINCT ?i) AS ?n) WHERE {{
  {_base(r, "")} ?d osr:iniziativa ?i . %FILTRO%
}} GROUP BY ?d"""
        for x in interroga(ep, q, f"numero firmatari {r}", anni):
            f = fasi.get(str(x["d"]))
            if f:
                f["nf"] = int(x.get("n") or 0)
    return fasi


def voti_senato(ep, oggi_anno):
    """{id votazione del Senato (es. '19-167-1'): numero del ddl (es. '1056')} per le votazioni su un ddl."""
    modello = f"""# q:leggi_voti ramo=S
SELECT DISTINCT ?v ?f WHERE {{
  ?v a osr:Votazione ; osr:legislatura {LEG} ; osr:seduta ?s ; osr:oggetto ?og . ?og osr:relativoA ?ddl .
  ?s osr:dataSeduta ?ds . ?ddl osr:fase ?f ; osr:ramo ?ramo . FILTER (str(?ramo) = "S") %FILTRO%
}}"""
    righe = interroga(ep, modello, "collegamento votazioni-ddl", list(range(2022, oggi_anno + 1)), var="?ds")
    out = {}
    for x in righe:
        f = str(x.get("f") or "")
        if f.startswith("S."):
            out.setdefault(nome_locale(str(x["v"])), f[2:])
    return out


def costruisci(fasi, temi):
    """Raggruppa le fasi per legge (idDdl) e calcola stadio, temi e date."""
    per_id = {}
    for f in fasi.values():
        per_id.setdefault(f["id"], []).append(f)
    leggi = []
    for idd, ff in per_id.items():
        ff.sort(key=lambda f: (f["dp"] or "9", f["prog"], f["f"]))
        prima, ultima = ff[0], ff[-1]
        stati = [f["stato"] for f in ff]
        st = "legge" if any(stadio(s) == "legge" for s in stati) else stadio(ultima["stato"])
        if st in ("presentato", "commissione", "aula") and any(stadio(s) == "approvato" for s in stati[:-1]):
            st = "approvato"  # già approvato da un ramo, ora all'esame dell'altro
        teseo = []
        for f in ff:
            teseo += [v for v in f["teseo"] if v not in teseo]
        breve = next((f["tb"] for f in reversed(ff) if f["tb"]), "")
        pf = prima["pf"] or {}
        legge = next((f["legge"] for f in ff if f["legge"]), "")
        x = {
            "id": idd, "t": ultima["t"] or prima["t"], "tb": breve, "nat": prima["nat"],
            "ini": INIZIATIVE.get(pf.get("tipo", ""), pf.get("tipo", "")), "chi": prima["chi"],
            "pf": {"n": pf.get("n", ""), "id": pf.get("id", "")} if pf else None, "nf": prima["nf"],
            "dp": prima["dp"], "st": st, "s": STATI.get(ultima["stato"], ultima["stato"]), "ds": ultima["ds"] or ultima["dp"],
            "legge": legge, "teseo": teseo[:8],
            "fasi": [{"f": f["f"], "u": nome_locale(f["uri"]), "s": STATI.get(f["stato"], f["stato"]), "st": stadio(f["stato"]),
                      "ds": f["ds"], "dp": f["dp"],
                      "comm": f["comm"][:3], "rel": [r["n"] for r in f["rel"]][:4],
                      "relid": [r["id"] for r in f["rel"] if r["id"]][:4]} for f in ff],
        }
        x["temi"] = temi.classifica(x["t"], x["tb"], " ".join(teseo))
        leggi.append(x)
    leggi.sort(key=lambda x: (x["ds"] or "", x["id"]), reverse=True)
    return leggi


def riclassifica(leggi, temi):
    for x in leggi:
        x["temi"] = temi.classifica(x["t"], x["tb"], " ".join(x.get("teseo", [])))
    return leggi


def temi_per_fase(leggi):
    """{'C.3133': [temi], 'S.2098': [temi]} per collegare le votazioni alle leggi."""
    out = {}
    for x in leggi:
        for f in x["fasi"]:
            out[f["f"]] = x["temi"]
    return out
