"""
STEP 4: Contact Enrichment with Extended Waterfall Strategy
Uses a multi-stage approach to find decision maker info while minimizing API costs.

Waterfall Strategy (cheapest to most expensive):
1. OSINT with Serper (Free) - Find LinkedIn profile & name
2. Dropcontact (Freemium) - GDPR-compliant email finding
3. Pattern Matching with Hunter.io (Freemium) - Get email patterns
4. Apollo.io (Free tier) - Contact database lookup
5. Email Reconstruction - Combine data to build email

Usage:
    python enrich.py --input .tmp/qualified_leads.json
"""

import os
import sys
import json
import logging
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

# Logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

# Load environment variables
load_dotenv()

# Local imports
from api_utils import call_with_retry, sleep_between_calls, save_tracker_snapshot

SERPER_API_KEY = os.getenv('SERPER_API_KEY')
HUNTER_API_KEY = os.getenv('HUNTER_API_KEY')
DROPCONTACT_API_KEY = os.getenv('DROPCONTACT_API_KEY')
APOLLO_API_KEY = os.getenv('APOLLO_API_KEY')


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

    print(f"  Step 1/5: OSINT via Serper")

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

        response = call_with_retry(
            lambda: requests.post(url, headers=headers, data=payload, timeout=15),
            label="Serper OSINT"
        )

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


def step3_hunter_pattern(domain):
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

    print(f"  Step 3/5: Pattern matching via Hunter.io")

    try:
        url = f"https://api.hunter.io/v2/domain-search"

        params = {
            'domain': domain,
            'api_key': HUNTER_API_KEY,
            'limit': 5
        }

        response = call_with_retry(
            lambda: requests.get(url, params=params, timeout=15),
            label="Hunter domain-search",
            base_delay=3.0,
            max_delay=120.0
        )

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

        else:
            print(f"    ❌ Hunter API error after retries: {response.status_code}")
            return {'pattern': '', 'generic_email': '', 'confidence': 0}

    except Exception as e:
        print(f"    ❌ Hunter error: {str(e)[:50]}")
        return {'pattern': '', 'generic_email': '', 'confidence': 0}


def step2_dropcontact(first_name, last_name, company_name, website_url):
    """
    STEP 2: Dropcontact enrichment (GDPR-compliant)
    Finds professional email from name + company.

    Args:
        first_name: Contact first name
        last_name: Contact last name
        company_name: Company name
        website_url: Company website

    Returns:
        Dictionary with email and confidence
    """
    if not DROPCONTACT_API_KEY:
        return {'email': '', 'source': 'dropcontact_skipped'}

    if not first_name or not last_name:
        return {'email': '', 'source': 'dropcontact_no_name'}

    print(f"  Step 2/5: Dropcontact enrichment")

    try:
        response = call_with_retry(
            lambda: requests.post(
                "https://api.dropcontact.io/batch",
                headers={
                    "X-Access-Token": DROPCONTACT_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "data": [{
                        "first_name": first_name,
                        "last_name": last_name,
                        "company": company_name,
                        "website": website_url
                    }],
                    "siren": True,
                    "language": "fr"
                },
                timeout=30
            ),
            label="Dropcontact batch"
        )

        if response.status_code == 200:
            data = response.json()
            request_id = data.get('request_id', '')

            # Dropcontact is async — poll for results (max 60s)
            MAX_POLL_ATTEMPTS = 12
            if request_id:
                for attempt_num in range(MAX_POLL_ATTEMPTS):
                    sleep(5)
                    poll = call_with_retry(
                        lambda: requests.get(
                            f"https://api.dropcontact.io/batch/{request_id}",
                            headers={"X-Access-Token": DROPCONTACT_API_KEY},
                            timeout=15
                        ),
                        label="Dropcontact poll",
                        max_retries=2
                    )
                    if poll.status_code == 200:
                        poll_data = poll.json()
                        if poll_data.get('success') and poll_data.get('data'):
                            contact = poll_data['data'][0]
                            email = contact.get('email', [{}])
                            if isinstance(email, list) and email:
                                found_email = email[0].get('email', '')
                            elif isinstance(email, str):
                                found_email = email
                            else:
                                found_email = ''

                            if found_email:
                                print(f"    Found: {found_email}")
                                return {'email': found_email, 'source': 'dropcontact'}

                        if not poll_data.get('error') or poll_data.get('success'):
                            break  # Done but no email found
                else:
                    print(f"    ⚠️  Dropcontact polling exhausted after {MAX_POLL_ATTEMPTS * 5}s — no result")

            print(f"    No email found via Dropcontact")
            return {'email': '', 'source': 'dropcontact_empty'}

        else:
            print(f"    Dropcontact API error: {response.status_code}")
            return {'email': '', 'source': 'dropcontact_error'}

    except Exception as e:
        print(f"    Dropcontact error: {str(e)[:50]}")
        return {'email': '', 'source': 'dropcontact_error'}


def step4_apollo(first_name, last_name, company_name, domain):
    """
    STEP 4: Apollo.io contact lookup
    Searches Apollo's 275M+ contact database.

    Args:
        first_name: Contact first name
        last_name: Contact last name
        company_name: Company name
        domain: Company domain

    Returns:
        Dictionary with email, title, and source
    """
    if not APOLLO_API_KEY:
        return {'email': '', 'title': '', 'source': 'apollo_skipped'}

    print(f"  Step 4/5: Apollo.io lookup")

    try:
        # Search by domain and person name
        payload = {
            "api_key": APOLLO_API_KEY,
            "q_organization_domains": domain or '',
            "q_organization_name": company_name,
            "person_titles": ["CEO", "Directeur", "Gérant", "Founder", "Owner", "Dirigeant", "President"],
            "page": 1,
            "per_page": 3
        }

        # If we have a name, add it to narrow the search
        if first_name and last_name:
            payload["q_keywords"] = f"{first_name} {last_name}"

        response = call_with_retry(
            lambda: requests.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=15
            ),
            label="Apollo people-search",
            base_delay=5.0,
            max_delay=120.0
        )

        if response.status_code == 200:
            data = response.json()
            people = data.get('people', [])

            if people:
                person = people[0]
                email = person.get('email', '')
                title = person.get('title', '')
                name = person.get('name', '')

                if email:
                    print(f"    Found: {email} ({title or name})")
                    return {
                        'email': email,
                        'title': title,
                        'name': name,
                        'source': 'apollo'
                    }

            print(f"    No results in Apollo")
            return {'email': '', 'title': '', 'source': 'apollo_empty'}

        else:
            print(f"    Apollo API error after retries: {response.status_code}")
            return {'email': '', 'title': '', 'source': 'apollo_error'}

    except Exception as e:
        print(f"    Apollo error: {str(e)[:50]}")
        return {'email': '', 'title': '', 'source': 'apollo_error'}


def step5_reconstruct_email(name_info, hunter_info, domain):
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

    print(f"  Step 5/5: Email reconstruction")

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
    Main enrichment function using Extended Waterfall strategy.
    Tries cheapest sources first, stops as soon as a valid email is found.

    Waterfall order:
    1. OSINT via Serper (free) → name + LinkedIn
    2. Dropcontact (GDPR) → email from name+company
    3. Hunter.io (pattern) → email pattern
    4. Apollo.io (database) → direct email lookup
    5. Reconstruction → build email from pattern + name

    Args:
        company_name: Name of the company
        website_url: Company website URL

    Returns:
        Dictionary with enriched contact data
    """

    # Extract domain
    domain = extract_domain(website_url)

    # STEP 1: OSINT with Serper (always run for name + LinkedIn)
    name_info = step1_osint_serper(company_name)
    first_name = name_info.get('first_name', '')
    last_name = name_info.get('last_name', '')

    sleep_between_calls(1.0, label="Serper→Dropcontact")

    # STEP 2: Dropcontact (if we have a name — cheapest email provider)
    email_found = ''
    email_source = 'not_found'

    if first_name and last_name:
        dc_result = step2_dropcontact(first_name, last_name, company_name, website_url)
        if dc_result['email']:
            email_found = dc_result['email']
            email_source = dc_result['source']

    # STEP 3: Hunter.io pattern (if Dropcontact didn't find email)
    hunter_info = {'pattern': '', 'generic_email': '', 'confidence': 0}
    if not email_found and domain:
        hunter_info = step3_hunter_pattern(domain)
        sleep_between_calls(1.0, label="Hunter→reconstruction")

        # Try reconstruction immediately if we have name + pattern
        if hunter_info['pattern'] and first_name and last_name:
            recon = step5_reconstruct_email(name_info, hunter_info, domain)
            if recon['email']:
                email_found = recon['email']
                email_source = recon['email_source']

        # Try generic email from Hunter
        if not email_found and hunter_info['generic_email']:
            email_found = hunter_info['generic_email']
            email_source = 'hunter_generic'

    # STEP 4: Apollo.io (if still no email)
    if not email_found:
        apollo_result = step4_apollo(first_name, last_name, company_name, domain)
        if apollo_result['email']:
            email_found = apollo_result['email']
            email_source = apollo_result['source']
            # Apollo may also provide a better title
            if apollo_result.get('title') and not name_info.get('title'):
                name_info['title'] = apollo_result['title']

    # Build final result
    result = {
        'Email_Decideur': email_found,
        'Email_Source': email_source,
        'Nom_Decideur': name_info['full_name'],
        'Poste_Decideur': name_info['title'],
        'LinkedIn_URL': name_info['linkedin_url']
    }

    return result


def enrich_leads(input_file):
    """Enrich all leads using Extended Waterfall strategy"""

    # Load qualified leads
    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"Enriching {len(leads)} leads with Extended Waterfall (5-step)...\n")

    # Track statistics by source
    stats = {
        'total': len(leads),
        'enriched': 0,
        'dropcontact': 0,
        'hunter_generic': 0,
        'reconstructed': 0,
        'apollo': 0,
        'not_found': 0,
        'skipped': 0
    }

    for i, lead in enumerate(leads, 1):
        company_name = lead.get('Nom_Entreprise', '')
        website_url = lead.get('Site_Web', '')

        print(f"[{i}/{len(leads)}] {company_name}")

        # Only enrich if website exists
        if website_url:
            enrichment = enrich_lead(company_name, website_url)
            lead.update(enrichment)

            # Track statistics by source
            source = enrichment.get('Email_Source', 'not_found')
            if enrichment['Email_Decideur']:
                stats['enriched'] += 1
                if source == 'dropcontact':
                    stats['dropcontact'] += 1
                elif source == 'hunter_generic':
                    stats['hunter_generic'] += 1
                elif source == 'reconstructed':
                    stats['reconstructed'] += 1
                elif source == 'apollo':
                    stats['apollo'] += 1
            else:
                stats['not_found'] += 1

            # Rate limiting between companies
            sleep_between_calls(1.5, label="inter-company")
        else:
            print(f"    Skipping (no website)")
            stats['skipped'] += 1

    print(f"\nEnrichment complete: {stats['enriched']}/{stats['total']} contacts enriched")
    print(f"  Breakdown by source:")
    print(f"    Dropcontact: {stats['dropcontact']}")
    print(f"    Hunter (generic): {stats['hunter_generic']}")
    print(f"    Hunter (reconstructed): {stats['reconstructed']}")
    print(f"    Apollo: {stats['apollo']}")
    print(f"    Not found: {stats['not_found']}")
    print(f"    Skipped (no website): {stats['skipped']}")

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
    print(f"API Keys status:")
    print(f"   - SERPER_API_KEY: {'Configured' if SERPER_API_KEY else 'Missing'}")
    print(f"   - DROPCONTACT_API_KEY: {'Configured' if DROPCONTACT_API_KEY else 'Skipped'}")
    print(f"   - HUNTER_API_KEY: {'Configured' if HUNTER_API_KEY else 'Skipped'}")
    print(f"   - APOLLO_API_KEY: {'Configured' if APOLLO_API_KEY else 'Skipped'}")
    print()

    # Enrich leads
    enriched_leads = enrich_leads(input_path)

    # Save results
    output_path = save_results(enriched_leads)

    print(f"\nStep 4 complete")
    print(f"Output: {output_path}")
    print(f"\nNext step: Verify emails with verify_email.py")

    save_tracker_snapshot("step3_enrich")


if __name__ == '__main__':
    main()
