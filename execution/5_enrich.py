"""
STEP 4: Contact Enrichment with Waterfall Strategy
Uses a multi-stage approach to find decision maker info while minimizing API costs.

Waterfall Strategy:
1. OSINT with Serper (Free) - Find LinkedIn profile & name
2. Pattern Matching with Hunter.io (Freemium) - Get email patterns
3. Email Reconstruction - Combine data to build email

Usage:
    python 5_enrich.py --input .tmp/qualified_leads.json
"""

import os
import sys
import json
import requests
import argparse
import re
from pathlib import Path
from dotenv import load_dotenv

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
from time import sleep
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

SERPER_API_KEY = os.getenv('SERPER_API_KEY')
HUNTER_API_KEY = os.getenv('HUNTER_API_KEY')


def extract_domain(url):
    """Extract clean domain from URL"""
    if not url:
        return None

    # Remove protocol
    clean_url = url.replace('https://', '').replace('http://', '').replace('www.', '')
    # Get just the domain
    domain = clean_url.split('/')[0]
    return domain


def parse_linkedin_name(linkedin_url, snippet=''):
    """
    Extract name from LinkedIn URL and/or search snippet

    Args:
        linkedin_url: LinkedIn profile URL
        snippet: Search result snippet text

    Returns:
        Dictionary with first_name, last_name, full_name
    """
    first_name = ''
    last_name = ''

    # Try to extract from URL: linkedin.com/in/jean-dupont-123
    if linkedin_url:
        match = re.search(r'/in/([^/\?]+)', linkedin_url)
        if match:
            slug = match.group(1)
            # Remove numbers and split
            name_parts = re.sub(r'-\d+.*$', '', slug).split('-')
            if len(name_parts) >= 2:
                first_name = name_parts[0].capitalize()
                last_name = name_parts[-1].capitalize()

    # Try to extract from snippet text
    if not first_name and snippet:
        # Look for patterns like "Jean Dupont - Directeur"
        name_match = re.search(r'^([A-ZÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇ][a-zàâäéèêëïîôöùûüÿç]+(?:\s+[A-ZÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇ][a-zàâäéèêëïîôöùûüÿç]+)+)', snippet)
        if name_match:
            full_name = name_match.group(1).strip()
            parts = full_name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = ' '.join(parts[1:])

    full_name = f"{first_name} {last_name}".strip()

    return {
        'first_name': first_name,
        'last_name': last_name,
        'full_name': full_name
    }


def step1_osint_serper(company_name):
    """
    STEP 1: OSINT with Serper (Free)
    Find decision maker LinkedIn profile via Google search

    Args:
        company_name: Name of the company

    Returns:
        Dictionary with name, title, linkedin_url
    """

    if not SERPER_API_KEY:
        print(f"    ⚠️  SERPER_API_KEY not configured - skipping OSINT")
        return {'full_name': '', 'first_name': '', 'last_name': '', 'title': '', 'linkedin_url': ''}

    print(f"  🔍 Step 1/3: OSINT via Serper")

    # Build search query for LinkedIn profiles
    query = f'site:linkedin.com/in "Directeur" OR "Gérant" OR "CEO" OR "Dirigeant" "{company_name}"'

    try:
        url = "https://google.serper.dev/search"

        payload = json.dumps({
            "q": query,
            "num": 3  # Get top 3 results
        })

        headers = {
            'X-API-KEY': SERPER_API_KEY,
            'Content-Type': 'application/json'
        }

        response = requests.post(url, headers=headers, data=payload, timeout=15)

        if response.status_code == 200:
            data = response.json()
            organic_results = data.get('organic', [])

            if organic_results:
                # Get first LinkedIn result
                result = organic_results[0]
                linkedin_url = result.get('link', '')
                snippet = result.get('snippet', '')
                title_text = result.get('title', '')

                # Extract name from URL and snippet
                name_info = parse_linkedin_name(linkedin_url, title_text + ' ' + snippet)

                # Extract title from snippet
                title = ''
                for job_title in ['CEO', 'Directeur', 'Gérant', 'Dirigeant', 'President', 'Fondateur', 'Founder', 'Manager']:
                    if job_title.lower() in snippet.lower() or job_title.lower() in title_text.lower():
                        title = job_title
                        break

                if name_info['full_name']:
                    print(f"    ✅ Found: {name_info['full_name']} ({title})")
                else:
                    print(f"    ⚠️  Found LinkedIn profile but couldn't parse name")

                return {
                    'full_name': name_info['full_name'],
                    'first_name': name_info['first_name'],
                    'last_name': name_info['last_name'],
                    'title': title,
                    'linkedin_url': linkedin_url
                }
            else:
                print(f"    ⚠️  No LinkedIn profiles found")
                return {'full_name': '', 'first_name': '', 'last_name': '', 'title': '', 'linkedin_url': ''}

        else:
            print(f"    ❌ Serper API error: {response.status_code}")
            return {'full_name': '', 'first_name': '', 'last_name': '', 'title': '', 'linkedin_url': ''}

    except Exception as e:
        print(f"    ❌ Serper error: {str(e)[:50]}")
        return {'full_name': '', 'first_name': '', 'last_name': '', 'title': '', 'linkedin_url': ''}


def step2_hunter_pattern(domain):
    """
    STEP 2: Pattern Matching with Hunter.io (Freemium)
    Get email pattern and generic emails from company domain

    Args:
        domain: Company domain (e.g., "company.com")

    Returns:
        Dictionary with pattern, generic_email, confidence
    """

    if not HUNTER_API_KEY:
        print(f"    ⚠️  HUNTER_API_KEY not configured - skipping Hunter")
        return {'pattern': '', 'generic_email': '', 'confidence': 0}

    if not domain:
        print(f"    ⚠️  No domain available - skipping Hunter")
        return {'pattern': '', 'generic_email': '', 'confidence': 0}

    print(f"  🔍 Step 2/3: Pattern matching via Hunter.io")

    try:
        url = f"https://api.hunter.io/v2/domain-search"

        params = {
            'domain': domain,
            'api_key': HUNTER_API_KEY,
            'limit': 5
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            domain_data = data.get('data', {})

            # Get email pattern
            pattern = domain_data.get('pattern', '')  # e.g., "{first}.{last}"

            # Get generic email if available
            emails = domain_data.get('emails', [])
            generic_email = ''

            for email_obj in emails:
                email = email_obj.get('value', '')
                email_type = email_obj.get('type', '')

                # Look for generic emails
                if email_type == 'generic' or any(keyword in email.lower() for keyword in ['contact', 'info', 'hello', 'bonjour']):
                    generic_email = email
                    break

            confidence = domain_data.get('pattern_confidence', 0)

            if pattern:
                print(f"    ✅ Pattern: {pattern} (confidence: {confidence}%)")
            if generic_email:
                print(f"    ✅ Generic email: {generic_email}")

            if not pattern and not generic_email:
                print(f"    ⚠️  No pattern or emails found")

            return {
                'pattern': pattern,
                'generic_email': generic_email,
                'confidence': confidence
            }

        elif response.status_code == 429:
            print(f"    ⚠️  Hunter rate limit reached")
            return {'pattern': '', 'generic_email': '', 'confidence': 0}

        else:
            print(f"    ❌ Hunter API error: {response.status_code}")
            return {'pattern': '', 'generic_email': '', 'confidence': 0}

    except Exception as e:
        print(f"    ❌ Hunter error: {str(e)[:50]}")
        return {'pattern': '', 'generic_email': '', 'confidence': 0}


def step3_reconstruct_email(name_info, hunter_info, domain):
    """
    STEP 3: Email Reconstruction (The Synthesis)
    Combine OSINT and Hunter data to build the most likely email

    Args:
        name_info: Dict from step1 (first_name, last_name, etc.)
        hunter_info: Dict from step2 (pattern, generic_email, etc.)
        domain: Company domain

    Returns:
        Dictionary with email and email_source
    """

    print(f"  🔍 Step 3/3: Email reconstruction")

    first = name_info.get('first_name', '').lower()
    last = name_info.get('last_name', '').lower()
    pattern = hunter_info.get('pattern', '')
    generic = hunter_info.get('generic_email', '')

    # CAS A: Best case - We have name AND pattern
    if first and last and pattern and domain:
        # Build email from pattern
        email = pattern.replace('{first}', first)
        email = email.replace('{last}', last)
        email = email.replace('{f}', first[0] if first else '')
        email = email.replace('{l}', last[0] if last else '')
        email = f"{email}@{domain}"

        # Clean up
        email = email.replace('..', '.').replace('--', '-').replace('__', '_')

        print(f"    ✅ Reconstructed: {email} (from pattern)")
        return {'email': email, 'email_source': 'reconstructed'}

    # CAS B: Medium case - We have generic email from Hunter
    if generic:
        print(f"    ✅ Using generic: {generic}")
        return {'email': generic, 'email_source': 'hunter_generic'}

    # CAS C: No reliable email found - Do NOT guess
    print(f"    ❌ Email not found (no pattern, no generic)")
    return {'email': '', 'email_source': 'not_found'}


def enrich_lead(company_name, website_url):
    """
    Main enrichment function using Waterfall strategy

    Args:
        company_name: Name of the company
        website_url: Company website URL

    Returns:
        Dictionary with enriched contact data
    """

    # Extract domain
    domain = extract_domain(website_url)

    # STEP 1: OSINT with Serper
    name_info = step1_osint_serper(company_name)

    # STEP 2: Hunter.io pattern matching (only if domain available)
    hunter_info = step2_hunter_pattern(domain) if domain else {'pattern': '', 'generic_email': '', 'confidence': 0}

    # Rate limiting between API calls
    sleep(1)

    # STEP 3: Email reconstruction
    email_info = step3_reconstruct_email(name_info, hunter_info, domain)

    # Build final result
    result = {
        'Email_Decideur': email_info['email'],
        'Nom_Decideur': name_info['full_name'],
        'Poste_Decideur': name_info['title'],
        'LinkedIn_URL': name_info['linkedin_url']
    }

    return result


def enrich_leads(input_file):
    """Enrich all leads using Waterfall strategy"""

    # Load qualified leads
    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"📋 Enriching {len(leads)} leads with Waterfall strategy...\n")

    enriched_count = 0
    reconstructed_count = 0
    generic_count = 0
    not_found_count = 0

    for i, lead in enumerate(leads, 1):
        company_name = lead.get('Nom_Entreprise', '')
        website_url = lead.get('Site_Web', '')

        print(f"[{i}/{len(leads)}] {company_name}")

        # Only enrich if website is active or exists
        if website_url:
            enrichment = enrich_lead(company_name, website_url)
            lead.update(enrichment)

            # Track statistics
            if enrichment['Email_Decideur']:
                enriched_count += 1

            # Rate limiting between companies
            sleep(2)
        else:
            print(f"    ⏭️  Skipping (no website)")

    print(f"\n✅ Enrichment complete: {enriched_count}/{len(leads)} contacts enriched")

    return leads


def save_results(leads, output_filename='enriched_leads.json'):
    """Save enriched leads to JSON"""
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    output_path = tmp_dir / output_filename

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"💾 Saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Enrich contacts with Waterfall strategy (Serper + Hunter.io)')
    parser.add_argument('--input', required=True, help='Input JSON file from qualification step')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return

    # Check API keys
    print(f"🔑 API Keys status:")
    print(f"   - SERPER_API_KEY: {'✅ Configured' if SERPER_API_KEY else '❌ Missing'}")
    print(f"   - HUNTER_API_KEY: {'✅ Configured' if HUNTER_API_KEY else '⚠️  Optional (will skip if missing)'}")
    print()

    # Enrich leads
    enriched_leads = enrich_leads(input_path)

    # Save results
    output_path = save_results(enriched_leads)

    print(f"\n✅ Step 4 complete")
    print(f"📄 Output: {output_path}")
    print(f"\n➡️  Next step: Save to Excel with save_to_excel.py")


if __name__ == '__main__':
    main()
