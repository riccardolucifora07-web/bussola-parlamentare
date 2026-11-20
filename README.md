# Bussola Parlamentare

Sito che mostra **tutte le votazioni** di Camera e Senato della XIX legislatura, con:
- il voto di ogni deputato e senatore;
- la posizione di ogni gruppo;
- gli indicatori di coerenza (compattezza, presenze, voti diversi dal proprio gruppo, cambi di gruppo, convergenza tra gruppi).

Si **aggiorna da solo ogni notte** dai dati aperti ufficiali di [dati.camera.it](https://dati.camera.it/) e [dati.senato.it](https://dati.senato.it/). Contiene anche la sezione **Governi ed economia** dal 1994.

## Come funziona

```
ogni notte (GitHub Actions, gratis)
  │
  ├─ 1. prova automatica con dati finti: se il codice è rotto si ferma qui
  ├─ 2. riprende i dati già scaricati (ramo "dati" del repository)
  ├─ 3. scarica da Camera e Senato le votazioni nuove e riscarica gli ultimi giorni
  ├─ 4. ricalcola tutti gli indicatori su tutta la legislatura
  ├─ 5. salva i dati nel ramo "dati"
  └─ 6. pubblica il sito su GitHub Pages
```

Il sito (`site/index.html`) è una pagina unica che legge i file JSON dalla cartella `data/`. Non c'è nessun server da mantenere.

## Pubblicarlo: 10 minuti, una volta sola

Serve un account GitHub gratuito ([github.com/signup](https://github.com/signup)).

1. **Crea un repository**. In alto a destra: **+ → New repository**.
   - Nome, per esempio `bussola-parlamentare`.
   - Scegli **Public**: GitHub Pages e le ore di calcolo sono gratuite solo per i repository pubblici.
   - Spunta **Add a README file**, poi **Create repository**.
2. **Carica i file**. Nel repository: **Add file → Upload files**.
   - Trascina **il contenuto** della cartella `bussola-parlamentare` (non la cartella stessa), poi **Commit changes**.
   - Attenzione: la cartella `.github` inizia con un punto e su Mac e Windows è nascosta, quindi spesso non viene trascinata. Controlla che nel repository compaia `.github/workflows/aggiorna.yml`.
   - Se manca: **Add file → Create new file**, scrivi come nome `.github/workflows/aggiorna.yml`, incolla il contenuto del file e salva.
3. **Attiva il sito**. **Settings → Pages**: in *Build and deployment*, alla voce *Source*, scegli **GitHub Actions**.
4. **Permessi di scrittura**. **Settings → Actions → General**: in fondo, in *Workflow permissions*, scegli **Read and write permissions** e salva.
5. **Primo aggiornamento**. Scheda **Actions → Aggiornamento quotidiano → Run workflow → Run workflow**.
   - Il primo giro scarica l'intera legislatura, cioè decine di migliaia di votazioni, e può richiedere **qualche ora**.
   - Se il tempo non basta (limite di circa 5 ore e mezza), salva il lavoro fatto e pubblica comunque il sito. Al giro successivo riparte da lì.
   - Puoi lanciare subito un altro giro a mano, oppure aspettare la notte.
   - In cima al sito un avviso dice se l'archivio è ancora in completamento.
6. **L'indirizzo del sito** è `https://TUO-NOME-UTENTE.github.io/bussola-parlamentare/`. Lo trovi anche in **Settings → Pages**.

Da qui in poi non devi fare nulla: ogni notte arrivano le votazioni del giorno prima, i nuovi cambi di gruppo e i nuovi capigruppo.

> GitHub sospende gli aggiornamenti programmati dei repository fermi da 60 giorni. Per evitarlo il programma si riattiva da solo ogni notte. Se mai succedesse comunque, GitHub lo segnala per email e basta un clic: **Actions → Aggiornamento quotidiano → Enable workflow**.

**Cosa si aggiorna da solo**: votazioni, composizione dei gruppi, cambi di gruppo, capigruppo di Camera e Senato, governo in carica, quali gruppi sono di maggioranza od opposizione (dai voti di fiducia) e l'elenco delle votazioni più rilevanti. **Cosa resta a mano**: i leader di partito, che non sono pubblicati in nessuna fonte aperta affidabile, e i dati economici annuali.

## Se qualcosa va storto

- **Il giro è rosso nella scheda Actions**: aprilo e leggi il passaggio in rosso.
  - Le righe `::warning::` sono avvisi; per esempio, un giorno che non si è riusciti a scaricare viene ritentato al giro dopo.
  - Le righe `::error::` indicano che un ramo intero non si è aggiornato. Il sito continua a mostrare i dati del giorno prima e lo segnala in cima alla pagina.
- **Gli endpoint di Camera o Senato sono lenti o fermi**: lo script ritenta da solo e, se non riesce, riprova la notte dopo.
- **Una regola dei dati è cambiata**, per esempio un campo con un nome diverso: il log lo dice, ad esempio con "anagrafe incompleta" o "espressioni di voto non riconosciute". Le query sono in `scripts/camera.py` e `scripts/senato.py`.

## Personalizzare

| Cosa | Dove |
|---|---|
| Nomi brevi dei gruppi e collocazione di riserva (usata solo finché non ci sono almeno 3 voti di fiducia) | `config/gruppi.json`: gli indicatori si ricalcolano al giro dopo, senza riscaricare nulla |
| Leader di partito, famiglie europee, capigruppo di riserva | `site/index.html`, oggetto `PARTIES` |
| Le 10 votazioni in evidenza con scheda di contesto | `site/index.html`, oggetto `VOTES` |
| Dati economici (annuali) | `site/index.html`, oggetti `SERIES` e `INDICATORS` |
| Orario dell'aggiornamento | `.github/workflows/aggiorna.yml`, riga `cron` |

Se cambia il governo non serve fare nulla: il nome arriva dai dati della Camera e la maggioranza si ricalcola dai voti di fiducia.

## Provarlo sul tuo computer

Serve Python 3.9 o successivo. Non ci sono librerie da installare.

```bash
python test/prova.py                                  # prova completa con endpoint finti, senza rete
python scripts/aggiorna.py --dati site/data --max-minuti 30   # scarica i dati veri per 30 minuti
python -m http.server -d site 8000                    # poi apri http://localhost:8000
```

Altre opzioni di `aggiorna.py`:
- `--ramo camera` o `--ramo senato`: aggiorna un solo ramo.
- `--solo-calcoli`: ricalcola gli indicatori senza scaricare nulla.
- `--rifai N`: quanti giorni o sedute recenti riscaricare (5 di norma).
- `--pausa`: secondi di attesa tra una richiesta e l'altra, per non sovraccaricare gli endpoint.

## Dati e licenze

- Camera dei deputati, [dati.camera.it](https://dati.camera.it/): CC BY-SA 4.0. Ontologia OCD, endpoint SPARQL `https://dati.camera.it/sparql`.
- Senato della Repubblica, [dati.senato.it](https://dati.senato.it/): CC BY 3.0. Ontologia OSR, endpoint SPARQL `https://dati.senato.it/sparql`.
- Le licenze chiedono di citare la fonte, cosa che il sito fa in ogni pagina. Per la Camera, chi ripubblica i dati deve usare la stessa licenza.

## Struttura

```
scripts/aggiorna.py    regia: anagrafe, votazioni, salvataggio, indicatori
scripts/camera.py      query SPARQL della Camera
scripts/senato.py      query SPARQL del Senato
scripts/calcoli.py     posizioni dei gruppi e indicatori (definizioni in testa al file)
scripts/sparql.py      client HTTP con tentativi e paginazione
scripts/comune.py      date, nomi, classificazione delle votazioni
config/gruppi.json     attribuzione dei gruppi a maggioranza od opposizione
site/index.html        il sito
test/                  endpoint finti e prova completa
```

Dati prodotti (ramo `dati`, pubblicati in `data/`):
- `meta.json`
- per ciascun ramo, `camera/` e `senato/`:
  - `membri.json`: anagrafe, gruppi, indicatori individuali;
  - `gruppi.json`: indicatori di gruppo, convergenza, cambi;
  - `indice.json`: una riga per ogni votazione;
  - `votazioni/AAAA-MM.json`: voto di ogni parlamentare;
  - `stato.json`: avanzamento dello scaricamento.
