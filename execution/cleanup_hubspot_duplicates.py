"""
One-shot script to remove duplicate contacts in HubSpot.
Groups contacts by company name, keeps the one with the most data (email > no email),
deletes the rest.

Usage:
    python execution/cleanup_hubspot_duplicates.py
    python execution/cleanup_hubspot_duplicates.py --dry-run   # preview only
"""

import os
import sys
import logging
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from time import sleep

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
load_dotenv()

from api_utils import sdk_call_with_retry

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')


def _normalize(name):
    if not name:
        return ''
    import re
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', name.lower().strip())).strip()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Preview without deleting')
    args = parser.parse_args()

    from hubspot import HubSpot
    client = HubSpot(access_token=HUBSPOT_API_KEY)

    print("Fetching all contacts from HubSpot...")
    contacts = sdk_call_with_retry(
        lambda: client.crm.contacts.get_all(
            properties=["email", "company", "website", "firstname", "lastname", "phone"],
            limit=100
        ),
        label="HubSpot get-all-contacts"
    )

    print(f"  {len(contacts)} contacts found\n")

    by_company = defaultdict(list)
    for c in contacts:
        props = c.properties or {}
        company = _normalize(props.get('company', ''))
        if not company:
            continue
        email = (props.get('email') or '').strip()
        score = sum([
            2 if email else 0,
            1 if props.get('firstname') else 0,
            1 if props.get('lastname') else 0,
            1 if props.get('phone') else 0,
        ])
        by_company[company].append({
            'id': c.id,
            'email': email,
            'company_raw': props.get('company', ''),
            'score': score,
        })

    duplicates = {k: v for k, v in by_company.items() if len(v) > 1}

    if not duplicates:
        print("No duplicates found!")
        return

    total_to_delete = 0
    ids_to_delete = []

    print(f"Found {len(duplicates)} companies with duplicates:\n")
    for company, entries in sorted(duplicates.items()):
        entries.sort(key=lambda x: x['score'], reverse=True)
        keep = entries[0]
        remove = entries[1:]
        total_to_delete += len(remove)

        print(f"  {entries[0]['company_raw']}")
        print(f"    KEEP:   id={keep['id']} email={keep['email'] or '--'} score={keep['score']}")
        for r in remove:
            print(f"    DELETE: id={r['id']} email={r['email'] or '--'} score={r['score']}")
            ids_to_delete.append(r['id'])
        print()

    print(f"Total: {total_to_delete} duplicates to delete\n")

    if args.dry_run:
        print("DRY RUN — no changes made.")
        return

    print("Deleting duplicates...")
    deleted = 0
    for cid in ids_to_delete:
        try:
            sdk_call_with_retry(
                lambda i=cid: client.crm.contacts.basic_api.archive(contact_id=i),
                label="HubSpot contact-delete"
            )
            deleted += 1
        except Exception as e:
            print(f"  Failed to delete {cid}: {str(e)[:80]}")
        sleep(0.2)

    print(f"\nDone! Deleted {deleted}/{total_to_delete} duplicate contacts.")


if __name__ == '__main__':
    main()
