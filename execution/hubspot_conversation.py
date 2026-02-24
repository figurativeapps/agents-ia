"""
HubSpot Conversations - Lecture et envoi d'emails
Permet à l'IA de communiquer avec les clients via HubSpot.

Approche:
1. Envoi réel via SMTP (le prospect reçoit l'email)
2. Consignation dans HubSpot via API Engagements (tracking CRM)

Usage:
    python hubspot_conversation.py --action get_messages --contact-email "user@example.com"
    python hubspot_conversation.py --action send_reply --ticket-id 123 --message "Votre réponse"
    python hubspot_conversation.py --action check_scopes
"""

import os
import sys
import json
import argparse
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dotenv import load_dotenv
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
HUBSPOT_HUB_ID = os.getenv("HUBSPOT_HUB_ID", "147476643")
BASE_URL = "https://api.hubapi.com"

# Email configuration
SENDER_EMAIL = os.getenv("HUBSPOT_SENDER_EMAIL", "jordane.pellerin@figurative.fr")
SENDER_NAME = os.getenv("HUBSPOT_SENDER_NAME", "Figurative Support")

# SMTP configuration for real email delivery
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


def _smtp_configured() -> bool:
    """Check if SMTP credentials are available."""
    return bool(SMTP_USER and SMTP_PASSWORD)


def _send_smtp_email(to_email: str, subject: str, body_html: str) -> dict:
    """
    Send an email via SMTP so the recipient actually receives it.
    Uses SENDER_EMAIL as From address (should match HubSpot connected email
    so replies are auto-captured as INCOMING in HubSpot).

    Returns:
        {"sent": bool, "error": str | None}
    """
    if not _smtp_configured():
        print("⚠️  SMTP not configured (SMTP_USER/SMTP_PASSWORD missing) — email will only be logged in HubSpot")
        return {"sent": False, "error": "SMTP not configured"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"] = to_email
        msg["Reply-To"] = SENDER_EMAIL

        plain_text = body_html.replace("<br>", "\n").replace("<br/>", "\n")
        plain_text = plain_text.replace("<p>", "").replace("</p>", "\n")
        plain_text = plain_text.replace("<strong>", "").replace("</strong>", "")
        plain_text = plain_text.replace("<em>", "").replace("</em>", "")

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ SMTP email sent to {to_email}")
        return {"sent": True, "error": None}

    except Exception as e:
        print(f"❌ SMTP send failed: {e}")
        return {"sent": False, "error": str(e)}


def get_headers() -> dict:
    """Get authorization headers for HubSpot API"""
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env")
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json"
    }


# =============================================================================
# SCOPE VERIFICATION
# =============================================================================

def check_available_scopes() -> dict:
    """
    Check which HubSpot API scopes are available.
    Returns dict with available features.
    """
    scopes = {
        "conversations_read": False,
        "conversations_write": False,
        "crm_objects_contacts": False,
        "crm_objects_tickets": False,
        "sales_email_read": False,
        "sales_email_write": False
    }
    
    # Test Conversations API (read)
    try:
        response = requests.get(
            f"{BASE_URL}/conversations/v3/conversations/threads",
            headers=get_headers(),
            params={"limit": 1},
            timeout=10
        )
        if response.status_code == 200:
            scopes["conversations_read"] = True
        elif response.status_code == 403:
            print("⚠️  conversations.read scope not available")
    except Exception as e:
        print(f"⚠️  Conversations API check failed: {e}")
    
    # Test CRM Contacts API
    try:
        response = requests.get(
            f"{BASE_URL}/crm/v3/objects/contacts",
            headers=get_headers(),
            params={"limit": 1},
            timeout=10
        )
        if response.status_code == 200:
            scopes["crm_objects_contacts"] = True
    except Exception:
        pass
    
    # Test CRM Tickets API
    try:
        response = requests.get(
            f"{BASE_URL}/crm/v3/objects/tickets",
            headers=get_headers(),
            params={"limit": 1},
            timeout=10
        )
        if response.status_code == 200:
            scopes["crm_objects_tickets"] = True
    except Exception:
        pass
    
    # Test Engagements API (for email sending)
    try:
        response = requests.get(
            f"{BASE_URL}/engagements/v1/engagements/recent/modified",
            headers=get_headers(),
            params={"count": 1},
            timeout=10
        )
        if response.status_code == 200:
            scopes["sales_email_read"] = True
    except Exception:
        pass
    
    return scopes


# =============================================================================
# GET CONTACT INFO
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_contact_by_email(email: str) -> Optional[dict]:
    """Get contact ID and details by email"""
    try:
        response = requests.post(
            f"{BASE_URL}/crm/v3/objects/contacts/search",
            headers=get_headers(),
            json={
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": email
                    }]
                }],
                "properties": ["email", "firstname", "lastname", "hs_object_id"]
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("total", 0) > 0:
                contact = data["results"][0]
                return {
                    "contact_id": contact["id"],
                    "email": contact["properties"].get("email"),
                    "firstname": contact["properties"].get("firstname", ""),
                    "lastname": contact["properties"].get("lastname", "")
                }
        return None
        
    except Exception as e:
        print(f"❌ Error getting contact: {e}")
        return None


# =============================================================================
# GET TICKET INFO
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_ticket_details(ticket_id: str) -> Optional[dict]:
    """Get ticket details including associated contact"""
    try:
        # Get ticket properties
        response = requests.get(
            f"{BASE_URL}/crm/v3/objects/tickets/{ticket_id}",
            headers=get_headers(),
            params={
                "properties": "subject,content,hs_pipeline_stage,validation_status,createdate,hs_lastmodifieddate"
            },
            timeout=15
        )
        
        if response.status_code != 200:
            print(f"❌ Ticket not found: {ticket_id}")
            return None
        
        ticket = response.json()
        
        # Get associated contact
        assoc_response = requests.get(
            f"{BASE_URL}/crm/v4/objects/tickets/{ticket_id}/associations/contacts",
            headers=get_headers(),
            timeout=15
        )
        
        contact_id = None
        if assoc_response.status_code == 200:
            assoc_data = assoc_response.json()
            if assoc_data.get("results"):
                contact_id = assoc_data["results"][0].get("toObjectId")
        
        return {
            "ticket_id": ticket_id,
            "subject": ticket["properties"].get("subject", ""),
            "content": ticket["properties"].get("content", ""),
            "stage": ticket["properties"].get("hs_pipeline_stage", ""),
            "validation_status": ticket["properties"].get("validation_status", ""),
            "contact_id": contact_id,
            "created": ticket["properties"].get("createdate"),
            "modified": ticket["properties"].get("hs_lastmodifieddate")
        }
        
    except Exception as e:
        print(f"❌ Error getting ticket: {e}")
        return None


# =============================================================================
# GET MESSAGES (via Engagements API)
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_recent_emails_for_contact(contact_id: str, days: int = 7) -> List[dict]:
    """
    Get recent email engagements for a contact.
    Uses the Engagements API as fallback when Conversations API is unavailable.
    """
    emails = []
    
    try:
        # Get engagements associated with contact
        response = requests.get(
            f"{BASE_URL}/crm/v4/objects/contacts/{contact_id}/associations/emails",
            headers=get_headers(),
            timeout=15
        )
        
        if response.status_code != 200:
            print(f"⚠️  Could not get email associations: {response.status_code}")
            return emails
        
        assoc_data = response.json()
        email_ids = [r.get("toObjectId") for r in assoc_data.get("results", [])]
        
        if not email_ids:
            return emails
        
        # Fetch email details (batch)
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for email_id in email_ids[:20]:  # Limit to recent 20
            try:
                email_response = requests.get(
                    f"{BASE_URL}/crm/v3/objects/emails/{email_id}",
                    headers=get_headers(),
                    params={
                        "properties": "hs_email_subject,hs_email_text,hs_email_html,hs_email_direction,hs_timestamp,hs_email_sender_email,hs_email_to_email"
                    },
                    timeout=10
                )
                
                if email_response.status_code == 200:
                    email_data = email_response.json()
                    props = email_data.get("properties", {})
                    
                    # Parse timestamp
                    timestamp_str = props.get("hs_timestamp", "")
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        if timestamp.replace(tzinfo=None) < cutoff_date:
                            continue
                    except (ValueError, TypeError):
                        pass
                    
                    emails.append({
                        "id": email_id,
                        "subject": props.get("hs_email_subject", ""),
                        "body_text": props.get("hs_email_text", ""),
                        "body_html": props.get("hs_email_html", ""),
                        "direction": props.get("hs_email_direction", ""),  # INCOMING or OUTGOING
                        "timestamp": timestamp_str,
                        "from_email": props.get("hs_email_sender_email", ""),
                        "to_email": props.get("hs_email_to_email", "")
                    })
                    
            except Exception as e:
                print(f"⚠️  Error fetching email {email_id}: {e}")
                continue
        
        # Sort by timestamp (newest first)
        emails.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return emails
        
    except Exception as e:
        print(f"❌ Error getting emails: {e}")
        return emails


def get_messages_for_ticket(ticket_id: str, days: int = 7) -> List[dict]:
    """
    Get all email messages related to a ticket.
    First gets the associated contact, then fetches their emails.
    """
    ticket = get_ticket_details(ticket_id)
    if not ticket:
        return []
    
    contact_id = ticket.get("contact_id")
    if not contact_id:
        print(f"⚠️  No contact associated with ticket {ticket_id}")
        return []
    
    return get_recent_emails_for_contact(contact_id, days)


# =============================================================================
# SEND EMAIL REPLY
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def send_email_to_contact(
    contact_id: str,
    subject: str,
    body_html: str,
    ticket_id: Optional[str] = None
) -> dict:
    """
    Send an email to a contact: real delivery via SMTP + CRM logging via HubSpot Engagements.

    Flow:
    1. Resolve contact email from HubSpot
    2. Send the email via SMTP (actual delivery to inbox)
    3. Log the email as an Engagement in HubSpot (CRM tracking)

    The SMTP sender address must match the HubSpot-connected mailbox so that
    prospect replies are automatically captured as INCOMING emails in HubSpot.

    Args:
        contact_id: HubSpot contact ID
        subject: Email subject
        body_html: HTML body content
        ticket_id: Optional ticket ID to associate

    Returns:
        {"success": bool, "email_id": str, "error": str, "smtp_sent": bool}
    """
    try:
        # Get contact email
        contact_response = requests.get(
            f"{BASE_URL}/crm/v3/objects/contacts/{contact_id}",
            headers=get_headers(),
            params={"properties": "email,firstname,lastname"},
            timeout=10
        )

        if contact_response.status_code != 200:
            return {"success": False, "error": "Contact not found"}

        contact_data = contact_response.json()
        to_email = contact_data["properties"].get("email")

        if not to_email:
            return {"success": False, "error": "Contact has no email"}

        # --- Step 1: Send the email via SMTP (real delivery) ---
        smtp_result = _send_smtp_email(to_email, subject, body_html)
        smtp_sent = smtp_result.get("sent", False)

        if not smtp_sent:
            print(f"⚠️  SMTP delivery failed — will still log in HubSpot. Reason: {smtp_result.get('error')}")

        # --- Step 2: Log the email as HubSpot Engagement (CRM tracking) ---
        timestamp = int(datetime.now().timestamp() * 1000)

        engagement_data = {
            "engagement": {
                "active": True,
                "type": "EMAIL",
                "timestamp": timestamp
            },
            "associations": {
                "contactIds": [int(contact_id)]
            },
            "metadata": {
                "from": {
                    "email": SENDER_EMAIL,
                    "firstName": SENDER_NAME.split()[0] if SENDER_NAME else "Support",
                    "lastName": SENDER_NAME.split()[-1] if SENDER_NAME and len(SENDER_NAME.split()) > 1 else ""
                },
                "to": [{"email": to_email}],
                "subject": subject,
                "html": body_html,
                "text": body_html.replace("<br>", "\n").replace("<br/>", "\n")
            }
        }

        if ticket_id:
            engagement_data["associations"]["ticketIds"] = [int(ticket_id)]

        response = requests.post(
            f"{BASE_URL}/engagements/v1/engagements",
            headers=get_headers(),
            json=engagement_data,
            timeout=15
        )

        if response.status_code in [200, 201]:
            result = response.json()
            email_id = result.get("engagement", {}).get("id")
            print(f"✅ Email logged in HubSpot: {email_id}")
            return {
                "success": True,
                "smtp_sent": smtp_sent,
                "email_id": str(email_id),
                "to_email": to_email,
                "subject": subject
            }
        else:
            error_msg = response.text[:200]
            print(f"❌ HubSpot engagement creation failed: {response.status_code} - {error_msg}")
            return {
                "success": smtp_sent,
                "smtp_sent": smtp_sent,
                "error": f"HubSpot log failed: {error_msg}",
                "to_email": to_email
            }

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"success": False, "smtp_sent": False, "error": str(e)}


def send_reply_to_ticket(
    ticket_id: str,
    subject: str,
    body_html: str
) -> dict:
    """
    Send an email reply associated with a ticket.
    Gets the contact from the ticket and sends the email.
    """
    ticket = get_ticket_details(ticket_id)
    if not ticket:
        return {"success": False, "error": "Ticket not found"}
    
    contact_id = ticket.get("contact_id")
    if not contact_id:
        return {"success": False, "error": "No contact associated with ticket"}
    
    return send_email_to_contact(
        contact_id=contact_id,
        subject=subject,
        body_html=body_html,
        ticket_id=ticket_id
    )


# =============================================================================
# DETECT CLIENT VALIDATION RESPONSE
# =============================================================================

def detect_validation_response(message_text: str) -> dict:
    """
    Analyze a client's email response to detect validation or rejection.
    
    Returns:
        {
            "detected": bool,
            "type": "validation" | "rejection" | "question" | "unknown",
            "confidence": int (0-100)
        }
    """
    if not message_text:
        return {"detected": False, "type": "unknown", "confidence": 0}
    
    text_lower = message_text.lower()
    
    # Validation keywords (French)
    validation_keywords = [
        "je valide", "j'accepte", "ok pour", "c'est bon", "d'accord",
        "je confirme", "validé", "accepté", "go", "on y va",
        "parfait", "ça me va", "je suis d'accord", "oui"
    ]
    
    # Rejection keywords (French)
    rejection_keywords = [
        "je refuse", "trop cher", "non merci", "pas d'accord",
        "annuler", "j'annule", "trop de crédits", "pas possible",
        "je ne valide pas", "refusé"
    ]
    
    # Question keywords
    question_keywords = [
        "pourquoi", "comment", "est-ce que", "pouvez-vous",
        "?", "je ne comprends pas", "expliquez"
    ]
    
    # Check for validation
    for kw in validation_keywords:
        if kw in text_lower:
            return {"detected": True, "type": "validation", "confidence": 85}
    
    # Check for rejection
    for kw in rejection_keywords:
        if kw in text_lower:
            return {"detected": True, "type": "rejection", "confidence": 85}
    
    # Check for questions
    for kw in question_keywords:
        if kw in text_lower:
            return {"detected": True, "type": "question", "confidence": 70}
    
    return {"detected": False, "type": "unknown", "confidence": 30}


# =============================================================================
# MAIN CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="HubSpot Conversations Management")
    parser.add_argument("--action", required=True,
                        choices=["check_scopes", "get_messages", "send_reply", "get_ticket"],
                        help="Action to perform")
    parser.add_argument("--contact-email", help="Contact email address")
    parser.add_argument("--contact-id", help="Contact ID")
    parser.add_argument("--ticket-id", help="Ticket ID")
    parser.add_argument("--subject", help="Email subject")
    parser.add_argument("--message", help="Email message (HTML)")
    parser.add_argument("--days", type=int, default=7, help="Days to look back for messages")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    result = {}
    
    if args.action == "check_scopes":
        result = check_available_scopes()
        print("\n📋 Available HubSpot Scopes:")
        for scope, available in result.items():
            status = "✅" if available else "❌"
            print(f"  {status} {scope}")
    
    elif args.action == "get_messages":
        if args.ticket_id:
            result = {"messages": get_messages_for_ticket(args.ticket_id, args.days)}
        elif args.contact_id:
            result = {"messages": get_recent_emails_for_contact(args.contact_id, args.days)}
        elif args.contact_email:
            contact = get_contact_by_email(args.contact_email)
            if contact:
                result = {"messages": get_recent_emails_for_contact(contact["contact_id"], args.days)}
            else:
                result = {"error": "Contact not found", "messages": []}
        else:
            print("❌ Provide --ticket-id, --contact-id, or --contact-email")
            sys.exit(1)
        
        print(f"\n📧 Found {len(result.get('messages', []))} messages")
        for msg in result.get("messages", [])[:5]:
            direction = "📥" if msg.get("direction") == "INCOMING" else "📤"
            print(f"  {direction} {msg.get('subject', 'No subject')[:50]}")
    
    elif args.action == "get_ticket":
        if not args.ticket_id:
            print("❌ --ticket-id is required")
            sys.exit(1)
        result = get_ticket_details(args.ticket_id)
        if result:
            print(f"\n🎫 Ticket: {result.get('subject', 'No subject')}")
            print(f"   Stage: {result.get('stage')}")
            print(f"   Validation: {result.get('validation_status', 'N/A')}")
    
    elif args.action == "send_reply":
        if not args.ticket_id or not args.message:
            print("❌ --ticket-id and --message are required")
            sys.exit(1)
        
        subject = args.subject or "Re: Votre demande de modélisation"
        result = send_reply_to_ticket(args.ticket_id, subject, args.message)
        
        if result.get("success"):
            print(f"✅ Email sent to {result.get('to_email')}")
        else:
            print(f"❌ Failed: {result.get('error')}")
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
