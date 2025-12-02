#!/usr/bin/env python3
"""
Sdílené funkce pro AI visibility monitoring
"""

import os
import re
import time
import json
import logging
import requests
import unicodedata
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# KONFIGURACE
# ============================================================

CONFIG = {
    "active_providers": ["Perplexity", "Gemini"],
    
    "model_names": {
        "perplexity": "sonar",
        "gemini": "gemini-2.0-flash-lite",
        "judge": "gemini-2.0-flash-lite"
    },
    
    "max_workers": 3,
    "batch_size": 30,
    "max_retries": 4,
    "request_timeout": 120,
}

# Thread-safe locks
sheets_lock = Lock()
failed_lock = Lock()

# ============================================================
# LOGGING
# ============================================================

def setup_logging(name):
    """Nastaví logging pro script"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{name}_{timestamp}.log"
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging("shared")

# ============================================================
# GOOGLE SHEETS
# ============================================================

def init_google_sheets():
    """Inicializuje připojení k Google Sheets"""
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    sheet_url = os.getenv("SHEET_URL")
    
    if not creds_json or not sheet_url:
        raise ValueError("Missing GOOGLE_SHEETS_CREDENTIALS or SHEET_URL")
    
    creds_dict = json.loads(creds_json)
    
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    wb = gc.open_by_url(sheet_url)
    
    return wb


def load_queries(wb):
    """Načte dotazy z Google Sheets - nová struktura s ACTIVE filtrem"""
    ws = wb.worksheet("Queries")
    data = ws.get_all_records()
    
    queries = []
    skipped = 0
    
    for row in data:
        # Přeskakuj prázdné řádky
        if not row.get('QUERY') or not str(row.get('QUERY')).strip():
            continue
        
        # Filtruj podle ACTIVE sloupce
        active = row.get('ACTIVE')
        is_active = False
        if isinstance(active, bool):
            is_active = active
        elif isinstance(active, str):
            is_active = active.upper() in ['TRUE', 'YES', '1', 'ANO']
        elif isinstance(active, int):
            is_active = active == 1
        
        if not is_active:
            skipped += 1
            continue
        
        queries.append({
            'query_id': str(row.get('QUERY_ID', '') or ''),
            'query': str(row.get('QUERY', '') or ''),
            'category': str(row.get('QUERY_CATEGORY', '') or ''),
            'product': str(row.get('QUERY_PRODUCT', '') or ''),
            'top_product': str(row.get('QUERY_TOP_PRODUCT', '') or ''),
            'sub_product': str(row.get('QUERY_SUB_PRODUCT', '') or ''),
            'query_type': str(row.get('QUERY_TYPE', '') or ''),
            'person': str(row.get('PERSON', '') or ''),
            'active': True
        })
    
    if skipped > 0:
        logger.info(f"⏭️  Skipped {skipped} inactive queries")
    
    return queries


def load_brands(wb):
    """Načte brandy (terms) z Google Sheets - seskupí podle TERM_NAME"""
    ws = wb.worksheet("Terms")
    data = ws.get_all_records()
    
    # Seskup podle TERM_NAME (hlavní název brandu)
    brands_dict = {}
    
    for row in data:
        # Přeskakuj prázdné řádky
        term_version = str(row.get('TERM_VERSION', '')).strip()
        if not term_version:
            continue
        
        term_name = str(row.get('TERM_NAME', '')).strip()
        category = str(row.get('TERM_CATEGORY', '')).strip()
        
        # Inicializuj brand pokud neexistuje
        if term_name not in brands_dict:
            brands_dict[term_name] = {
                'name': term_name,
                'category': category,
                'keywords': []
            }
        
        # Přidej keyword (variantu)
        brands_dict[term_name]['keywords'].append(term_version)
    
    # Převeď na list
    brands = list(brands_dict.values())
    
    return brands


def load_urls(wb):
    """Načte URLs z Google Sheets - nová struktura"""
    ws = wb.worksheet("Urls")
    data = ws.get_all_records()
    
    urls = []
    for row in data:
        # Přeskakuj prázdné řádky
        if not row.get('URL') or not str(row.get('URL')).strip():
            continue
        
        urls.append({
            'url': str(row.get('URL', '')),
            'name': str(row.get('URL_NAME', '')),
            'category': str(row.get('URL_CATEGORY', ''))
        })
    
    return urls


def save_results_to_sheets_internal(log_rows, data_rows, url_rows):
    """Uloží výsledky do Google Sheets"""
    
    if not log_rows and not data_rows and not url_rows:
        return
    
    wb = init_google_sheets()
    
    # Log answers sheet
    if log_rows:
        log_headers = [
            'Date', 'Timestamp', 'Query_ID', 'Query', 'Query_Category',
            'Query_Product', 'Query_Top_Product', 'Query_Sub_Product',
            'Query_Type', 'Person', 'Provider', 'Response',
            'Input_Tokens', 'Output_Tokens'
        ]
        
        try:
            ws_log = wb.worksheet("log_answers")
        except:
            ws_log = wb.add_worksheet(title="log_answers", rows=1000, cols=len(log_headers))
            ws_log.append_row(log_headers)
        
        rows = [[row.get(h, '') for h in log_headers] for row in log_rows]
        ws_log.append_rows(rows)
        logger.info(f"✅ Saved {len(rows)} rows to log_answers")
    
    # Data analysis sheet
    if data_rows:
        data_headers = [
            'Date', 'Timestamp', 'Query_ID', 'Query', 'Query_Category',
            'Query_Product', 'Query_Top_Product', 'Query_Sub_Product',
            'Query_Type', 'Person', 'Provider', 'Term_Version', 'Term_Name',
            'Term_Category', 'Text_Presence', 'Citation_Presence',
            'Rank', 'Mention_Count', 'Sentiment', 'Recommendation'
        ]
        
        try:
            ws_data = wb.worksheet("data_analysis")
        except:
            ws_data = wb.add_worksheet(title="data_analysis", rows=10000, cols=len(data_headers))
            ws_data.append_row(data_headers)
        
        rows = [[row.get(h, '') for h in data_headers] for row in data_rows]
        ws_data.append_rows(rows)
        logger.info(f"✅ Saved {len(rows)} rows to data_analysis")
    
    # URL analysis sheet
    if url_rows:
        url_headers = [
            'Date', 'Timestamp', 'Query_ID', 'Query', 'Query_Category',
            'Query_Product', 'Query_Top_Product', 'Query_Sub_Product',
            'Query_Type', 'Person', 'Provider', 'URL', 'URL_Name', 'URL_Category'
        ]
        
        try:
            ws_url = wb.worksheet("url_analysis")
        except:
            ws_url = wb.add_worksheet(title="url_analysis", rows=10000, cols=len(url_headers))
            ws_url.append_row(url_headers)
        
        rows = [[row.get(h, '') for h in url_headers] for row in url_rows]
        ws_url.append_rows(rows)
        logger.info(f"✅ Saved {len(rows)} rows to url_analysis")

# ============================================================
# API CONNECTORS
# ============================================================

def retry_with_backoff(func, max_retries=None):
    """Zkusí funkci s exponenciálním backoffem"""
    if max_retries is None:
        max_retries = CONFIG["max_retries"]
    
    for attempt in range(max_retries):
        result = func()
        if result is not None:
            return result
        
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            time.sleep(wait_time)
    
    return None


def ask_perplexity(query, api_key):
    """Zavolej Perplexity API"""
    model_name = CONFIG["model_names"]["perplexity"]
    url = "https://api.perplexity.ai/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": query}]
    }
    
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=CONFIG["request_timeout"]
        )
        
        if resp.status_code == 200:
            d = resp.json()
            usage = d.get('usage', {})
            
            if 'choices' in d and d['choices']:
                msg = d['choices'][0].get('message', {})
                txt = msg.get('content', '')
                cits = msg.get('citations', [])
                
                return {
                    "text": txt,
                    "citations": cits,
                    "tokens": (usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))
                }
        elif resp.status_code in [429, 500, 503, 504]:
            time.sleep(3)
            return None
        else:
            logger.error(f"Perplexity error {resp.status_code}: {resp.text}")
            return None
    
    except requests.exceptions.Timeout:
        logger.warning("Perplexity timeout")
        return None
    except Exception as e:
        logger.error(f"Perplexity exception: {e}")
        return None


def resolve_redirect(url):
    """Vyřeší Google grounding redirect"""
    if 'url?q=' in url:
        match = re.search(r'[?&]q=([^&]+)', url)
        if match:
            from urllib.parse import unquote
            return unquote(match.group(1))
    return url


def ask_gemini(query, api_key):
    """Zavolej Gemini API"""
    model_name = CONFIG["model_names"]["gemini"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}]
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=CONFIG["request_timeout"])
        
        if resp.status_code == 200:
            d = resp.json()
            usage = d.get('usageMetadata', {})
            
            if 'candidates' in d and d['candidates']:
                cand = d['candidates'][0]
                txt = cand.get('content', {}).get('parts', [])[0].get('text', "") if cand.get('content') else ""
                cits = []
                
                if 'groundingMetadata' in cand:
                    for ch in cand.get('groundingMetadata', {}).get('groundingChunks', []):
                        if 'web' in ch and ch['web'].get('uri'):
                            cits.append(resolve_redirect(ch['web']['uri']))
                
                if not txt:
                    logger.warning("Gemini returned empty text")
                    return None
                
                return {
                    "text": txt,
                    "citations": cits,
                    "tokens": (usage.get('promptTokenCount', 0), usage.get('candidatesTokenCount', 0))
                }
            else:
                logger.warning(f"Gemini no candidates: {d}")
                return None
        elif resp.status_code in [429, 500, 503, 504]:
            logger.warning(f"Gemini {resp.status_code}")
            time.sleep(3)
            return None
        else:
            logger.error(f"Gemini error {resp.status_code}: {resp.text}")
            return None
    
    except requests.exceptions.Timeout:
        logger.warning("Gemini timeout")
        return None
    except Exception as e:
        logger.error(f"Gemini exception: {e}")
        return None


def get_ai_response(provider, query, perplexity_key, gemini_key):
    """Získá odpověď od AI providera s retry"""
    
    def _call():
        if provider == "Perplexity":
            return ask_perplexity(query, perplexity_key)
        elif provider == "Gemini":
            return ask_gemini(query, gemini_key)
        else:
            logger.error(f"Unknown provider: {provider}")
            return None
    
    return retry_with_backoff(_call)


def get_batch_sentiment(text, mentioned_brands, gemini_key):
    """
    Analyzuje sentiment pro více brandů najednou - šetří API cally
    """
    if not mentioned_brands:
        return {}
    
    model_name = CONFIG["model_names"]["judge"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
    
    text_sample = text[:3000] if len(text) > 3000 else text
    brands_list = ', '.join([f'"{b}"' for b in mentioned_brands])
    
    prompt = f"""Analyzuj sentiment k následujícím značkám v textu: {brands_list}

Text:
{text_sample}

Odpověz POUZE validním JSON pole v tomto formátu (bez markdown, bez vysvětlení):
[
  {{"brand": "Česká spořitelna", "sentiment": "POSITIVE", "recommendation": "ANO"}},
  {{"brand": "ČSOB", "sentiment": "NEUTRAL", "recommendation": "NE"}}
]

sentiment = POSITIVE pokud pozitivní, NEGATIVE pokud negativní, NEUTRAL pokud neutrální
recommendation = ANO pokud doporučuje, NE pokud nedoporučuje

Odpověz POUZE JSON pole, nic jiného."""
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)
        
        if resp.status_code == 200:
            d = resp.json()
            if 'candidates' in d and d['candidates']:
                candidate = d['candidates'][0]
                
                # Kontrola jestli není blokovaný
                if candidate.get('finishReason') == 'SAFETY':
                    logger.warning("⚠️ Batch sentiment blocked by safety filter")
                    return {}
                
                txt = candidate.get('content', {}).get('parts', [])[0].get('text', '')
                
                if not txt:
                    logger.warning("⚠️ Empty batch sentiment response")
                    return {}
                
                # Čištění
                txt = txt.strip()
                txt = re.sub(r'```json\s*', '', txt)
                txt = re.sub(r'```\s*', '', txt)
                
                # Najdi JSON pole
                start = txt.find('[')
                end = txt.rfind(']')
                if start != -1 and end != -1:
                    txt = txt[start:end+1]
                else:
                    logger.warning(f"⚠️ No JSON array in batch sentiment: {txt[:100]}")
                    return {}
                
                # Parse
                results = json.loads(txt)
                
                # Vytvoř dictionary
                sentiment_dict = {}
                for item in results:
                    brand = item.get('brand', '')
                    sentiment = item.get('sentiment', 'NEUTRAL').upper()
                    recommendation = item.get('recommendation', 'NE').upper()
                    
                    # Normalizace
                    if sentiment not in ['POSITIVE', 'NEGATIVE', 'NEUTRAL']:
                        sentiment = 'NEUTRAL'
                    if recommendation in ['YES']:
                        recommendation = 'ANO'
                    elif recommendation in ['NO']:
                        recommendation = 'NE'
                    elif recommendation not in ['ANO', 'NE']:
                        recommendation = 'NE'
                    
                    sentiment_dict[brand] = {
                        'sentiment': sentiment,
                        'recommendation': recommendation
                    }
                
                logger.info(f"✅ Batch sentiment for {len(sentiment_dict)} brands")
                return sentiment_dict
        
        elif resp.status_code == 429:
            logger.warning("⚠️ Rate limit for batch sentiment")
            time.sleep(2)
            return {}
        else:
            logger.error(f"❌ Batch sentiment API error {resp.status_code}")
            return {}
    
    except json.JSONDecodeError as e:
        logger.error(f"❌ Batch sentiment JSON parse error: {e}")
        return {}
    except Exception as e:
        logger.error(f"❌ Batch sentiment exception: {e}")
        return {}

# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================

def clean_text_aggressive(text):
    """Agresivní normalizace textu pro porovnání"""
    if not text:
        return ""
    
    # Unicode normalizace
    text = unicodedata.normalize('NFKC', text)
    
    # Lowercase
    text = text.lower()
    
    # Odstraň diakritiku
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    
    # Odstraň speciální znaky
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # Odstraň extra mezery
    text = ' '.join(text.split())
    
    return text


def find_all_brand_mentions(text, all_brands):
    """
    Najde všechny zmínky všech brandů v textu a vrátí je seřazené podle pozice
    """
    text_clean = clean_text_aggressive(text)
    
    all_mentions = []
    
    for brand in all_brands:
        brand_name = brand['name']
        keywords = brand['keywords']
        
        first_pos = None
        matched_kws = []
        total_mentions = 0
        
        for keyword in keywords:
            keyword_clean = clean_text_aggressive(keyword)
            
            # Pro krátké keywords používej word boundary
            if len(keyword_clean) <= 2:
                pattern = r'\b' + re.escape(keyword_clean) + r'\b'
                matches = list(re.finditer(pattern, text_clean))
            else:
                # Najdi všechny výskyty
                matches = list(re.finditer(re.escape(keyword_clean), text_clean))
            
            if matches:
                matched_kws.append(keyword)
                total_mentions += len(matches)
                
                # Zapamatuj první pozici
                for match in matches:
                    if first_pos is None or match.start() < first_pos:
                        first_pos = match.start()
        
        # Pokud byl brand nalezen, přidej do seznamu
        if first_pos is not None:
            all_mentions.append({
                'brand_name': brand_name,
                'position': first_pos,
                'matched_keywords': matched_kws,
                'mention_count': total_mentions
            })
    
    # Seřaď podle pozice (nejdřív = rank 1)
    all_mentions.sort(key=lambda x: x['position'])
    
    # Vytvoř lookup dictionary s ranky
    brand_rankings = {}
    for rank, mention in enumerate(all_mentions, start=1):
        brand_rankings[mention['brand_name']] = {
            'rank': rank,
            'position': mention['position'],
            'matched_keywords': mention['matched_keywords'],
            'mention_count': mention['mention_count']
        }
    
    return brand_rankings


def analyze_presence_with_position(brand_name, brand_rankings, citations, brand_keywords):
    """
    Analyzuje přítomnost brandu - používá pre-computed rankings
    """
    # Text presence a rank z pre-computed rankings
    brand_info = brand_rankings.get(brand_name)
    
    if brand_info:
        found_text = True
        position_index = brand_info['rank']
        matched_keywords = brand_info['matched_keywords']
        mention_count = brand_info['mention_count']
    else:
        found_text = False
        position_index = None
        matched_keywords = []
        mention_count = 0
    
    # Hledej v citacích
    found_citation = False
    citations_clean = [clean_text_aggressive(c) for c in citations]
    
    for citation_clean in citations_clean:
        for keyword in brand_keywords:
            keyword_clean = clean_text_aggressive(keyword)
            if keyword_clean in citation_clean:
                found_citation = True
                break
        if found_citation:
            break
    
    return {
        'found_text': found_text,
        'found_citation': found_citation,
        'position_index': position_index,
        'matched_keywords': matched_keywords,
        'mention_count': mention_count
    }


def identify_url_owner(url, brands):
    """Identifikuje vlastníka URL podle brand URLs"""
    if not url:
        return None
    
    url_lower = url.lower()
    
    for brand in brands:
        for keyword in brand['keywords']:
            if keyword.lower() in url_lower:
                return brand['name']
    
    return None

# ============================================================
# PROCESSING
# ============================================================

def process_single_query(item, providers, all_brands, timestamp, date_only, perplexity_key, gemini_key):
    """Zpracuje jeden dotaz napříč všemi providery"""
    
    query_text = item['query']
    query_id = item.get('query_id', '')
    category = item.get('category', '')
    product = item.get('product', '')
    top_product = item.get('top_product', '')
    sub_product = item.get('sub_product', '')
    query_type = item.get('query_type', '')
    person = item.get('person', '')
    
    logger.info(f"Processing: {query_text[:50]}...")
    
    results = {
        'log': [],
        'data': [],
        'url': [],
        'failed': []
    }
    
    for provider in providers:
        try:
            # Získej AI odpověď
            response = get_ai_response(provider, query_text, perplexity_key, gemini_key)
            
            if not response:
                # Selhání
                results['failed'].append({
                    'query': item,
                    'provider': provider,
                    'error': 'API timeout/error',
                    'timestamp': datetime.now().isoformat(),
                    'retry_count': 1
                })
                continue
            
            # Log záznam
            log_entry = {
                'Date': date_only,
                'Timestamp': timestamp,
                'Query_ID': query_id,
                'Query': query_text,
                'Query_Category': category,
                'Query_Product': product,
                'Query_Top_Product': top_product,
                'Query_Sub_Product': sub_product,
                'Query_Type': query_type,
                'Person': person,
                'Provider': provider,
                'Response': response['text'][:5000] if response['text'] else '',
                'Input_Tokens': response['tokens'][0],
                'Output_Tokens': response['tokens'][1]
            }
            results['log'].append(log_entry)
            
            # Najdi VŠECHNY brandy JEDNOU
            brand_rankings = find_all_brand_mentions(response['text'], all_brands)
            
            # Batch sentiment pro všechny zmíněné brandy
            mentioned_brands = list(brand_rankings.keys())
            if mentioned_brands:
                batch_sentiments = get_batch_sentiment(response['text'], mentioned_brands, gemini_key)
            else:
                batch_sentiments = {}
            
            # Analýza brandů
            for brand in all_brands:
                # Analyzuj pomocí rankings
                presence = analyze_presence_with_position(
                    brand['name'],
                    brand_rankings,
                    response['citations'],
                    brand['keywords']
                )
                
                # Získej sentiment z batch (pokud byl brand zmíněn)
                if brand['name'] in batch_sentiments:
                    sentiment_data = batch_sentiments[brand['name']]
                else:
                    sentiment_data = {'sentiment': '', 'recommendation': ''}
                
                # Vytvoř Term_Version ze seznamu nalezených keywords
                if presence.get('matched_keywords'):
                    term_version = ', '.join(presence['matched_keywords'])
                else:
                    term_version = ''
                
                data_entry = {
                    'Date': date_only,
                    'Timestamp': timestamp,
                    'Query_ID': query_id,
                    'Query': query_text,
                    'Query_Category': category,
                    'Query_Product': product,
                    'Query_Top_Product': top_product,
                    'Query_Sub_Product': sub_product,
                    'Query_Type': query_type,
                    'Person': person,
                    'Provider': provider,
                    'Term_Version': term_version,
                    'Term_Name': brand['name'],
                    'Term_Category': brand['category'],
                    'Text_Presence': 1 if presence['found_text'] else 0,
                    'Citation_Presence': 1 if presence['found_citation'] else 0,
                    'Rank': presence['position_index'] if presence['position_index'] else '',
                    'Mention_Count': presence.get('mention_count', 0),
                    'Sentiment': sentiment_data.get('sentiment', ''),
                    'Recommendation': sentiment_data.get('recommendation', '')
                }
                results['data'].append(data_entry)
            
            # URL analýza
            for citation in response['citations']:
                owner = identify_url_owner(citation, all_brands)
                
                url_entry = {
                    'Date': date_only,
                    'Timestamp': timestamp,
                    'Query_ID': query_id,
                    'Query': query_text,
                    'Query_Category': category,
                    'Query_Product': product,
                    'Query_Top_Product': top_product,
                    'Query_Sub_Product': sub_product,
                    'Query_Type': query_type,
                    'Person': person,
                    'Provider': provider,
                    'URL': citation,
                    'URL_Name': owner if owner else '',
                    'URL_Category': ''
                }
                results['url'].append(url_entry)
        
        except Exception as e:
            logger.error(f"Error processing {provider}: {e}")
            results['failed'].append({
                'query': item,
                'provider': provider,
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'retry_count': 1
            })
    
    return results


def process_queries_parallel(queries, brands, providers, max_workers, perplexity_key, gemini_key):
    """Zpracuje dotazy paralelně"""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_only = datetime.now().strftime("%Y-%m-%d")
    
    all_log = []
    all_data = []
    all_url = []
    all_failed = []
    successful = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_single_query,
                item,
                providers,
                brands,
                timestamp,
                date_only,
                perplexity_key,
                gemini_key
            ): item for item in queries
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                
                all_log.extend(result['log'])
                all_data.extend(result['data'])
                all_url.extend(result['url'])
                all_failed.extend(result['failed'])
                
                if not result['failed']:
                    successful += 1
                
                # Batch save
                if len(all_log) >= CONFIG["batch_size"]:
                    with sheets_lock:
                        save_results_to_sheets_internal(all_log, all_data, all_url)
                    all_log, all_data, all_url = [], [], []
            
            except Exception as e:
                logger.error(f"Future error: {e}")
    
    # Final save
    if all_log or all_data or all_url:
        with sheets_lock:
            save_results_to_sheets_internal(all_log, all_data, all_url)
    
    return {
        'successful': successful,
        'failed': all_failed,
        'failed_count': len(all_failed)
    }

# ============================================================
# FAILED QUERIES MANAGEMENT
# ============================================================

def save_failed_queries(new_failed, filepath):
    """Uloží selhané dotazy - MERGE s existujícími"""
    
    # Načti existující
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                existing = json.load(f)
            except:
                existing = []
    else:
        existing = []
    
    # Merge
    all_failed = existing + new_failed
    
    # Deduplikace podle query + provider
    seen = set()
    unique_failed = []
    
    for item in all_failed:
        key = (item['query']['query'], item['provider'])
        if key not in seen:
            seen.add(key)
            unique_failed.append(item)
    
    # Uložení
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(unique_failed, f, indent=2, ensure_ascii=False)
    
    if unique_failed:
        logger.info(f"💾 Saved {len(unique_failed)} failed queries to {filepath}")
    else:
        logger.info(f"💾 No failed queries")