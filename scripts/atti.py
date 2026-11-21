"""Legge in discussione per ogni votazione della Camera.

Dal 2026 la Camera pubblica descrizioni brevi ("EM 2.8", "ODG 9/3148/28") senza il
titolo della legge. Qui si ricava per ogni votazione il numero dell'atto Camera
(dal prefisso "DDL 3148 - ...", dal numero dell'ordine del giorno "9/3148/..", dal titolo
ufficiale "(3148)" o, se manca, dalla votazione precedente della stessa seduta) e il
titolo della legge (dai titoli già presenti nell'archivio e da camera/atti.json,
che l'aggiornamento notturno completa chiedendo i titoli mancanti all'endpoint)."""
import re

R_PREFISSO = re.compile(r"\b(?:DDL|PDL|PDLC)(?:\s+COST)?\s+(?:n\.\s*)?0*(\d+)", re.I)
R_ODG = re.compile(r"\b9/0*(\d+)")
R_AC = re.compile(r"\bA\.\s?C\.\s*0*(\d+)", re.I)
R_T_NUMERO = re.compile(r"\b(?:DDL|PDL)\s+n\.\s*0*(\d+)", re.I)
R_PARENTESI = re.compile(r"\((\d+)(?:-[A-Za-z]+)*(?:\s+e\s+abb\.?)?\)", re.I)
R_O_PARENTESI = re.compile(r"\((?:DDL|PDL)(?:\s+COST)?\s+0*(\d+)", re.I)
R_VIRGOLETTE = re.compile(r"[\"“]([^\"”]{8,})[\"”]")
# solo le descrizioni brevi senza numero ("EM 1.2", "ART AGG 1.02", "ARTICOLO 3"...) prendono
# la legge dalla votazione precedente della stessa seduta
R_EREDITA = re.compile(r"^(?:EM|ART|ARTICOLO|ODG|SUBEM|TAB|MANTENIMENTO|VOTO FINALE|QUEST)\b")
R_AUTORIFERIMENTO = re.compile(r"^(?:Ordin[ei] del giorno|Mozion[ei]|Risoluzion[ei])\b", re.I)
EREDITANO = {"emendamento", "articolo", "odg", "finale", "fiducia", "pregiudiziale"}
MAX_TITOLO = 200


def pulisci_titolo(s):
    s = re.sub(r"<[^>]+>", "", str(s or ""))
    m = R_VIRGOLETTE.search(s)
    if m:
        s = m.group(1)
    s = re.sub(r"\s+", " ", s).strip(" .;,-")
    return s[:1].upper() + s[1:] if s else ""


def _senza_virgolette(t):
    return R_VIRGOLETTE.sub("", t or "")


def numero_proprio(v):
    """Numero dell'atto Camera citato nella votazione stessa, o None."""
    o, t = v.get("o") or "", v.get("t") or ""
    for r, s in ((R_PREFISSO, o), (R_ODG, o), (R_AC, o), (R_O_PARENTESI, o), (R_T_NUMERO, t)):
        m = r.search(s)
        if m:
            return m.group(1)
    trovati = R_PARENTESI.findall(_senza_virgolette(t))
    return trovati[-1] if trovati else None


def titoli_dall_archivio(votazioni):
    """{numero: titolo} dai titoli ufficiali già scaricati e dai voti finali."""
    titoli = {}
    for v in votazioni:
        t = v.get("t") or ""
        if R_VIRGOLETTE.search(t):
            nums = R_PARENTESI.findall(_senza_virgolette(t)) or R_T_NUMERO.findall(t)
            if nums:
                titoli.setdefault(nums[-1], pulisci_titolo(t))
        if v.get("c") == "finale":
            m = re.match(r"^(.{15,}?)\s*\((?:DDL|PDL)(?:\s+COST)?\s+0*(\d+)", v.get("o") or "", re.I)
            if m:
                titoli.setdefault(m.group(2), pulisci_titolo(m.group(1)))
    return titoli


def collega(votazioni, cache=None):
    """{id votazione: (numero, titolo)} per le votazioni della Camera; titolo può essere ""."""
    ordinate = sorted(votazioni, key=lambda v: (v["d"], v.get("s") or "", v.get("n") or 0))
    numeri, seduta, prec = {}, None, None
    for v in ordinate:
        chiave = (v["d"], v.get("s"))
        if chiave != seduta:
            seduta, prec = chiave, None
        n = numero_proprio(v)
        eredita = v.get("c") in EREDITANO
        if n is None and eredita and R_EREDITA.match(v.get("o") or ""):
            n = prec
        if n:
            numeri[v["id"]] = n
        prec = n if eredita else None
    titoli = titoli_dall_archivio(votazioni)
    titoli.update({k: pulisci_titolo(t) for k, t in (cache or {}).items() if t})
    return {vid: (n, titoli.get(n, "")) for vid, n in numeri.items()}


def numeri_senza_titolo(collegamenti):
    return sorted({n for n, t in collegamenti.values() if not t}, key=int)


def titolo_indice(v, collegamento):
    """Titolo da mostrare: la legge in discussione, altrimenti il titolo ufficiale se dice qualcosa in più."""
    t = collegamento[1] if collegamento and collegamento[1] else (v.get("t") or "").strip()
    if R_AUTORIFERIMENTO.match(t):
        return ""
    if len(t) > MAX_TITOLO:
        t = t[:MAX_TITOLO - 1].rsplit(" ", 1)[0].rstrip(" ,;") + "…"
    return t
