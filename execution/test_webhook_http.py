"""
Test script for Webhook HTTP integration.
Tests the webhook endpoint directly via HTTP requests.

Usage:
    python test_webhook_http.py --url http://localhost:5000
    python test_webhook_http.py --url http://server:5000 --live
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


# Test payloads
TEST_PAYLOADS = {
    "support_simple": {
        "source": "contact",
        "objet": "Problème de connexion à mon compte",
        "description": "Bonjour,\n\nJe n'arrive plus à me connecter à mon compte depuis ce matin.\nJ'ai essayé de réinitialiser mon mot de passe mais je ne reçois pas l'email.\n\nMerci de votre aide,\nJean",
        "user_email": "jean.test@example.com",
        "user_name": "Jean Test",
        "fichiers": []
    },
    "modelisation_simple": {
        "source": "modelisation",
        "objet": "Demande de modélisation - Vase décoratif",
        "description": "Bonjour,\n\nJe souhaite faire modéliser un vase décoratif pour ma boutique en ligne.\nJe voudrais pouvoir le visualiser en AR.\n\nCordialement,\nMarie",
        "user_email": "marie.test@example.com",
        "user_name": "Marie Test",
        "fichiers": []
    },
    "modelisation_with_files": {
        "source": "modelisation",
        "objet": "Modélisation 3D lampe design scandinave",
        "description": """Bonjour,

Je suis designer d'intérieur et je travaille sur un projet d'aménagement.

J'aurais besoin de faire modéliser une lampe de bureau design scandinave.
Le client souhaite la visualiser en réalité augmentée dans ses bureaux.

Dimensions approximatives :
- Hauteur totale : 45 cm
- Diamètre abat-jour : 25 cm
- Base : 15 cm de diamètre

Matériaux :
- Pied en laiton brossé
- Abat-jour en tissu lin beige

Merci de me confirmer la faisabilité.

Cordialement,
Sophie Lemaire
Studio Intérieurs & Espaces""",
        "user_email": "sophie.test@example.com",
        "user_name": "Sophie Test",
        "fichiers": [
            {
                "name": "lampe_photo.jpg",
                "url": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=800",
                "type": "image/jpeg",
                "size": 245000
            },
            {
                "name": "dimensions.pdf",
                "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
                "type": "application/pdf",
                "size": 13264
            }
        ]
    }
}


def test_health(base_url: str) -> bool:
    """Test the health endpoint"""
    print("\n" + "="*60)
    print("TEST: Health Check")
    print("="*60)
    
    url = f"{base_url}/health"
    print(f"\nGET {url}")
    
    try:
        response = requests.get(url, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nResponse:")
            print(json.dumps(data, indent=2))
            
            # Check features
            features = data.get("features", {})
            all_ok = all([
                features.get("classification"),
                features.get("hubspot"),
                features.get("clickup"),
                features.get("conversation_threading")
            ])
            
            if all_ok:
                print("\n✅ Server is healthy and all features are enabled")
                return True
            else:
                print("\n⚠️  Server is running but some features may be disabled")
                return True
        else:
            print(f"\n❌ Health check failed: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Could not connect to {base_url}")
        print("   Make sure the webhook server is running.")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def test_webhook(base_url: str, payload_name: str, live: bool = False) -> dict | None:
    """Test the webhook endpoint with a payload"""
    print("\n" + "="*60)
    print(f"TEST: Webhook - {payload_name}")
    print("="*60)
    
    payload = TEST_PAYLOADS[payload_name]
    url = f"{base_url}/webhook/request"
    
    print(f"\nPOST {url}")
    print(f"Source: {payload['source']}")
    print(f"Email: {payload['user_email']}")
    print(f"Subject: {payload['objet']}")
    print(f"Files: {len(payload.get('fichiers', []))}")
    
    if not live:
        print("\n[DRY RUN] Would send the following payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:500] + "...")
        return {"dry_run": True}
    
    try:
        print("\n📤 Sending request...")
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60  # 60s timeout for file uploads
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Response:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return data
        else:
            print(f"\n❌ Error response:")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text[:500])
            return None
            
    except requests.exceptions.Timeout:
        print("\n❌ Request timed out after 60 seconds")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


def test_threading(base_url: str, live: bool = False) -> bool:
    """Test conversation threading - send two requests from same email"""
    print("\n" + "#"*60)
    print("TEST: Conversation Threading")
    print("#"*60)
    
    # First request - should create new ticket
    print("\n--- First Request (should create new ticket) ---")
    payload1 = {
        "source": "modelisation",
        "objet": "Test threading - Demande initiale",
        "description": "Bonjour, je souhaite modéliser un produit pour mon e-commerce.",
        "user_email": "threading.test@example.com",
        "user_name": "Test Threading",
        "fichiers": []
    }
    
    if not live:
        print("[DRY RUN] Would send first request")
        print("[DRY RUN] Would send second request")
        print("[DRY RUN] Would verify both use the same ticket")
        return True
    
    result1 = requests.post(
        f"{base_url}/webhook/request",
        json=payload1,
        timeout=60
    )
    
    if result1.status_code != 200:
        print(f"❌ First request failed: {result1.status_code}")
        return False
    
    data1 = result1.json()
    print(f"✅ First request: {data1['status']}")
    print(f"   Ticket: {data1.get('ticket_id')}")
    print(f"   Is new: {data1.get('is_new_ticket')}")
    
    # Second request - should update existing ticket
    print("\n--- Second Request (should update existing ticket) ---")
    payload2 = {
        "source": "modelisation",
        "objet": "RE: Test threading - Demande initiale",
        "description": "Voici les informations complémentaires demandées.",
        "user_email": "threading.test@example.com",  # Same email
        "user_name": "Test Threading",
        "fichiers": []
    }
    
    result2 = requests.post(
        f"{base_url}/webhook/request",
        json=payload2,
        timeout=60
    )
    
    if result2.status_code != 200:
        print(f"❌ Second request failed: {result2.status_code}")
        return False
    
    data2 = result2.json()
    print(f"✅ Second request: {data2['status']}")
    print(f"   Ticket: {data2.get('ticket_id')}")
    print(f"   Is new: {data2.get('is_new_ticket')}")
    
    # Verify threading
    if data1.get('ticket_id') == data2.get('ticket_id'):
        print(f"\n✅ THREADING OK: Both requests used ticket #{data1.get('ticket_id')}")
        return True
    else:
        print(f"\n⚠️  THREADING: Different tickets used")
        print(f"   Request 1: #{data1.get('ticket_id')}")
        print(f"   Request 2: #{data2.get('ticket_id')}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Webhook HTTP integration")
    parser.add_argument("--url", default="http://localhost:5000", help="Webhook base URL")
    parser.add_argument("--payload", choices=list(TEST_PAYLOADS.keys()), 
                        default="modelisation_simple", help="Test payload to use")
    parser.add_argument("--live", action="store_true", help="Actually send requests (not dry run)")
    parser.add_argument("--test", choices=["health", "webhook", "threading", "all"],
                        default="all", help="Which test to run")
    
    args = parser.parse_args()
    
    print("\n" + "#"*60)
    print(f"WEBHOOK HTTP TEST")
    print(f"URL: {args.url}")
    print(f"Mode: {'LIVE' if args.live else 'DRY RUN'}")
    print("#"*60)
    
    results = {}
    
    # Health test
    if args.test in ["health", "all"]:
        results["health"] = test_health(args.url)
        if not results["health"] and args.test == "all":
            print("\n❌ Server not available, skipping other tests")
            return
    
    # Webhook test
    if args.test in ["webhook", "all"]:
        result = test_webhook(args.url, args.payload, args.live)
        results["webhook"] = result is not None
    
    # Threading test
    if args.test in ["threading", "all"]:
        results["threading"] = test_threading(args.url, args.live)
    
    # Summary
    print("\n" + "#"*60)
    print("TEST SUMMARY")
    print("#"*60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")


if __name__ == "__main__":
    main()
