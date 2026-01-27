"""
STEP 2: Website Qualification with Firecrawl
Verifies if websites are active and extracts generic emails.

Usage:
    python 2_qualify_site.py --input .tmp/google_maps_results.json
"""

import os
import sys
import json
import requests
import argparse
import re
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

# Load environment variables
load_dotenv()

FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')


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


def check_ecommerce(text, url):
    """Check if site has e-commerce indicators"""
    ecommerce_keywords = [
        'panier', 'cart', 'checkout', 'commander', 'acheter',
        'shop', 'boutique', 'e-commerce', 'prix', 'ajouter au panier',
        'payment', 'paiement', 'shipping', 'livraison'
    ]

    text_lower = text.lower()
    has_ecommerce = any(keyword in text_lower for keyword in ecommerce_keywords)

    return 'Oui' if has_ecommerce else 'Non'


def is_manufacturer_or_seller(text):
    """
    Detect if the website is a manufacturer/seller vs a service provider

    Returns:
        'Manufacturer' if it's a manufacturer/seller
        'Service' if it's a service provider (spa experience, wellness center)
        'Unknown' if unclear
    """
    text_lower = text.lower()

    # Strong indicators of MANUFACTURER/SELLER (positive signals)
    manufacturer_keywords = [
        'fabricant', 'manufacturer', 'usine', 'production', 'fabrication',
        'vente', 'achat', 'acheter', 'catalogue', 'produits', 'modèles',
        'gamme', 'collection', 'série', 'références',
        'installation', 'garantie', 'sav', 'service après-vente',
        'distributeur', 'revendeur', 'showroom', 'magasin',
        'devis', 'prix €', 'tarifs', 'financement',
        # Brand names (jacuzzi/spa manufacturers)
        'jacuzzi', 'sundance', 'caldera', 'hot spring', 'arctic spas',
        'dimension one', 'marquis', 'bullfrog', 'coast spas',
        # Technical specifications
        'jets', 'pompe', 'filtration', 'capacité', 'dimensions',
        'modèle', 'version', 'équipement', 'options',
        # Commercial terms
        'livraison gratuite', 'paiement en plusieurs fois', 'stock',
        'commander en ligne', 'disponible', 'en promotion'
    ]

    # Strong indicators of SERVICE PROVIDER (negative signals)
    service_keywords = [
        'réservation', 'booking', 'réserver', 'séance', 'soin', 'massage',
        'détente', 'bien-être', 'relaxation', 'privatif', 'privé',
        'forfait', 'abonnement', 'prestation', 'expérience',
        'moment', 'parenthèse', 'échappée', 'escapade',
        'hammam', 'sauna infrarouge', 'balnéo', 'thalasso',
        'nos soins', 'nos prestations', 'nos forfaits',
        'heure', 'créneaux', 'disponibilités', 'planning',
        'accueil', 'reception', 'rendez-vous',
        'carte cadeau', 'bon cadeau', 'offrir',
        # Service-specific terms
        'duo', 'couple', 'romantique', 'amoureux',
        'zen', 'cocooning', 'sérénité', 'volupté',
        'espace détente', 'centre de bien-être', 'institut'
    ]

    # Count occurrences
    manufacturer_score = sum(1 for keyword in manufacturer_keywords if keyword in text_lower)
    service_score = sum(1 for keyword in service_keywords if keyword in text_lower)

    # Decision logic
    if manufacturer_score >= 3 and manufacturer_score > service_score:
        return 'Manufacturer'
    elif service_score >= 3 and service_score > manufacturer_score:
        return 'Service'
    elif manufacturer_score > service_score * 2:  # Strong manufacturer signal
        return 'Manufacturer'
    elif service_score > manufacturer_score * 2:  # Strong service signal
        return 'Service'
    else:
        return 'Unknown'


def qualify_website(url):
    """
    Use Firecrawl to scrape and qualify a website

    Args:
        url: Website URL to qualify

    Returns:
        Dictionary with qualification results
    """

    if not url or url == '':
        return {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown'
        }

    if not FIRECRAWL_API_KEY:
        raise ValueError("❌ FIRECRAWL_API_KEY not found in .env file")

    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'

    print(f"  🔍 Checking: {url}")

    try:
        # Firecrawl API endpoint
        api_url = "https://api.firecrawl.dev/v0/scrape"

        headers = {
            'Authorization': f'Bearer {FIRECRAWL_API_KEY}',
            'Content-Type': 'application/json'
        }

        payload = {
            'url': url,
            'pageOptions': {
                'onlyMainContent': True
            }
        }

        response = requests.post(api_url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            content = data.get('data', {}).get('markdown', '') or data.get('data', {}).get('content', '')

            # Extract emails
            emails = extract_emails(content)
            email = emails[0] if emails else ''

            # Check for e-commerce
            ecommerce = check_ecommerce(content, url)

            # Check if manufacturer or service provider
            business_type = is_manufacturer_or_seller(content)

            print(f"    ✅ Active | Email: {email or 'None'} | E-commerce: {ecommerce} | Type: {business_type}")

            return {
                    'Email_Generique': email,
                'Ecommerce': ecommerce,
                'Business_Type': business_type
            }

        else:
            print(f"    ⚠️  Website unreachable (Status: {response.status_code})")
            return {
                    'Email_Generique': '',
                'Ecommerce': 'Non',
                'Business_Type': 'Unknown'
            }

    except Exception as e:
        print(f"    ❌ Error: {str(e)[:50]}")
        return {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown'
        }


def process_leads(input_file):
    """Process all leads and qualify their websites"""

    # Load leads from JSON
    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"📋 Processing {len(leads)} leads...\n")

    qualified_leads = []
    filtered_count = 0

    for i, lead in enumerate(leads, 1):
        print(f"[{i}/{len(leads)}] {lead.get('Nom_Entreprise', 'Unknown')}")

        # Qualify the website
        qualification = qualify_website(lead.get('Site_Web', ''))

        # Update lead with qualification data
        lead.update(qualification)

        # CRITICAL FILTERS: Only keep leads with e-commerce AND manufacturer/seller type
        ecommerce = qualification.get('Ecommerce')
        business_type = qualification.get('Business_Type')

        if ecommerce == 'Oui' and business_type == 'Manufacturer':
            qualified_leads.append(lead)
        else:
            filtered_count += 1
            if ecommerce != 'Oui':
                print(f"    ⚠️  Filtered out: No e-commerce detected")
            elif business_type == 'Service':
                print(f"    ⚠️  Filtered out: Service provider (not manufacturer)")
            else:
                print(f"    ⚠️  Filtered out: Business type unclear")

        # Rate limiting - be nice to the API
        sleep(1)

    print(f"\n✅ Qualification complete: {len(qualified_leads)}/{len(leads)} manufacturer/seller leads")
    print(f"🚫 Filtered out: {filtered_count} leads (no e-commerce or service providers)")

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
    parser = argparse.ArgumentParser(description='Qualify websites using Firecrawl')
    parser.add_argument('--input', required=True, help='Input JSON file from scraping step')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return

    # Process leads
    qualified_leads = process_leads(input_path)

    # Save results
    output_path = save_results(qualified_leads)

    print(f"\n✅ Step 2 complete")
    print(f"📄 Output: {output_path}")
    print(f"\n➡️  Next step: Run enrichment with 5_enrich.py")


if __name__ == '__main__':
    main()
