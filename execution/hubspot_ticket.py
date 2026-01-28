"""
HubSpot Help Desk Ticket Management
Creates tickets and manages contact associations.

Usage:
    python hubspot_ticket.py --action find_or_create_contact --email "user@example.com" --name "John Doe"
    python hubspot_ticket.py --action create_ticket --contact-id 123 --objet "Title" --description "Content" --type SUPPORT
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate as ContactInput
from hubspot.crm.tickets import SimplePublicObjectInputForCreate as TicketInput
from hubspot.crm.tickets import ApiException as TicketApiException
from hubspot.crm.contacts import ApiException as ContactApiException
from tenacity import retry, stop_after_attempt, wait_exponential

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
load_dotenv()

HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")
HUBSPOT_PIPELINE_ID = os.getenv("HUBSPOT_PIPELINE_ID", "0")
HUBSPOT_STAGE_NEW = os.getenv("HUBSPOT_STAGE_NEW", "1")

# HubSpot Hub ID (for URL generation) - will be fetched dynamically
HUB_ID = None


def get_hubspot_client():
    """Initialize HubSpot client"""
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env")
    return HubSpot(access_token=HUBSPOT_API_KEY)


def get_hub_id(client):
    """Get HubSpot Hub ID for URL generation"""
    global HUB_ID
    if HUB_ID is None:
        try:
            # Get account info
            account_info = client.account.api_client.call_api(
                '/account-info/v3/details', 'GET'
            )
            HUB_ID = account_info[0].get('portalId')
        except Exception:
            # Fallback: extract from API response if available
            HUB_ID = os.getenv("HUBSPOT_HUB_ID", "UNKNOWN")
    return HUB_ID


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def search_contact_by_email(client, email: str) -> str | None:
    """Search for a contact by email"""
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
            "properties": ["email", "firstname", "lastname"]
        }
        
        results = client.crm.contacts.search_api.do_search(
            public_object_search_request=search_request
        )
        
        if results.total > 0:
            return results.results[0].id
        return None
        
    except Exception as e:
        print(f"⚠️  Search error: {str(e)[:100]}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_contact(client, email: str, name: str = None) -> str | None:
    """Create a new contact"""
    properties = {"email": email}
    
    if name:
        name_parts = name.split()
        if name_parts:
            properties["firstname"] = name_parts[0]
            if len(name_parts) > 1:
                properties["lastname"] = " ".join(name_parts[1:])
    
    try:
        contact_input = ContactInput(properties=properties)
        contact = client.crm.contacts.basic_api.create(
            simple_public_object_input_for_create=contact_input
        )
        print(f"✅ Created contact: {email}")
        return contact.id
        
    except ContactApiException as e:
        if "CONFLICT" in str(e):
            # Contact already exists, search for it
            return search_contact_by_email(client, email)
        print(f"❌ Error creating contact: {str(e)[:200]}")
        return None


def find_or_create_contact(email: str, name: str = None) -> dict:
    """Find existing contact or create new one"""
    client = get_hubspot_client()
    
    print(f"🔍 Searching for contact: {email}")
    contact_id = search_contact_by_email(client, email)
    
    if contact_id:
        print(f"✅ Found existing contact: {contact_id}")
        return {"contact_id": contact_id, "created": False}
    
    print(f"📝 Creating new contact: {email}")
    contact_id = create_contact(client, email, name)
    
    if contact_id:
        return {"contact_id": contact_id, "created": True}
    
    return {"contact_id": None, "error": "Failed to create contact"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_ticket(
    contact_id: str,
    type_final: str,
    objet: str,
    description: str,
    fichiers_urls: list = None,
    source_formulaire: str = None,
    reclassifie: bool = False
) -> dict:
    """Create a ticket in HubSpot Help Desk"""
    client = get_hubspot_client()
    hub_id = get_hub_id(client)
    
    # Build ticket content
    content = description
    if fichiers_urls:
        content += "\n\n---\nFichiers joints:\n"
        for url in fichiers_urls:
            content += f"- {url}\n"
    
    # Ticket properties
    properties = {
        "subject": objet,
        "content": content,
        "hs_pipeline": HUBSPOT_PIPELINE_ID,
        "hs_pipeline_stage": HUBSPOT_STAGE_NEW,
        "hs_ticket_priority": "HIGH" if reclassifie else "MEDIUM",
    }
    
    # Add custom properties if they exist in HubSpot
    # These may need to be created manually in HubSpot first
    try:
        if type_final:
            properties["type_demande"] = type_final
        if source_formulaire:
            properties["source_formulaire"] = source_formulaire
        if reclassifie:
            properties["reclassifie"] = "true"
    except Exception:
        pass  # Custom properties may not exist
    
    try:
        ticket_input = TicketInput(properties=properties)
        ticket = client.crm.tickets.basic_api.create(
            simple_public_object_input_for_create=ticket_input
        )
        
        ticket_id = ticket.id
        ticket_url = f"https://app.hubspot.com/contacts/{hub_id}/ticket/{ticket_id}"
        
        print(f"✅ Created ticket: {ticket_id}")
        
        # Associate ticket with contact
        if contact_id:
            try:
                client.crm.tickets.associations_api.create(
                    ticket_id=ticket_id,
                    to_object_type="contacts",
                    to_object_id=contact_id,
                    association_type="ticket_to_contact"
                )
                print(f"🔗 Associated ticket with contact {contact_id}")
            except Exception as e:
                print(f"⚠️  Association failed: {str(e)[:100]}")
        
        return {
            "ticket_id": ticket_id,
            "ticket_url": ticket_url,
            "hub_id": hub_id
        }
        
    except TicketApiException as e:
        print(f"❌ Error creating ticket: {str(e)[:200]}")
        return {"ticket_id": None, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="HubSpot Ticket Management")
    parser.add_argument("--action", required=True, 
                        choices=["find_or_create_contact", "create_ticket"],
                        help="Action to perform")
    
    # Contact arguments
    parser.add_argument("--email", help="User email")
    parser.add_argument("--name", help="User name")
    
    # Ticket arguments
    parser.add_argument("--contact-id", help="Contact ID for ticket")
    parser.add_argument("--objet", help="Ticket subject")
    parser.add_argument("--description", help="Ticket description")
    parser.add_argument("--type", choices=["SUPPORT", "MODELISATION"], help="Request type")
    parser.add_argument("--source", help="Form source")
    parser.add_argument("--reclassifie", action="store_true", help="Was reclassified")
    parser.add_argument("--fichiers-urls", help="JSON array of file URLs")
    
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    if args.action == "find_or_create_contact":
        if not args.email:
            print("❌ --email is required for find_or_create_contact")
            sys.exit(1)
        result = find_or_create_contact(args.email, args.name)
        
    elif args.action == "create_ticket":
        if not args.contact_id or not args.objet:
            print("❌ --contact-id and --objet are required for create_ticket")
            sys.exit(1)
        
        fichiers_urls = json.loads(args.fichiers_urls) if args.fichiers_urls else []
        
        result = create_ticket(
            contact_id=args.contact_id,
            type_final=args.type or "SUPPORT",
            objet=args.objet,
            description=args.description or "",
            fichiers_urls=fichiers_urls,
            source_formulaire=args.source,
            reclassifie=args.reclassifie
        )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
