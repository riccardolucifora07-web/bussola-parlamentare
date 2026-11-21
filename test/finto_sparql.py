"""Finti endpoint SPARQL di Camera e Senato per provare la pipeline senza rete.

Riconosce le query dal commento '# q:nome' e risponde con dati sintetici ma
strutturati come quelli veri (stessi predicati, stessi formati delle date).
Simula anche i difetti reali: limite di 1000 righe per risposta, un errore 503
temporaneo e il 403 del Senato senza User-Agent da browser."""
import json
import random
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

XSD = "http://www.w3.org/2001/XMLSchema#"
OCD = "http://dati.camera.it/ocd/"
OSR = "http://dati.senato.it/osr/"
DC = "http://purl.org/dc/elements/1.1/"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
MAX_RIGHE = 1000

U = lambda v: {"type": "uri", "value": v}  # noqa: E731
L = lambda v: {"type": "literal", "value": str(v)}  # noqa: E731
I = lambda v: {"type": "typed-literal", "datatype": XSD + "integer", "value": str(v)}  # noqa: E731,E741
B = lambda v: {"type": "typed-literal", "datatype": XSD + "boolean", "value": "1" if v else "0"}  # noqa: E731
D = lambda v: {"type": "typed-literal", "datatype": XSD + "date", "value": v}  # noqa: E731


def genera(seed=7):
    rnd = random.Random(seed)
    # ---------------- CAMERA ----------------
    cg = {
        "gr1": ("FDI", "FRATELLI D'ITALIA", "magg", 118),
        "gr2": ("PD-IDP", "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA", "opp", 69),
        "gr3": ("LEGA", "LEGA - SALVINI PREMIER", "magg", 60),
        "gr4": ("M5S", "MOVIMENTO 5 STELLE", "opp", 50),
        "gr9": ("FI-PPE", "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE", "magg", 45),
        "gr5": ("A-IV-RE", "AZIONE-ITALIA VIVA-RENEW EUROPE", "opp", 20),
        "gr8": ("MISTO", "MISTO", "alt", 38),
    }
    dep = []
    n = 1
    for g, (_, _, _, k) in cg.items():
        for _ in range(k):
            dep.append({"uri": f"{OCD}deputato.rdf/d{300000 + n}_19", "nome": "MARIO", "cognome": f"ROSSI {n}",
                        "g": [(g, "20221013", None)], "m": ("20221013", None)})
            n += 1
    # scioglimento di Azione-IV il 2023-11-07: metà ad Azione (gr6), metà a IV (gr7)
    for j, d in enumerate([d for d in dep if d["g"][0][0] == "gr5"]):
        d["g"] = [("gr5", "20221013", "20231106"), ("gr6" if j % 2 == 0 else "gr7", "20231107", None)]
    cg["gr6"] = ("AZ-PER-RE", "AZIONE - POPOLARI EUROPEISTI RIFORMATORI - RENEW EUROPE", "opp", 0)
    cg["gr7"] = ("IV-C-RE", "ITALIA VIVA - IL CENTRO - RENEW EUROPE", "opp", 0)
    # un cambio individuale e una cessazione con subentro
    dep[5]["g"] = [("gr1", "20221013", "20240301"), ("gr8", "20240302", None)]
    dep[10]["m"] = ("20221013", "20240115")
    dep[10]["g"] = [("gr1", "20221013", "20240115")]
    dep.append({"uri": f"{OCD}deputato.rdf/d{300000 + n}_19", "nome": "LUCIA", "cognome": "D'ALESSIO",
                "g": [("gr1", "20240116", None)], "m": ("20240116", None)})

    giorni = ["20221025", "20230615", "20231108", "20240117", "20240305", "20261119"]
    cvot = []
    for gi, gg in enumerate(giorni):
        for nv in range(1, 5):
            uri = f"{OCD}votazione.rdf/vs19_{gi + 1:04d}_{nv:04d}"
            segreta = (gi == 2 and nv == 4)
            finale = nv == 4 and not segreta
            fiducia = gi == 0 and nv == 4
            voti = {}
            for d in dep:
                if not (d["m"][0] <= gg and (d["m"][1] is None or gg <= d["m"][1])):
                    continue
                g = next((x[0] for x in d["g"] if x[1] <= gg and (x[2] is None or gg <= x[2])), None)
                lato = cg[g][2] if g else "alt"
                r = rnd.random()
                if r < 0.12:
                    voti[d["uri"]] = "Non ha votato"
                    continue
                if segreta:
                    voti[d["uri"]] = "Ha votato"
                    continue
                pref = {"magg": "Favorevole", "opp": "Contrario", "alt": rnd.choice(["Favorevole", "Contrario", "Astensione"])}[lato]
                if nv == 2:  # emendamento dell'opposizione
                    pref = {"magg": "Contrario", "opp": "Favorevole"}.get(lato, pref)
                if r > 0.96:
                    pref = rnd.choice(["Favorevole", "Contrario", "Astensione"])
                voti[d["uri"]] = pref
            f = sum(1 for x in voti.values() if x == "Favorevole")
            c = sum(1 for x in voti.values() if x == "Contrario")
            a = sum(1 for x in voti.values() if x == "Astensione")
            cvot.append({"uri": uri, "d": gg, "nv": nv, "voti": voti, "segreta": segreta, "finale": finale, "fiducia": fiducia,
                         "desc": ["DDL 1234 - ART. 1", "DDL 1234 - EM. 1.25", "MOZIONE 1-00123", "DDL 1234 - VOTO FINALE"][nv - 1],
                         "f": f, "c": c, "a": a, "app": (f > c) if not segreta else True})

    # ---------------- SENATO ----------------
    sg = {
        "57": ("Fratelli d'Italia", "magg", 63),
        "33": ("Partito Democratico - Italia Democratica e Progressista", "opp", 37),
        "9": ("Lega Salvini Premier - Partito Sardo d'Azione", "magg", 29),
        "70": ("MoVimento 5 Stelle", "opp", 28),
        "40": ("Forza Italia - Berlusconi Presidente - PPE", "magg", 18),
        "79": ("Per le Autonomie (SVP-Patt, Campobase)", "alt", 7),
        "49": ("Misto", "alt", 14),
    }
    sen = []
    n = 1
    for g, (_, _, k) in sg.items():
        for j in range(k):
            sen.append({"uri": f"http://dati.senato.it/senatore/{30000 + n}", "nome": "Anna", "cognome": f"Bianchi {n}",
                        "g": [(g, "2022-10-13", None, "Presidente" if j == 0 else "Membro")],
                        "m": ("2022-10-13", None), "vita": False})
            n += 1
    # senatrice a vita senza mandato legato alla XIX
    sen.append({"uri": "http://dati.senato.it/senatore/25000", "nome": "Liliana", "cognome": "Segre",
                "g": [("49", "2022-10-13", None, "Membro")], "m": ("2018-01-19", None), "vita": True})
    sedute = [("22501", "2022-10-26"), ("22600", "2023-06-20"), ("22999", "2026-11-19")]
    svot = []
    for si, (sed, d) in enumerate(sedute):
        for nv in range(1, 4):
            uri = f"http://dati.senato.it/votazione/19-{sed}-{nv}"
            legale = si == 1 and nv == 3
            liste = {}
            for s in sen:
                g = s["g"][0][0]
                lato = sg[g][1]
                r = rnd.random()
                if r < 0.15:
                    continue  # assente: non compare in nessuna lista
                if r < 0.2:
                    liste.setdefault("inCongedoMissione", []).append(s["uri"])
                    continue
                if legale:
                    liste.setdefault("presenteNonVotante", []).append(s["uri"])
                    continue
                p = {"magg": "favorevole", "opp": "contrario", "alt": "astenuto"}[lato]
                if r > 0.97:
                    p = rnd.choice(["favorevole", "contrario", "astenuto"])
                liste.setdefault(p, []).append(s["uri"])
            svot.append({"uri": uri, "sed": sed, "d": d, "nv": nv, "liste": liste, "legale": legale,
                         "label": "Verifica del numero legale" if legale else ["Em. 1.5, Rossi e altri", "Art. 2", "DDL n. 1026. Votazione finale"][nv - 1]})
    return {"cg": cg, "dep": dep, "cvot": cvot, "sg": sg, "sen": sen, "svot": svot, "sedute": sedute}


DATI = genera()


def risposta(nome, q):
    D_ = DATI
    m = re.search(r'giorno=(\d{4}-\d{2}-\d{2})', q)
    giorno = m.group(1).replace("-", "") if m else None
    m = re.search(r"seduta=(\S+)", q)
    seduta = m.group(1) if m else None
    vars_, righe = [], []
    if nome == "camera_deputati":
        vars_ = ["d", "nome", "cognome", "genere", "m", "inizio", "fine"]
        for d in D_["dep"]:
            r = {"d": U(d["uri"]), "nome": L(d["nome"]), "cognome": L(d["cognome"]), "genere": L("male"),
                 "m": U(d["uri"].replace("deputato", "mandatoCamera")), "inizio": L(d["m"][0])}
            if d["m"][1]:
                r["fine"] = L(d["m"][1])
            righe.append(r)
    elif nome == "camera_adesioni":
        for d in D_["dep"]:
            for k, (g, da, a) in enumerate(d["g"]):
                r = {"d": U(d["uri"]), "a": U(d["uri"] + f"_a{k}"), "g": U(f"{OCD}gruppoParlamentare.rdf/{g}"),
                     "inizio": L(da), "etichetta": L(f"{D_['cg'][g][0]} (dal {da[6:]}.{da[4:6]}.{da[:4]})")}
                if a:
                    r["fine"] = L(a)
                righe.append(r)
    elif nome == "camera_gruppi":
        for g, (sig, nom, _, _) in D_["cg"].items():
            righe.append({"g": U(f"{OCD}gruppoParlamentare.rdf/{g}"), "sigla": L(sig), "nome": L(f"{nom} (13.10.2022)")})
    elif nome == "camera_incarichi":
        capo = D_["dep"][0]["uri"]
        righe = [{"d": U(capo), "g": U(f"{OCD}gruppoParlamentare.rdf/gr1"), "inizio": L("20221019")}]
    elif nome == "camera_governi":
        righe = [{"g": U(OCD + "governo.rdf/g182"), "t": L("I Governo Draghi (12.02.2021 - 21.10.2022)"), "d": L("20210212-20221021")},
                 {"g": U(OCD + "governo.rdf/g202"), "t": L("I Governo Meloni (21.10.2022)"), "d": L("20221021")}]
    elif nome == "camera_giorni":
        righe = [{"data": L(g)} for g in sorted({v["d"] for v in D_["cvot"]})]
    elif nome == "camera_lista":
        righe = [{"v": U(v["uri"])} for v in D_["cvot"] if v["d"] == giorno]
    elif nome == "senato_lista":
        sed = seduta.rsplit("/", 1)[-1]
        righe = [{"v": U(v["uri"])} for v in D_["svot"] if v["sed"] == sed]
    elif nome == "camera_votazioni":
        if "VALUES" not in q:
            raise KeyError("manca VALUES")
        for v in [v for v in D_["cvot"] if v["d"] == giorno and f"<{v['uri']}>" in q]:
            s = v["uri"]
            props = [(RDF + "type", U(OCD + "votazione")), (DC + "date", L(v["d"])), (DC + "identifier", L(s.rsplit("/", 1)[1])),
                     (DC + "description", L(v["desc"])), (RDFS + "label", L(f"Votazione n. {v['nv']}")),
                     (OCD + "approvato", B(v["app"])), (OCD + "votazioneFinale", B(v["finale"])),
                     (OCD + "votazioneSegreta", B(v["segreta"])), (OCD + "richiestaFiducia", B(v["fiducia"])),
                     (OCD + "favorevoli", I(v["f"])), (OCD + "contrari", I(v["c"])), (OCD + "astenuti", I(v["a"])),
                     (OCD + "rif_seduta", U(f"{OCD}seduta.rdf/s19_{v['d']}")), (OCD + "rif_attoCamera", U(f"{OCD}attocamera.rdf/ac19_1234"))]
            righe += [{"v": U(s), "p": U(p), "o": o} for p, o in props]
    elif nome == "camera_atti":
        for v in [v for v in D_["cvot"] if v["d"] == giorno and v["nv"] in (1, 2, 4)]:
            righe.append({"v": U(v["uri"]), "atto": U(f"{OCD}attocamera.rdf/ac19_1234"), "titolo": L("Disposizioni in materia di prova")})
    elif nome == "camera_titoli_atti":
        if "VALUES" not in q:
            raise KeyError("manca VALUES")
        for n in re.findall(r"attocamera\.rdf/ac19_(\d+)>", q):
            if n == "1234":
                righe.append({"atto": U(f"{OCD}attocamera.rdf/ac19_{n}"),
                              "titolo": L('ROSSI ed altri: "Disposizioni in materia di prova" (1234)')})
    elif nome == "camera_voti":
        for v in [v for v in D_["cvot"] if v["d"] == giorno and f"<{v['uri']}>" in q]:
            righe += [{"v": U(v["uri"]), "dep": U(d), "espr": L(e)} for d, e in v["voti"].items()]
            # come nella banca dati vera: a volte compare un "deputato 0" che non è nei totali ufficiali
            righe.append({"v": U(v["uri"]), "dep": U("http://dati.camera.it/ocd/deputato.rdf/d0_19"), "espr": L("Favorevole")})
    elif nome == "senato_senatori":
        for s in D_["sen"]:
            if s["vita"]:
                continue
            righe.append({"s": U(s["uri"]), "nome": L(s["nome"]), "cognome": L(s["cognome"]),
                          "m": U(s["uri"] + "/m19"), "inizio": D(s["m"][0]), "tipo": L("elettivo")})
        # ex senatore oggi deputato: la banca dati del Senato elenca il suo mandato alla Camera
        righe.append({"s": U("http://dati.senato.it/senatore/99999"), "nome": L("Paolo"), "cognome": L("Deputato"),
                      "m": U("http://dati.senato.it/mandato/C_19_99999_1"), "inizio": D("2022-10-13")})
    elif nome == "senato_senatore_extra":
        uri = re.search(r"<(http://dati\.senato\.it/senatore/\d+)>", q).group(1)
        s = next(x for x in D_["sen"] if x["uri"] == uri)
        righe = [{"nome": L(s["nome"]), "cognome": L(s["cognome"]), "m": U(uri + "/m18"), "inizio": D(s["m"][0]),
                  "tipo": L("di nomina presidenziale (a vita)")}]
    elif nome == "senato_adesioni":
        for s in D_["sen"]:
            for g, da, a, car in s["g"]:
                r = {"s": U(s["uri"]), "g": U(f"http://dati.senato.it/gruppo/{g}"), "inizio": D(da), "carica": L(car)}
                righe.append(r)
                if car == "Presidente":  # nei dati veri il presidente è anche "Membro" dallo stesso giorno
                    righe.append(dict(r, carica=L("Membro")))
    elif nome == "senato_gruppi":
        for g, (nom, _, _) in D_["sg"].items():
            righe.append({"g": U(f"http://dati.senato.it/gruppo/{g}"), "titolo": L(nom), "inizio": D("2022-10-13")})
        righe.append({"g": U("http://dati.senato.it/gruppo/49"), "titolo": L("Misto (vecchia denominazione)"),
                      "inizio": D("2018-03-23"), "fine": D("2022-10-12")})
    elif nome == "senato_sedute":
        for sed, d in D_["sedute"]:
            righe.append({"s": U(f"http://dati.senato.it/sedutaassemblea/{sed}"), "data": D(d), "num": I(int(sed) - 22400)})
    elif nome == "senato_votazioni":
        if "VALUES" in q or "POST" in q:
            raise KeyError("il Senato non conosce VALUES")
        sed = seduta.rsplit("/", 1)[-1]
        for v in [v for v in D_["svot"] if v["sed"] == sed and f"<{v['uri']}>" in q]:
            s = v["uri"]
            props = [(RDF + "type", U(OSR + "Votazione")), (OSR + "numero", I(v["nv"])), (RDFS + "label", L(v["label"])),
                     (OSR + "seduta", U(seduta)), (OSR + "legislatura", I(19)),
                     (OSR + "tipoVotazione", L("verifica numero legale" if v["legale"] else "elettronica")),
                     (OSR + "esito", L("approvato" if len(v["liste"].get("favorevole", [])) > len(v["liste"].get("contrario", [])) else "respinto")),
                     (OSR + "favorevoli", I(len(v["liste"].get("favorevole", [])))),
                     (OSR + "contrari", I(len(v["liste"].get("contrario", [])))),
                     (OSR + "astenuti", I(len(v["liste"].get("astenuto", []))))]
            for lista, sens in v["liste"].items():
                props += [(OSR + lista, U(x)) for x in sens]
            righe += [{"v": U(s), "p": U(p), "o": o} for p, o in props]
    elif nome.startswith("leggi_"):
        righe = risposta_leggi(nome, q, D_)
    elif nome == "senato_ddl":
        sed = seduta.rsplit("/", 1)[-1]
        for v in [v for v in D_["svot"] if v["sed"] == sed and not v["legale"]]:
            righe.append({"v": U(v["uri"]), "ddl": U("http://dati.senato.it/ddl/1026"), "breve": L("Legge annuale sulle PMI")})
    else:
        raise KeyError(nome)
    m = re.search(r"LIMIT\s+(\d+)\s+OFFSET\s+(\d+)", q)
    if m:
        lim, off = int(m.group(1)), int(m.group(2))
        if "ORDER BY" in q and lim + off > 10000:
            raise ValueError("Virtuoso 22023 Error SR353: Sorted TOP clause specifies more then 10000 rows")
        righe = righe[off:off + min(lim, MAX_RIGHE)]
    else:
        righe = righe[:MAX_RIGHE]
    return {"head": {"vars": vars_}, "results": {"bindings": righe}}


SKOS = "http://www.w3.org/2004/02/skos/core#"
S_ = lambda v: {"type": "typed-literal", "datatype": XSD + "string", "value": str(v)}  # noqa: E731
# disegni di legge finti: una legge approvata in due letture (C.1234 -> S.1026), una proposta
# appena presentata da un deputato e un decreto-legge in commissione al Senato
DDL = [
    {"uri": "http://dati.senato.it/ddl/5001", "f": "C.1234", "r": "C", "id": 900, "prog": 1,
     "t": "Legge annuale per il mercato e la concorrenza delle piccole e medie imprese", "tb": "",
     "s": "approvato", "ds": "2023-06-15", "dp": "2023-01-10", "nat": "ordinario", "descr": "Pres. Consiglio Meloni Giorgia (Meloni-I)",
     "legge": "", "teseo": ["PICCOLE E MEDIE IMPRESE", "CONCORRENZA"],
     "comm": ("10&ordf; (Attivit&agrave; produttive, commercio e turismo)", "referente", "2023-01-20"),
     "rel": ("On. Mario Rossi 3", None), "pf": ("Pres. Consiglio  Giorgia Meloni (Gov. Meloni-I)", "Governativa", None), "nf": 2},
    {"uri": "http://dati.senato.it/ddl/5002", "f": "S.1026", "r": "S", "id": 900, "prog": 2,
     "t": "Legge annuale per il mercato e la concorrenza delle piccole e medie imprese", "tb": "Legge annuale sulle PMI",
     "s": "appr. definit. Legge", "ds": "2026-11-19", "dp": "2023-06-16", "nat": "ordinario", "descr": "Pres. Consiglio Meloni Giorgia (Meloni-I)",
     "legge": "55", "teseo": ["PICCOLE E MEDIE IMPRESE"],
     "comm": ("9&ordf; (Industria, commercio, turismo, agricoltura e produzione agroalimentare)", "referente", "2023-06-20"),
     "rel": ("Sen. Anna Bianchi 2", "http://dati.senato.it/senatore/30002"), "pf": ("Pres. Consiglio  Giorgia Meloni (Gov. Meloni-I)", "Governativa", None), "nf": 2},
    {"uri": "http://dati.senato.it/ddl/5003", "f": "C.2000", "r": "C", "id": 901, "prog": 1,
     "t": "Disposizioni per lo sviluppo delle energie rinnovabili", "tb": "",
     "s": "assegnato (no esame)", "ds": "2026-11-12", "dp": "2026-11-10", "nat": "ordinario", "descr": "Dep. Rossi 1 Mario ed altri",
     "legge": "", "teseo": ["FONTI RINNOVABILI DI ENERGIA"],
     "comm": ("8&ordf; (Ambiente, territorio e lavori pubblici)", "referente", "2026-11-12"),
     "rel": None, "pf": ("On. Mario Rossi 1", "Parlamentare", "http://dati.camera.it/ocd/deputato.rdf/d300001_19"), "nf": 4},
    {"uri": "http://dati.senato.it/ddl/5004", "f": "S.1500", "r": "S", "id": 902, "prog": 1,
     "t": "Conversione in legge del decreto-legge 1 novembre 2026, n. 170, recante misure urgenti in materia sanitaria", "tb": "d-l 170/2026 - Sanità",
     "s": "esame in comm.", "ds": "2026-11-05", "dp": "2026-11-02", "nat": "di conversione di decreto-legge", "descr": "Pres. Consiglio Meloni Giorgia (Meloni-I)",
     "legge": "", "teseo": ["TUTELA DELLA SALUTE"],
     "comm": ("10&ordf; (Affari sociali, sanit&agrave;, lavoro pubblico e privato, previdenza sociale)", "referente", "2026-11-03"),
     "rel": ("Sen. Anna Bianchi 70", "http://dati.senato.it/senatore/30070"), "pf": ("Pres. Consiglio  Giorgia Meloni (Gov. Meloni-I)", "Governativa", None), "nf": 1},
]


def risposta_leggi(nome, q, D_):
    m = re.search(r"ramo=(\w)", q)
    ramo = m.group(1) if m else None
    if 'str(?ramo) = "' not in q and nome != "leggi_voti":
        raise KeyError("manca il filtro sul ramo")
    righe = []
    for d in [d for d in DDL if d["r"] == ramo]:
        u = U(d["uri"])
        if nome == "leggi_base":
            x = {"d": u, "f": S_(d["f"]), "id": I(d["id"]), "titolo": S_(d["t"]), "stato": S_(d["s"]), "ds": D(d["ds"]),
                 "dp": S_(d["dp"]), "nat": S_(d["nat"]), "descr": S_(d["descr"]), "prog": I(d["prog"])}
            if d["tb"]:
                x["breve"] = S_(d["tb"])
            if d["legge"]:
                x["legge"] = S_(d["legge"])
            righe += [x, dict(x)]  # come il Senato vero: ogni risultato compare due volte se manca DISTINCT
        elif nome == "leggi_teseo":
            righe += [{"d": u, "lab": L(t)} for t in d["teseo"]]
        elif nome == "leggi_commissioni":
            righe.append({"d": u, "lab": L(d["comm"][0]), "sede": S_(d["comm"][1]), "data": D(d["comm"][2])})
        elif nome == "leggi_relatori" and d["rel"]:
            x = {"d": u, "nome": L(d["rel"][0])}
            if d["rel"][1]:
                x["sen"] = U(d["rel"][1])
            righe.append(x)
        elif nome == "leggi_firmatari":
            x = {"d": u, "pres": L(d["pf"][0]), "tipo": S_(d["pf"][1])}
            if d["pf"][2]:
                x["dep"] = U(d["pf"][2])
            righe.append(x)
        elif nome == "leggi_conta_firme":
            righe.append({"d": u, "n": I(d["nf"])})
    if nome == "leggi_voti":
        righe = [{"v": U(v["uri"]), "f": S_("S.1026")} for v in D_["svot"] if not v["legale"]]
    return righe


class Gestore(BaseHTTPRequestHandler):
    errori_iniettati = {"n": 0}
    contatore = {"n": 0}

    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        q = qs.get("query", [""])[0]
        Gestore.contatore["n"] += 1
        if url.path.startswith("/senato") and len(url.query) > 2000:
            self.send_response(403)  # come il Senato vero con le richieste troppo lunghe
            self.end_headers()
            return
        if url.path.startswith("/senato") and "Mozilla" not in self.headers.get("User-Agent", ""):
            self.send_response(403)
            self.end_headers()
            return
        if Gestore.contatore["n"] == 3 and Gestore.errori_iniettati["n"] == 0:
            Gestore.errori_iniettati["n"] += 1
            self.send_response(503)
            self.end_headers()
            return
        m = re.search(r"# q:(\w+)", q)
        try:
            corpo = json.dumps(risposta(m.group(1), q)).encode()
        except Exception as e:  # noqa: BLE001
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(e).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/sparql-results+json")
        self.end_headers()
        self.wfile.write(corpo)


def avvia(porta=0):
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Gestore)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
