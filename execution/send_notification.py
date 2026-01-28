"""
Admin Notification System
Sends email notifications when new requests are processed.

Usage:
    python send_notification.py --ticket-url "https://..." --type MODELISATION --objet "Title" --email "client@example.com"
"""

import os
import sys
import json
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from hubspot import HubSpot

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
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "yvanol.fotso@valione-services.com")

# SMTP Configuration (fallback if HubSpot not available)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@figurative.fr")


def build_email_content(
    ticket_url: str,
    type_final: str,
    objet: str,
    user_email: str,
    reclassifie: bool = False
) -> tuple[str, str, str]:
    """Build email subject and body (plain + HTML)"""
    
    # Subject
    prefix = "[RECLASSIFIE] " if reclassifie else ""
    subject = f"{prefix}[Figurative] Nouvelle demande {type_final} - {objet}"
    
    # Plain text body
    plain_body = f"""Nouvelle demande reçue

Type : {type_final}
Client : {user_email}
Objet : {objet}
"""
    
    if reclassifie:
        plain_body += """
ATTENTION : Cette demande a été reclassifiée par l'IA 
(le formulaire utilisé ne correspondait pas au contenu).
"""
    
    plain_body += f"""
Voir le ticket : {ticket_url}

---
Notification automatique - Agent DOE Figurative
"""
    
    # HTML body
    reclassifie_warning = ""
    if reclassifie:
        reclassifie_warning = """
        <p style="color: #d97706; background: #fef3c7; padding: 10px; border-radius: 4px;">
            <strong>Attention :</strong> Cette demande a été reclassifiée par l'IA 
            (le formulaire utilisé ne correspondait pas au contenu).
        </p>
        """
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #1f2937; }}
            .info {{ margin: 15px 0; }}
            .info strong {{ color: #4b5563; }}
            .button {{ 
                display: inline-block; 
                background: #3b82f6; 
                color: white !important; 
                padding: 12px 24px; 
                text-decoration: none; 
                border-radius: 6px;
                margin-top: 20px;
            }}
            .footer {{ 
                margin-top: 30px; 
                padding-top: 20px; 
                border-top: 1px solid #e5e7eb; 
                font-size: 12px; 
                color: #9ca3af; 
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Nouvelle demande reçue</h2>
            
            <div class="info">
                <p><strong>Type :</strong> {type_final}</p>
                <p><strong>Client :</strong> {user_email}</p>
                <p><strong>Objet :</strong> {objet}</p>
            </div>
            
            {reclassifie_warning}
            
            <a href="{ticket_url}" class="button">Voir le ticket dans HubSpot</a>
            
            <div class="footer">
                Notification automatique - Agent DOE Figurative
            </div>
        </div>
    </body>
    </html>
    """
    
    return subject, plain_body, html_body


def send_via_hubspot(
    to_email: str,
    subject: str,
    html_body: str,
    contact_id: str = None
) -> bool:
    """Send email via HubSpot API (logged as engagement)"""
    try:
        client = HubSpot(access_token=HUBSPOT_API_KEY)
        
        # HubSpot transactional email would go here
        # For now, we'll use the engagement API to log it
        # Note: Actual email sending requires Marketing Hub or Transactional Email add-on
        
        print(f"⚠️  HubSpot transactional email not configured - using SMTP fallback")
        return False
        
    except Exception as e:
        print(f"⚠️  HubSpot email failed: {str(e)[:100]}")
        return False


def send_via_smtp(
    to_email: str,
    subject: str,
    plain_body: str,
    html_body: str
) -> bool:
    """Send email via SMTP"""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("⚠️  SMTP not configured - notification not sent")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = to_email
        
        msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"❌ SMTP error: {str(e)[:200]}")
        return False


def send_notification(
    ticket_url: str,
    type_final: str,
    objet: str,
    user_email: str,
    reclassifie: bool = False,
    to_email: str = None
) -> dict:
    """
    Send notification email to admin.
    
    Args:
        ticket_url: HubSpot ticket URL
        type_final: SUPPORT or MODELISATION
        objet: Request title
        user_email: Client email
        reclassifie: Was reclassified by AI
        to_email: Override recipient (default: NOTIFICATION_EMAIL)
    
    Returns:
        {
            "sent": bool,
            "method": "hubspot" | "smtp" | "none",
            "to": str
        }
    """
    recipient = to_email or NOTIFICATION_EMAIL
    
    print(f"📧 Sending notification to {recipient}")
    
    subject, plain_body, html_body = build_email_content(
        ticket_url=ticket_url,
        type_final=type_final,
        objet=objet,
        user_email=user_email,
        reclassifie=reclassifie
    )
    
    # Try HubSpot first
    if HUBSPOT_API_KEY:
        if send_via_hubspot(recipient, subject, html_body):
            return {"sent": True, "method": "hubspot", "to": recipient}
    
    # Fallback to SMTP
    if send_via_smtp(recipient, subject, plain_body, html_body):
        return {"sent": True, "method": "smtp", "to": recipient}
    
    # Both failed
    print("⚠️  Notification could not be sent (no method available)")
    return {"sent": False, "method": "none", "to": recipient}


def main():
    parser = argparse.ArgumentParser(description="Send admin notification")
    parser.add_argument("--ticket-url", required=True, help="HubSpot ticket URL")
    parser.add_argument("--type", required=True, choices=["SUPPORT", "MODELISATION"], help="Request type")
    parser.add_argument("--objet", required=True, help="Request title")
    parser.add_argument("--email", required=True, help="Client email")
    parser.add_argument("--reclassifie", action="store_true", help="Was reclassified")
    parser.add_argument("--to", help="Override recipient email")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    result = send_notification(
        ticket_url=args.ticket_url,
        type_final=args.type,
        objet=args.objet,
        user_email=args.email,
        reclassifie=args.reclassifie,
        to_email=args.to
    )
    
    print(json.dumps(result, indent=2))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
