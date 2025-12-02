#!/usr/bin/env python3
"""
Hlavní denní run - stahuje všechny dotazy z Google Sheets
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Přidej cestu ke sdíleným funkcím
sys.path.append(str(Path(__file__).parent))

from shared_functions import (
    init_google_sheets,
    load_brands,
    load_queries,
    process_queries_parallel,
    save_failed_queries,
    setup_logging,
    CONFIG
)

# Logging
logger = setup_logging("main_run")

def main():
    logger.info("=" * 60)
    logger.info("🚀 MAIN DAILY RUN STARTED")
    logger.info("=" * 60)
    
    # Načti credentials z environment
    perplexity_key = os.getenv("PERPLEXITY_KEY")
    gemini_key = os.getenv("GEMINI_KEY")
    
    if not perplexity_key or not gemini_key:
        logger.error("❌ Missing API keys in environment")
        sys.exit(1)
    
    # Inicializuj Sheets
    try:
        wb = init_google_sheets()
        logger.info("✅ Google Sheets connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Sheets: {e}")
        sys.exit(1)
    
    # Načti brandy a dotazy
    try:
        brands = load_brands(wb)
        queries = load_queries(wb)
        
        logger.info(f"📊 Loaded {len(brands)} brands, {len(queries)} queries")
        
        if not queries:
            logger.warning("⚠️  No queries to process")
            sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Zpracuj všechny dotazy
    start_time = datetime.now()
    
    try:
        results = process_queries_parallel(
            queries=queries,
            brands=brands,
            providers=CONFIG['active_providers'],
            max_workers=CONFIG['max_workers'],
            perplexity_key=perplexity_key,
            gemini_key=gemini_key
        )
    except Exception as e:
        logger.error(f"❌ Processing failed: {e}")
        sys.exit(1)
    
    # Ulož selhané dotazy do JSON
    failed_path = Path("data/failed_queries.json")
    failed_path.parent.mkdir(exist_ok=True)
    
    save_failed_queries(results['failed'], failed_path)
    
    # Report
    elapsed = (datetime.now() - start_time).total_seconds()
    
    logger.info("=" * 60)
    logger.info("✅ MAIN RUN COMPLETED")
    logger.info(f"⏱️  Duration: {elapsed/60:.1f} minutes")
    logger.info(f"✅ Successful: {results['successful']}")
    logger.info(f"❌ Failed: {results['failed_count']}")
    
    if results['successful'] + results['failed_count'] > 0:
        success_rate = results['successful']/(results['successful']+results['failed_count'])*100
        logger.info(f"📊 Success rate: {success_rate:.1f}%")
        
        # Jen warning, ne exit - nech to doběhnout
        if success_rate < 70:
            logger.warning(f"⚠️  Low success rate: {success_rate:.1f}%")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main()