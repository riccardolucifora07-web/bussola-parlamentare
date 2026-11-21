"""Prova completa della pipeline contro i finti endpoint (nessuna rete necessaria).

Uso: python test/prova.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
sys.path.insert(0, QUI)
import finto_sparql  # noqa: E402


def leggi(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def esegui(dati, porta, *extra):
    env = dict(os.environ,
               BUSSOLA_CAMERA_ENDPOINT=f"http://127.0.0.1:{porta}/camera/sparql",
               BUSSOLA_SENATO_ENDPOINT=f"http://127.0.0.1:{porta}/senato/sparql")
    r = subprocess.run([sys.executable, os.path.join(RADICE, "scripts", "aggiorna.py"), "--dati", dati, "--pausa", "0", *extra],
                       env=env, capture_output=True, text=True, timeout=600)
    print(r.stdout[-3000:])
    if r.returncode != 0:
        print(r.stderr[-3000:])
        raise SystemExit(f"aggiorna.py è uscito con codice {r.returncode}")
    return r.stdout


def main():
    srv = finto_sparql.avvia()
    porta = srv.server_address[1]
    dati = tempfile.mkdtemp(prefix="bussola-prova-")
    try:
        out = esegui(dati, porta)
        assert "HTTP 503" in out, "l'errore temporaneo simulato doveva essere ritentato"
        meta = leggi(os.path.join(dati, "meta.json"))
        cam, sen = meta["rami"]["camera"], meta["rami"]["senato"]
        assert cam["votazioni"] == 24, cam
        assert sen["votazioni"] == 9, sen
        assert cam["controllo_totali"] == 0 and sen["controllo_totali"] == 0, "i voti nominativi devono tornare con i totali"
        assert cam["da_scaricare"] == 0

        # --- Camera
        M = leggi(os.path.join(dati, "camera", "membri.json"))
        membri, gruppi = M["membri"], M["gruppi"]
        assert len(membri) == 401
        chiavi = {g["chiave"] for g in gruppi.values()}
        assert {"fdi", "pd", "lega", "m5s", "fi", "aziv", "az", "iv", "misto"} <= chiavi, chiavi
        assert gruppi["gr5"]["breve"] == "Azione-IV" and gruppi["gr6"]["chiave"] == "az" and gruppi["gr7"]["chiave"] == "iv"
        assert membri[0]["cognome"] == "Rossi 1", membri[0]["cognome"]
        assert any(m["cognome"] == "D'Alessio" for m in membri)
        assert membri[0]["capo"] and membri[0]["capo"][0][0] == "gr1", "capogruppo Camera"
        assert not membri[1]["capo"], "solo i presidenti dei gruppi sono capigruppo"
        assert meta["governo"]["nome"] == "Governo Meloni" and meta["governo"]["dal"] == "2022-10-21", meta.get("governo")
        G = leggi(os.path.join(dati, "camera", "gruppi.json"))
        cambi = G["cambi"]
        sciolti = [c for c in cambi if c["sciolto"]]
        assert len(sciolti) == 20, len(sciolti)
        individuali = [c for c in cambi if not c["sciolto"]]
        assert len(individuali) == 1 and individuali[0]["a"] == "gr8"
        gfdi = next(g for g in G["gruppi"] if g["id"] == "gr1")
        assert gfdi["coal"] == "maggioranza" and gfdi["coesione"] > 0.8 and gfdi["allineamento"] > 0.9, gfdi
        assert gfdi["coal_fonte"] == "configurazione", "con una sola fiducia vale la configurazione"
        gpd = next(g for g in G["gruppi"] if g["id"] == "gr2")
        assert gpd["allineamento"] < 0.2, gpd
        assert G["convergenza"]["ids"] == [] or len(G["convergenza"]["m"]) == len(G["convergenza"]["ids"])

        V = leggi(os.path.join(dati, "camera", "votazioni", "2024-03.json"))["votazioni"]
        assert len(V) == 4 and all(v["k"] == "2024-03-05" for v in V)
        v = V[0]
        i_cessato = 10
        i_subentro = next(m["i"] for m in membri if m["cognome"] == "D'Alessio")
        assert v["v"][i_cessato] == ".", "il deputato cessato non deve risultare assente"
        assert v["v"][i_subentro] in "FCA-", "il subentrante è in carica"
        assert v["t"] == "Disposizioni in materia di prova" and v["o"] == "DDL 1234 - ART. 1" and v["c"] == "articolo"
        V0 = leggi(os.path.join(dati, "camera", "votazioni", "2022-10.json"))["votazioni"]
        assert V0[3]["c"] == "fiducia" and "Q" in V0[3]["f"]
        assert V0[0]["v"][i_subentro] == "." if i_subentro < len(V0[0]["v"]) else True
        Vs = leggi(os.path.join(dati, "camera", "votazioni", "2023-11.json"))["votazioni"]
        segreta = [x for x in Vs if "S" in x["f"]]
        assert len(segreta) == 1 and set(segreta[0]["p"]) <= {"-", "."}, segreta[0]["p"]
        assert Vs[1]["c"] == "emendamento"
        I = leggi(os.path.join(dati, "camera", "indice.json"))  # noqa: E741
        assert len(I["righe"]) == 24 and len(I["righe"][0][11]) == len(I["gruppi"])
        assert I["campi"][14] == "atto"
        r_art = next(r for r in I["righe"] if r[4] == "DDL 1234 - ART. 1")
        assert r_art[3] == "Disposizioni in materia di prova" and r_art[14] == "1234", r_art
        r_moz = next(r for r in I["righe"] if r[4].upper().startswith("MOZIONE"))
        assert r_moz[14] is None, r_moz
        assert leggi(os.path.join(dati, "camera", "atti.json")) == {"1234": 'ROSSI ed altri: "Disposizioni in materia di prova" (1234)'}
        st = membri[0]["st"]
        assert st["tot"] == 24 and st["pres"] + st["mis"] + st["ass"] == st["tot"], st

        # --- Senato
        C_ = leggi(os.path.join(dati, "camera", "membri.json"))
        assert not any("d0_" in m["id"] for m in C_["membri"]), "il deputato 0 non è una persona"
        S = leggi(os.path.join(dati, "senato", "membri.json"))
        assert not any(m["cognome"] == "Deputato" and m["mandati"] for m in S["membri"]), "i mandati alla Camera non sono senatori"
        segre = next(m for m in S["membri"] if m["cognome"] == "Segre")
        assert segre["mandati"] and segre["mandati"][0][0] == "2022-10-13", segre
        assert segre["adesioni"] and segre["adesioni"][0][0] == "g49"
        assert S["gruppi"]["g49"]["nome"] == "Misto", S["gruppi"]["g49"]
        assert S["gruppi"]["g9"]["chiave"] == "lega", "Lega con 'Partito Sardo d'Azione' non deve finire in Azione"
        assert S["gruppi"]["g79"]["chiave"] == "aut"
        capi = [m for m in S["membri"] if m["capo"]]
        assert len(capi) == 7, len(capi)
        SV = leggi(os.path.join(dati, "senato", "votazioni", "2023-06.json"))["votazioni"]
        legale = [x for x in SV if "L" in x["f"]]
        assert len(legale) == 1 and legale[0]["c"] == "numero_legale"
        assert SV[2]["u"].startswith("https://dati.senato.it/votazione/19-22600-3")
        tot_sen = next(m for m in S["membri"] if m["cognome"] == "Bianchi 1")["st"]["tot"]
        assert tot_sen == 8, f"le verifiche del numero legale vanno escluse ({tot_sen})"
        SV3 = leggi(os.path.join(dati, "senato", "votazioni", "2026-11.json"))["votazioni"]
        assert SV3[2]["c"] == "finale" and SV3[2]["t"] == "Legge annuale sulle PMI"

        # --- secondo giro: incrementale e idempotente
        prima = {p: open(os.path.join(dati, p), encoding="utf-8").read()
                 for p in ["camera/indice.json", "senato/gruppi.json", "camera/votazioni/2026-11.json"]}
        out2 = esegui(dati, porta, "--rifai", "2")
        assert "da scaricare: 2" in out2, "al secondo giro si riscaricano solo le unità recenti"
        for p, testo in prima.items():
            assert open(os.path.join(dati, p), encoding="utf-8").read() == testo, f"{p} è cambiato senza motivo"

        # --- solo calcoli (senza rete)
        srv.shutdown()
        esegui(dati, porta, "--solo-calcoli")
        print("\nTUTTE LE PROVE SUPERATE")
        if len(sys.argv) > 1:
            dest = sys.argv[1]
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(dati, dest)
            print("dati di prova copiati in", dest)
    finally:
        shutil.rmtree(dati, ignore_errors=True)




def prova_coalizioni():
    """Maggioranza e opposizione dedotte dai voti di fiducia, anche quando un gruppo cambia campo."""
    sys.path.insert(0, os.path.join(RADICE, "scripts"))
    from calcoli import Calcolo
    G = {"a": {"chiave": "fdi", "coal": "opposizione"}, "b": {"chiave": "pd", "coal": "maggioranza"},
         "c": {"chiave": "az", "coal": "opposizione"}, "m": {"chiave": "misto", "coal": "altro"}}
    membri = [{"i": i, "mandati": [["2022-10-13", None]], "adesioni": [[g, "2022-10-13", None]]}
              for i, g in enumerate("aaabbbccm")]
    vot = []
    for k in range(20):
        c_voto = "FFF" if k < 10 else "CCC"  # il gruppo c passa all'opposizione dopo 10 fiducie
        vot.append({"id": f"v{k}", "d": f"2023-01-{k + 1:02d}", "c": "fiducia", "f": "Q", "v": "FFF" + "CCC" + c_voto + "F"})
    vot.append({"id": "x", "d": "2022-10-20", "c": "fiducia", "f": "Q", "v": "CCCFFFFFF"})  # prima del governo: ignorata
    Calcolo(membri, G, vot, "2026-11-20", "2022-10-21").esegui()
    assert G["a"]["coal"] == "maggioranza" and G["a"]["coal_fonte"] == "fiducia", G["a"]
    assert G["b"]["coal"] == "opposizione", G["b"]
    assert G["c"]["coal"] == "altro" and G["c"]["fiducia"]["n"] == 15, G["c"]  # ultime 15: 5 Sì e 10 No
    assert G["m"]["coal"] == "altro" and G["m"]["coal_fonte"] == "configurazione", G["m"]
    print("prova coalizioni superata")


def prova_atti():
    """Legge in discussione ricavata dalle descrizioni brevi della Camera."""
    sys.path.insert(0, os.path.join(RADICE, "scripts"))
    import atti
    s, d = "s19_737", "2026-11-03"
    vot = [
        {"id": "a", "d": d, "s": s, "n": 1, "o": "DICHIARAZIONE DI URGENZA PDL 2916", "t": "", "c": "altro"},
        {"id": "b", "d": d, "s": s, "n": 2, "o": "DDL 3159 - QUEST PREG 1, 2, 3 E 4", "t": "", "c": "pregiudiziale"},
        {"id": "c", "d": d, "s": s, "n": 3, "o": "DDL 3148 - EM 1.1", "t": "", "c": "emendamento"},
        {"id": "e", "d": d, "s": s, "n": 4, "o": "EM 1.2", "t": "", "c": "emendamento"},
        {"id": "f", "d": d, "s": s, "n": 5, "o": "ODG 9/3148/28", "t": "Ordine del giorno 9/3148/28", "c": "odg"},
        {"id": "g", "d": d, "s": s, "n": 6, "o": "MOZ 1-346 CPV 1,2 DISP", "t": "", "c": "mozione"},
        {"id": "h", "d": d, "s": s, "n": 7, "o": "ODG 9/3148/29", "t": "", "c": "odg"},
        {"id": "l", "d": d, "s": s, "n": 8, "o": "DOC VIII N 7 - VOTO FINALE", "t": "", "c": "finale"},
        {"id": "m", "d": d, "s": s, "n": 9, "o": "Documento approvato dalla XIV Commissione", "t": "", "c": "finale"},
        {"id": "i", "d": "2026-11-04", "s": "s19_738", "n": 1, "o": "EM 2.1", "t": "", "c": "emendamento"},
        {"id": "j", "d": "2025-01-10", "s": "s19_400", "n": 1, "o": "Emendamento 1.3 ROSSI MARIO (PD-IDP)",
         "t": 'S. 1359. - "Conversione in legge del decreto-legge 24 gennaio 2025, n. 3" <em>(approvato dal Senato)</em> (2213)', "c": "emendamento"},
        {"id": "k", "d": "2025-01-10", "s": "s19_400", "n": 2, "o": "Ordine del giorno n. 9/2213/4 BIANCHI LUCA (FDI)",
         "t": "Ordine del giorno 9/2213/4 DDL n. 2213", "c": "odg"},
    ]
    col = atti.collega(vot, {"3159": '"Disposizioni sul turismo" (3159)'})
    assert col["a"] == ("2916", ""), col["a"]
    assert col["b"] == ("3159", "Disposizioni sul turismo"), col["b"]
    assert col["c"] == col["e"] == col["f"] == col["h"] == ("3148", ""), col
    assert not {"g", "i", "l", "m"} & set(col), "mozioni, documenti e sedute senza riferimento restano senza legge"
    assert col["j"] == col["k"] == ("2213", "Conversione in legge del decreto-legge 24 gennaio 2025, n. 3"), col["j"]
    assert atti.numeri_senza_titolo(col) == ["2916", "3148"]
    assert atti.titolo_indice(vot[4], None) == "" and atti.titolo_indice({"t": "Legge sulle PMI"}, None) == "Legge sulle PMI"
    lungo = atti.titolo_indice({}, ("1", "parola " * 60))
    assert len(lungo) <= 200 and lungo.endswith("parola…"), lungo
    print("prova atti superata")


if __name__ == "__main__":
    prova_coalizioni()
    prova_atti()
    main()
