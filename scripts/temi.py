"""Temi di leggi e votazioni (energia, sanità, fisco...).

Le regole stanno in config/temi.json: espressioni regolari cercate nel titolo della
legge e nelle voci di classificazione ufficiali del Senato (TESEO), dopo aver tolto
accenti, apostrofi, punteggiatura e maiuscole. Una legge può avere più temi."""
import json
import os
import re
import unicodedata

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TEMI = 3


def normalizza(testo):
    s = unicodedata.normalize("NFKD", str(testo or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()  # toglie gli accenti
    s = re.sub(r"[^a-z0-9]+", " ", s)  # apostrofi e punteggiatura diventano spazi
    return " " + s.strip() + " "


class Temi:
    def __init__(self, percorso=None):
        with open(percorso or os.path.join(RADICE, "config", "temi.json"), encoding="utf-8") as f:
            dati = json.load(f)
        self.elenco = [{"codice": t["codice"], "nome": t["nome"]} for t in dati["temi"]]
        self.regole = [(t["codice"], [re.compile(r) for r in t["regole"]]) for t in dati["temi"]]

    def nomi(self):
        return {t["codice"]: t["nome"] for t in self.elenco}

    def classifica(self, *testi):
        """Codici dei temi trovati nei testi, ordinati per numero di corrispondenze (al massimo 3)."""
        s = normalizza(" ".join(str(t) for t in testi if t))
        if not s.strip():
            return []
        punti = []
        for i, (codice, rr) in enumerate(self.regole):
            n = sum(1 for r in rr if r.search(s))
            if n:
                punti.append((-n, i, codice))
        return [c for _, _, c in sorted(punti)[:MAX_TEMI]]
