"""
STEP 4b: Email Verification
Verifies enriched emails using MillionVerifier API before HubSpot sync.
Filters out invalid emails to protect sender reputation.

Usage:
    python verify_email.py --input .tmp/enriched_leads.json
"""

import os
import sys
import json
import logging
import requests
import argparse
from pathlib import Path
from dotenv import load_dotenv
from time import sleep

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

# Load environment variables
load_dotenv()

# Local imports
from api_utils import call_with_retry, save_tracker_snapshot

MILLIONVERIFIER_API_KEY = os.getenv('MILLIONVERIFIER_API_KEY')


def verify_single_email(email):
    """
    Verify a single email address via MillionVerifier API

    Args:
        email: Email address to verify

    Returns:
        Dictionary with:
            - is_valid: bool
            - result: 'ok' | 'catch_all' | 'unknown' | 'invalid' | 'disposable'
            - quality_score: int (0-100)
    """
    if not email:
        return {'is_valid': False, 'result': 'empty', 'quality_score': 0}

    if not MILLIONVERIFIER_API_KEY:
        # If no API key, pass through (don't block pipeline)
        print(f"    MILLIONVERIFIER_API_KEY not configured - skipping verification")
        return {'is_valid': True, 'result': 'skipped', 'quality_score': 50}

    try:
        url = "https://api.millionverifier.com/api/v3/"
        params = {
            'api': MILLIONVERIFIER_API_KEY,
            'email': email
        }

        response = call_with_retry(
            lambda: requests.get(url, params=params, timeout=15),
            label="MillionVerifier"
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get('result', 'unknown')
            quality_score = data.get('quality_score', 0)

            # Classification:
            # 'ok' = valid, deliverable
            # 'catch_all' = domain accepts all emails (risky but possible)
            # 'unknown' = could not verify (SMTP timeout, etc.)
            # 'invalid' = mailbox doesn't exist
            # 'disposable' = temporary email
            is_valid = result in ('ok', 'catch_all')

            return {
                'is_valid': is_valid,
                'result': result,
                'quality_score': quality_score
            }

        else:
            print(f"    API error: {response.status_code}")
            # On API error, don't block - mark as unknown
            return {'is_valid': True, 'result': 'api_error', 'quality_score': 30}

    except Exception as e:
        print(f"    Verification error: {str(e)[:50]}")
        return {'is_valid': True, 'result': 'error', 'quality_score': 30}


def verify_leads(input_file):
    """Verify all email addresses in enriched leads"""

    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"Verifying emails for {len(leads)} leads...\n")

    valid_count = 0
    invalid_count = 0
    catch_all_count = 0
    no_email_count = 0

    for i, lead in enumerate(leads, 1):
        company = lead.get('Nom_Entreprise', 'Unknown')
        email_decideur = lead.get('Email_Decideur', '')
        email_generique = lead.get('Email_Generique', '')

        print(f"[{i}/{len(leads)}] {company}")

        # Verify decision maker email
        if email_decideur:
            result = verify_single_email(email_decideur)
            lead['Email_Decideur_Verified'] = result['is_valid']
            lead['Email_Decideur_Status'] = result['result']

            if result['is_valid']:
                if result['result'] == 'catch_all':
                    print(f"    Email decideur: {email_decideur} (catch-all)")
                    catch_all_count += 1
                else:
                    print(f"    Email decideur: {email_decideur} (valid)")
                    valid_count += 1
            else:
                print(f"    Email decideur: {email_decideur} (INVALID - {result['result']})")
                invalid_count += 1
                # Clear invalid email to prevent bounce
                lead['Email_Decideur_Original'] = email_decideur
                lead['Email_Decideur'] = ''
        else:
            no_email_count += 1

        # Verify generic email (if no decision maker email)
        if email_generique and not email_decideur:
            result = verify_single_email(email_generique)
            lead['Email_Generique_Verified'] = result['is_valid']
            lead['Email_Generique_Status'] = result['result']

            if not result['is_valid']:
                print(f"    Email generique: {email_generique} (INVALID)")
                lead['Email_Generique_Original'] = email_generique
                lead['Email_Generique'] = ''

        # Rate limiting
        sleep(0.3)

    print(f"\nVerification complete:")
    print(f"  Valid: {valid_count}")
    print(f"  Catch-all: {catch_all_count}")
    print(f"  Invalid (removed): {invalid_count}")
    print(f"  No email: {no_email_count}")

    return leads


def save_results(leads, output_file):
    """Save verified leads back to same file"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"Saved to: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description='Verify email addresses in enriched leads')
    parser.add_argument('--input', required=True, help='Input JSON file from enrichment step')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    # Check API key
    print(f"API Key status:")
    print(f"   - MILLIONVERIFIER_API_KEY: {'Configured' if MILLIONVERIFIER_API_KEY else 'Missing (will skip verification)'}")
    print()

    # Verify emails
    verified_leads = verify_leads(input_path)

    # Save results (overwrite input file with verified data)
    save_results(verified_leads, input_path)

    print(f"\nStep 4b complete")
    print(f"Output: {input_path}")
    print(f"\nNext step: Score leads with score_lead.py")

    save_tracker_snapshot("step3b_verify")


if __name__ == '__main__':
    main()
