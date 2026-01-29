"""
Classification des demandes clients - Version optimisée
Utilise un pré-filtrage par règles + Claude 3.5 Haiku pour les cas ambigus.

Optimisations appliquées:
1. Pré-filtrage règles → ~70% des cas résolus sans LLM
2. Claude 3.5 Haiku → 10x moins cher que Sonnet
3. Prompt compact → ~200 tokens vs ~600

Usage:
    python classify_request.py --objet "Titre" --description "Contenu" --source "contact"
"""

import os
import sys
import json
import re
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

# Mots-clés pour le pré-filtrage (sans LLM)
SUPPORT_KEYWORDS = [
    'paiement', 'payer', 'facture', 'facturation', 'abonnement',
    'bug', 'erreur', 'problème', 'probleme', 'dysfonctionnement',
    'compte', 'connexion', 'connecter', 'mot de passe', 'password',
    'crédit', 'credit', 'remboursement', 'annuler', 'annulation',
    'aide', 'support', 'assistance', 'question'
]

MODELISATION_KEYWORDS = [
    'modéliser', 'modeliser', 'modélisation', 'modelisation',
    'créer', 'creer', 'création', 'creation',
    '3d', 'ar', 'réalité augmentée', 'realite augmentee',
    'scanner', 'scan', 'objet', 'produit', 'visualiser'
]

# Extensions de fichiers 3D
FILE_3D_EXTENSIONS = ('.glb', '.usdz', '.obj', '.fbx', '.stl', '.gltf', '.dae')


def has_3d_files(fichiers: list) -> bool:
    """Vérifie si des fichiers 3D sont présents"""
    if not fichiers:
        return False
    return any(
        f.get("name", "").lower().endswith(FILE_3D_EXTENSIONS)
        for f in fichiers
    )


def count_keywords(text: str, keywords: list) -> int:
    """Compte le nombre de mots-clés trouvés dans le texte"""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def rule_based_classify(objet: str, description: str, fichiers: list, source: str) -> dict | None:
    """
    Classification par règles (sans LLM).
    Retourne None si le cas est ambigu et nécessite le LLM.
    """
    text = f"{objet} {description}".lower()
    
    # Règle 1: Fichiers 3D présents → MODELISATION (très forte confiance)
    if has_3d_files(fichiers):
        return {
            "type_detecte": "MODELISATION",
            "confiance": 95,
            "raison": "Fichiers 3D détectés",
            "method": "rules"
        }
    
    # Compter les mots-clés
    support_count = count_keywords(text, SUPPORT_KEYWORDS)
    modelisation_count = count_keywords(text, MODELISATION_KEYWORDS)
    
    # Règle 2: Mots-clés SUPPORT dominants (sans mots-clés modélisation)
    if support_count >= 2 and modelisation_count == 0:
        return {
            "type_detecte": "SUPPORT",
            "confiance": 90,
            "raison": f"Mots-clés support détectés ({support_count})",
            "method": "rules"
        }
    
    # Règle 3: Mots-clés MODELISATION dominants (sans mots-clés support)
    if modelisation_count >= 2 and support_count == 0:
        return {
            "type_detecte": "MODELISATION",
            "confiance": 90,
            "raison": f"Mots-clés modélisation détectés ({modelisation_count})",
            "method": "rules"
        }
    
    # Règle 4: Source formulaire + aucun mot-clé contradictoire
    if support_count == 0 and modelisation_count == 0:
        source_type = "MODELISATION" if source == "modelisation" else "SUPPORT"
        return {
            "type_detecte": source_type,
            "confiance": 75,
            "raison": "Basé sur le formulaire utilisé (pas de mots-clés spécifiques)",
            "method": "rules"
        }
    
    # Cas ambigu → nécessite LLM
    return None


def llm_classify(objet: str, description: str, fichiers: list, source: str) -> dict:
    """
    Classification via Claude 3.5 Haiku (cas ambigus uniquement).
    Prompt optimisé (~200 tokens).
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    fichiers_liste = ", ".join([f.get("name", "") for f in fichiers]) if fichiers else "aucun"
    
    # Prompt compact (~200 tokens)
    prompt = f"""Classifie cette demande: SUPPORT ou MODELISATION.

SUPPORT = paiement, compte, bug, abonnement, aide technique
MODELISATION = créer/modéliser un objet 3D pour AR

Demande:
- Source: {source}
- Objet: {objet}
- Description: {description[:300]}
- Fichiers: {fichiers_liste}

Réponds en JSON: {{"type": "SUPPORT" ou "MODELISATION", "confiance": 0-100, "raison": "courte"}}"""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",  # 10x moins cher que Sonnet
            max_tokens=100,  # Réponse courte suffisante
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = response.content[0].text.strip()
        
        # Nettoyer si markdown
        if "```" in response_text:
            match = re.search(r'\{[^}]+\}', response_text)
            if match:
                response_text = match.group()
        
        result = json.loads(response_text)
        
        return {
            "type_detecte": result.get("type", "SUPPORT"),
            "confiance": result.get("confiance", 70),
            "raison": result.get("raison", "Classification LLM"),
            "method": "llm"
        }
        
    except (json.JSONDecodeError, KeyError) as e:
        log_error("llm_classify", f"Parse error: {e}", response_text if 'response_text' in locals() else "")
        # Fallback sur source
        return {
            "type_detecte": "MODELISATION" if source == "modelisation" else "SUPPORT",
            "confiance": 50,
            "raison": "Erreur LLM, fallback sur source",
            "method": "fallback"
        }
    except Exception as e:
        log_error("llm_classify", f"API error: {e}", "")
        raise


def classify_request(objet: str, description: str, fichiers: list, source: str) -> dict:
    """
    Classification optimisée: règles d'abord, LLM si nécessaire.
    
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
            "reclassifie": bool,
            "method": "rules" | "llm" | "fallback"
        }
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not found in .env")
    
    # Étape 1: Essayer classification par règles
    result = rule_based_classify(objet, description, fichiers or [], source)
    
    # Étape 2: Si ambigu, utiliser LLM
    if result is None:
        result = llm_classify(objet, description, fichiers or [], source)
    
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
        "reclassifie": reclassifie,
        "method": result.get("method", "unknown")
    }


def log_error(function: str, error: str, context: str):
    """Log les erreurs pour self-annealing"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "function": function,
        "error": error,
        "context": context[:500] if context else ""
    }
    
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
    parser = argparse.ArgumentParser(description="Classify client requests (optimized)")
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
    
    method_icon = "📋" if result['method'] == 'rules' else "🤖"
    print(f"{method_icon} Method: {result['method']}")
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
