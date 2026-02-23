"""
Validation Workflow Orchestrator
Surveille les tickets en attente de validation et traite les réponses clients/admin.

Modes de fonctionnement:
1. Polling: Vérifie périodiquement les tickets en attente et les nouveaux emails
2. Manuel: Appelé via endpoint /webhook/validate

Usage:
    python validation_workflow.py --mode poll --interval 60
    python validation_workflow.py --mode check --ticket-id 123456
    python validation_workflow.py --mode process-response --ticket-id 123456 --response "Je valide"
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dotenv import load_dotenv

# Add execution directory to path
execution_dir = Path(__file__).parent
if str(execution_dir) not in sys.path:
    sys.path.insert(0, str(execution_dir))

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

load_dotenv()

import requests
from hubspot import HubSpot
from tenacity import retry, stop_after_attempt, wait_exponential

from hubspot_ticket import (
    get_hubspot_client,
    update_ticket_property
)
from hubspot_conversation import (
    get_ticket_details,
    get_messages_for_ticket,
    send_email_to_contact,
    detect_validation_response
)
from clickup_subtask import create_subtask
from analyze_request import (
    analyze_request,
    generate_missing_info_message,
    generate_credit_quote_message
)

# Configuration
HUBSPOT_HUB_ID = os.getenv("HUBSPOT_HUB_ID", "147476643")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://127.0.0.1:5000")

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# FIND PENDING TICKETS
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_pending_validation_tickets() -> List[Dict]:
    """
    Find all tickets with validation_status in pending states.
    
    Returns list of tickets with:
        - pending_info: Waiting for client to provide more info
        - pending_credits: Quote sent, waiting for client validation
        - pending_admin: Waiting for admin to validate credits
    """
    client = get_hubspot_client()
    
    pending_statuses = ["pending_info", "pending_credits", "pending_admin"]
    all_tickets = []
    
    for status in pending_statuses:
        try:
            search_request = {
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "validation_status",
                        "operator": "EQ",
                        "value": status
                    }]
                }],
                "properties": [
                    "subject", "content", "validation_status", "credits_estimes",
                    "hs_lastmodifieddate", "clickup_subtask_id"
                ],
                "limit": 50
            }
            
            results = client.crm.tickets.search_api.do_search(
                public_object_search_request=search_request
            )
            
            for ticket in results.results:
                # Get associated contact
                try:
                    assoc = client.crm.associations.v4.basic_api.get_page(
                        object_type="tickets",
                        object_id=ticket.id,
                        to_object_type="contacts",
                        limit=1
                    )
                    contact_id = assoc.results[0].to_object_id if assoc.results else None
                except Exception:
                    contact_id = None
                
                all_tickets.append({
                    "ticket_id": ticket.id,
                    "subject": ticket.properties.get("subject", ""),
                    "validation_status": ticket.properties.get("validation_status", ""),
                    "credits_estimes": ticket.properties.get("credits_estimes"),
                    "last_modified": ticket.properties.get("hs_lastmodifieddate", ""),
                    "contact_id": contact_id,
                    "ticket_url": f"https://app-eu1.hubspot.com/contacts/{HUBSPOT_HUB_ID}/ticket/{ticket.id}"
                })
                
        except Exception as e:
            logger.warning(f"Error searching for {status} tickets: {e}")
            continue
    
    logger.info(f"Found {len(all_tickets)} pending validation tickets")
    return all_tickets


# =============================================================================
# CHECK FOR NEW RESPONSES
# =============================================================================

def check_ticket_for_response(ticket_id: str, last_check_time: Optional[datetime] = None) -> Dict:
    """
    Check if there are new incoming emails for a ticket since last check.
    
    Returns:
        {
            "has_new_response": bool,
            "response_type": "validation" | "rejection" | "question" | "info" | None,
            "message_text": str,
            "message_id": str
        }
    """
    # Get recent messages for this ticket
    messages = get_messages_for_ticket(ticket_id, days=7)
    
    if not messages:
        return {"has_new_response": False, "response_type": None}
    
    # Filter for incoming messages only
    incoming = [m for m in messages if m.get("direction") == "INCOMING"]
    
    if not incoming:
        return {"has_new_response": False, "response_type": None}
    
    # Get the most recent incoming message
    latest = incoming[0]
    
    # Check if it's newer than last check
    if last_check_time:
        try:
            msg_time = datetime.fromisoformat(latest.get("timestamp", "").replace("Z", "+00:00"))
            if msg_time.replace(tzinfo=None) <= last_check_time:
                return {"has_new_response": False, "response_type": None}
        except (ValueError, TypeError):
            pass
    
    # Analyze the response
    message_text = latest.get("body_text", "") or latest.get("body_html", "")
    detection = detect_validation_response(message_text)
    
    return {
        "has_new_response": True,
        "response_type": detection.get("type"),
        "confidence": detection.get("confidence", 0),
        "message_text": message_text[:500],
        "message_id": latest.get("id"),
        "timestamp": latest.get("timestamp")
    }


# =============================================================================
# PROCESS VALIDATION RESPONSE
# =============================================================================

def process_validation(ticket_id: str, credits: int) -> Dict:
    """
    Process a validated request: create ClickUp subtask and update ticket.
    """
    logger.info(f"Processing validation for ticket {ticket_id} ({credits} credits)")
    
    # Get ticket details
    ticket = get_ticket_details(ticket_id)
    if not ticket:
        return {"success": False, "error": "Ticket not found"}
    
    contact_id = ticket.get("contact_id")
    if not contact_id:
        return {"success": False, "error": "No contact associated"}
    
    # Get contact email
    client = get_hubspot_client()
    try:
        contact = client.crm.contacts.basic_api.get_by_id(
            contact_id=contact_id,
            properties=["email"]
        )
        user_email = contact.properties.get("email", "unknown@email.com")
    except Exception as e:
        logger.warning(f"Could not get contact email: {e}")
        user_email = "unknown@email.com"
    
    ticket_url = f"https://app-eu1.hubspot.com/contacts/{HUBSPOT_HUB_ID}/ticket/{ticket_id}"
    
    # Create ClickUp subtask
    subtask_result = create_subtask(
        objet=ticket.get("subject", "Demande modélisation"),
        user_email=user_email,
        ticket_url=ticket_url,
        description=f"{ticket.get('content', '')}\n\n[Crédits validés: {credits}]",
        fichiers_urls=[]
    )
    
    subtask_id = subtask_result.get("subtask_id")
    
    if subtask_id:
        # Update ticket
        update_ticket_property(ticket_id, "validation_status", "validated")
        update_ticket_property(ticket_id, "clickup_subtask_id", subtask_id)
        
        # Send confirmation to client
        confirmation_html = f"""
        <p>Bonjour,</p>
        <p>Votre demande de modélisation a été validée et est maintenant en cours de traitement.</p>
        <p><strong>Crédits débités : {credits}</strong></p>
        <p>Vous serez notifié dès que la modélisation sera terminée.</p>
        <p>Cordialement,<br>L'équipe Figurative</p>
        """
        
        send_email_to_contact(
            contact_id=contact_id,
            subject=f"Re: {ticket.get('subject', 'Votre demande')} - Modélisation en cours",
            body_html=confirmation_html,
            ticket_id=ticket_id
        )
        
        logger.info(f"✅ Ticket {ticket_id} validated, subtask {subtask_id} created")
        
        return {
            "success": True,
            "ticket_id": ticket_id,
            "subtask_id": subtask_id,
            "credits": credits
        }
    else:
        return {
            "success": False,
            "error": subtask_result.get("error", "Subtask creation failed")
        }


def process_rejection(ticket_id: str, reason: str = "") -> Dict:
    """
    Process a rejected request: update ticket status.
    """
    logger.info(f"Processing rejection for ticket {ticket_id}")
    
    update_ticket_property(ticket_id, "validation_status", "rejected")
    
    return {
        "success": True,
        "ticket_id": ticket_id,
        "status": "rejected",
        "reason": reason
    }


def process_info_response(ticket_id: str, new_info: str) -> Dict:
    """
    Process additional info from client: re-analyze and send quote if complete.
    """
    logger.info(f"Processing info response for ticket {ticket_id}")
    
    ticket = get_ticket_details(ticket_id)
    if not ticket:
        return {"success": False, "error": "Ticket not found"}
    
    contact_id = ticket.get("contact_id")
    
    # Re-analyze with new info appended
    original_content = ticket.get("content", "")
    updated_description = f"{original_content}\n\n[Informations complémentaires du client:]\n{new_info}"
    
    # For now, we'll assume the new info makes it complete
    # In production, you'd re-run analyze_request with updated data
    
    # Get credits estimate from ticket
    credits = int(ticket.get("credits_estimes") or 2)
    
    # Update ticket and send quote
    update_ticket_property(ticket_id, "validation_status", "pending_credits")
    
    quote_html = f"""
    <p>Bonjour,</p>
    <p>Merci pour ces informations complémentaires.</p>
    <p>Après analyse, le coût estimé pour votre modélisation est de :</p>
    <p><strong style='font-size: 18px;'>➤ {credits} crédit{'s' if credits > 1 else ''}</strong></p>
    <p>Pour confirmer et lancer la modélisation, merci de répondre à cet email avec votre validation.</p>
    <p>Cordialement,<br>L'équipe Figurative</p>
    """
    
    if contact_id:
        send_email_to_contact(
            contact_id=contact_id,
            subject=f"Re: {ticket.get('subject', 'Votre demande')} - Devis modélisation",
            body_html=quote_html,
            ticket_id=ticket_id
        )
    
    return {
        "success": True,
        "ticket_id": ticket_id,
        "new_status": "pending_credits",
        "credits": credits
    }


# =============================================================================
# POLLING LOOP
# =============================================================================

def poll_pending_tickets(interval_seconds: int = 60):
    """
    Main polling loop: check pending tickets for new responses.
    """
    logger.info(f"Starting validation polling (interval: {interval_seconds}s)")
    
    last_check = {}  # ticket_id -> last check time
    
    while True:
        try:
            # Find all pending tickets
            pending = find_pending_validation_tickets()
            
            for ticket in pending:
                ticket_id = ticket["ticket_id"]
                status = ticket["validation_status"]
                
                # Check for new responses
                last_time = last_check.get(ticket_id)
                response = check_ticket_for_response(ticket_id, last_time)
                
                if response.get("has_new_response"):
                    logger.info(f"📬 New response for ticket {ticket_id}: {response.get('response_type')}")
                    
                    response_type = response.get("response_type")
                    
                    if response_type == "validation":
                        # Client validated - process
                        credits = int(ticket.get("credits_estimes") or 2)
                        process_validation(ticket_id, credits)
                    
                    elif response_type == "rejection":
                        # Client rejected
                        process_rejection(ticket_id, response.get("message_text", ""))
                    
                    elif response_type == "question":
                        # Client has questions - log for manual handling
                        logger.info(f"❓ Client has questions for ticket {ticket_id}")
                    
                    elif status == "pending_info":
                        # New info received
                        process_info_response(ticket_id, response.get("message_text", ""))
                
                # Update last check time
                last_check[ticket_id] = datetime.now()
            
            # Wait before next poll
            logger.info(f"💤 Sleeping {interval_seconds}s...")
            time.sleep(interval_seconds)
            
        except KeyboardInterrupt:
            logger.info("Polling stopped by user")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(interval_seconds)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Validation Workflow Orchestrator")
    parser.add_argument("--mode", required=True,
                        choices=["poll", "check", "process-response", "list-pending"],
                        help="Operation mode")
    parser.add_argument("--interval", type=int, default=60,
                        help="Polling interval in seconds (for poll mode)")
    parser.add_argument("--ticket-id", help="Ticket ID (for check/process modes)")
    parser.add_argument("--response", help="Client response text (for process-response mode)")
    parser.add_argument("--credits", type=int, help="Credits to validate (for manual validation)")
    
    args = parser.parse_args()
    
    if args.mode == "poll":
        poll_pending_tickets(args.interval)
    
    elif args.mode == "list-pending":
        tickets = find_pending_validation_tickets()
        print(f"\n📋 Pending Validation Tickets: {len(tickets)}")
        for t in tickets:
            print(f"  - #{t['ticket_id']}: {t['subject'][:40]}... ({t['validation_status']})")
        print(json.dumps(tickets, indent=2, ensure_ascii=False))
    
    elif args.mode == "check":
        if not args.ticket_id:
            print("❌ --ticket-id required for check mode")
            sys.exit(1)
        
        response = check_ticket_for_response(args.ticket_id)
        print(f"\n🔍 Check result for ticket {args.ticket_id}:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
    
    elif args.mode == "process-response":
        if not args.ticket_id:
            print("❌ --ticket-id required")
            sys.exit(1)
        
        if args.credits:
            # Manual validation with specific credits
            result = process_validation(args.ticket_id, args.credits)
        elif args.response:
            # Process text response
            detection = detect_validation_response(args.response)
            print(f"Detected: {detection}")
            
            if detection.get("type") == "validation":
                credits = args.credits or 2
                result = process_validation(args.ticket_id, credits)
            elif detection.get("type") == "rejection":
                result = process_rejection(args.ticket_id, args.response)
            else:
                result = {"message": "Response type unclear, manual review needed"}
        else:
            print("❌ --response or --credits required")
            sys.exit(1)
        
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
