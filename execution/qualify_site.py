"""
STEP 2: Website Qualification with Firecrawl + LLM
Verifies if websites are active, classifies business type via LLM,
detects e-commerce capability, and extracts generic emails.

Usage:
    python qualify_site.py --input .tmp/google_maps_results.json
"""

import os
import sys
import json
import logging
import requests
import argparse
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv
from time import sleep

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

# Load environment variables
load_dotenv()

# Local imports
from api_utils import call_with_retry, sleep_between_calls, save_tracker_snapshot

FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

_firecrawl_semaphore = None
_print_lock = threading.Lock()


class CrawlError(Exception):
    """Raised when a website crawl fails due to network/API issues (retryable)."""
    pass


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def extract_emails(text):
    """Extract email addresses from text"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)

    # Filter out common no-reply and image emails
    filtered = [
        email for email in emails
        if not any(x in email.lower() for x in ['noreply', 'no-reply', '.png', '.jpg', 'example.com'])
    ]

    return list(set(filtered))  # Remove duplicates


def classify_business(text, url):
    """
    Keyword-based classification of business type and e-commerce capability.
    """
    text_lower = text.lower()

    # E-commerce detection
    ecommerce_keywords = [
        'panier', 'cart', 'checkout', 'commander', 'acheter',
        'shop', 'boutique', 'e-commerce', 'prix', 'ajouter au panier',
        'payment', 'paiement', 'shipping', 'livraison'
    ]
    has_ecommerce = any(kw in text_lower for kw in ecommerce_keywords)

    # Business type detection
    manufacturer_keywords = [
        'fabricant', 'manufacturer', 'usine', 'production', 'fabrication',
        'vente', 'catalogue', 'produits', 'modèles', 'gamme',
        'distributeur', 'revendeur', 'showroom', 'devis', 'tarifs'
    ]
    service_keywords = [
        'réservation', 'booking', 'réserver', 'séance', 'soin', 'massage',
        'détente', 'bien-être', 'relaxation', 'privatif',
        'forfait', 'abonnement', 'prestation', 'expérience'
    ]

    m_score = sum(1 for kw in manufacturer_keywords if kw in text_lower)
    s_score = sum(1 for kw in service_keywords if kw in text_lower)

    if m_score >= 3 and m_score > s_score:
        btype = 'Manufacturer'
    elif s_score >= 3 and s_score > m_score:
        btype = 'Service'
    else:
        btype = 'Unknown'

    return {
        'business_type': btype,
        'ecommerce': 'Oui' if has_ecommerce else 'Non',
        'confidence': 50,
        'justification': 'Keyword-based fallback classification',
        'tech_stack': 'unknown'
    }


def classify_with_llm(text, url, industry=''):
    """Classify business type using Claude Haiku. Returns dict or None on failure."""
    if not ANTHROPIC_API_KEY:
        return None

    snippet = text[:3000]
    prompt = f"""Analyse ce site web et classifie l'entreprise.

URL: {url}
Industrie recherchée: {industry or 'non spécifiée'}

Contenu du site:
{snippet}

Réponds UNIQUEMENT en JSON strict (pas de markdown):
{{"business_type": "Manufacturer" ou "Service" ou "Unknown", "ecommerce": "Oui" ou "Non", "confidence": 0-100, "justification": "explication courte"}}

Règles:
- "Manufacturer" = fabrique, construit, vend ses propres produits physiques (saunas, hammams, spas, etc.), même s'il propose aussi de l'installation
- "Service" = propose uniquement des prestations (spa/hammam d'accueil, massage, séances bien-être) sans vendre de produits
- Un revendeur/distributeur qui vend des produits = "Manufacturer"
- En cas de doute entre Manufacturer et Service, favorise "Manufacturer" si le site présente un catalogue de produits à vendre"""

    try:
        resp = call_with_retry(
            lambda: requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            ),
            label="Anthropic classify"
        )

        if resp.status_code != 200:
            logging.warning(f"Anthropic classify returned {resp.status_code}")
            return None

        raw = resp.json()['content'][0]['text'].strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        result = json.loads(raw)

        return {
            'business_type': result.get('business_type', 'Unknown'),
            'ecommerce': result.get('ecommerce', 'Non'),
            'confidence': result.get('confidence', 70),
            'justification': result.get('justification', 'LLM classification'),
            'tech_stack': 'unknown'
        }
    except Exception as e:
        logging.warning(f"LLM classification failed: {e}")
        return None


CONTACT_PAGE_SUFFIXES = [
    '/contact', '/nous-contacter', '/contactez-nous',
    '/mentions-legales', '/a-propos', '/qui-sommes-nous',
    '/about', '/about-us', '/legal', '/imprint', '/impressum',
]


def _scrape_page(url, headers):
    """Scrape a single page via Firecrawl. Respects global semaphore for rate limiting."""
    payload = {'url': url}
    sem = _firecrawl_semaphore

    if sem:
        sem.acquire()
    try:
        resp = call_with_retry(
            lambda: requests.post(
                "https://api.firecrawl.dev/v0/scrape",
                headers=headers, json=payload, timeout=30
            ),
            label=f"Firecrawl scrape {url}"
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', {}).get('markdown', '') or data.get('data', {}).get('content', '')
        raise CrawlError(f"Firecrawl returned {resp.status_code} for {url}")
    except CrawlError:
        raise
    except Exception as e:
        raise CrawlError(f"Scrape failed for {url}: {str(e)[:80]}")
    finally:
        if sem:
            sem.release()


def _find_emails_deep(base_url, headers):
    """
    Crawl the main page + common contact/legal pages to find emails.
    Returns all unique emails found across pages.
    Raises CrawlError if the homepage itself fails (retryable at caller level).
    """
    all_emails = []

    # 1) Scrape homepage — CrawlError propagates to caller for retry
    _safe_print(f"    Crawling homepage...")
    homepage_content = _scrape_page(base_url, headers)
    all_emails.extend(extract_emails(homepage_content))

    if all_emails:
        return all_emails, homepage_content

    # 2) No emails on homepage — try contact/legal pages (tolerant of failures)
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    for suffix in CONTACT_PAGE_SUFFIXES:
        page_url = base + suffix
        _safe_print(f"    Crawling {page_url}...")
        try:
            content = _scrape_page(page_url, headers)
        except CrawlError:
            continue
        if content:
            found = extract_emails(content)
            if found:
                all_emails.extend(found)
                homepage_content += '\n' + content
                break
        sleep_between_calls(0.5, label="inter-page")

    return list(set(all_emails)), homepage_content


def qualify_website(url, industry=''):
    """
    Use Firecrawl to scrape + LLM (with keyword fallback) to qualify a website.
    Crawls multiple pages (homepage + contact/legal) to find emails.

    Raises CrawlError if the crawl fails (network/API), so the caller can retry.
    Returns a normal dict (with Business_Type) for legitimate classification results.
    """

    if not url or url == '':
        return {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown',
            'Confidence': 0,
            'Justification': '',
            'Tech_Stack': 'unknown'
        }

    if not FIRECRAWL_API_KEY:
        raise ValueError("FIRECRAWL_API_KEY not found in .env file")

    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'

    _safe_print(f"  Checking: {url}")

    headers = {
        'Authorization': f'Bearer {FIRECRAWL_API_KEY}',
        'Content-Type': 'application/json'
    }

    # CrawlError from _find_emails_deep propagates to caller for retry
    emails, content = _find_emails_deep(url, headers)
    email = emails[0] if emails else ''

    if not content:
        _safe_print(f"    Website unreachable")
        return {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown',
            'Confidence': 0,
            'Justification': 'Website unreachable after crawl',
            'Tech_Stack': 'unknown'
        }

    classification = classify_with_llm(content, url, industry)
    if classification is None:
        classification = classify_business(content, url)

    ecommerce = classification['ecommerce']
    business_type = classification['business_type']
    confidence = classification['confidence']
    justification = classification['justification']
    tech_stack = classification['tech_stack']

    _safe_print(f"    Active | Email: {email or 'None'} | E-commerce: {ecommerce} | Type: {business_type} ({confidence}%)")
    if justification:
        _safe_print(f"    Reason: {justification}")

    return {
        'Email_Generique': email,
        'Ecommerce': ecommerce,
        'Business_Type': business_type,
        'Confidence': confidence,
        'Justification': justification,
        'Tech_Stack': tech_stack
    }


MAX_CRAWL_RETRIES = 2
CRAWL_RETRY_DELAY = 5


def _qualify_single_lead(index, lead, total, industry=''):
    """
    Qualify one lead with retry on CrawlError.
    Returns (lead, is_qualified, filter_reason).
    """
    name = lead.get('Nom_Entreprise', 'Unknown')
    _safe_print(f"[{index}/{total}] {name}")

    qualification = None
    last_err = None

    for attempt in range(1, MAX_CRAWL_RETRIES + 2):
        try:
            qualification = qualify_website(lead.get('Site_Web', ''), industry=industry)
            break
        except CrawlError as e:
            last_err = e
            if attempt <= MAX_CRAWL_RETRIES:
                _safe_print(f"    Crawl error (attempt {attempt}/{MAX_CRAWL_RETRIES + 1}), retrying in {CRAWL_RETRY_DELAY}s...")
                sleep(CRAWL_RETRY_DELAY)
            else:
                _safe_print(f"    Crawl failed after {attempt} attempts: {str(e)[:60]}")

    if qualification is None:
        qualification = {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown',
            'Confidence': 0,
            'Justification': f'Crawl error: {str(last_err)[:80]}',
            'Tech_Stack': 'unknown'
        }

    lead.update(qualification)

    business_type = qualification.get('Business_Type')
    if business_type == 'Manufacturer':
        return lead, True, None

    reason = "Service provider (not manufacturer)" if business_type == 'Service' else "Business type unclear"
    _safe_print(f"    Filtered out: {reason}")
    return lead, False, reason


def process_leads(input_file, workers=3, industry=''):
    """Process all leads and qualify their websites in parallel.

    Args:
        input_file: Path to JSON file with scraped leads
        workers: Number of parallel workers (default 3)
        industry: Target industry for LLM context
    """
    global _firecrawl_semaphore
    _firecrawl_semaphore = threading.Semaphore(workers)

    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    mode = "LLM classification" if ANTHROPIC_API_KEY else "keyword classification"
    total = len(leads)
    print(f"Processing {total} leads ({mode}, {workers} workers)...\n")

    qualified_leads = []
    filtered_count = 0
    error_count = 0

    if workers <= 1:
        for i, lead in enumerate(leads, 1):
            lead, is_qualified, reason = _qualify_single_lead(i, lead, total, industry=industry)
            if is_qualified:
                qualified_leads.append(lead)
            else:
                filtered_count += 1
                if reason and 'Crawl error' in (lead.get('Justification') or ''):
                    error_count += 1
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for i, lead in enumerate(leads, 1):
                future = executor.submit(_qualify_single_lead, i, lead, total, industry=industry)
                futures[future] = i

            for future in as_completed(futures):
                lead, is_qualified, reason = future.result()
                if is_qualified:
                    qualified_leads.append(lead)
                else:
                    filtered_count += 1
                    if lead.get('Justification', '').startswith('Crawl error'):
                        error_count += 1

    print(f"\nQualification complete: {len(qualified_leads)}/{total} manufacturer/seller leads")
    print(f"Filtered out: {filtered_count} leads ({error_count} crawl errors, {filtered_count - error_count} service/unclear)")

    return qualified_leads


def save_results(leads, output_filename='qualified_leads.json'):
    """Save qualified leads to JSON"""
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    output_path = tmp_dir / output_filename

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"💾 Saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Qualify websites using Firecrawl + keyword analysis')
    parser.add_argument('--input', required=True, help='Input JSON file from scraping step')
    parser.add_argument('--industry', default='', help='Target industry for LLM classification context')
    parser.add_argument('--workers', type=int, default=3, help='Number of parallel workers (default: 3, use 1 for sequential)')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    print(f"API Keys status:")
    print(f"   - FIRECRAWL_API_KEY: {'Configured' if FIRECRAWL_API_KEY else 'Missing'}")
    print(f"   - ANTHROPIC_API_KEY: {'Configured (LLM mode)' if ANTHROPIC_API_KEY else 'Missing (keyword fallback)'}")
    print()

    qualified_leads = process_leads(input_path, workers=args.workers, industry=args.industry)

    output_path = save_results(qualified_leads)

    print(f"\nStep 2 complete")
    print(f"Output: {output_path}")
    print(f"\nNext step: Run enrichment with enrich.py")

    save_tracker_snapshot("step2_qualify")


if __name__ == '__main__':
    main()
