#!/usr/bin/env python3
"""
Retry script - opakuje jen selhané dotazy z failed_queries.json
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from shared_functions import (
    init_google_sheets,
    load_brands,
    process_queries_parallel,
    save_failed_queries,
    setup_logging,
    CONFIG
)

logger = setup_logging("retry_run")

def main():
    logger.info("🔄 RETRY RUN STARTED")
    
    # Načti selhané dotazy
    failed_path = Path("data/failed_queries.json")
    
    if not failed_path.exists():
        logger.info("✅ No failed queries file found")
        return
    
    with open(failed_path, 'r', encoding='utf-8') as f:
        failed_items = json.load(f)
    
    if not failed_items:
        logger.info("✅ No failed queries to retry")
        return
    
    logger.info(f"📋 Found {len(failed_items)} failed query attempts")
    
    # Seskup podle dotazu (můžou být duplicity pro různé providery)
    queries_to_retry = {}
    for item in failed_items:
        query_text = item['query']['query']
        provider = item['provider']
        retry_count = item.get('retry_count', 0)
        
        # Přeskoč dotazy s více než 10 pokusy
        if retry_count >= 10:
            logger.warning(f"⏭️  Skipping query (too many retries): {query_text[:50]}")
            continue
        
        if query_text not in queries_to_retry:
            queries_to_retry[query_text] = {
                'query_obj': item['query'],
                'providers': [],
                'max_retry_count': retry_count
            }
        
        queries_to_retry[query_text]['providers'].append(provider)
        queries_to_retry[query_text]['max_retry_count'] = max(
            queries_to_retry[query_text]['max_retry_count'], 
            retry_count
        )
    
    if not queries_to_retry:
        logger.info("✅ No queries eligible for retry")
        return
    
    logger.info(f"🎯 Unique queries to retry: {len(queries_to_retry)}")
    
    # Načti credentials
    perplexity_key = os.getenv("PERPLEXITY_KEY")
    gemini_key = os.getenv("GEMINI_KEY")
    
    if not perplexity_key or not gemini_key:
        logger.error("❌ Missing API keys")
        sys.exit(1)
    
    # Inicializuj Sheets
    try:
        wb = init_google_sheets()
        brands = load_brands(wb)
    except Exception as e:
        logger.error(f"❌ Failed to initialize: {e}")
        sys.exit(1)
    
    # Zpracuj jen selhané dotazy
    queries = [data['query_obj'] for data in queries_to_retry.values()]
    
    logger.info(f"⚙️  Processing {len(queries)} queries with {CONFIG['max_workers']} workers")
    
    start_time = datetime.now()
    
    try:
        results = process_queries_parallel(
            queries=queries,
            brands=brands,
            providers=CONFIG['active_providers'],
            max_workers=CONFIG['max_workers'],
            perplexity_key=perplexity_key,
            gemini_key=gemini_key,
            is_retry=True
        )
    except Exception as e:
        logger.error(f"❌ Processing failed: {e}")
        sys.exit(1)
    
    # Aktualizuj failed_queries.json
    save_failed_queries(results['failed'], failed_path)
    
    # Report
    elapsed = (datetime.now() - start_time).total_seconds()
    initial_count = len(failed_items)
    
    logger.info("=" * 60)
    logger.info("✅ RETRY RUN COMPLETED")
    logger.info(f"⏱️  Duration: {elapsed/60:.1f} minutes")
    logger.info(f"📊 Initial failed: {initial_count}")
    logger.info(f"✅ Recovered: {results['successful']}")
    logger.info(f"❌ Still failing: {results['failed_count']}")
    
    if results['failed_count'] > 0:
        logger.warning(f"⚠️  {results['failed_count']} queries still failing")
    else:
        logger.info("🎉 All queries recovered!")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
