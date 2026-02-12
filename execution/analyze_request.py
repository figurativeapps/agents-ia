"""
Analyse de complétude et estimation des crédits pour les demandes de modélisation.
Utilise la grille tarifaire définie dans directives/grille_credits_modelisation.md

Usage:
    python analyze_request.py --objet "Titre" --description "Contenu" --fichiers '[{"name": "photo.jpg"}]'
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Optional
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# =============================================================================
# FILE TYPE DETECTION
# =============================================================================

# Extensions de fichiers 3D
FILE_3D_EXTENSIONS = ('.glb', '.usdz', '.obj', '.fbx', '.stl', '.gltf', '.dae', '.blend')

# Extensions d'images
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.heic')

# Extensions de documents
DOC_EXTENSIONS = ('.pdf', '.doc', '.docx')


def categorize_files(fichiers: List[Dict]) -> Dict:
    """
    Catégorise les fichiers joints par type.
    
    Returns:
        {
            "has_3d": bool,
            "has_images": bool,
            "has_docs": bool,
            "files_3d": list,
            "files_images": list,
            "files_docs": list,
            "total": int
        }
    """
    result = {
        "has_3d": False,
        "has_images": False,
        "has_docs": False,
        "files_3d": [],
        "files_images": [],
        "files_docs": [],
        "files_other": [],
        "total": 0
    }
    
    if not fichiers:
        return result
    
    for f in fichiers:
        name = f.get("name", "").lower()
        result["total"] += 1
        
        if any(name.endswith(ext) for ext in FILE_3D_EXTENSIONS):
            result["has_3d"] = True
            result["files_3d"].append(name)
        elif any(name.endswith(ext) for ext in IMAGE_EXTENSIONS):
            result["has_images"] = True
            result["files_images"].append(name)
        elif any(name.endswith(ext) for ext in DOC_EXTENSIONS):
            result["has_docs"] = True
            result["files_docs"].append(name)
        else:
            result["files_other"].append(name)
    
    return result


# =============================================================================
# COMPLETENESS CHECK
# =============================================================================

def check_completeness(
    objet: str,
    description: str,
    fichiers: List[Dict]
) -> Dict:
    """
    Vérifie si la demande est complète.
    
    Critères obligatoires:
    1. Au moins 1 fichier visuel (image, PDF, ou 3D)
    2. Description identifiant clairement l'objet
    
    Returns:
        {
            "complete": bool,
            "missing": list of missing elements,
            "warnings": list of recommendations
        }
    """
    missing = []
    warnings = []
    
    file_info = categorize_files(fichiers)
    
    # Critère 1: Fichier visuel obligatoire
    has_visual = file_info["has_3d"] or file_info["has_images"] or file_info["has_docs"]
    if not has_visual:
        missing.append("fichier_visuel")
    
    # Critère 2: Description suffisante
    text = f"{objet} {description}".lower()
    
    # Vérifier si l'objet est identifiable
    if len(objet.strip()) < 5:
        missing.append("objet_identifiable")
    
    if len(description.strip()) < 20:
        missing.append("description_detaillee")
    
    # Recommandations (non bloquantes)
    dimension_keywords = ['cm', 'mm', 'm ', 'dimension', 'taille', 'hauteur', 'largeur', 'profondeur', 'longueur']
    has_dimensions = any(kw in text for kw in dimension_keywords)
    if not has_dimensions:
        warnings.append("dimensions_non_specifiees")
    
    material_keywords = ['bois', 'metal', 'acier', 'verre', 'tissu', 'cuir', 'plastique', 'pierre', 'marbre', 'ceramique']
    has_materials = any(kw in text for kw in material_keywords)
    if not has_materials:
        warnings.append("materiaux_non_specifies")
    
    # Si une seule image, recommander plusieurs angles
    if file_info["has_images"] and len(file_info["files_images"]) == 1:
        warnings.append("une_seule_image")
    
    return {
        "complete": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
        "file_info": file_info
    }


# =============================================================================
# CREDIT ESTIMATION (Rules-based)
# =============================================================================

def estimate_credits_rules(
    objet: str,
    description: str,
    fichiers: List[Dict]
) -> Dict:
    """
    Estimation des crédits basée sur les règles.
    
    Returns:
        {
            "credits": int (1, 2, or None if needs_admin),
            "needs_admin": bool,
            "reason": str,
            "confidence": int (0-100)
        }
    """
    file_info = categorize_files(fichiers)
    text = f"{objet} {description}".lower()
    
    # Règle 1: Fichier 3D fourni → 1 crédit (ajustements)
    if file_info["has_3d"]:
        return {
            "credits": 1,
            "needs_admin": False,
            "reason": "Fichier 3D fourni - ajustements/optimisation uniquement",
            "confidence": 95
        }
    
    # Mots-clés de complexité élevée
    complex_keywords = [
        'ornement', 'sculpture', 'sculpte', 'marqueterie', 'ciselure',
        'baroque', 'rococo', 'louis xv', 'louis xiv', 'ancien', 'antique',
        'mecanique', 'mecanisme', 'articule', 'mobile', 'pivotant',
        'lustre', 'chandelier', 'ferronnerie', 'forge',
        'tres detaille', 'tres complexe', 'haute precision'
    ]
    
    # Mots-clés de simplicité
    simple_keywords = [
        'simple', 'basique', 'minimaliste', 'epure', 'moderne',
        'cube', 'rectangle', 'carre', 'rond', 'cylindre',
        'boite', 'etagere simple', 'tablette'
    ]
    
    is_complex = any(kw in text for kw in complex_keywords)
    is_simple = any(kw in text for kw in simple_keywords)
    
    # Règle 2: Objet très complexe → demander admin
    if is_complex and not is_simple:
        return {
            "credits": None,
            "needs_admin": True,
            "reason": "Objet complexe détecté - validation admin requise",
            "confidence": 75
        }
    
    # Règle 3: Objet simple → 1 crédit
    if is_simple and not is_complex:
        return {
            "credits": 1,
            "needs_admin": False,
            "reason": "Objet simple - modélisation basique",
            "confidence": 80
        }
    
    # Règle 4: Par défaut → 2 crédits (modélisation complète)
    return {
        "credits": 2,
        "needs_admin": False,
        "reason": "Modélisation complète avec textures",
        "confidence": 70
    }


# =============================================================================
# CREDIT ESTIMATION (LLM-enhanced)
# =============================================================================

def estimate_credits_llm(
    objet: str,
    description: str,
    fichiers: List[Dict]
) -> Dict:
    """
    Estimation des crédits avec assistance LLM pour les cas ambigus.
    Utilise Claude Haiku pour une analyse rapide et économique.
    """
    if not ANTHROPIC_API_KEY:
        # Fallback sur règles si pas de clé API
        return estimate_credits_rules(objet, description, fichiers)
    
    file_info = categorize_files(fichiers)
    
    # Si fichier 3D fourni, pas besoin de LLM
    if file_info["has_3d"]:
        return {
            "credits": 1,
            "needs_admin": False,
            "reason": "Fichier 3D fourni - ajustements uniquement",
            "confidence": 95,
            "method": "rules"
        }
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    fichiers_str = ", ".join([f.get("name", "") for f in fichiers]) if fichiers else "aucun"
    
    prompt = f"""Analyse cette demande de modélisation 3D et estime le coût en crédits.

GRILLE TARIFAIRE:
- 1 crédit: Objet SIMPLE (forme basique, peu de détails, texture unie)
- 2 crédits: Modélisation COMPLETE (objet moyen, plusieurs éléments, textures réalistes)
- ADMIN: Objet TRES COMPLEXE (ornements sculptés, mécanismes, marqueterie) → demander validation

DEMANDE:
- Objet: {objet}
- Description: {description[:500]}
- Fichiers: {fichiers_str}

Réponds en JSON:
{{"credits": 1 ou 2 ou null, "needs_admin": true/false, "reason": "explication courte", "confidence": 0-100}}

Si needs_admin=true, credits doit être null."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = response.content[0].text.strip()
        
        # Nettoyer si markdown
        if "```" in response_text:
            match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
            if match:
                response_text = match.group()
        
        result = json.loads(response_text)
        result["method"] = "llm"
        
        # Validation
        if result.get("needs_admin"):
            result["credits"] = None
        elif result.get("credits") not in [1, 2]:
            result["credits"] = 2  # Default
        
        return result
        
    except Exception as e:
        print(f"⚠️  LLM estimation failed: {e}")
        # Fallback sur règles
        result = estimate_credits_rules(objet, description, fichiers)
        result["method"] = "rules_fallback"
        return result


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_request(
    objet: str,
    description: str,
    fichiers: List[Dict],
    use_llm: bool = True
) -> Dict:
    """
    Analyse complète d'une demande de modélisation.
    
    Args:
        objet: Titre de la demande
        description: Description détaillée
        fichiers: Liste des fichiers joints
        use_llm: Utiliser le LLM pour l'estimation (défaut: True)
    
    Returns:
        {
            "complete": bool,
            "missing": list,
            "warnings": list,
            "credits": int or None,
            "needs_admin": bool,
            "credit_reason": str,
            "confidence": int,
            "file_info": dict,
            "recommendation": str
        }
    """
    # Étape 1: Vérifier la complétude
    completeness = check_completeness(objet, description, fichiers)
    
    # Étape 2: Estimer les crédits (si complet)
    if completeness["complete"]:
        if use_llm:
            credit_estimate = estimate_credits_llm(objet, description, fichiers)
        else:
            credit_estimate = estimate_credits_rules(objet, description, fichiers)
    else:
        credit_estimate = {
            "credits": None,
            "needs_admin": False,
            "reason": "Demande incomplète - estimation impossible",
            "confidence": 0
        }
    
    # Étape 3: Générer la recommandation
    if not completeness["complete"]:
        missing_labels = {
            "fichier_visuel": "une image, un PDF ou un fichier 3D de référence",
            "objet_identifiable": "un titre plus descriptif de l'objet",
            "description_detaillee": "une description plus détaillée"
        }
        missing_text = [missing_labels.get(m, m) for m in completeness["missing"]]
        recommendation = f"DEMANDER_INFO: {', '.join(missing_text)}"
    elif credit_estimate.get("needs_admin"):
        recommendation = "DEMANDER_ADMIN: Validation requise avant devis"
    else:
        recommendation = f"ENVOYER_DEVIS: {credit_estimate.get('credits')} crédit(s)"
    
    return {
        "complete": completeness["complete"],
        "missing": completeness["missing"],
        "warnings": completeness["warnings"],
        "credits": credit_estimate.get("credits"),
        "needs_admin": credit_estimate.get("needs_admin", False),
        "credit_reason": credit_estimate.get("reason", ""),
        "confidence": credit_estimate.get("confidence", 0),
        "file_info": completeness["file_info"],
        "recommendation": recommendation,
        "method": credit_estimate.get("method", "rules")
    }


# =============================================================================
# GENERATE MISSING INFO MESSAGE
# =============================================================================

def generate_missing_info_message(analysis: Dict, objet: str) -> str:
    """
    Génère le message à envoyer au client pour demander les informations manquantes.
    """
    missing = analysis.get("missing", [])
    warnings = analysis.get("warnings", [])
    
    message_parts = [
        f"Bonjour,",
        f"",
        f"Merci pour votre demande de modélisation concernant : <strong>{objet}</strong>.",
        f"",
        f"Pour pouvoir traiter votre demande et vous fournir un devis précis, nous aurions besoin des éléments suivants :",
        f""
    ]
    
    # Éléments manquants (obligatoires)
    if "fichier_visuel" in missing:
        message_parts.append("• <strong>Une image de référence</strong> (photo, croquis, ou inspiration) de l'objet à modéliser")
    
    if "objet_identifiable" in missing:
        message_parts.append("• <strong>Le nom précis de l'objet</strong> que vous souhaitez modéliser")
    
    if "description_detaillee" in missing:
        message_parts.append("• <strong>Une description plus détaillée</strong> de vos attentes")
    
    # Recommandations (optionnelles mais utiles)
    if warnings:
        message_parts.append("")
        message_parts.append("Les informations suivantes nous aideraient également :")
        
        if "dimensions_non_specifiees" in warnings:
            message_parts.append("• Les dimensions souhaitées (hauteur, largeur, profondeur)")
        
        if "materiaux_non_specifies" in warnings:
            message_parts.append("• Les matériaux ou finitions désirés")
        
        if "une_seule_image" in warnings:
            message_parts.append("• Des photos sous plusieurs angles si possible")
    
    message_parts.extend([
        "",
        "Dès réception de ces éléments, nous vous enverrons une estimation du coût en crédits.",
        "",
        "Cordialement,",
        "L'équipe Figurative"
    ])
    
    return "<br>".join(message_parts)


# =============================================================================
# GENERATE CREDIT QUOTE MESSAGE
# =============================================================================

def generate_credit_quote_message(analysis: Dict, objet: str) -> str:
    """
    Génère le message de devis à envoyer au client.
    """
    credits = analysis.get("credits", 2)
    reason = analysis.get("credit_reason", "")
    
    message_parts = [
        f"Bonjour,",
        f"",
        f"Nous avons bien reçu votre demande de modélisation pour : <strong>{objet}</strong>.",
        f"",
        f"Après analyse, le coût estimé pour cette modélisation est de :",
        f"",
        f"<strong style='font-size: 18px;'>➤ {credits} crédit{'s' if credits > 1 else ''}</strong>",
        f"",
        f"<em>{reason}</em>",
        f"",
        f"Pour confirmer et lancer la modélisation, merci de répondre à cet email avec votre validation.",
        f"",
        f"Cordialement,",
        f"L'équipe Figurative"
    ]
    
    return "<br>".join(message_parts)


# =============================================================================
# GENERATE ADMIN NOTIFICATION MESSAGE
# =============================================================================

def generate_admin_message(analysis: Dict, objet: str, description: str, user_email: str) -> str:
    """
    Génère le message de notification pour l'admin (cas complexe).
    """
    file_info = analysis.get("file_info", {})
    
    message_parts = [
        f"⚠️ <strong>VALIDATION REQUISE - Demande complexe</strong>",
        f"",
        f"<strong>Client:</strong> {user_email}",
        f"<strong>Objet:</strong> {objet}",
        f"",
        f"<strong>Description:</strong>",
        f"{description[:500]}{'...' if len(description) > 500 else ''}",
        f"",
        f"<strong>Fichiers joints:</strong> {file_info.get('total', 0)}",
    ]
    
    if file_info.get("files_images"):
        message_parts.append(f"  - Images: {', '.join(file_info['files_images'])}")
    if file_info.get("files_3d"):
        message_parts.append(f"  - 3D: {', '.join(file_info['files_3d'])}")
    if file_info.get("files_docs"):
        message_parts.append(f"  - Docs: {', '.join(file_info['files_docs'])}")
    
    message_parts.extend([
        f"",
        f"<strong>Analyse IA:</strong> {analysis.get('credit_reason', 'Cas complexe')}",
        f"",
        f"Merci de valider le nombre de crédits à facturer pour cette demande.",
        f"",
        f"Options:",
        f"• Répondre '1 crédit' pour une modélisation simple",
        f"• Répondre '2 crédits' pour une modélisation complète",
        f"• Répondre avec un autre montant si nécessaire"
    ])
    
    return "<br>".join(message_parts)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Analyze modeling request completeness and estimate credits")
    parser.add_argument("--objet", required=True, help="Request title/subject")
    parser.add_argument("--description", required=True, help="Request description")
    parser.add_argument("--fichiers", default="[]", help="JSON array of files")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM estimation")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    fichiers = json.loads(args.fichiers) if args.fichiers else []
    
    print(f"🔍 Analyzing request: {args.objet}")
    print(f"   Files: {len(fichiers)}")
    
    result = analyze_request(
        objet=args.objet,
        description=args.description,
        fichiers=fichiers,
        use_llm=not args.no_llm
    )
    
    # Display results
    complete_icon = "✅" if result["complete"] else "❌"
    print(f"\n{complete_icon} Complete: {result['complete']}")
    
    if result["missing"]:
        print(f"   Missing: {', '.join(result['missing'])}")
    
    if result["warnings"]:
        print(f"   Warnings: {', '.join(result['warnings'])}")
    
    if result["credits"]:
        print(f"\n💰 Credits: {result['credits']}")
    elif result["needs_admin"]:
        print(f"\n⚠️  Needs admin validation")
    
    print(f"   Reason: {result['credit_reason']}")
    print(f"   Confidence: {result['confidence']}%")
    print(f"\n📋 Recommendation: {result['recommendation']}")
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
