"""Indicatori calcolati sui voti individuali.

Definizioni (le stesse spiegate nella pagina "Fonti e metodo" del sito):
- posizione di un gruppo in una votazione: l'opzione (Sì, No, astensione) scelta
  dal maggior numero dei suoi membri che hanno votato; in caso di parità "diviso".
  È ricavata dai voti, non dall'indicazione ufficiale del gruppo, che non è un dato aperto.
- compattezza: quota media dei votanti del gruppo che hanno seguito la posizione del gruppo.
- partecipazione: quota di votazioni in cui un parlamentare in carica era presente
  (ha votato, o era presente senza votare). Le missioni sono contate a parte.
- voti diversi dal gruppo: votazioni palesi in cui il parlamentare ha votato in modo
  diverso dalla posizione del suo gruppo (escluso il Misto, che non ha una linea comune).
- allineamento alla maggioranza: quota di votazioni palesi in cui la posizione del gruppo
  coincide con quella prevalente tra i deputati o senatori dei gruppi di maggioranza.
- convergenza tra due gruppi: quota di votazioni palesi in cui hanno preso la stessa posizione.
Le verifiche del numero legale sono escluse da tutti gli indicatori.
"""
import datetime as dt
import os
from collections import defaultdict

from comune import CODICI_POSIZIONE, CODICI_PRESENTE

MIN_VOTAZIONI_MATRICE = int(os.environ.get("BUSSOLA_MIN_MATRICE", "30"))
MAX_DIVERSI_PER_MEMBRO = 80


def _giorno(s):
    return dt.date.fromisoformat(s)


def unisci_intervalli(adesioni):
    """[(gid, da, a)] -> intervalli uniti per gruppo, ordinati per inizio."""
    per_g = defaultdict(list)
    for gid, da, a in adesioni:
        if da:
            per_g[gid].append([da, a])
    out = []
    for gid, ints in per_g.items():
        ints.sort(key=lambda x: x[0])
        unito = [ints[0][:]]
        for da, a in ints[1:]:
            ult = unito[-1]
            if ult[1] is None:
                continue
            if _giorno(da) <= _giorno(ult[1]) + dt.timedelta(days=1):
                ult[1] = None if a is None else max(ult[1], a)
            else:
                unito.append([da, a])
        out += [[gid, da, a] for da, a in unito]
    out.sort(key=lambda x: (x[1], x[0]))
    return out


def in_intervallo(d, da, a):
    return (da is None or da <= d) and (a is None or d <= a)


def gruppo_alla_data(adesioni, d):
    trovato = None
    for gid, da, a in adesioni:  # ordinate per inizio: vince l'ultima che copre la data
        if in_intervallo(d, da, a):
            trovato = gid
    return trovato


def in_carica(mandati, d):
    return any(in_intervallo(d, da, a) for da, a in mandati)


def posizione(f, c, a):
    tot = f + c + a
    if tot == 0:
        return "-"
    m = max(f, c, a)
    if [f, c, a].count(m) > 1:
        return "D"
    return "F" if f == m else "C" if c == m else "A"


FIDUCIE_CONSIDERATE = 15   # ultime votazioni di fiducia guardate per ogni gruppo
SOGLIA_COALIZIONE = 0.7    # quota di Sì (o di No) per dirsi di maggioranza (o di opposizione)


class Calcolo:
    def __init__(self, membri, gruppi, votazioni, oggi, inizio_governo=None):
        self.membri = membri          # lista ordinata per indice i
        self.gruppi = gruppi          # gid -> info (con 'coal' e 'chiave')
        self.votazioni = votazioni    # ordinate per data e numero
        self.oggi = oggi
        self.inizio_governo = inizio_governo
        self._cache_date = {}

    def coalizioni_da_fiducia(self):
        """Maggioranza e opposizione ricavate dai voti di fiducia al governo in carica:
        un gruppo che nelle sue ultime fiducie ha votato Sì almeno il 70% delle volte è di
        maggioranza, No almeno il 70% di opposizione, altrimenti 'altro'. Il Misto resta 'altro'."""
        storia = defaultdict(list)
        for v in self.votazioni:
            if v.get("c") != "fiducia" or "S" in v.get("f", ""):
                continue
            if self.inizio_governo and v["d"] < self.inizio_governo:
                continue
            gvec = self.gruppi_alla_data(v["d"])
            s = v.get("v", "")
            conta = {}
            for i, g in enumerate(gvec):
                c = s[i] if i < len(s) else "."
                if g is not None and c in "FCA":
                    conta.setdefault(g, [0, 0, 0])["FCA".index(c)] += 1
            for g, x in conta.items():
                p = posizione(*x)
                if p in CODICI_POSIZIONE:
                    storia[g].append(p)
        out = {}
        for g, pos in storia.items():
            if self.gruppi.get(g, {}).get("chiave") == "misto":
                continue
            ultime = pos[-FIDUCIE_CONSIDERATE:]
            n = len(ultime)
            if n < 3:
                continue
            si, no = ultime.count("F") / n, ultime.count("C") / n
            coal = "maggioranza" if si >= SOGLIA_COALIZIONE else "opposizione" if no >= SOGLIA_COALIZIONE else "altro"
            out[g] = {"coal": coal, "n": n, "si": round(si, 3), "no": round(no, 3)}
        return out

    def gruppi_alla_data(self, d):
        if d not in self._cache_date:
            self._cache_date[d] = [gruppo_alla_data(m["adesioni"], d) for m in self.membri]
        return self._cache_date[d]

    def esegui(self):
        G = self.gruppi
        auto = self.coalizioni_da_fiducia()
        for g, info in G.items():
            if g in auto:
                info["coal"] = auto[g]["coal"]
                info["coal_fonte"] = "fiducia"
                info["fiducia"] = {k: auto[g][k] for k in ("n", "si", "no")}
            else:
                info["coal_fonte"] = "configurazione"
                info.pop("fiducia", None)
        nm = len(self.membri)
        st = [dict(tot=0, pres=0, mis=0, ass=0, cmp=0, dis=0) for _ in range(nm)]
        diversi = [[] for _ in range(nm)]
        gs = {g: dict(coe_s=0.0, coe_n=0, all_s=0, all_n=0, par_p=0, par_t=0, pos=defaultdict(int),
                      anni=defaultdict(lambda: [0.0, 0, 0, 0, 0, 0])) for g in G}
        conv = defaultdict(lambda: [0, 0])  # (g1,g2) -> [uguali, entrambi]
        ordine = self.ordine_gruppi()

        for k, v in enumerate(self.votazioni):
            d = v["d"]
            anno = d[:4]
            gvec = self.gruppi_alla_data(d)
            s = v.get("v", "")
            conteggi = {}
            legale = "L" in v.get("f", "")
            for i in range(nm):
                c = s[i] if i < len(s) else "."
                g = gvec[i]
                if c == ".":
                    continue
                if g is not None:
                    x = conteggi.setdefault(g, [0, 0, 0, 0, 0, 0])
                    if c in "FCA":
                        x["FCA".index(c)] += 1
                    elif c in "VNP":
                        x[3] += 1
                    elif c == "M":
                        x[4] += 1
                    else:
                        x[5] += 1
                if legale:
                    continue
                st[i]["tot"] += 1
                if c in CODICI_PRESENTE:
                    st[i]["pres"] += 1
                elif c == "M":
                    st[i]["mis"] += 1
                else:
                    st[i]["ass"] += 1
                if g is not None:
                    gs[g]["par_t"] += 1
                    gs[g]["anni"][anno][5] += 1
                    if c in CODICI_PRESENTE:
                        gs[g]["par_p"] += 1
                        gs[g]["anni"][anno][4] += 1

            segreta = "S" in v.get("f", "") or any(x[3] and not (x[0] or x[1] or x[2]) for x in conteggi.values())
            pos = {}
            if not segreta and not legale:
                pos = {g: posizione(*x[:3]) for g, x in conteggi.items()}
            # posizione prevalente tra i membri dei gruppi di maggioranza e di opposizione
            coal = {}
            for nome in ("maggioranza", "opposizione"):
                tot = [0, 0, 0]
                for g, x in conteggi.items():
                    if G.get(g, {}).get("coal") == nome:
                        tot = [tot[j] + x[j] for j in range(3)]
                coal[nome] = posizione(*tot) if pos else "-"
            v["g"] = conteggi
            v["p"] = "".join(pos.get(g, "." if g not in conteggi else "-") for g in ordine)
            v["pm"] = coal["maggioranza"]
            v["po"] = coal["opposizione"]

            if pos:
                pm = coal["maggioranza"]
                for g, p in pos.items():
                    x = conteggi[g]
                    if p in CODICI_POSIZIONE:
                        gs[g]["pos"][p] += 1
                    n_vot = x[0] + x[1] + x[2]
                    if n_vot >= 2 and p != "-":
                        q = max(x[:3]) / n_vot
                        gs[g]["coe_s"] += q
                        gs[g]["coe_n"] += 1
                        gs[g]["anni"][anno][0] += q
                        gs[g]["anni"][anno][1] += 1
                    if p in CODICI_POSIZIONE and pm in CODICI_POSIZIONE:
                        gs[g]["all_n"] += 1
                        gs[g]["anni"][anno][3] += 1
                        if p == pm:
                            gs[g]["all_s"] += 1
                            gs[g]["anni"][anno][2] += 1
                validi = [g for g, p in pos.items() if p in CODICI_POSIZIONE]
                for a in validi:
                    for b in validi:
                        if a < b:
                            cv = conv[(a, b)]
                            cv[1] += 1
                            if pos[a] == pos[b]:
                                cv[0] += 1
                for i in range(nm):
                    c = s[i] if i < len(s) else "."
                    g = gvec[i]
                    if c in CODICI_POSIZIONE and g is not None and G.get(g, {}).get("chiave") != "misto":
                        p = pos.get(g)
                        if p in CODICI_POSIZIONE:
                            st[i]["cmp"] += 1
                            if c != p:
                                st[i]["dis"] += 1
                                diversi[i].append([k, c])

        # ---- risultati: membri
        for i, m in enumerate(self.membri):
            m["st"] = st[i]
            m["div"] = diversi[i][-MAX_DIVERSI_PER_MEMBRO:]

        # ---- risultati: gruppi
        attuali = defaultdict(int)
        for m in self.membri:
            if in_carica(m["mandati"], self.oggi):
                g = gruppo_alla_data(m["adesioni"], self.oggi)
                if g:
                    attuali[g] += 1
        out_g = []
        for g in ordine:
            x = gs[g]
            info = dict(G[g])
            info.update({
                "id": g,
                "membri": attuali.get(g, 0),
                "coesione": round(x["coe_s"] / x["coe_n"], 4) if x["coe_n"] else None,
                "n_coesione": x["coe_n"],
                "partecipazione": round(x["par_p"] / x["par_t"], 4) if x["par_t"] else None,
                "allineamento": round(x["all_s"] / x["all_n"], 4) if x["all_n"] else None,
                "n_allineamento": x["all_n"],
                "posizioni": dict(x["pos"]),
                "anni": {a: {
                    "coesione": round(y[0] / y[1], 4) if y[1] else None,
                    "allineamento": round(y[2] / y[3], 4) if y[3] else None,
                    "n": y[3],
                    "partecipazione": round(y[4] / y[5], 4) if y[5] else None,
                } for a, y in sorted(x["anni"].items())},
            })
            out_g.append(info)

        npos = {g: sum(gs[g]["pos"].values()) for g in ordine}
        mat_ids = [g for g in ordine if npos[g] >= MIN_VOTAZIONI_MATRICE]
        matrice = []
        for a in mat_ids:
            riga = []
            for b in mat_ids:
                if a == b:
                    riga.append(None)
                    continue
                u, n = conv.get((min(a, b), max(a, b)), [0, 0])
                riga.append([round(u / n, 4), n] if n else None)
            matrice.append(riga)
        return {"gruppi": out_g, "ordine": ordine, "convergenza": {"ids": mat_ids, "m": matrice},
                "cambi": self.cambi()}

    def ordine_gruppi(self):
        rank = {"maggioranza": 0, "opposizione": 1, "altro": 2}
        conta = defaultdict(int)
        for m in self.membri:
            for g, _, _ in m["adesioni"]:
                conta[g] += 1
        usati = [g for g in self.gruppi if conta[g]]
        attuali = defaultdict(int)
        for m in self.membri:
            if in_carica(m["mandati"], self.oggi):
                g = gruppo_alla_data(m["adesioni"], self.oggi)
                if g:
                    attuali[g] += 1
        return sorted(usati, key=lambda g: (rank.get(self.gruppi[g].get("coal"), 3),
                                            self.gruppi[g].get("chiave") == "misto",
                                            -attuali[g], -conta[g], g))

    def cambi(self):
        fine_gruppo = {}
        for m in self.membri:
            for g, da, a in m["adesioni"]:
                if g not in fine_gruppo:
                    fine_gruppo[g] = a
                elif fine_gruppo[g] is not None:
                    fine_gruppo[g] = None if a is None else max(fine_gruppo[g], a)
        out = []
        for m in self.membri:
            ad = m["adesioni"]
            for prima, dopo in zip(ad, ad[1:]):
                if prima[0] == dopo[0]:
                    continue
                d = dopo[1]
                fg = fine_gruppo.get(prima[0])
                sciolto = fg is not None and _giorno(fg) <= _giorno(d) + dt.timedelta(days=7)
                stesso = (self.gruppi.get(prima[0], {}).get("chiave") == self.gruppi.get(dopo[0], {}).get("chiave")
                          and self.gruppi.get(prima[0], {}).get("chiave") != "misto")
                out.append({"i": m["i"], "da": prima[0], "a": dopo[0], "d": d, "sciolto": sciolto, "stesso": stesso})
        out.sort(key=lambda x: x["d"], reverse=True)
        return out
