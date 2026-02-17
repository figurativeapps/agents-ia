"""
Test script for Request Handler workflow.
Tests each component individually without making actual API calls.

Usage:
    python test_request_handler.py
    python test_request_handler.py --live  # Run with actual API calls
"""

import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
load_dotenv()

# Test payloads
TEST_PAYLOADS = {
    "support_simple": {
        "source": "contact",
        "objet": "Probleme de paiement",
        "description": "Je n'arrive pas a payer mon abonnement avec ma carte bancaire.",
        "user_email": "test@example.com",
        "user_name": "Jean Dupont",
        "fichiers": []
    },
    "modelisation_with_files": {
        "source": "modelisation",
        "objet": "Demande de modelisation chaise design",
        "description": "Je souhaite faire modeliser une chaise pour la visualiser en AR.",
        "user_email": "designer@example.com",
        "user_name": "Marie Martin",
        "fichiers": [
            {"name": "chaise_photo.jpg", "url": "https://example.com/chaise.jpg"},
            {"name": "chaise_3d.glb", "url": "https://example.com/chaise.glb"}
        ]
    },
    "support_via_modelisation_form": {
        "source": "modelisation",
        "objet": "Question sur mon compte",
        "description": "Comment puis-je modifier mon mot de passe?",
        "user_email": "confused@example.com",
        "user_name": "Pierre Durand",
        "fichiers": []
    },
    # Nouveau payload réaliste pour test de modélisation
    "modelisation_realiste": {
        "source": "modelisation",
        "objet": "Modélisation 3D lampe de bureau design scandinave",
        "description": """Bonjour,

Je suis designer d'intérieur et je travaille actuellement sur un projet d'aménagement pour un client corporate.

J'aurais besoin de faire modéliser une lampe de bureau design scandinave que j'ai sélectionnée pour ce projet. Le client souhaite pouvoir visualiser cette lampe en réalité augmentée directement dans ses bureaux avant de passer commande.

Je vous joins :
1. Une photo haute résolution de la lampe (vue de face)
2. Les dimensions techniques au format PDF

Dimensions approximatives :
- Hauteur totale : 45 cm
- Diamètre abat-jour : 25 cm
- Base : 15 cm de diamètre

Matériaux : 
- Pied en laiton brossé
- Abat-jour en tissu lin beige

Merci de me confirmer la faisabilité et le délai estimé.

Cordialement,
Sophie Lemaire
Studio Intérieurs & Espaces""",
        "user_email": "sophie.lemaire@studioie.fr",
        "user_name": "Sophie Lemaire",
        "fichiers": [
            {
                "name": "lampe_scandinave_HD.jpg",
                "url": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=800",
                "type": "image/jpeg",
                "size": 245000
            },
            {
                "name": "dimensions_techniques.pdf",
                "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
                "type": "application/pdf",
                "size": 13264
            }
        ]
    },
    # Payload pour tester le threading (réponse à un ticket existant)
    "modelisation_followup": {
        "source": "modelisation",
        "objet": "RE: Modélisation 3D lampe de bureau design scandinave",
        "description": """Bonjour,

Suite à notre échange, voici les informations complémentaires demandées :

- Le fil électrique est de couleur noire tressée
- L'interrupteur est intégré sur le fil à 30cm de la base
- J'ai ajouté une photo supplémentaire montrant le détail du pied

Merci !
Sophie""",
        "user_email": "sophie.lemaire@studioie.fr",
        "user_name": "Sophie Lemaire",
        "fichiers": [
            {
                "name": "detail_pied_lampe.jpg",
                "url": "https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=800",
                "type": "image/jpeg",
                "size": 180000
            }
        ]
    }
}


def check_env_variables():
    """Check if required environment variables are set"""
    print("\n" + "="*60)
    print("ENVIRONMENT VARIABLES CHECK")
    print("="*60)
    
    required_vars = {
        "ANTHROPIC_API_KEY": "Classification LLM",
        "HUBSPOT_API_KEY": "HubSpot integration",
        "CLICKUP_API_KEY": "ClickUp integration",
    }
    
    optional_vars = {
        "R2_ACCESS_KEY_ID": "Cloudflare R2",
        "R2_SECRET_ACCESS_KEY": "Cloudflare R2",
        "R2_BUCKET_NAME": "Cloudflare R2",
        "R2_ENDPOINT_URL": "Cloudflare R2",
        "SMTP_USER": "Email notifications",
        "SMTP_PASSWORD": "Email notifications",
    }
    
    all_ok = True
    
    print("\nRequired:")
    for var, purpose in required_vars.items():
        value = os.getenv(var)
        if value:
            masked = value[:4] + "..." + value[-4:] if len(value) > 10 else "***"
            print(f"  [OK] {var}: {masked} ({purpose})")
        else:
            print(f"  [MISSING] {var} ({purpose})")
            all_ok = False
    
    print("\nOptional:")
    for var, purpose in optional_vars.items():
        value = os.getenv(var)
        if value:
            print(f"  [OK] {var} ({purpose})")
        else:
            print(f"  [--] {var} not set ({purpose})")
    
    return all_ok


def test_classification(payload: dict, live: bool = False):
    """Test the classification module"""
    print("\n" + "="*60)
    print("TEST: Classification")
    print("="*60)
    
    print(f"\nPayload: {payload['objet']}")
    print(f"Source: {payload['source']}")
    print(f"Files: {len(payload['fichiers'])} file(s)")
    
    if live:
        from classify_request import classify_request
        result = classify_request(
            objet=payload['objet'],
            description=payload['description'],
            fichiers=payload['fichiers'],
            source=payload['source']
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call classify_request()")
        return {
            "type_final": "SUPPORT" if payload['source'] == "contact" else "MODELISATION",
            "confiance": 85,
            "reclassifie": False
        }


def test_hubspot_contact(payload: dict, live: bool = False):
    """Test HubSpot contact lookup/creation"""
    print("\n" + "="*60)
    print("TEST: HubSpot Contact")
    print("="*60)
    
    print(f"\nEmail: {payload['user_email']}")
    print(f"Name: {payload['user_name']}")
    
    if live:
        from hubspot_ticket import find_or_create_contact
        result = find_or_create_contact(
            email=payload['user_email'],
            name=payload['user_name']
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call find_or_create_contact()")
        return {"contact_id": "12345", "created": False}


def test_hubspot_ticket(contact_id: str, payload: dict, classification: dict, live: bool = False):
    """Test HubSpot ticket creation"""
    print("\n" + "="*60)
    print("TEST: HubSpot Ticket")
    print("="*60)
    
    print(f"\nContact ID: {contact_id}")
    print(f"Type: {classification['type_final']}")
    print(f"Subject: {payload['objet']}")
    
    if live:
        from hubspot_ticket import create_ticket
        result = create_ticket(
            contact_id=contact_id,
            type_final=classification['type_final'],
            objet=payload['objet'],
            description=payload['description'],
            fichiers_urls=[],
            source_formulaire=payload['source'],
            reclassifie=classification.get('reclassifie', False)
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call create_ticket()")
        return {"ticket_id": "67890", "ticket_url": "https://app.hubspot.com/contacts/XXX/ticket/67890"}


def test_hubspot_note(contact_id: str, ticket_id: str, payload: dict, fichiers_urls: list, classification: dict, live: bool = False):
    """Test HubSpot note creation with file URLs"""
    print("\n" + "="*60)
    print("TEST: HubSpot Note (fichiers sur fiche contact)")
    print("="*60)
    
    print(f"\nContact ID: {contact_id}")
    print(f"Ticket ID: {ticket_id}")
    print(f"Files: {len(fichiers_urls)} URL(s)")
    for url in fichiers_urls:
        print(f"  - {url}")
    
    if live:
        from hubspot_ticket import create_note
        result = create_note(
            contact_id=contact_id,
            objet=payload['objet'],
            fichiers_urls=fichiers_urls,
            ticket_id=ticket_id,
            type_demande=classification['type_final']
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call create_note()")
        return {"note_id": "note123", "success": True}


def test_clickup_subtask(payload: dict, ticket_url: str, fichiers_urls: list = None, live: bool = False):
    """Test ClickUp subtask creation"""
    print("\n" + "="*60)
    print("TEST: ClickUp Subtask")
    print("="*60)
    
    print(f"\nEmail: {payload['user_email']}")
    print(f"Objet: {payload['objet']}")
    print(f"Description: {payload['description'][:80]}..." if len(payload.get('description', '')) > 80 else f"Description: {payload.get('description', '')}")
    print(f"Fichiers: {len(fichiers_urls or [])} URL(s)")
    print(f"Ticket URL: {ticket_url}")
    
    if live:
        from clickup_subtask import create_subtask
        result = create_subtask(
            objet=payload['objet'],
            user_email=payload['user_email'],
            ticket_url=ticket_url,
            description=payload.get('description', ''),
            fichiers_urls=fichiers_urls or []
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call create_subtask()")
        return {"subtask_id": "abc123", "subtask_url": "https://app.clickup.com/t/abc123", "success": True}


def test_notification(payload: dict, ticket_url: str, classification: dict, live: bool = False):
    """Test notification sending"""
    print("\n" + "="*60)
    print("TEST: Notification")
    print("="*60)
    
    notification_email = os.getenv("NOTIFICATION_EMAIL", "yvanol.fotso@valione-services.com")
    print(f"\nTo: {notification_email}")
    print(f"Type: {classification['type_final']}")
    print(f"Reclassifie: {classification.get('reclassifie', False)}")
    
    if live:
        from send_notification import send_notification
        result = send_notification(
            ticket_url=ticket_url,
            type_final=classification['type_final'],
            objet=payload['objet'],
            user_email=payload['user_email'],
            reclassifie=classification.get('reclassifie', False)
        )
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    else:
        print("\n[DRY RUN] Would call send_notification()")
        return {"sent": True, "method": "smtp", "to": notification_email}


def run_full_test(payload_name: str = "support_simple", live: bool = False):
    """Run complete workflow test"""
    print("\n" + "#"*60)
    print(f"FULL WORKFLOW TEST: {payload_name}")
    print(f"Mode: {'LIVE' if live else 'DRY RUN'}")
    print("#"*60)
    
    payload = TEST_PAYLOADS[payload_name]
    
    # Step 1: Check environment
    env_ok = check_env_variables()
    if live and not env_ok:
        print("\n[ERROR] Missing required environment variables for live test")
        return
    
    # Step 2: Classification
    classification = test_classification(payload, live)
    
    # Step 3: HubSpot Contact
    contact_result = test_hubspot_contact(payload, live)
    contact_id = contact_result.get("contact_id")
    
    # Step 4: HubSpot Ticket (avec URLs fichiers si présents)
    # Note: En production, les fichiers seraient uploadés sur R2 avant cette étape
    # et on passerait les URLs R2 ici. Pour le test, on simule avec des URLs fictives.
    fichiers_urls = []
    if payload.get('fichiers'):
        fichiers_urls = [f"https://pub-xxx.r2.dev/requests/test/{f['name']}" for f in payload['fichiers']]
    
    ticket_result = test_hubspot_ticket(contact_id, payload, classification, live)
    ticket_id = ticket_result.get("ticket_id", "67890")
    ticket_url = ticket_result.get("ticket_url", "https://example.com/ticket/123")
    
    # Step 5: HubSpot Note (only if files present)
    if fichiers_urls:
        note_result = test_hubspot_note(contact_id, ticket_id, payload, fichiers_urls, classification, live)
    else:
        print("\n" + "="*60)
        print("SKIP: HubSpot Note (no files in request)")
        print("="*60)
    
    # Step 6: ClickUp (only for MODELISATION)
    if classification['type_final'] == "MODELISATION":
        clickup_result = test_clickup_subtask(payload, ticket_url, fichiers_urls, live)
    else:
        print("\n" + "="*60)
        print("SKIP: ClickUp Subtask (not a MODELISATION request)")
        print("="*60)
    
    # Step 7: Notification
    notification_result = test_notification(payload, ticket_url, classification, live)
    
    print("\n" + "#"*60)
    print("TEST COMPLETE")
    print("#"*60)


def main():
    parser = argparse.ArgumentParser(description="Test Request Handler workflow")
    parser.add_argument("--live", action="store_true", help="Run with actual API calls")
    parser.add_argument("--payload", choices=list(TEST_PAYLOADS.keys()), 
                        default="support_simple", help="Test payload to use")
    parser.add_argument("--all", action="store_true", help="Test all payloads")
    
    args = parser.parse_args()
    
    if args.all:
        for payload_name in TEST_PAYLOADS.keys():
            run_full_test(payload_name, args.live)
            print("\n" + "="*60 + "\n")
    else:
        run_full_test(args.payload, args.live)


if __name__ == "__main__":
    main()
