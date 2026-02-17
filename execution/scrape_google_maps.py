"""
STEP 1: Google Maps Scraping
Searches for businesses on Google Maps using Serper API and extracts basic information.

Usage:
    python scrape_google_maps.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
"""

import os
import sys
import json
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

# Load environment variables
load_dotenv()

SERPER_API_KEY = os.getenv('SERPER_API_KEY')


def search_google_maps(query, location, max_results=50):
    """
    Search Google Maps using Serper API

    Args:
        query: Business type to search for (e.g., "Cuisinistes")
        location: Geographic location (e.g., "Bordeaux")
        max_results: Maximum number of results to return

    Returns:
        List of business dictionaries
    """

    if not SERPER_API_KEY:
        raise ValueError("❌ SERPER_API_KEY not found in .env file")

    print(f"🔍 Searching for: {query} in {location}")

    url = "https://google.serper.dev/maps"

    payload = json.dumps({
        "q": f"{query} {location}",
        "num": min(max_results, 100)  # Serper max is 100 per request
    })

    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, headers=headers, data=payload, timeout=30)
        response.raise_for_status()
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
                'Ville': location,
                'Code_Postal': extract_postal_code(address),
                'Pays': extract_country(address),
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

    except requests.exceptions.RequestException as e:
        print(f"❌ Error during API request: {e}")
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

    args = parser.parse_args()

    # Search Google Maps
    leads = search_google_maps(args.industry, args.location, args.max_leads)

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


if __name__ == '__main__':
    main()
