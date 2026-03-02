"""
STEP 1: Google Maps Scraping
Searches for businesses on Google Maps using Serper API and extracts basic information.

Usage:
    python scrape_google_maps.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
"""

import os
import sys
import json
import logging
import requests
import argparse
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

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
from api_utils import call_with_retry, save_tracker_snapshot

SERPER_API_KEY = os.getenv('SERPER_API_KEY')


def _build_manufacturer_query(industry, country):
    """
    Build a search query that targets manufacturers/constructors who sell products.
    Automatically prepends 'fabricant' to avoid returning service providers.
    """
    industry_lower = industry.lower()
    already_targeted = any(kw in industry_lower for kw in [
        'fabricant', 'constructeur', 'manufacturer', 'vendeur', 'vente',
        'distributeur', 'revendeur', 'fournisseur'
    ])
    if already_targeted:
        return f"{industry} {country}"
    return f"fabricant {industry} {country}"


def search_google_maps(query, location, max_results=50, query_override=None):
    """
    Search Google Maps using Serper API

    Args:
        query: Business type to search for (e.g., "Cuisinistes")
        location: Country (e.g., "France")
        max_results: Maximum number of results to return
        query_override: Raw search query (skips auto-build if provided)

    Returns:
        List of business dictionaries
    """

    if not SERPER_API_KEY:
        raise ValueError("❌ SERPER_API_KEY not found in .env file")

    search_query = query_override if query_override else _build_manufacturer_query(query, location)
    print(f"🔍 Searching for: {search_query}")

    url = "https://google.serper.dev/maps"

    payload = json.dumps({
        "q": search_query,
        "num": min(max_results, 100)
    })

    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        response = call_with_retry(
            lambda: requests.post(url, headers=headers, data=payload, timeout=30),
            label="Serper Maps"
        )

        if response.status_code != 200:
            print(f"❌ Serper API error: {response.status_code}")
            return []

        data = response.json()

        places = data.get('places', [])

        print(f"✅ Found {len(places)} results")

        # Transform results to our format
        leads = []
        for place in places[:max_results]:
            address = place.get('address', '')
            lead = {
                'Nom_Entreprise': place.get('title', ''),
                'Adresse': address,
                'Code_Postal': extract_postal_code(address),
                'Pays': location,
                'Site_Web': place.get('website', ''),
                'Tel_Standard': place.get('phoneNumber', ''),
                'Date_Ajout': datetime.now().strftime('%Y-%m-%d'),
                # Fields to be enriched later
                'Email_Generique': '',
                'Email_Decideur': '',
                'Nom_Decideur': '',
                'Poste_Decideur': '',
                'LinkedIn_URL': '',
                'Ecommerce': '',
            }
            leads.append(lead)

        return leads

    except Exception as e:
        print(f"❌ Error during API request: {e}")
        return []


def search_google_web(query, location, max_results=20, query_override=None):
    """
    Search Google Web (organic results) via Serper /search endpoint.
    Captures manufacturers that don't have a Google Maps listing
    (e.g. large multi-product companies like Novellini).

    Returns leads in the same format as search_google_maps().
    """
    if not SERPER_API_KEY:
        raise ValueError("SERPER_API_KEY not found in .env file")

    search_query = query_override if query_override else _build_manufacturer_query(query, location)
    print(f"🌐 Web search: {search_query}")

    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": search_query,
        "gl": "fr",
        "hl": "fr",
        "num": min(max_results, 100)
    })
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        response = call_with_retry(
            lambda: requests.post(url, headers=headers, data=payload, timeout=30),
            label="Serper Web"
        )
        if response.status_code != 200:
            print(f"❌ Serper Web API error: {response.status_code}")
            return []

        data = response.json()
        organic = data.get('organic', [])
        print(f"✅ Found {len(organic)} web results")

        leads = []
        seen_domains = set()
        for item in organic:
            link = item.get('link', '')
            if not link:
                continue

            from urllib.parse import urlparse
            parsed = urlparse(link)
            domain = parsed.netloc.lower().replace('www.', '')

            # Skip duplicates, social media, directories, and marketplaces
            skip_domains = [
                'facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com',
                'youtube.com', 'pinterest.com', 'tiktok.com',
                'pagesjaunes.fr', 'societe.com', 'kompass.com', 'europages.fr',
                'amazon.fr', 'cdiscount.com', 'leboncoin.fr', 'manomano.fr',
                'wikipedia.org', 'google.com',
            ]
            if domain in seen_domains or any(sd in domain for sd in skip_domains):
                continue
            seen_domains.add(domain)

            title = item.get('title', '')
            # Clean title: remove common suffixes
            for suffix in [' - Accueil', ' | Accueil', ' - Home', ' | Home', ' - Site officiel']:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]

            lead = {
                'Nom_Entreprise': title.strip(),
                'Adresse': '',
                'Code_Postal': '',
                'Pays': location,
                'Site_Web': f"{parsed.scheme}://{parsed.netloc}",
                'Tel_Standard': '',
                'Date_Ajout': datetime.now().strftime('%Y-%m-%d'),
                'Email_Generique': '',
                'Email_Decideur': '',
                'Nom_Decideur': '',
                'Poste_Decideur': '',
                'LinkedIn_URL': '',
                'Ecommerce': '',
                '_source': 'web',
            }
            leads.append(lead)

        return leads

    except Exception as e:
        print(f"❌ Web search error: {e}")
        return []


def extract_postal_code(address):
    """Extract postal code from address string (French format)"""
    import re
    match = re.search(r'\b\d{5}\b', address)
    return match.group(0) if match else ''


def extract_country(address):
    """Extract country from address string"""
    if not address:
        return ''

    # Common country names and patterns
    # Split by comma and take the last part (usually country)
    parts = address.split(',')
    if len(parts) > 0:
        country = parts[-1].strip()
        # Clean up common patterns
        country = country.split()[-1] if country else ''
        return country
    return ''


def save_to_json(leads, filename='google_maps_results.json'):
    """Save leads to JSON file in .tmp folder"""
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    tmp_dir.mkdir(exist_ok=True)

    output_path = tmp_dir / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"💾 Saved {len(leads)} leads to {output_path}")
    return output_path


def clean_industry_name(industry_raw):
    """
    Clean and simplify the industry name to 1-2 keywords.

    Examples:
        "vente jacuzzi spa fabricant" -> "jacuzzi/spa"
        "fabricant cheminées vente" -> "cheminées"
        "spa jacuzzi" -> "spa/jacuzzi"
    """
    # Words to remove (generic terms, not industry-specific)
    words_to_remove = [
        'fabricant', 'fabricants', 'manufacturer', 'vente', 'ventes',
        'achat', 'magasin', 'boutique', 'shop', 'store',
        'distributeur', 'revendeur', 'vendeur', 'seller',
        'france', 'paris', 'lyon', 'bordeaux', 'marseille',
        'et', 'de', 'du', 'des', 'la', 'le', 'les', 'en', 'à', 'a'
    ]

    # Split and clean
    words = industry_raw.lower().split()

    # Filter out generic words
    keywords = [word for word in words if word not in words_to_remove]

    # Take max 2 keywords
    if len(keywords) == 0:
        # If all words were filtered, take first significant word from original
        for word in words:
            if len(word) > 3 and word not in ['vente', 'achat']:
                return word
        return industry_raw.split()[0] if industry_raw.split() else industry_raw
    elif len(keywords) == 1:
        return keywords[0]
    else:
        # Return max 2 keywords separated by /
        return '/'.join(keywords[:2])


def main():
    parser = argparse.ArgumentParser(description='Scrape Google Maps for business leads')
    parser.add_argument('--industry', required=True, help='Industry/business type (e.g., "Cuisinistes")')
    parser.add_argument('--location', required=True, help='Location to search (e.g., "Bordeaux")')
    parser.add_argument('--max_leads', type=int, default=50, help='Maximum number of leads to fetch')
    parser.add_argument('--query-override', help='Use this exact search query instead of auto-building')
    parser.add_argument('--source', choices=['maps', 'web'], default='maps', help='Search source: maps (default) or web')

    args = parser.parse_args()

    if args.source == 'web':
        leads = search_google_web(args.industry, args.location, args.max_leads, query_override=args.query_override)
    else:
        leads = search_google_maps(args.industry, args.location, args.max_leads, query_override=args.query_override)

    if leads:
        # Add cleaned industry to each lead
        cleaned_industry = clean_industry_name(args.industry)
        for lead in leads:
            lead['Industrie'] = cleaned_industry

        # Save to JSON
        output_path = save_to_json(leads)
        print(f"\n✅ Step 1 complete: {len(leads)} leads scraped")
        print(f"📄 Output: {output_path}")
        print(f"\n➡️  Next step: Run qualification with qualify_site.py")
    else:
        print("❌ No leads found")

    save_tracker_snapshot("step1_scrape")


if __name__ == '__main__':
    main()
