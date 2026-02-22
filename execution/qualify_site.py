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
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')


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


def classify_with_llm(text, url, industry=''):
    """
    Use Claude Haiku to classify the website semantically.
    Determines business type and e-commerce capability.

    Args:
        text: Website content (markdown from Firecrawl)
        url: Website URL
        industry: Industry context from search query

    Returns:
        Dictionary with:
            - business_type: 'Manufacturer' | 'Service' | 'Unknown'
            - ecommerce: 'Oui' | 'Non'
            - confidence: int (0-100)
            - justification: str
            - tech_stack: str (detected e-commerce platform)
    """
    if not ANTHROPIC_API_KEY:
        print(f"    ANTHROPIC_API_KEY not configured - falling back to keyword analysis")
        return _fallback_keyword_classification(text, url)

    # Truncate content to avoid excessive token usage (Haiku is cheap but let's be efficient)
    content_truncated = text[:4000] if len(text) > 4000 else text

    prompt = f"""Analyse ce site web et reponds UNIQUEMENT en JSON valide (pas de markdown, pas de texte avant/apres).

URL: {url}
Industrie recherchee: {industry}

Contenu du site:
{content_truncated}

Reponds avec ce JSON exact:
{{
  "business_type": "Manufacturer" ou "Service" ou "Unknown",
  "ecommerce": "Oui" ou "Non",
  "confidence": 0-100,
  "justification": "1 phrase explicative",
  "tech_stack": "Shopify/WooCommerce/PrestaShop/Magento/custom/unknown"
}}

Regles de classification:
- "Manufacturer" = fabrique, vend, distribue ou revend des PRODUITS physiques (fabricant, revendeur, distributeur, showroom, magasin en ligne). Inclut les sites qui vendent des produits meme s'ils utilisent du vocabulaire marketing lifestyle/bien-etre.
- "Service" = propose des SERVICES (location, reservation, seances, soins, experiences, wellness center, spa privatif). Le client vient utiliser un service, il n'achete PAS un produit physique a emporter/livrer.
- "Unknown" = impossible a determiner
- "ecommerce" = "Oui" si le site permet d'acheter en ligne (panier, checkout, commander, prix affiches avec possibilite d'achat)
- "tech_stack" = plateforme e-commerce detectee dans le contenu (Shopify, WooCommerce, PrestaShop, etc.) ou "unknown" si non detectable"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get('content', [{}])[0].get('text', '{}')

            # Parse JSON response (handle potential markdown wrapping)
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[-1].rsplit('```', 1)[0]

            result = json.loads(content)

            return {
                'business_type': result.get('business_type', 'Unknown'),
                'ecommerce': result.get('ecommerce', 'Non'),
                'confidence': result.get('confidence', 0),
                'justification': result.get('justification', ''),
                'tech_stack': result.get('tech_stack', 'unknown')
            }

        else:
            print(f"    LLM API error: {response.status_code} - falling back to keywords")
            return _fallback_keyword_classification(text, url)

    except json.JSONDecodeError:
        print(f"    LLM response not valid JSON - falling back to keywords")
        return _fallback_keyword_classification(text, url)
    except Exception as e:
        print(f"    LLM error: {str(e)[:50]} - falling back to keywords")
        return _fallback_keyword_classification(text, url)


def _fallback_keyword_classification(text, url):
    """
    Fallback keyword-based classification if LLM is unavailable.
    Uses the original keyword matching logic.
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


def qualify_website(url, industry=''):
    """
    Use Firecrawl to scrape and LLM to qualify a website

    Args:
        url: Website URL to qualify
        industry: Industry context from search query

    Returns:
        Dictionary with qualification results
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

    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'

    print(f"  Checking: {url}")

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

            # LLM-based classification (with keyword fallback)
            classification = classify_with_llm(content, url, industry)

            ecommerce = classification['ecommerce']
            business_type = classification['business_type']
            confidence = classification['confidence']
            justification = classification['justification']
            tech_stack = classification['tech_stack']

            print(f"    Active | Email: {email or 'None'} | E-commerce: {ecommerce} | Type: {business_type} ({confidence}%)")
            if justification:
                print(f"    Reason: {justification}")

            return {
                'Email_Generique': email,
                'Ecommerce': ecommerce,
                'Business_Type': business_type,
                'Confidence': confidence,
                'Justification': justification,
                'Tech_Stack': tech_stack
            }

        else:
            print(f"    Website unreachable (Status: {response.status_code})")
            return {
                'Email_Generique': '',
                'Ecommerce': 'Non',
                'Business_Type': 'Unknown',
                'Confidence': 0,
                'Justification': '',
                'Tech_Stack': 'unknown'
            }

    except Exception as e:
        print(f"    Error: {str(e)[:50]}")
        return {
            'Email_Generique': '',
            'Ecommerce': 'Non',
            'Business_Type': 'Unknown',
            'Confidence': 0,
            'Justification': '',
            'Tech_Stack': 'unknown'
        }


def process_leads(input_file, industry=''):
    """Process all leads and qualify their websites

    Args:
        input_file: Path to JSON file with scraped leads
        industry: Industry context for LLM classification
    """

    # Load leads from JSON
    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"Processing {len(leads)} leads (LLM classification)...\n")

    qualified_leads = []
    filtered_count = 0

    for i, lead in enumerate(leads, 1):
        print(f"[{i}/{len(leads)}] {lead.get('Nom_Entreprise', 'Unknown')}")

        # Qualify the website with LLM classification
        qualification = qualify_website(lead.get('Site_Web', ''), industry=industry)

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
                print(f"    Filtered out: No e-commerce detected")
            elif business_type == 'Service':
                print(f"    Filtered out: Service provider (not manufacturer)")
            else:
                print(f"    Filtered out: Business type unclear")

        # Rate limiting - be nice to the APIs
        sleep(1)

    print(f"\nQualification complete: {len(qualified_leads)}/{len(leads)} manufacturer/seller leads")
    print(f"Filtered out: {filtered_count} leads (no e-commerce or service providers)")

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
    parser = argparse.ArgumentParser(description='Qualify websites using Firecrawl + LLM')
    parser.add_argument('--input', required=True, help='Input JSON file from scraping step')
    parser.add_argument('--industry', default='', help='Industry context for better LLM classification')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    # Check API keys
    print(f"API Keys status:")
    print(f"   - FIRECRAWL_API_KEY: {'Configured' if FIRECRAWL_API_KEY else 'Missing'}")
    print(f"   - ANTHROPIC_API_KEY: {'Configured (LLM mode)' if ANTHROPIC_API_KEY else 'Missing (keyword fallback)'}")
    print()

    # Process leads
    qualified_leads = process_leads(input_path, industry=args.industry)

    # Save results
    output_path = save_results(qualified_leads)

    print(f"\nStep 2 complete")
    print(f"Output: {output_path}")
    print(f"\nNext step: Run enrichment with enrich.py")


if __name__ == '__main__':
    main()
