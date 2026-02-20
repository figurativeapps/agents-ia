"""
SYNC FROM HUBSPOT: Reverse Sync (HubSpot → Excel)
Detects contacts deleted in HubSpot and removes them from Excel.

Usage:
    python sync_from_hubspot.py
"""

import os
import sys
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from hubspot import HubSpot
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

# Load environment variables
load_dotenv()

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')


def init_hubspot_client():
    """Initialize HubSpot API client"""
    if not HUBSPOT_API_KEY:
        raise ValueError("❌ HUBSPOT_API_KEY not found in .env file")

    return HubSpot(access_token=HUBSPOT_API_KEY)


def check_excel_locked(excel_path):
    """Check if Excel file is locked (open in another program)"""
    try:
        with open(excel_path, 'a') as f:
            pass
        return False
    except PermissionError:
        return True


def contact_exists_in_hubspot(client, email):
    """
    Check if contact exists in HubSpot by email

    Returns:
        True if contact exists, False otherwise
    """
    if not email:
        return False

    try:
        filter_groups = [{
            "filters": [{
                "propertyName": "email",
                "operator": "EQ",
                "value": email
            }]
        }]

        search_request = {
            "filterGroups": filter_groups,
            "properties": ["email"]
        }

        results = client.crm.contacts.search_api.do_search(public_object_search_request=search_request)

        return results.total > 0

    except Exception as e:
        print(f"    ⚠️  Error checking {email}: {str(e)[:50]}")
        return True  # In case of error, assume it exists to avoid accidental deletion


def sync_from_hubspot(excel_path):
    """
    Sync from HubSpot to Excel: Remove contacts that were deleted in HubSpot

    Args:
        excel_path: Path to Generate_leads.xlsx
    """

    print("=" * 60)
    print("🔄 REVERSE SYNC: HubSpot → Excel")
    print("=" * 60)
    print("\nDetecting contacts deleted in HubSpot...\n")

    # Check if Excel is locked
    if check_excel_locked(excel_path):
        print("\n⚠️  WARNING: Generate_leads.xlsx is currently open!")
        print("Please close the file and try again.")
        sys.exit(1)

    # Load Excel data
    try:
        df = pd.read_excel(excel_path, sheet_name='Leads')
        initial_count = len(df)
        print(f"📊 Loaded {initial_count} leads from Excel\n")
    except Exception as e:
        print(f"❌ Error loading Excel: {e}")
        return

    # Initialize HubSpot client
    client = init_hubspot_client()

    # Track deletions
    deleted_leads = []
    checked_count = 0

    # Check each lead in Excel
    for idx, row in df.iterrows():
        email = row.get('Email_Decideur') or row.get('Email_Generique')
        company_name = row.get('Nom_Entreprise', 'Unknown')

        if not email:
            print(f"[{idx+1}/{initial_count}] {company_name} - ⏭️  No email, skipping")
            continue

        checked_count += 1

        # Check if contact exists in HubSpot
        exists = contact_exists_in_hubspot(client, email)

        if not exists:
            print(f"[{idx+1}/{initial_count}] {company_name} - ❌ Deleted in HubSpot")
            deleted_leads.append(idx)
        else:
            print(f"[{idx+1}/{initial_count}] {company_name} - ✅ Still in HubSpot")

        # Rate limiting
        sleep(0.5)

    print(f"\n{'='*60}")
    print(f"📊 SYNC SUMMARY")
    print(f"{'='*60}")
    print(f"Total leads in Excel:     {initial_count}")
    print(f"Leads checked:            {checked_count}")
    print(f"Deleted in HubSpot:       {len(deleted_leads)}")
    print(f"Remaining after sync:     {initial_count - len(deleted_leads)}")

    # Remove deleted contacts from DataFrame
    if deleted_leads:
        print(f"\n🗑️  Removing {len(deleted_leads)} deleted contacts from Excel...")

        # Show which contacts will be deleted
        print("\nContacts to be removed:")
        for idx in deleted_leads:
            company = df.loc[idx, 'Nom_Entreprise']
            email = df.loc[idx, 'Email_Decideur'] or df.loc[idx, 'Email_Generique']
            print(f"  - {company} ({email})")

        # Drop the rows
        df = df.drop(deleted_leads)
        df = df.reset_index(drop=True)

        # Save updated Excel
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Leads', index=False)

            # Get worksheet for formatting
            worksheet = writer.sheets['Leads']

            # Set column widths
            column_widths = {
                'A': 20, 'B': 30, 'C': 40, 'D': 20, 'E': 12, 'F': 15,
                'G': 35, 'H': 18, 'I': 30, 'J': 30, 'K': 25,
                'L': 35, 'M': 35, 'N': 12, 'O': 15, 'P': 15
            }

            for col, width in column_widths.items():
                worksheet.column_dimensions[col].width = width

            # Freeze first row (header)
            worksheet.freeze_panes = 'A2'

        print(f"\n✅ Excel updated successfully!")
        print(f"📄 Location: {excel_path}")
        print(f"📊 New total: {len(df)} leads")
    else:
        print(f"\n✅ No contacts to remove - Excel is up to date!")

    print("\n" + "="*60)


def main():
    excel_path = Path(__file__).parent.parent / 'Generate_leads.xlsx'

    if not excel_path.exists():
        print(f"❌ Excel file not found: {excel_path}")
        print("In direct mode (default), HubSpot is the source of truth.")
        print("This script is only needed with --use-excel mode.")
        print("To create an Excel backup: python execution/run_pipeline.py --industry ... --location ...")
        return

    sync_from_hubspot(excel_path)

    print("\n💡 Tip: Run this script periodically to keep Excel in sync with HubSpot")


if __name__ == '__main__':
    main()
