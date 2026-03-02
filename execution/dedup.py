"""
STEP 1b: Deduplication — Eliminate already-known leads before expensive qualification.

Two-phase dedup:
  1. Intra-batch: fuzzy-match within the scraped batch itself (zero API cost)
  2. vs HubSpot: bulk-fetch existing companies, compare locally (1-3 API calls)

Usage:
    python dedup.py --input .tmp/google_maps_results.json
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import urlparse
from dotenv import load_dotenv
from time import sleep

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from api_utils import sdk_call_with_retry, save_tracker_snapshot

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

FUZZY_THRESHOLD = 0.82


def _normalize_domain(url):
    """Extract and normalize domain from a URL or raw domain string."""
    if not url:
        return ''
    url = url.strip().lower()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
    except Exception:
        domain = url
    domain = domain.replace('www.', '')
    return domain.strip().rstrip('/')


def _normalize_name(name):
    """Lowercase + strip punctuation for fuzzy comparison."""
    if not name:
        return ''
    import re
    name = name.lower().strip()
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _fuzzy_match(a, b, threshold=FUZZY_THRESHOLD):
    """Return True if two normalized names are similar above threshold."""
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


# ───────────────────────────────────────────────────────────────
# Phase 1: Intra-batch deduplication (zero API cost)
# ───────────────────────────────────────────────────────────────

def deduplicate_batch(leads):
    """Remove duplicates within a single scrape batch.

    Matches by exact domain OR fuzzy company name.
    Keeps the first occurrence (richer data usually comes first from Google Maps).

    Returns:
        (unique_leads, removed_count)
    """
    if not leads:
        return leads, 0

    seen_domains = {}
    seen_names = []
    unique = []
    removed = 0

    for lead in leads:
        domain = _normalize_domain(lead.get('Site_Web', ''))
        name = _normalize_name(lead.get('Nom_Entreprise', ''))

        is_dup = False

        if domain and domain in seen_domains:
            print(f"    [intra-batch] Doublon domaine: {lead.get('Nom_Entreprise', '?')} "
                  f"({domain}) — deja vu comme {seen_domains[domain]}")
            is_dup = True

        if not is_dup and name:
            for existing_name, existing_raw in seen_names:
                if _fuzzy_match(name, existing_name):
                    print(f"    [intra-batch] Doublon nom: \"{lead.get('Nom_Entreprise', '')}\" "
                          f"≈ \"{existing_raw}\" (score {SequenceMatcher(None, name, existing_name).ratio():.0%})")
                    is_dup = True
                    break

        if is_dup:
            removed += 1
            continue

        if domain:
            seen_domains[domain] = lead.get('Nom_Entreprise', '')
        if name:
            seen_names.append((name, lead.get('Nom_Entreprise', '')))
        unique.append(lead)

    return unique, removed


# ───────────────────────────────────────────────────────────────
# Phase 2: Deduplication against HubSpot (bulk fetch)
# ───────────────────────────────────────────────────────────────

def _init_hubspot_client():
    """Initialize HubSpot client."""
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env — cannot deduplicate against HubSpot")
    from hubspot import HubSpot
    return HubSpot(access_token=HUBSPOT_API_KEY)


def fetch_hubspot_companies(client):
    """Bulk-fetch all companies from HubSpot with domain + name.

    Uses get_all with pagination (100 per page).
    Returns list of dicts: [{"name": ..., "domain": ...}, ...]
    """
    print("  Fetching existing companies from HubSpot...")

    try:
        all_companies = sdk_call_with_retry(
            lambda: client.crm.companies.get_all(
                properties=["name", "domain"],
                limit=100
            ),
            label="HubSpot get-all-companies"
        )
    except Exception as e:
        print(f"  ⚠️  Could not fetch companies: {str(e)[:100]}")
        return []

    results = []
    for company in all_companies:
        props = company.properties if hasattr(company, 'properties') else {}
        name = props.get('name', '') or ''
        domain = props.get('domain', '') or ''
        results.append({
            'name': name,
            'domain': _normalize_domain(domain),
            'name_normalized': _normalize_name(name),
            'id': company.id,
        })

    print(f"  📦 {len(results)} companies existantes dans HubSpot")
    return results


def fetch_hubspot_contacts(client):
    """Bulk-fetch all contacts from HubSpot with company + email.

    Used as a secondary check for contacts without company records.
    Returns list of dicts: [{"email": ..., "company": ...}, ...]
    """
    try:
        all_contacts = sdk_call_with_retry(
            lambda: client.crm.contacts.get_all(
                properties=["email", "company", "website"],
                limit=100
            ),
            label="HubSpot get-all-contacts"
        )
    except Exception as e:
        print(f"  ⚠️  Could not fetch contacts: {str(e)[:100]}")
        return []

    results = []
    for contact in all_contacts:
        props = contact.properties if hasattr(contact, 'properties') else {}
        results.append({
            'email': (props.get('email', '') or '').lower().strip(),
            'company': props.get('company', '') or '',
            'company_normalized': _normalize_name(props.get('company', '') or ''),
            'website': _normalize_domain(props.get('website', '') or ''),
            'id': contact.id,
        })

    return results


def deduplicate_against_hubspot(leads, client=None):
    """Compare scraped leads against existing HubSpot companies + contacts.

    Strategy:
      1. Bulk-fetch all companies (paginated, ~1-3 API calls)
      2. Bulk-fetch all contacts (paginated, ~1-3 API calls)
      3. For each lead, check domain match OR fuzzy name match
      4. Return only truly new leads

    Returns:
        (new_leads, duplicate_leads, stats_dict)
    """
    if client is None:
        client = _init_hubspot_client()

    companies = fetch_hubspot_companies(client)
    contacts = fetch_hubspot_contacts(client)

    hs_domains = {c['domain'] for c in companies if c['domain']}
    hs_names = [(c['name_normalized'], c['name']) for c in companies if c['name_normalized']]
    hs_contact_companies = [(c['company_normalized'], c['company']) for c in contacts if c['company_normalized']]
    hs_contact_websites = {c['website'] for c in contacts if c['website']}

    new_leads = []
    duplicate_leads = []

    for lead in leads:
        domain = _normalize_domain(lead.get('Site_Web', ''))
        name = _normalize_name(lead.get('Nom_Entreprise', ''))
        raw_name = lead.get('Nom_Entreprise', '?')

        is_dup = False
        match_reason = ''

        if domain and domain in hs_domains:
            is_dup = True
            match_reason = f"domaine exact ({domain})"

        if not is_dup and domain and domain in hs_contact_websites:
            is_dup = True
            match_reason = f"domaine contact ({domain})"

        if not is_dup and name:
            for hs_norm, hs_raw in hs_names:
                if _fuzzy_match(name, hs_norm):
                    score = SequenceMatcher(None, name, hs_norm).ratio()
                    is_dup = True
                    match_reason = f"nom company ≈ \"{hs_raw}\" ({score:.0%})"
                    break

        if not is_dup and name:
            for ct_norm, ct_raw in hs_contact_companies:
                if _fuzzy_match(name, ct_norm):
                    score = SequenceMatcher(None, name, ct_norm).ratio()
                    is_dup = True
                    match_reason = f"nom contact company ≈ \"{ct_raw}\" ({score:.0%})"
                    break

        if is_dup:
            print(f"    [vs HubSpot] Doublon: {raw_name} — {match_reason}")
            duplicate_leads.append(lead)
        else:
            new_leads.append(lead)

    stats = {
        'total_scraped': len(leads),
        'hubspot_companies': len(companies),
        'hubspot_contacts': len(contacts),
        'duplicates_found': len(duplicate_leads),
        'new_leads': len(new_leads),
    }

    return new_leads, duplicate_leads, stats


# ───────────────────────────────────────────────────────────────
# Full dedup pipeline (called from run_pipeline.py)
# ───────────────────────────────────────────────────────────────

def run_dedup(input_file, output_file=None, skip_hubspot=False):
    """Run full deduplication: intra-batch + HubSpot check.

    Args:
        input_file: Path to google_maps_results.json
        output_file: Path to save deduplicated results (default: same as input)
        skip_hubspot: If True, only do intra-batch dedup

    Returns:
        Path to output file
    """
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return None

    with open(input_path, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    total_initial = len(leads)
    print(f"📋 Deduplication de {total_initial} leads...\n")

    # Phase 1: Intra-batch
    print("  Phase 1/2: Deduplication intra-batch...")
    leads, batch_removed = deduplicate_batch(leads)
    if batch_removed:
        print(f"    → {batch_removed} doublons internes elimines")
    else:
        print(f"    → Aucun doublon interne")

    # Phase 2: vs HubSpot
    hubspot_removed = 0
    if skip_hubspot:
        print("\n  Phase 2/2: Skipped (--no-hubspot)")
    else:
        print("\n  Phase 2/2: Deduplication vs HubSpot...")
        try:
            leads, duplicates, stats = deduplicate_against_hubspot(leads)
            hubspot_removed = stats['duplicates_found']
            if hubspot_removed:
                print(f"    → {hubspot_removed} leads deja presents dans HubSpot")
            else:
                print(f"    → Aucun doublon HubSpot")
        except Exception as e:
            print(f"    ⚠️  HubSpot dedup failed: {str(e)[:100]} — continuing with all leads")

    # Summary
    total_removed = batch_removed + hubspot_removed
    print(f"\n✅ Deduplication terminee:")
    print(f"  📊 Initial: {total_initial} | Elimines: {total_removed} | Restants: {len(leads)}")
    if total_removed > 0:
        print(f"  💰 Economies: ~{total_removed * 4} appels API evites (Firecrawl + LLM + OSINT + Scoring)")

    # Save
    output_path = Path(output_file) if output_file else input_path
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"  💾 Sauvegarde: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Deduplicate scraped leads before qualification')
    parser.add_argument('--input', required=True, help='Input JSON from scraping step')
    parser.add_argument('--output', help='Output JSON (default: overwrites input)')
    parser.add_argument('--no-hubspot', action='store_true', help='Skip HubSpot check (intra-batch only)')

    args = parser.parse_args()
    run_dedup(args.input, args.output, skip_hubspot=args.no_hubspot)
    save_tracker_snapshot("step1b_dedup")


if __name__ == '__main__':
    main()
