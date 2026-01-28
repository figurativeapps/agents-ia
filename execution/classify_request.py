"""
Classification des demandes clients via LLM
Self-annealing: ajuste automatiquement le prompt si taux d'erreur élevé

Usage:
    python classify_request.py --objet "Titre" --description "Contenu" --source "contact"
    
    Or import as module:
    from classify_request import classify_request
"""

import os
import sys
import json
import argparse
from datetime import datetime
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

import anthropic

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CONFIDENCE_THRESHOLD = 70


def classify_request(objet: str, description: str, fichiers: list, source: str) -> dict:
    """
    Classifie une demande client en SUPPORT ou MODELISATION
    
    Args:
        objet: Titre de la demande
        description: Contenu du message
        fichiers: Liste des fichiers joints [{"name": "file.glb", "url": "..."}, ...]
        source: Source du formulaire ("contact" ou "modelisation")
    
    Returns:
        {
            "type_detecte": "SUPPORT" | "MODELISATION",
            "confiance": int (0-100),
            "raison": str,
            "coherent": bool,
            "type_final": "SUPPORT" | "MODELISATION",
            "reclassifie": bool
        }
    """
    
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not found in .env")
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    fichiers_liste = ", ".join([f.get("name", "fichier") for f in fichiers]) if fichiers else "Aucun"
    fichiers_3d = any(
        f.get("name", "").lower().endswith(('.glb', '.usdz', '.obj', '.fbx', '.stl'))
        for f in fichiers
    ) if fichiers else False
    
    prompt = f"""Tu es un assistant de classification pour Figurative, une plateforme de réalité augmentée.

CONTEXTE :
- Les utilisateurs soumettent 2 types de demandes :
  1. SUPPORT : questions sur le paiement, le compte, bugs, fonctionnalités, abonnement, problèmes techniques
  2. MODELISATION : demande de création/modélisation d'un objet 3D pour la réalité augmentée

DEMANDE À ANALYSER :
- Formulaire utilisé par l'utilisateur : {source}
- Objet/Titre : {objet}
- Description : {description}
- Fichiers joints : {fichiers_liste}
- Contient des fichiers 3D : {fichiers_3d}

RÈGLES DE CLASSIFICATION :
- Mots-clés SUPPORT : paiement, facture, abonnement, bug, erreur, compte, mot de passe, connexion, crédit, problème
- Mots-clés MODELISATION : créer, modéliser, visualiser, objet, produit, 3D, AR, réalité augmentée, scanner
- La présence de fichiers 3D (.glb, .usdz, .obj) est un indicateur FORT de MODELISATION
- Une question posée via le formulaire modélisation reste du SUPPORT si le contenu est clairement une question

Réponds UNIQUEMENT en JSON valide :
{{
  "type_detecte": "SUPPORT" ou "MODELISATION",
  "confiance": nombre entre 0 et 100,
  "raison": "explication courte en français"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parser la réponse
        response_text = response.content[0].text.strip()
        
        # Nettoyer si markdown
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        result = json.loads(response_text)
        
        # Déterminer cohérence et type final
        source_normalized = "MODELISATION" if source == "modelisation" else "SUPPORT"
        coherent = result["type_detecte"] == source_normalized
        
        # Si confiance faible, utiliser la source comme fallback
        if result["confiance"] < CONFIDENCE_THRESHOLD:
            type_final = source_normalized
            reclassifie = False
        else:
            type_final = result["type_detecte"]
            reclassifie = not coherent
        
        return {
            "type_detecte": result["type_detecte"],
            "confiance": result["confiance"],
            "raison": result["raison"],
            "coherent": coherent,
            "type_final": type_final,
            "reclassifie": reclassifie
        }
        
    except json.JSONDecodeError as e:
        # Self-annealing: log l'erreur pour ajustement futur du prompt
        log_error("classify_request", f"JSON parse error: {e}", response_text)
        # Fallback sur la source
        return {
            "type_detecte": source.upper() if source == "modelisation" else "SUPPORT",
            "confiance": 50,
            "raison": "Erreur de parsing, fallback sur source",
            "coherent": True,
            "type_final": source.upper() if source == "modelisation" else "SUPPORT",
            "reclassifie": False
        }
        
    except Exception as e:
        log_error("classify_request", f"API error: {e}", "")
        raise


def log_error(function: str, error: str, context: str):
    """Log les erreurs pour self-annealing"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "function": function,
        "error": error,
        "context": context[:500] if context else ""
    }
    
    # Ensure .tmp directory exists
    tmp_dir = Path(".tmp")
    tmp_dir.mkdir(exist_ok=True)
    
    log_path = tmp_dir / "error_log.json"
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []
    
    logs.append(log_entry)
    
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(logs[-100:], f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Classify client requests")
    parser.add_argument("--objet", required=True, help="Request title")
    parser.add_argument("--description", required=True, help="Request content")
    parser.add_argument("--source", required=True, choices=["contact", "modelisation"], help="Form source")
    parser.add_argument("--fichiers", default="[]", help="JSON array of files")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    fichiers = json.loads(args.fichiers) if args.fichiers else []
    
    print(f"🔍 Classifying request: {args.objet}")
    
    result = classify_request(
        objet=args.objet,
        description=args.description,
        fichiers=fichiers,
        source=args.source
    )
    
    print(f"✅ Classification: {result['type_final']} (confidence: {result['confiance']}%)")
    print(f"   Reason: {result['raison']}")
    
    if result['reclassifie']:
        print(f"⚠️  Reclassified from {args.source} to {result['type_final']}")
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
