#!/usr/bin/env python3
"""
Lokální test script - pro testování před pushem do GitHub Actions

Použití:
  python scripts/local_test.py

Potřebuješ mít .env soubor s credentials (viz .env.example)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Načti .env
env_path = Path(__file__).parent.parent / '.env'
if not env_path.exists():
    print("❌ Nenašel jsem .env soubor!")
    print("📝 Zkopíruj .env.example jako .env a vyplň credentials")
    sys.exit(1)

load_dotenv(env_path)

# Importuj main run
sys.path.append(str(Path(__file__).parent))
from main_run import main

if __name__ == "__main__":
    print("🧪 LOKÁLNÍ TEST")
    print("=" * 60)
    print()
    
    # Kontrola credentials
    required = ["PERPLEXITY_KEY", "GEMINI_KEY", "GOOGLE_SHEETS_CREDENTIALS", "SHEET_URL"]
    missing = [key for key in required if not os.getenv(key)]
    
    if missing:
        print(f"❌ Chybí environment variables: {', '.join(missing)}")
        print("📝 Zkontroluj .env soubor")
        sys.exit(1)
    
    print("✅ Credentials OK")
    print()
    
    # Spusť
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Přerušeno uživatelem")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Chyba: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
