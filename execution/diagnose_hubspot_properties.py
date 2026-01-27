"""
Diagnostic Script: List all HubSpot Contact and Company Properties
This will help identify the exact internal names of custom properties.

Usage:
    python diagnose_hubspot_properties.py
"""

import os
import sys
from dotenv import load_dotenv
from hubspot import HubSpot

# Fix Windows console encoding
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


def list_contact_properties():
    """List all contact properties in HubSpot"""
    if not HUBSPOT_API_KEY:
        print("❌ HUBSPOT_API_KEY not found in .env file")
        return

    client = HubSpot(access_token=HUBSPOT_API_KEY)

    print("=" * 80)
    print("📋 CONTACT PROPERTIES")
    print("=" * 80)

    try:
        # Get all contact properties
        properties = client.crm.properties.core_api.get_all(object_type="contacts")

        # Filter for custom properties and relevant ones
        print("\n🔍 Looking for: industrie, linkedin, url...")
        print("-" * 80)
        print(f"{'Label':<30} {'Internal Name':<30} {'Type':<15}")
        print("-" * 80)

        for prop in properties.results:
            label = prop.label.lower()
            name = prop.name.lower()

            # Show all properties that might be related
            if any(keyword in label or keyword in name for keyword in ['industrie', 'industry', 'linkedin', 'url', 'adresse', 'ville', 'pays', 'country']):
                print(f"{prop.label:<30} {prop.name:<30} {prop.type:<15}")

        print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {e}")


def list_company_properties():
    """List all company properties in HubSpot"""
    if not HUBSPOT_API_KEY:
        print("❌ HUBSPOT_API_KEY not found in .env file")
        return

    client = HubSpot(access_token=HUBSPOT_API_KEY)

    print("\n" + "=" * 80)
    print("🏢 COMPANY PROPERTIES")
    print("=" * 80)

    try:
        # Get all company properties
        properties = client.crm.properties.core_api.get_all(object_type="companies")

        # Filter for custom properties and relevant ones
        print("\n🔍 Looking for: industrie, linkedin, url...")
        print("-" * 80)
        print(f"{'Label':<30} {'Internal Name':<30} {'Type':<15}")
        print("-" * 80)

        for prop in properties.results:
            label = prop.label.lower()
            name = prop.name.lower()

            # Show all properties that might be related
            if any(keyword in label or keyword in name for keyword in ['industrie', 'industry', 'linkedin', 'url', 'adresse', 'ville', 'pays', 'country']):
                print(f"{prop.label:<30} {prop.name:<30} {prop.type:<15}")

        print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == '__main__':
    print("\n🔍 HUBSPOT PROPERTIES DIAGNOSTIC\n")
    print("This script will list all relevant HubSpot properties to identify exact internal names.\n")

    list_contact_properties()
    list_company_properties()

    print("\n✅ Diagnostic complete!")
    print("\n💡 Use the 'Internal Name' column values in sync_hubspot.py")
