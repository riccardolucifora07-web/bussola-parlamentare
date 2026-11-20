"""Funzioni comuni: date, nomi, file JSON, classificazione delle votazioni."""
import gzip
import html
import json
import os
import re
import tempfile

INIZIO_LEG = "2022-10-13"  # prima seduta della XIX legislatura


# ---------- date ----------
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_RE_COMPATTA = re.compile(r"^(\d{4})(\d{2})(\d{2})")
_RE_PUNTI = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")


def data_iso(x):
    """Normalizza '20221025', '2022-10-25', '2022-10-25T00:00:00', '25.10.2022' in 'AAAA-MM-GG'."""
    if x is None:
        return None
    s = str(x).strip()
    m = _RE_ISO.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _RE_COMPATTA.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _RE_PUNTI.search(s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def date_in_testo(s):
    """Tutte le date gg.mm.aaaa presenti in un'etichetta, in ordine."""
    if not s:
        return []
    return [f"{a}-{int(b):02d}-{int(g):02d}" for g, b, a in _RE_PUNTI.findall(str(s))]


# ---------- nomi ----------
_PARTICELLE = {"de", "di", "da", "del", "della", "dei", "degli", "dello", "la", "lo", "le", "van", "von"}


def nome_proprio(s):
    """'D'ALESSIO' -> "D'Alessio"; lascia invariati i nomi già in maiuscolo/minuscolo misto."""
    if not s:
        return ""
    s = " ".join(str(s).split())
    if s != s.upper():
        return s
    parti = []
    for i, w in enumerate(s.lower().split(" ")):
        w = "-".join(x[:1].upper() + x[1:] for x in w.split("-"))
        w = "'".join(x[:1].upper() + x[1:] for x in w.split("'"))
        parti.append(w)
    return " ".join(parti)


_SIGLE = {"PPE", "UDC", "MAIE", "SVP", "PATT", "AVS", "IDP", "M5S", "FDI", "PD", "NM", "CP", "RE", "PSI", "USEI", "UE", "PRI"}
_MINUSCOLE = {"e", "di", "d", "del", "della", "delle", "dei", "degli", "per", "le", "la", "il", "lo", "l",
              "con", "al", "a", "in", "da", "ed"}


def nome_gruppo(s):
    """'FRATELLI D'ITALIA' -> "Fratelli d'Italia"; 'FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE' -> '... - PPE'."""
    if not s or s != s.upper():
        return s or ""
    out, primo = [], True
    for tok in re.findall(r"[^\W_]+|[\W_]+", s):
        if not tok[0].isalnum():
            out.append(tok)
            continue
        if tok in _SIGLE:
            out.append(tok)
        elif tok.lower() in _MINUSCOLE and not primo:
            out.append(tok.lower())
        else:
            out.append(tok[:1].upper() + tok[1:].lower())
        primo = False
    return "".join(out)


def pulisci_nome_gruppo(s):
    if not s:
        return ""
    s = re.sub(r"\s*\((?:dal|dall'|\d)[^)]*\)\s*$", "", str(s).strip(), flags=re.I)
    return " ".join(s.split())


# ---------- file ----------
def leggi_json(percorso, predefinito=None):
    try:
        if percorso.endswith(".gz"):
            with gzip.open(percorso, "rt", encoding="utf-8") as f:
                return json.load(f)
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return predefinito


def scrivi_json(percorso, dati, compatto=True):
    """Scrittura atomica; restituisce True se il contenuto è cambiato."""
    os.makedirs(os.path.dirname(percorso) or ".", exist_ok=True)
    if compatto:
        testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    else:
        testo = json.dumps(dati, ensure_ascii=False, indent=1)
    try:
        with open(percorso, encoding="utf-8") as f:
            if f.read() == testo:
                return False
    except FileNotFoundError:
        pass
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(percorso) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(testo)
    os.replace(tmp, percorso)
    return True


def nome_locale(uri):
    """Ultima parte di un URI (dopo # o /)."""
    if not uri:
        return ""
    return re.split(r"[#/]", str(uri))[-1]


# ---------- classificazione delle votazioni ----------
CATEGORIE = {
    "finale": "Voto finale",
    "fiducia": "Fiducia",
    "emendamento": "Emendamento",
    "articolo": "Articolo",
    "odg": "Ordine del giorno",
    "mozione": "Mozione o risoluzione",
    "pregiudiziale": "Pregiudiziale o sospensiva",
    "numero_legale": "Verifica del numero legale",
    "altro": "Altro",
}

_REGOLE_CAT = [
    ("fiducia", re.compile(r"fiducia", re.I)),
    ("finale", re.compile(r"vot[oa]\w*\s+finale|votazione finale|nel suo complesso|voto finale", re.I)),
    ("pregiudiziale", re.compile(r"pregiudizial|\bquest\.?\s+preg|sospensiv", re.I)),
    ("odg", re.compile(r"ordin[ei] del giorno|\bo\.?d\.?g\b|\bodg\b|^\s*9/", re.I)),
    ("mozione", re.compile(r"mozion|risoluzion|\bmoz\b|\bris\b", re.I)),
    ("emendamento", re.compile(r"\b(?:sub)?emm?\b|\bemm?\.|emendament|subem|\bart\.?\s+(?:agg|prem)", re.I)),
    ("articolo", re.compile(r"\bart(?:icol[oi]|t?\.)?\s*\d|\barticolo\b|\bart\b", re.I)),
]

# tipo dichiarato dalla Camera (dc:type della votazione): vale più della descrizione
_TIPI = [("fiducia", "fiducia"), ("finale", "finale"), ("emendament", "emendamento"),
         ("ordine del giorno", "odg"), ("mozion", "mozione"), ("risoluzion", "mozione"),
         ("articol", "articolo"), ("pregiudizial", "pregiudiziale")]


def categoria(testo, finale=False, fiducia=False, numero_legale=False, tipo=""):
    if numero_legale:
        return "numero_legale"
    if fiducia:
        return "fiducia"
    if finale:
        return "finale"
    t = (tipo or "").lower()
    for chiave, nome in _TIPI:
        if chiave in t:
            return nome
    for nome, rx in _REGOLE_CAT:
        if testo and rx.search(testo):
            return nome
    return "altro"


def pulisci_testo(s):
    """Toglie le entità HTML (anche doppie, come '&amp;#39;') e gli spazi superflui."""
    s = str(s or "")
    for _ in range(3):
        nuovo = html.unescape(s)
        if nuovo == s:
            break
        s = nuovo
    return " ".join(s.split())


# ---------- codici dei voti individuali ----------
# F favorevole, C contrario, A astenuto, V ha votato (scrutinio segreto),
# N presente non votante, P presidente di turno, M missione o congedo,
# - assente o non ha votato, . non in carica in quel ramo in quella data
CODICI_PRESENTE = set("FCAVNP")
CODICI_POSIZIONE = set("FCA")


def codice_camera(espressione):
    e = (espressione or "").strip().lower()
    if not e:
        return "?"
    if "favorev" in e:
        return "F"
    if "contrar" in e:
        return "C"
    if "asten" in e:
        return "A"
    if "non ha votato" in e or "non votante" in e or "assente" in e:
        return "-"
    if "mission" in e or "congedo" in e:
        return "M"
    if "president" in e:
        return "P"
    if "ha votato" in e or "partecip" in e:
        return "V"
    return "?"


PRIORITA = {"F": 6, "C": 6, "A": 6, "V": 5, "N": 4, "P": 3, "M": 2, "-": 1, "?": 0, ".": -1}


def unisci_codice(vecchio, nuovo):
    return nuovo if PRIORITA.get(nuovo, 0) > PRIORITA.get(vecchio, -1) else vecchio
