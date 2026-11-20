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
        righe = [{"d": U(capo), "i": U(capo + "_inc1"), "g": U(f"{OCD}gruppoParlamentare.rdf/gr1"), "p": U(DC + "title"), "o": L("PRESIDENTE")},
                 {"d": U(capo), "i": U(capo + "_inc1"), "g": U(f"{OCD}gruppoParlamentare.rdf/gr1"), "p": U(OCD + "startDate"), "o": L("20221019")},
                 {"d": U(D_["dep"][1]["uri"]), "i": U("x_inc2"), "g": U(f"{OCD}gruppoParlamentare.rdf/gr1"), "p": U(DC + "title"), "o": L("VICEPRESIDENTE")}]
    elif nome == "camera_giorni":
        righe = [{"data": L(g)} for g in sorted({v["d"] for v in D_["cvot"]})]
    elif nome == "camera_votazioni":
        for v in [v for v in D_["cvot"] if v["d"] == giorno]:
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
    elif nome == "camera_voti":
        for v in [v for v in D_["cvot"] if v["d"] == giorno]:
            righe += [{"v": U(v["uri"]), "dep": U(d), "espr": L(e)} for d, e in v["voti"].items()]
    elif nome == "senato_senatori":
        for s in D_["sen"]:
            if s["vita"]:
                continue
            righe.append({"s": U(s["uri"]), "nome": L(s["nome"]), "cognome": L(s["cognome"]),
                          "m": U(s["uri"] + "/m19"), "inizio": D(s["m"][0]), "tipo": L("elettivo")})
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
        sed = seduta.rsplit("/", 1)[1]
        for v in [v for v in D_["svot"] if v["sed"] == sed]:
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
    elif nome == "senato_ddl":
        sed = seduta.rsplit("/", 1)[1]
        for v in [v for v in D_["svot"] if v["sed"] == sed and not v["legale"]]:
            righe.append({"v": U(v["uri"]), "ddl": U("http://dati.senato.it/ddl/1026"), "breve": L("Legge annuale sulle PMI")})
    else:
        raise KeyError(nome)
    m = re.search(r"LIMIT\s+(\d+)\s+OFFSET\s+(\d+)", q)
    if m:
        lim, off = int(m.group(1)), int(m.group(2))
        righe = righe[off:off + min(lim, MAX_RIGHE)]
    return {"head": {"vars": vars_}, "results": {"bindings": righe}}


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
