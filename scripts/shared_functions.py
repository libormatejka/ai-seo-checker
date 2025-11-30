"""
Sdílené funkce pro main_run.py i retry_run.py
Obsahuje všechnu core logiku pro API calls, analýzu a ukladání dat
"""

import os
import json
import logging
import gspread
import requests
import time
import unicodedata
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ==========================================
# CONFIG
# ==========================================

CONFIG = {
    "active_providers": ["Perplexity", "Gemini"],
    
    "model_names": {
        "perplexity": "sonar",
        "gemini": "gemini-2.5-flash",
        "judge": "gemini-2.5-flash"
    },
    
    "sheets": {
        "queries": "Queries",
        "terms": "Terms",
        "urls": "Urls",
        "log_output": "log_answers",
        "data_output": "data_analysis",
        "url_output": "url_analysis"
    },
    
    "max_workers": 3,
    "batch_size": 30,
    "max_retries": 4,
    "request_timeout": 120,
}

# Thread locks
sheets_lock = threading.Lock()

# ==========================================
# LOGGING
# ==========================================

def setup_logging(script_name):
    """Nastav logging do souboru i konzole"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # Vytvoř logger
    logger = logging.getLogger(script_name)
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

# ==========================================
# GOOGLE SHEETS
# ==========================================

def init_google_sheets():
    """Inicializuj Google Sheets přes service account"""
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    sheet_url = os.getenv("SHEET_URL")
    
    if not creds_json:
        raise ValueError("Missing GOOGLE_SHEETS_CREDENTIALS environment variable")
    
    if not sheet_url:
        raise ValueError("Missing SHEET_URL environment variable")
    
    creds_dict = json.loads(creds_json)
    
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    
    return gc.open_by_url(sheet_url)

# ==========================================
# DATA LOADING
# ==========================================

def load_brands(wb):
    """Načti brandy z Terms a Urls sheetů"""
    brands_map = {}
    
    try:
        # Načti Terms
        ws_terms = wb.worksheet(CONFIG["sheets"]["terms"])
        for row in ws_terms.get_all_values()[1:]:
            if len(row) < 2: 
                continue
            term, name = row[0].strip(), row[1].strip()
            if not term or not name: 
                continue
            if name not in brands_map:
                type_val = row[2].strip() if len(row) > 2 else "Competitor"
                brands_map[name] = {"name": name, "type": type_val, "keywords": [], "urls": []}
            brands_map[name]["keywords"].append(term)
        
        # Načti URLs
        ws_urls = wb.worksheet(CONFIG["sheets"]["urls"])
        for row in ws_urls.get_all_values()[1:]:
            if len(row) < 2: 
                continue
            url_val, name = row[0].strip(), row[1].strip()
            if not url_val or not name: 
                continue
            if name not in brands_map:
                type_val = row[2].strip() if len(row) > 2 else "Competitor"
                brands_map[name] = {"name": name, "type": type_val, "keywords": [], "urls": []}
            brands_map[name]["urls"].append(url_val)
        
        return list(brands_map.values())
        
    except Exception as e:
        logger.error(f"Failed to load brands: {e}")
        return []

def load_queries(wb):
    """Načti dotazy z Queries sheetu"""
    queries = []
    
    try:
        ws_queries = wb.worksheet(CONFIG["sheets"]["queries"])
        all_data = ws_queries.get_all_values()
        
        if len(all_data) <= 1:
            return []
        
        headers = [h.strip().lower() for h in all_data[0]]
        
        idx_query = headers.index('query') if 'query' in headers else -1
        idx_category = headers.index('query category') if 'query category' in headers else -1
        idx_product = headers.index('query product') if 'query product' in headers else -1
        idx_type = headers.index('query type') if 'query type' in headers else -1
        idx_persona = headers.index('persona') if 'persona' in headers else -1
        
        if idx_query == -1:
            logger.error("Column 'query' not found in Queries sheet")
            return []
        
        for row in all_data[1:]:
            q_text = row[idx_query].strip() if len(row) > idx_query else ""
            if not q_text: 
                continue
            
            q_cat = row[idx_category].strip() if idx_category != -1 and len(row) > idx_category else "Obecné"
            q_prod = row[idx_product].strip() if idx_product != -1 and len(row) > idx_product else "Neurčeno"
            q_type = row[idx_type].strip() if idx_type != -1 and len(row) > idx_type else "Neurčeno"
            q_persona = row[idx_persona].strip() if idx_persona != -1 and len(row) > idx_persona else "Neurčeno"
            
            queries.append({
                "query": q_text,
                "category": q_cat,
                "product": q_prod,
                "type": q_type,
                "persona": q_persona
            })
        
        return queries
        
    except Exception as e:
        logger.error(f"Failed to load queries: {e}")
        return []

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def resolve_redirect(url):
    """Resolve Google grounding redirects"""
    if not url: 
        return ""
    url = str(url).strip()
    
    matches = list(re.finditer(r'https?://', url))
    if len(matches) > 1:
        first_start = matches[0].start()
        second_start = matches[1].start()
        candidate = url[first_start:second_start]
        if "vertexaisearch" not in candidate and "google.com/grounding" not in candidate:
            return candidate
        url = candidate
    
    if "vertexaisearch.cloud.google.com" in url or "google.com/grounding-api-redirect" in url:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, allow_redirects=True, timeout=5, headers=headers, stream=True)
            final_url = resp.url
            resp.close()
            return final_url
        except:
            return url
    
    return url

def clean_text_aggressive(text):
    """Vyčisti text pro porovnání"""
    if not text: 
        return ""
    t = str(text)
    t = re.sub(r'\[.*?\]', '', t)
    t = t.replace('*', '').replace('#', '').replace('_', '')
    t = unicodedata.normalize("NFKC", t)
    t = t.lower()
    t = re.sub(r'\s+', ' ', t)
    return t.strip()

# ==========================================
# RETRY LOGIC
# ==========================================

def retry_with_backoff(func, max_retries=None, initial_delay=1):
    """Univerzální retry funkce s exponenciálním backoffem"""
    if max_retries is None:
        max_retries = CONFIG["max_retries"]
    
    for attempt in range(max_retries):
        try:
            result = func()
            if result is not None:
                return result
        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                return None
        except Exception as e:
            if attempt == max_retries - 1:
                return None
        
        delay = initial_delay * (2 ** attempt)
        time.sleep(min(delay, 10))
    
    return None

# ==========================================
# API CALLS
# ==========================================

def ask_perplexity(query, api_key):
    """Zavolej Perplexity API"""
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": CONFIG["model_names"]["perplexity"],
        "messages": [{"role": "user", "content": query}],
        "return_citations": True
    }
    
    resp = requests.post(url, json=payload, headers=headers, timeout=CONFIG["request_timeout"])
    
    if resp.status_code == 200:
        d = resp.json()
        usage = d.get('usage', {})
        return {
            "text": d['choices'][0]['message']['content'],
            "citations": d.get('citations', []),
            "tokens": (usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))
        }
    elif resp.status_code == 429:
        time.sleep(5)
        return None
    else:
        return None

def ask_gemini(query, api_key):
    """Zavolej Gemini API"""
    model_name = CONFIG["model_names"]["gemini"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}]
    }
    
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
                return None
            
            return {
                "text": txt,
                "citations": cits,
                "tokens": (usage.get('promptTokenCount', 0), usage.get('candidatesTokenCount', 0))
            }
        else:
            return None
    elif resp.status_code in [429, 500, 503, 504]:
        time.sleep(3)
        return None
    else:
        return None

def get_ai_response(provider, query, perplexity_key, gemini_key):
    """Wrapper s retry logikou"""
    def api_call():
        if provider == "Perplexity":
            return ask_perplexity(query, perplexity_key)
        elif provider == "Gemini":
            return ask_gemini(query, gemini_key)
        return None
    
    return retry_with_backoff(api_call)

def get_advanced_metrics(text, brand_name, gemini_key):
    """Získej sentiment a recommendation pomocí Gemini"""
    if not text or not brand_name:
        return "N/A", "NE"
    
    text_snippet = text[:3000]
    prompt = f"""Analyze regarding "{brand_name}". 1. Sentiment: POSITIVE/NEGATIVE/NEUTRAL. 2. Recommendation: Explicit top choice? (YES/NO). Format: SENTIMENT | RECOMMENDATION"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{CONFIG['model_names']['judge']}:generateContent?key={gemini_key}"
    
    try:
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if resp.status_code == 200:
            raw = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip().upper()
            parts = raw.split('|')
            
            if len(parts) >= 2:
                sent = parts[0].strip()
                if sent not in ["POSITIVE", "NEGATIVE", "NEUTRAL"]:
                    sent = "NEUTRAL"
                rec = "ANO" if "YES" in parts[1].strip() else "NE"
                return sent, rec
        
        return "NEUTRAL", "NE"
    except:
        return "N/A", "NE"

# ==========================================
# ANALYSIS
# ==========================================

def analyze_presence_with_position(text, citations, brand_obj):
    """Analyzuj přítomnost brandu v textu a citacích"""
    clean_content = clean_text_aggressive(text)
    found_text = 0
    first_index = float('inf')
    
    for kw in brand_obj['keywords']:
        clean_kw = clean_text_aggressive(kw)
        idx = clean_content.find(clean_kw)
        if idx != -1:
            found_text = 1
            if idx < first_index:
                first_index = idx
    
    final_position_index = first_index if found_text else -1
    
    found_citation = 0
    for u in brand_obj['urls']:
        if u and any(u.lower() in cit.lower() for cit in citations):
            found_citation = 1
            break
    
    return found_text, found_citation, final_position_index

def identify_url_owner(url, all_brands):
    """Identifikuj vlastníka URL"""
    url_lower = url.lower()
    for brand in all_brands:
        for b_url in brand['urls']:
            if b_url.lower() in url_lower:
                return brand['name'], brand['type']
    return "Ostatní / Média", "Other"

# ==========================================
# QUERY PROCESSING
# ==========================================

def process_single_query(item, providers, all_brands, timestamp, date_only, perplexity_key, gemini_key):
    """Zpracuj jeden dotaz"""
    dotaz = item['query']
    q_cat = item['category']
    q_type = item['type']
    q_persona = item['persona']
    q_product = item['product']
    
    results = {
        'log': [],
        'data': [],
        'url': [],
        'failed': []
    }
    
    for provider in providers:
        result = get_ai_response(provider, dotaz, perplexity_key, gemini_key)
        
        if result:
            content = result['text']
            citations = result['citations']
            tokens = result.get('tokens', (0, 0))
            found_count = 0
            
            temp_res = []
            for brand in all_brands:
                in_txt, in_cit, pos_index = analyze_presence_with_position(content, citations, brand)
                temp_res.append({"brand": brand, "in_txt": in_txt, "in_cit": in_cit, "pos_index": pos_index})
            
            brands_in_text = [b for b in temp_res if b['pos_index'] != -1]
            brands_in_text.sort(key=lambda x: x['pos_index'])
            rank_map = {b_obj['brand']['name']: rank for rank, b_obj in enumerate(brands_in_text, 1)}
            
            for res in temp_res:
                b_name = res['brand']['name']
                final_rank = rank_map.get(b_name, "")
                sentiment, recommended = "N/A", "NE"
                
                if res['in_txt'] or res['in_cit']:
                    found_count += 1
                    sentiment, recommended = get_advanced_metrics(content, b_name, gemini_key)
                
                results['data'].append([
                    timestamp, date_only, q_cat, q_type, q_product, q_persona,
                    dotaz, provider, b_name, res['brand']['type'],
                    res['in_txt'], res['in_cit'], sentiment, recommended, final_rank
                ])
            
            for cit_url in citations:
                o_name, o_type = identify_url_owner(cit_url, all_brands)
                results['url'].append([
                    timestamp, date_only, q_cat, q_type, q_product, q_persona,
                    dotaz, provider, cit_url, o_name, o_type
                ])
            
            results['log'].append([
                timestamp, date_only, q_cat, q_type, q_product, q_persona,
                dotaz, provider, found_count, tokens[0], tokens[1], content
            ])
        else:
            # Selhalo
            results['failed'].append({
                "query": item,
                "provider": provider,
                "error": "API timeout/error",
                "timestamp": datetime.now().isoformat(),
                "retry_count": 1
            })
            
            results['log'].append([
                timestamp, date_only, q_cat, q_type, q_product, q_persona,
                dotaz, provider, 0, 0, 0, "ERROR / TIMEOUT"
            ])
    
    return results

def process_queries_parallel(queries, brands, providers, max_workers, perplexity_key, gemini_key, is_retry=False):
    """Zpracuj dotazy paralelně"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_only = datetime.now().strftime("%Y-%m-%d")
    
    all_log, all_data, all_url, all_failed = [], [], [], []
    completed = 0
    
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
            ): item
            for item in queries
        }
        
        for future in as_completed(futures):
            completed += 1
            item = futures[future]
            
            try:
                results = future.result(timeout=180)
                
                all_log.extend(results['log'])
                all_data.extend(results['data'])
                all_url.extend(results['url'])
                all_failed.extend(results['failed'])
                
                # Průběžný zápis
                if len(all_log) >= CONFIG["batch_size"]:
                    save_results_to_sheets_internal(all_log, all_data, all_url)
                    all_log, all_data, all_url = [], [], []
                
            except Exception as e:
                logger.error(f"Query failed: {item['query'][:50]} - {e}")
                all_failed.append({
                    "query": item,
                    "provider": "ALL",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                    "retry_count": 1
                })
    
    # Finální zápis
    if all_log or all_data or all_url:
        save_results_to_sheets_internal(all_log, all_data, all_url)
    
    return {
        'successful': len(queries) * len(providers) - len(all_failed),
        'failed_count': len(all_failed),
        'failed': all_failed
    }

# ==========================================
# SHEETS WRITING
# ==========================================

def append_to_sheet_safe(wb, sheet_name, data_rows, header):
    """Thread-safe zápis do Sheets"""
    if not data_rows:
        return
    
    with sheets_lock:
        try:
            try:
                ws = wb.worksheet(sheet_name)
                if len(ws.get_all_values()) == 0:
                    ws.append_row(header)
                    ws.format('1:1', {'textFormat': {'bold': True}})
            except gspread.WorksheetNotFound:
                ws = wb.add_worksheet(title=sheet_name, rows=1000, cols=20)
                ws.append_row(header)
                ws.format('1:1', {'textFormat': {'bold': True}})
            
            ws.append_rows(data_rows)
            logger.info(f"✅ Saved {len(data_rows)} rows to {sheet_name}")
            
        except Exception as e:
            logger.error(f"Failed to write to {sheet_name}: {e}")
            time.sleep(2)
            try:
                ws = wb.worksheet(sheet_name)
                ws.append_rows(data_rows)
            except:
                pass

# Global workbook reference
_wb = None

def save_results_to_sheets_internal(log_batch, data_batch, url_batch):
    """Internal helper pro zápis - používá globální workbook"""
    global _wb
    if _wb is None:
        _wb = init_google_sheets()
    
    if log_batch:
        append_to_sheet_safe(
            _wb,
            CONFIG["sheets"]["log_output"],
            log_batch,
            ["Timestamp", "Date", "Query Category", "Query type", "Query Product", "Persona", "Query", "AI Tool", "Found Count", "Input Tokens", "Output Tokens", "Response"]
        )
    
    if data_batch:
        append_to_sheet_safe(
            _wb,
            CONFIG["sheets"]["data_output"],
            data_batch,
            ["Timestamp", "Date", "Query Category", "Query type", "Query Product", "Persona", "Query", "AI Tool", "Brand", "Brand Type", "Text Presence", "Citation Presence", "Sentiment", "Recommendation", "Rank"]
        )
    
    if url_batch:
        append_to_sheet_safe(
            _wb,
            CONFIG["sheets"]["url_output"],
            url_batch,
            ["Timestamp", "Date", "Query Category", "Query type", "Query Product", "Persona", "Query", "AI Tool", "URL", "Owner", "Owner Type"]
        )

# ==========================================
# FAILED QUERIES
# ==========================================

def save_failed_queries(failed_list, filepath):
    """Ulož selhané dotazy do JSON"""
    # Načti existující
    existing = []
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except:
            existing = []
    
    # Merge s novými
    unique_failed = {}
    
    # Nejdřív existující
    for item in existing:
        key = f"{item['query']['query']}_{item['provider']}"
        unique_failed[key] = item
    
    # Pak nové (přepíše staré pokud mají vyšší retry_count)
    for item in failed_list:
        key = f"{item['query']['query']}_{item['provider']}"
        if key not in unique_failed or item.get('retry_count', 0) > unique_failed[key].get('retry_count', 0):
            unique_failed[key] = item
    
    # Ulož
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(list(unique_failed.values()), f, indent=2, ensure_ascii=False)
    
    logger.info(f"💾 Saved {len(unique_failed)} failed queries to {filepath}")
