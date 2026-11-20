"""Client SPARQL minimale (solo libreria standard) per gli endpoint Virtuoso
di dati.camera.it e dati.senato.it.

- Ritenta in caso di errori di rete, 5xx o risultati parziali di Virtuoso.
- Pagina i risultati finché una pagina torna vuota: così funziona anche se
  l'endpoint ha un limite di righe più basso della pagina richiesta.
- Manda uno User-Agent da browser: il Senato risponde 403 senza.
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 BussolaParlamentare/1.0")

PREFISSI = """PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX osr: <http://dati.senato.it/osr/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

LIMITE_RIGHE = 10000      # righe massime per risposta (Camera e Senato)
LIMITE_ORDINATE = 10000   # OFFSET + LIMIT massimi con ORDER BY

INTERI = ("integer", "int", "long", "short", "nonNegativeInteger", "positiveInteger",
          "unsignedInt", "unsignedLong", "byte")


class ErroreSparql(Exception):
    pass


def converti(b):
    """Converte un binding SPARQL JSON in un valore Python semplice."""
    if b is None:
        return None
    t, v = b.get("type"), b.get("value")
    dt = b.get("datatype", "")
    if t == "uri":
        return v
    if t == "bnode":
        return "_:" + v
    if dt:
        loc = dt.rsplit("#", 1)[-1]
        if loc in INTERI:
            try:
                return int(v)
            except ValueError:
                return v
        if loc in ("decimal", "double", "float"):
            try:
                return float(v)
            except ValueError:
                return v
        if loc == "boolean":
            return v.strip().lower() in ("1", "true")
    return v


class Endpoint:
    def __init__(self, url, nome, pausa=0.35, timeout=180, tentativi=5, pagina=5000, log=None):
        self.url = url
        self.nome = nome
        self.pausa = pausa
        self.timeout = timeout
        self.tentativi = tentativi
        self.pagina = pagina
        self.richieste = 0
        self.log = log or (lambda *a: print(*a, file=sys.stderr, flush=True))

    def _get(self, query):
        params = urllib.parse.urlencode({
            "query": query,
            "format": "application/sparql-results+json",
            "timeout": str(self.timeout * 1000),
        })
        req = urllib.request.Request(
            self.url + ("&" if "?" in self.url else "?") + params,
            headers={"Accept": "application/sparql-results+json", "User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=self.timeout + 30) as r:
            stato_sql = r.headers.get("X-SQL-State", "")
            corpo = r.read()
        if stato_sql and stato_sql.upper().startswith("S1TAT"):
            raise ErroreSparql("risultato parziale (timeout Virtuoso)")
        return json.loads(corpo.decode("utf-8"))

    def query(self, q):
        q = PREFISSI + q
        attesa = 3
        ultimo = None
        for n in range(1, self.tentativi + 1):
            try:
                time.sleep(self.pausa)
                self.richieste += 1
                dati = self._get(q)
                righe = dati.get("results", {}).get("bindings", [])
                return [{k: converti(v) for k, v in r.items()} for r in righe]
            except urllib.error.HTTPError as e:
                ultimo = e
                corpo = ""
                try:
                    corpo = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                # 400 = query sbagliata: inutile ritentare
                if e.code == 400 or (e.code < 500 and e.code not in (403, 408, 429)):
                    raise ErroreSparql(f"{self.nome}: HTTP {e.code} {corpo}") from e
                riga = " ".join(corpo.split())[:240]
                self.log(f"  [{self.nome}] HTTP {e.code}{': ' + riga if riga else ''}; nuovo tentativo {n}/{self.tentativi} tra {attesa}s")
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                    json.JSONDecodeError, ErroreSparql) as e:
                ultimo = e
                self.log(f"  [{self.nome}] {type(e).__name__}: {e}; nuovo tentativo {n}/{self.tentativi} tra {attesa}s")
            time.sleep(attesa)
            attesa = min(attesa * 2, 60)
        raise ErroreSparql(f"{self.nome}: troppi errori ({ultimo})")

    def query_tutto(self, q, ordina):
        """Esegue `q` a pagine (ORDER BY `ordina` LIMIT/OFFSET) fino a una pagina vuota.
        Virtuoso ordina al massimo LIMITE_ORDINATE righe (OFFSET + LIMIT): oltre serve query_lotti."""
        tutte = []
        offset = 0
        pagina = self.pagina
        while True:
            n = min(pagina, LIMITE_ORDINATE - offset)
            if n <= 0:
                raise ErroreSparql(f"{self.nome}: più di {LIMITE_ORDINATE} righe, la query va divisa in lotti")
            try:
                righe = self.query(f"{q}\nORDER BY {ordina}\nLIMIT {n} OFFSET {offset}")
            except ErroreSparql:
                if pagina <= 500:
                    raise
                pagina //= 2
                self.log(f"  [{self.nome}] riduco la pagina a {pagina} righe")
                continue
            if not righe:
                break
            tutte.extend(righe)
            offset += len(righe)
        return tutte

    def query_lotti(self, modello, uris, lotto, separatore=" "):
        """Esegue `modello` sostituendo %VALORI% con gruppi di URI (VALUES o FILTER IN).
        Se una risposta sembra tagliata dal limite di righe dell'endpoint, rifà il lotto più piccolo."""
        uris = list(uris)
        out = []
        i = 0
        while i < len(uris):
            parte = uris[i:i + lotto]
            valori = separatore.join(f"<{u}>" for u in parte)
            righe = self.query(modello.replace("%VALORI%", valori))
            n = len(righe)
            tagliata = n >= LIMITE_RIGHE or (n >= 1000 and n % 1000 == 0)
            if tagliata and len(parte) > 1:
                lotto = max(1, len(parte) // 2)
                continue
            if tagliata:
                self.log(f"  [{self.nome}] attenzione: {n} righe per un solo elemento, la risposta potrebbe essere incompleta")
            out.extend(righe)
            i += len(parte)
        return out
