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