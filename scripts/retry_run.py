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
    
    # Seskup podle dotazu + provider (KLÍČOVÁ ZMĚNA!)
    queries_to_retry = {}
    for item in failed_items:
        query_text = item['query']['query']
        provider = item['provider']
        retry_count = item.get('retry_count', 0)
        
        # Přeskoč dotazy s více než 10 pokusy
        if retry_count >= 10:
            logger.warning(f"⏭️  Skipping query (too many retries): {query_text[:50]}")
            continue
        
        # ZMĚNA: Používáme tuple (query, provider) jako klíč
        key = (query_text, provider)
        
        if key not in queries_to_retry:
            queries_to_retry[key] = {
                'query_obj': item['query'],
                'provider': provider,  # ← Jen tento provider
                'max_retry_count': retry_count
            }
    
    if not queries_to_retry:
        logger.info("✅ No queries eligible for retry")
        return
    
    logger.info(f"🎯 Unique query+provider combinations to retry: {len(queries_to_retry)}")
    
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
    
    # ZMĚNA: Zpracuj každý dotaz+provider zvlášť
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_only = datetime.now().strftime("%Y-%m-%d")
    
    all_results = {
        'log': [],
        'data': [],
        'url': [],
        'failed': [],
        'successful': 0,
        'failed_count': 0
    }
    
    from shared_functions import process_single_query
    
    for (query_text, provider), data in queries_to_retry.items():
        logger.info(f"⚙️  Retrying: {query_text[:50]}... with {provider}")
        
        try:
            # Zpracuj s JEDNÍM providerem
            result = process_single_query(
                item=data['query_obj'],
                providers=[provider],  # ← JEN TENTO PROVIDER!
                all_brands=brands,
                timestamp=timestamp,
                date_only=date_only,
                perplexity_key=perplexity_key,
                gemini_key=gemini_key
            )
            
            # Shromáždi výsledky
            all_results['log'].extend(result['log'])
            all_results['data'].extend(result['data'])
            all_results['url'].extend(result['url'])
            all_results['failed'].extend(result['failed'])
            
            if result['failed']:
                all_results['failed_count'] += len(result['failed'])
            else:
                all_results['successful'] += 1
                
        except Exception as e:
            logger.error(f"❌ Error processing: {e}")
            all_results['failed'].append({
                'query': data['query_obj'],
                'provider': provider,
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'retry_count': data['max_retry_count'] + 1
            })
            all_results['failed_count'] += 1
    
    # Uložení výsledků
    from shared_functions import save_results_to_sheets_internal
    save_results_to_sheets_internal(all_results['log'], all_results['data'], all_results['url'])
    
    # Aktualizuj failed_queries.json
    save_failed_queries(all_results['failed'], failed_path)
    
    # Report
    logger.info("=" * 60)
    logger.info("✅ RETRY RUN COMPLETED")
    logger.info(f"📊 Attempted: {len(queries_to_retry)}")
    logger.info(f"✅ Recovered: {all_results['successful']}")
    logger.info(f"❌ Still failing: {all_results['failed_count']}")
    
    if all_results['failed_count'] > 0:
        logger.warning(f"⚠️  {all_results['failed_count']} queries still failing")
    else:
        logger.info("🎉 All queries recovered!")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main()