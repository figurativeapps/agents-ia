"""
HubSpot Help Desk Ticket Management
Creates tickets, notes, and manages contact associations.
Supports conversation threading (1 ticket per conversation).

Usage:
    python hubspot_ticket.py --action find_or_create_contact --email "user@example.com" --name "John Doe"
    python hubspot_ticket.py --action create_ticket --contact-id 123 --objet "Title" --description "Content" --type SUPPORT
    python hubspot_ticket.py --action create_note --contact-id 123 --objet "Fichiers reçus" --fichiers-urls '["https://..."]'
    python hubspot_ticket.py --action find_open_ticket --contact-id 123
    python hubspot_ticket.py --action ensure_properties
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate as ContactInput
from hubspot.crm.tickets import SimplePublicObjectInputForCreate as TicketInput
from hubspot.crm.tickets import SimplePublicObjectInput as TicketUpdateInput
from hubspot.crm.tickets import ApiException as TicketApiException
from hubspot.crm.contacts import ApiException as ContactApiException
from hubspot.crm.objects.notes import SimplePublicObjectInputForCreate as NoteInput
from hubspot.crm.objects.notes import ApiException as NoteApiException
from hubspot.crm.properties import PropertyCreate
from hubspot.crm.properties import ApiException as PropertyApiException
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
HUBSPOT_HUB_ID = os.getenv("HUBSPOT_HUB_ID", "147476643")  # Your HubSpot portal ID


def get_hubspot_client():
    """Initialize HubSpot client"""
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env")
    return HubSpot(access_token=HUBSPOT_API_KEY)


# =============================================================================
# CUSTOM PROPERTIES MANAGEMENT
# =============================================================================

def ensure_custom_properties() -> dict:
    """
    Create custom ticket properties if they don't exist.
    Called once at startup to ensure properties are available.
    
    Creates:
        - clickup_subtask_id: Stores the ClickUp subtask ID for conversation threading
        - fichiers_urls: Stores concatenated R2 file URLs (one per line)
    
    Returns:
        {"success": bool, "properties": list of created/existing properties}
    """
    client = get_hubspot_client()
    properties_to_create = [
        {
            "name": "clickup_subtask_id",
            "label": "ClickUp Subtask ID",
            "type": "string",
            "field_type": "text",
            "group_name": "ticketinformation",
            "description": "ID de la subtask ClickUp associée à ce ticket"
        },
        {
            "name": "fichiers_urls",
            "label": "Fichiers URLs",
            "type": "string",
            "field_type": "textarea",
            "group_name": "ticketinformation",
            "description": "URLs des fichiers uploadés sur R2 (une par ligne)"
        },
        {
            "name": "validation_status",
            "label": "Statut Validation",
            "type": "enumeration",
            "field_type": "select",
            "group_name": "ticketinformation",
            "description": "Statut de validation de la demande de modélisation",
            "options": [
                {"label": "En attente d'infos", "value": "pending_info", "displayOrder": 1},
                {"label": "Devis envoyé", "value": "pending_credits", "displayOrder": 2},
                {"label": "Attente admin", "value": "pending_admin", "displayOrder": 3},
                {"label": "Validé", "value": "validated", "displayOrder": 4},
                {"label": "Refusé", "value": "rejected", "displayOrder": 5}
            ]
        },
        {
            "name": "credits_estimes",
            "label": "Crédits Estimés",
            "type": "number",
            "field_type": "number",
            "group_name": "ticketinformation",
            "description": "Nombre de crédits estimés pour cette modélisation"
        }
    ]
    
    results = []
    for prop in properties_to_create:
        try:
            # Build property creation kwargs
            create_kwargs = {
                "name": prop["name"],
                "label": prop["label"],
                "type": prop["type"],
                "field_type": prop["field_type"],
                "group_name": prop["group_name"],
                "description": prop["description"]
            }
            
            # Add options for enumeration type
            if prop.get("options"):
                create_kwargs["options"] = prop["options"]
            
            property_create = PropertyCreate(**create_kwargs)
            client.crm.properties.core_api.create(
                object_type="tickets",
                property_create=property_create
            )
            print(f"✅ Created property: {prop['name']}")
            results.append({"name": prop["name"], "status": "created"})
            
        except PropertyApiException as e:
            if "PROPERTY_EXISTS" in str(e) or "already exists" in str(e).lower():
                print(f"ℹ️  Property already exists: {prop['name']}")
                results.append({"name": prop["name"], "status": "exists"})
            else:
                print(f"⚠️  Error creating property {prop['name']}: {str(e)[:100]}")
                results.append({"name": prop["name"], "status": "error", "error": str(e)[:100]})
    
    return {"success": True, "properties": results}


# =============================================================================
# TICKET THREADING - FIND OPEN TICKET
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_open_ticket(contact_id: str, max_age_days: int = 14) -> dict | None:
    """
    Find an open ticket for a contact that was active within the last N days.
    
    An "open" ticket has status:
        - "1" (Nouveau / New)
        - "2" (En cours / In Progress)
    
    Args:
        contact_id: HubSpot contact ID
        max_age_days: Maximum days since last update (default 14)
    
    Returns:
        {
            "ticket_id": str,
            "ticket_url": str,
            "clickup_subtask_id": str | None,
            "fichiers_urls": list[str]
        } or None if no open ticket found
    """
    client = get_hubspot_client()
    hub_id = HUBSPOT_HUB_ID
    
    # Calculate the cutoff date
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    cutoff_timestamp = int(cutoff_date.timestamp() * 1000)  # HubSpot uses milliseconds
    
    try:
        # Get tickets associated with this contact
        # First, get all ticket associations for the contact
        associations = client.crm.associations.v4.basic_api.get_page(
            object_type="contacts",
            object_id=contact_id,
            to_object_type="tickets",
            limit=100
        )
        
        if not associations.results:
            print(f"ℹ️  No tickets found for contact {contact_id}")
            return None
        
        # Get ticket IDs
        ticket_ids = [assoc.to_object_id for assoc in associations.results]
        
        # Fetch ticket details with our custom properties
        open_tickets = []
        for ticket_id in ticket_ids:
            try:
                ticket = client.crm.tickets.basic_api.get_by_id(
                    ticket_id=ticket_id,
                    properties=[
                        "subject", "hs_pipeline_stage", "hs_lastmodifieddate",
                        "clickup_subtask_id", "fichiers_urls"
                    ]
                )
                
                props = ticket.properties
                stage = props.get("hs_pipeline_stage", "")
                last_modified = props.get("hs_lastmodifieddate", "")
                
                # Check if ticket is open (stage 1 or 2)
                if stage in ["1", "2"]:
                    # Check if ticket was modified within max_age_days
                    if last_modified:
                        try:
                            modified_dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                            if modified_dt.timestamp() * 1000 >= cutoff_timestamp:
                                # Parse fichiers_urls (stored as newline-separated string)
                                fichiers_urls_str = props.get("fichiers_urls") or ""
                                fichiers_urls = [u.strip() for u in fichiers_urls_str.split("\n") if u.strip()]
                                
                                open_tickets.append({
                                    "ticket_id": ticket_id,
                                    "ticket_url": f"https://app-eu1.hubspot.com/contacts/{hub_id}/ticket/{ticket_id}",
                                    "subject": props.get("subject", ""),
                                    "last_modified": last_modified,
                                    "clickup_subtask_id": props.get("clickup_subtask_id"),
                                    "fichiers_urls": fichiers_urls
                                })
                        except (ValueError, TypeError):
                            # If date parsing fails, still consider the ticket if open
                            fichiers_urls_str = props.get("fichiers_urls") or ""
                            fichiers_urls = [u.strip() for u in fichiers_urls_str.split("\n") if u.strip()]
                            
                            open_tickets.append({
                                "ticket_id": ticket_id,
                                "ticket_url": f"https://app-eu1.hubspot.com/contacts/{hub_id}/ticket/{ticket_id}",
                                "subject": props.get("subject", ""),
                                "last_modified": last_modified,
                                "clickup_subtask_id": props.get("clickup_subtask_id"),
                                "fichiers_urls": fichiers_urls
                            })
                            
            except Exception as e:
                print(f"⚠️  Error fetching ticket {ticket_id}: {str(e)[:100]}")
                continue
        
        if open_tickets:
            # Return the most recently modified open ticket
            open_tickets.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
            best_ticket = open_tickets[0]
            print(f"✅ Found open ticket: {best_ticket['ticket_id']} ({best_ticket['subject']})")
            return best_ticket
        
        print(f"ℹ️  No open tickets within {max_age_days} days for contact {contact_id}")
        return None
        
    except Exception as e:
        print(f"⚠️  Error searching for open tickets: {str(e)[:200]}")
        return None


# =============================================================================
# TICKET UPDATE FUNCTIONS
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def update_ticket_property(ticket_id: str, property_name: str, value: str) -> dict:
    """
    Update a single property on a ticket.
    
    Args:
        ticket_id: HubSpot ticket ID
        property_name: Property internal name (e.g., "clickup_subtask_id")
        value: New value for the property
    
    Returns:
        {"success": bool, "ticket_id": str}
    """
    client = get_hubspot_client()
    
    try:
        update_input = TicketUpdateInput(
            properties={property_name: value}
        )
        client.crm.tickets.basic_api.update(
            ticket_id=ticket_id,
            simple_public_object_input=update_input
        )
        print(f"✅ Updated ticket {ticket_id}: {property_name}")
        return {"success": True, "ticket_id": ticket_id}
        
    except TicketApiException as e:
        print(f"❌ Error updating ticket: {str(e)[:200]}")
        return {"success": False, "ticket_id": ticket_id, "error": str(e)}


def append_fichiers_urls(ticket_id: str, new_urls: list, existing_urls: list = None) -> dict:
    """
    Append new file URLs to the ticket's fichiers_urls property.
    
    Args:
        ticket_id: HubSpot ticket ID
        new_urls: List of new R2 URLs to add
        existing_urls: Existing URLs (if already fetched, to avoid extra API call)
    
    Returns:
        {"success": bool, "total_urls": int, "all_urls": list}
    """
    if not new_urls:
        return {"success": True, "total_urls": len(existing_urls or []), "all_urls": existing_urls or []}
    
    # Combine existing and new URLs
    all_urls = list(existing_urls or [])
    for url in new_urls:
        if url not in all_urls:
            all_urls.append(url)
    
    # Store as newline-separated string
    urls_string = "\n".join(all_urls)
    
    result = update_ticket_property(ticket_id, "fichiers_urls", urls_string)
    
    if result["success"]:
        print(f"📎 Updated fichiers_urls: {len(all_urls)} total files")
        return {"success": True, "total_urls": len(all_urls), "all_urls": all_urls}
    else:
        return {"success": False, "error": result.get("error"), "all_urls": all_urls}


# =============================================================================
# CONTACT FUNCTIONS
# =============================================================================

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
    reclassifie: bool = False,
    user_email: str = None
) -> dict:
    """Create a ticket in HubSpot Help Desk"""
    client = get_hubspot_client()
    hub_id = HUBSPOT_HUB_ID
    
    # Build ticket content
    content = description
    if fichiers_urls:
        content += "\n\n---\nFichiers joints:\n"
        for url in fichiers_urls:
            content += f"- {url}\n"
    
    # Ticket properties (using only standard HubSpot properties)
    properties = {
        "subject": objet,
        "content": content,
        "hs_pipeline": HUBSPOT_PIPELINE_ID,
        "hs_pipeline_stage": HUBSPOT_STAGE_NEW,
        "hs_ticket_priority": "HIGH" if reclassifie else "MEDIUM",
    }
    
    # Add metadata to content instead of custom properties
    # (Custom properties would need to be created in HubSpot first)
    metadata = []
    if user_email:
        metadata.append(f"Email: {user_email}")
    if type_final:
        metadata.append(f"Type: {type_final}")
    if source_formulaire:
        metadata.append(f"Source: {source_formulaire}")
    if reclassifie:
        metadata.append("RECLASSIFIE PAR IA")
    
    if metadata:
        properties["content"] = f"[{' | '.join(metadata)}]\n\n{content}"
    
    try:
        ticket_input = TicketInput(properties=properties)
        ticket = client.crm.tickets.basic_api.create(
            simple_public_object_input_for_create=ticket_input
        )
        
        ticket_id = ticket.id
        ticket_url = f"https://app-eu1.hubspot.com/contacts/{hub_id}/ticket/{ticket_id}"
        
        print(f"✅ Created ticket: {ticket_id}")
        
        # Associate ticket with contact using v4 associations API
        if contact_id:
            try:
                from hubspot.crm.associations.v4 import BatchInputPublicDefaultAssociationMultiPost
                from hubspot.crm.associations.v4.models import PublicDefaultAssociationMultiPost
                
                association_input = BatchInputPublicDefaultAssociationMultiPost(
                    inputs=[
                        PublicDefaultAssociationMultiPost(
                            _from={"id": ticket_id},
                            to={"id": contact_id}
                        )
                    ]
                )
                client.crm.associations.v4.batch_api.create_default(
                    from_object_type="tickets",
                    to_object_type="contacts",
                    batch_input_public_default_association_multi_post=association_input
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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_note(
    contact_id: str,
    objet: str,
    fichiers_urls: list,
    ticket_id: str = None,
    type_demande: str = "MODELISATION"
) -> dict:
    """
    Create a Note on a contact with file URLs.
    
    This note will appear in the contact's Activity timeline,
    making file history visible on the contact record.
    
    Args:
        contact_id: HubSpot contact ID
        objet: Subject/title of the request
        fichiers_urls: List of R2 public URLs
        ticket_id: Optional ticket ID to associate the note with
        type_demande: Type of request (for note title)
    
    Returns:
        {"note_id": str, "success": bool} or {"error": str}
    """
    if not fichiers_urls:
        return {"note_id": None, "success": True, "message": "No files to note"}
    
    client = get_hubspot_client()
    hub_id = HUBSPOT_HUB_ID
    
    # Build note content with HTML formatting (HubSpot notes support HTML)
    note_body = f"<strong>📁 Fichiers reçus - {type_demande}</strong><br><br>"
    note_body += f"<strong>Objet:</strong> {objet}<br><br>"
    note_body += "<strong>Fichiers:</strong><br>"
    
    for url in fichiers_urls:
        # Extract filename from URL
        filename = url.split("/")[-1] if "/" in url else url
        note_body += f'• <a href="{url}">{filename}</a><br>'
    
    note_body += f"<br><em>Reçu le {datetime.now().strftime('%d/%m/%Y à %H:%M')}</em>"
    
    # Note properties (hs_timestamp must be Unix timestamp in milliseconds)
    properties = {
        "hs_note_body": note_body,
        "hs_timestamp": str(int(datetime.now().timestamp() * 1000))
    }
    
    try:
        note_input = NoteInput(properties=properties)
        note = client.crm.objects.notes.basic_api.create(
            simple_public_object_input_for_create=note_input
        )
        
        note_id = note.id
        print(f"✅ Created note: {note_id}")
        
        # Associate note with contact
        try:
            from hubspot.crm.associations.v4 import BatchInputPublicDefaultAssociationMultiPost
            from hubspot.crm.associations.v4.models import PublicDefaultAssociationMultiPost
            
            # Associate note -> contact
            association_input = BatchInputPublicDefaultAssociationMultiPost(
                inputs=[
                    PublicDefaultAssociationMultiPost(
                        _from={"id": note_id},
                        to={"id": contact_id}
                    )
                ]
            )
            client.crm.associations.v4.batch_api.create_default(
                from_object_type="notes",
                to_object_type="contacts",
                batch_input_public_default_association_multi_post=association_input
            )
            print(f"🔗 Associated note with contact {contact_id}")
            
            # Also associate with ticket if provided
            if ticket_id:
                ticket_association = BatchInputPublicDefaultAssociationMultiPost(
                    inputs=[
                        PublicDefaultAssociationMultiPost(
                            _from={"id": note_id},
                            to={"id": ticket_id}
                        )
                    ]
                )
                client.crm.associations.v4.batch_api.create_default(
                    from_object_type="notes",
                    to_object_type="tickets",
                    batch_input_public_default_association_multi_post=ticket_association
                )
                print(f"🔗 Associated note with ticket {ticket_id}")
                
        except Exception as e:
            print(f"⚠️  Note association failed: {str(e)[:100]}")
        
        return {
            "note_id": note_id,
            "success": True,
            "hub_id": hub_id
        }
        
    except NoteApiException as e:
        print(f"❌ Error creating note: {str(e)[:200]}")
        return {"note_id": None, "success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="HubSpot Ticket Management")
    parser.add_argument("--action", required=True, 
                        choices=[
                            "find_or_create_contact", "create_ticket", "create_note",
                            "find_open_ticket", "update_property", "append_urls",
                            "ensure_properties"
                        ],
                        help="Action to perform")
    
    # Contact arguments
    parser.add_argument("--email", help="User email")
    parser.add_argument("--name", help="User name")
    
    # Ticket arguments
    parser.add_argument("--contact-id", help="Contact ID for ticket/note")
    parser.add_argument("--objet", help="Ticket/note subject")
    parser.add_argument("--description", help="Ticket description")
    parser.add_argument("--type", choices=["SUPPORT", "MODELISATION"], help="Request type")
    parser.add_argument("--source", help="Form source")
    parser.add_argument("--reclassifie", action="store_true", help="Was reclassified")
    parser.add_argument("--fichiers-urls", help="JSON array of file URLs")
    parser.add_argument("--ticket-id", help="Ticket ID (for note association or update)")
    parser.add_argument("--max-age-days", type=int, default=14, help="Max days for open ticket search")
    
    # Property update arguments
    parser.add_argument("--property-name", help="Property name to update")
    parser.add_argument("--property-value", help="Property value")
    
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    if args.action == "ensure_properties":
        result = ensure_custom_properties()
    
    elif args.action == "find_or_create_contact":
        if not args.email:
            print("❌ --email is required for find_or_create_contact")
            sys.exit(1)
        result = find_or_create_contact(args.email, args.name)
    
    elif args.action == "find_open_ticket":
        if not args.contact_id:
            print("❌ --contact-id is required for find_open_ticket")
            sys.exit(1)
        result = find_open_ticket(args.contact_id, args.max_age_days)
        if result is None:
            result = {"found": False, "message": "No open ticket found"}
        else:
            result["found"] = True
        
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
    
    elif args.action == "create_note":
        if not args.contact_id or not args.fichiers_urls:
            print("❌ --contact-id and --fichiers-urls are required for create_note")
            sys.exit(1)
        
        fichiers_urls = json.loads(args.fichiers_urls)
        
        result = create_note(
            contact_id=args.contact_id,
            objet=args.objet or "Fichiers reçus",
            fichiers_urls=fichiers_urls,
            ticket_id=args.ticket_id,
            type_demande=args.type or "MODELISATION"
        )
    
    elif args.action == "update_property":
        if not args.ticket_id or not args.property_name or not args.property_value:
            print("❌ --ticket-id, --property-name, and --property-value are required")
            sys.exit(1)
        result = update_ticket_property(args.ticket_id, args.property_name, args.property_value)
    
    elif args.action == "append_urls":
        if not args.ticket_id or not args.fichiers_urls:
            print("❌ --ticket-id and --fichiers-urls are required for append_urls")
            sys.exit(1)
        fichiers_urls = json.loads(args.fichiers_urls)
        result = append_fichiers_urls(args.ticket_id, fichiers_urls)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
