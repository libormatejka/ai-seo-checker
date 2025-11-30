# GEO Analyzer - AI Chatbot Visibility Tracking

Automatický systém pro sledování viditelnosti brandů v AI chatbotech (Perplexity, Gemini).

## 🎯 Co to dělá

- **Main Run** (8:00 denně): Stahuje odpovědi na všechny dotazy z Google Sheets
- **Retry Runs** (4× denně): Opakuje selhané dotazy
- **Automatické retry**: Pokud dotaz selže, zkusí se znovu až 10×
- **Data do Sheets**: Výsledky se ukládají do Google Sheets pro analýzu
- **Tracking selhaných dotazů**: `data/failed_queries.json` se commituje do Gitu

## 📁 Struktura

```
geo-analyzer/
├── .github/workflows/
│   ├── main_run.yml       # Hlavní denní run (8:00)
│   └── retry_run.yml      # Retry selhání (4× denně)
├── scripts/
│   ├── main_run.py        # Stahuje všechny dotazy
│   ├── retry_run.py       # Opakuje jen selhané
│   └── shared_functions.py # Core logika
├── data/
│   └── failed_queries.json # Selhané dotazy
├── logs/                   # Logy z běhů
├── requirements.txt
└── README.md
```

## 🚀 Instalace

### 1. Fork/Clone repository

```bash
git clone https://github.com/YOUR_USERNAME/geo-analyzer.git
cd geo-analyzer
```

### 2. Nastav GitHub Secrets

Jdi do **Settings → Secrets and variables → Actions → New repository secret**

Přidej následující secrets:

#### `PERPLEXITY_KEY`
```
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
```

#### `GEMINI_KEY`
```
AIzaSyAZp8_LUKswqt15Gk3pKulKU_udJXn8-z0
```

#### `SHEET_URL`
```
https://docs.google.com/spreadsheets/d/1ZVYlFY0feJjZP6ppefgREOW4Zm46ZzzNOCXPlaLV01c/edit
```

#### `GOOGLE_SHEETS_CREDENTIALS`

Potřebuješ vytvořit **Service Account** v Google Cloud:

1. Jdi na [Google Cloud Console](https://console.cloud.google.com/)
2. Vytvoř nový projekt (nebo vyber existující)
3. Zapni **Google Sheets API** a **Google Drive API**
4. Vytvoř **Service Account**:
   - IAM & Admin → Service Accounts → Create Service Account
   - Dej mu název např. "github-actions-bot"
   - Skip role selection
   - Create
5. Vyber service account → Keys → Add Key → Create new key → JSON
6. Stáhne se ti JSON soubor
7. Otevři Google Sheet a sdílej ho s emailem service accountu (najdeš v JSON: `client_email`)
   - Dej mu **Editor** práva
8. Celý JSON zkopíruj jako jeden řádek a vlož do GitHub Secret `GOOGLE_SHEETS_CREDENTIALS`

Příklad JSON (zkráceno):
```json
{"type":"service_account","project_id":"your-project","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"github-actions-bot@your-project.iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}
```

### 3. Struktura Google Sheets

Tvůj Google Sheet musí obsahovat tyto sheety:

#### Sheet: `Queries`
| Query | Query Category | Query Product | Query type | Persona |
|-------|---------------|---------------|------------|---------|
| Jaké jsou nejlepší banky v ČR? | Finance | Bankovnictví | Informační | Investor |

#### Sheet: `Terms`
| Term | Brand Name | Brand Type |
|------|-----------|-----------|
| Česká spořitelna | Česká spořitelna | Target |
| ČS | Česká spořitelna | Target |
| ČSOB | ČSOB | Competitor |

#### Sheet: `Urls`
| URL | Brand Name | Brand Type |
|-----|-----------|-----------|
| csas.cz | Česká spořitelna | Target |
| csob.cz | ČSOB | Competitor |

Output sheety se vytvoří automaticky:
- `log_answers` - Raw odpovědi z AI
- `data_analysis` - Analýza brandů
- `url_analysis` - Analýza citovaných URL

### 4. Testovací run

Spusť manuálně workflow:

1. Jdi do **Actions**
2. Vyber **Main Daily Run**
3. Klikni **Run workflow**
4. Počkej ~5-10 minut
5. Zkontroluj Google Sheets

## ⏰ Harmonogram

GitHub Actions běží automaticky:

```
07:00 UTC (08:00 CET) → Main run - všechny dotazy
09:00 UTC (10:00 CET) → Retry #1
11:00 UTC (12:00 CET) → Retry #2
13:00 UTC (14:00 CET) → Retry #3
15:00 UTC (16:00 CET) → Retry #4
```

## 📊 Monitoring

### Kontrola logů

1. **GitHub Actions**:
   - Actions → vybrat run → kliknout na job
   - Downloaduj artifacts (logy)

2. **Failed queries**:
   - Otevři `data/failed_queries.json` v repozitáři
   - Pokud je prázdný `[]` → všechno OK ✅
   - Pokud obsahuje dotazy → některé stále selhávají ⚠️

### Metriky úspěšnosti

V logu každého runu najdeš:

```
✅ MAIN RUN COMPLETED
⏱️  Duration: 5.2 minutes
✅ Successful: 95
❌ Failed: 5
📊 Success rate: 95.0%
```

## 🔧 Konfigurace

### Změna času spuštění

Edituj `.github/workflows/main_run.yml`:

```yaml
schedule:
  - cron: '0 7 * * *'  # 7:00 UTC = 8:00 CET
```

[Cron syntax helper](https://crontab.guru/)

### Změna počtu workerů

V `scripts/shared_functions.py`:

```python
CONFIG = {
    "max_workers": 3,  # Zvyš na 5-8 pro rychlejší běh
    "batch_size": 30,
    "max_retries": 4,
}
```

### Přidání nového AI provideru

1. V `shared_functions.py` přidej funkci `ask_newprovider()`
2. Přidej do `CONFIG["active_providers"]`
3. Přidej API klíč do GitHub Secrets

## 🐛 Troubleshooting

### "Missing API keys"
→ Zkontroluj, že jsou všechny secrets nastavené v Settings → Secrets

### "Failed to connect to Sheets"
→ Ověř, že service account má přístup ke Sheetu (sdílení)

### "High failure rate"
→ Zkontroluj API limity (Gemini má free tier limit)
→ Zkontroluj `data/failed_queries.json` pro detaily

### Dotazy stále selhávají i po retry
→ Možné příčiny:
  - Rate limit API (příliš rychlé requesty)
  - Timeout (dotaz trvá moc dlouho)
  - Špatný API klíč
→ Zkontroluj logy v Actions artifacts

## 💰 Náklady

- **GitHub Actions**: 2000 minut/měsíc ZDARMA
  - Tento setup: ~30 min/den = 900 min/měsíc → V rámci free tier ✅
- **Gemini API**: Free tier (15 requests/min)
- **Perplexity API**: Záleží na plánu

## 📈 Rozšíření

### Přidat email notifikace

V `.github/workflows/main_run.yml` odkomentuj:

```yaml
- name: Notify on failure
  if: failure()
  uses: dawidd6/action-send-mail@v3
  with:
    server_address: smtp.gmail.com
    server_port: 465
    username: ${{ secrets.EMAIL_USERNAME }}
    password: ${{ secrets.EMAIL_PASSWORD }}
    subject: "❌ Main Run Failed"
    to: your-email@example.com
```

Přidej secrets: `EMAIL_USERNAME`, `EMAIL_PASSWORD`

### Export do BigQuery

Přidej do `shared_functions.py`:

```python
from google.cloud import bigquery

def save_to_bigquery(results):
    client = bigquery.Client()
    table_id = "project.dataset.table"
    client.insert_rows_json(table_id, results)
```

## 🤝 Contribution

Pro přidání nových features:

1. Fork repo
2. Vytvoř branch: `git checkout -b feature/new-feature`
3. Commit: `git commit -m "Add new feature"`
4. Push: `git push origin feature/new-feature`
5. Vytvoř Pull Request

## 📝 License

MIT License - použij jak chceš!

## 🆘 Support

Otevři Issue na GitHubu nebo kontaktuj: [tvůj email]

---

**Happy analyzing! 🚀**
