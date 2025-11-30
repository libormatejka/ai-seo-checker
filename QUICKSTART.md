# 🚀 Quick Start - 5 minut setup

## 1️⃣ Vytvoř Google Cloud Service Account (2 min)

1. Jdi na https://console.cloud.google.com/
2. Vytvoř projekt (nebo vyber existující)
3. **APIs & Services** → **Enable APIs** → zapni:
   - Google Sheets API
   - Google Drive API
4. **IAM & Admin** → **Service Accounts** → **Create Service Account**
   - Název: `github-actions-bot`
   - Role: žádná (skip)
5. Klikni na service account → **Keys** → **Add Key** → **JSON**
6. Stáhne se JSON soubor
7. **DŮLEŽITÉ**: Zkopíruj `client_email` z JSONu (např. `github-actions-bot@project.iam.gserviceaccount.com`)

## 2️⃣ Sdílej Google Sheet s botem (30 sec)

1. Otevři tvůj Google Sheet
2. Klikni **Share**
3. Vlož email ze service accountu (`client_email` z JSONu)
4. Dej mu **Editor** práva
5. Zkopíruj URL Sheetu

## 3️⃣ Nahraj na GitHub (1 min)

```bash
# Vytvoř nový repo na GitHubu (prázdný, bez README)
# Pak:

git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/geo-analyzer.git
git push -u origin main
```

## 4️⃣ Nastav GitHub Secrets (1 min)

Jdi do **Settings → Secrets and variables → Actions**

Přidej 4 secrets (klikni **New repository secret** pro každý):

| Name | Value |
|------|-------|
| `PERPLEXITY_KEY` | `pplx-tvůj-klíč` |
| `GEMINI_KEY` | `AIza-tvůj-klíč` |
| `SHEET_URL` | `https://docs.google.com/spreadsheets/d/...` |
| `GOOGLE_SHEETS_CREDENTIALS` | Celý JSON z kroku 1 (jeden řádek) |

**Tip**: Pro `GOOGLE_SHEETS_CREDENTIALS` otevři JSON soubor v editoru, zkopíruj celý obsah a vlož jako jeden řádek (bez mezer mezi řádky).

## 5️⃣ Testuj! (30 sec)

1. Jdi do **Actions**
2. Vyber **Main Daily Run**
3. Klikni **Run workflow** → **Run workflow**
4. Počkej ~2-5 minut
5. Zkontroluj Google Sheets → měly by se objevit nové sheety s daty

## ✅ Hotovo!

Od teď běží automaticky každý den. Zkontroluj:
- `data/failed_queries.json` - pokud `[]` → všechno OK
- GitHub Actions logy - vidíš metriky úspěšnosti

---

## 🐛 Něco nefunguje?

### Chyba: "Missing API keys"
→ Zkontroluj, že jsi přidal všechny 4 secrets

### Chyba: "Failed to connect to Sheets"  
→ Sdílel jsi Sheet s `client_email` z JSON?

### Chyba: "Permission denied"
→ Service account musí mít **Editor** práva, ne jen Viewer

### Script běží, ale nic se neukládá
→ Zkontroluj, že máš v Sheetu správné názvy:
   - `Queries` (s velkým Q)
   - `Terms` (s velkým T)
   - `Urls` (s velkým U)

---

**Potřebuješ pomoc?** Otevři Issue na GitHubu!
