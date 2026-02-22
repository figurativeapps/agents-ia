"""
STEP 4c: Lead Scoring with LLM
Scores each lead on 0-100 using Claude Haiku for intelligent prioritization.

Scoring dimensions:
- ICP Fit (40%): Industry match, geography, business type
- Data Completeness (30%): Email, phone, LinkedIn, decision maker name
- Website Quality (20%): E-commerce, professional site, tech stack
- Confidence (10%): Qualification confidence, email verification status

Usage:
    python score_lead.py --input .tmp/enriched_leads.json
"""

import os
import sys
import json
import logging
import requests
import argparse
from pathlib import Path
from dotenv import load_dotenv
from time import sleep

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

# Load environment variables
load_dotenv()

# Local imports
from api_utils import call_with_retry, save_tracker_snapshot

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')


def compute_data_score(lead):
    """
    Compute a deterministic data completeness score (0-100).
    No LLM needed for this — pure field checking.

    Returns:
        int: Score 0-100
    """
    score = 0
    max_score = 100

    # Email fields (40 points)
    if lead.get('Email_Decideur'):
        score += 30
        if lead.get('Email_Decideur_Verified') is True:
            score += 10
        elif lead.get('Email_Decideur_Status') == 'skipped':
            score += 5  # Unverified but present
    elif lead.get('Email_Generique'):
        score += 15

    # Contact identity (25 points)
    if lead.get('Nom_Decideur'):
        score += 10
    if lead.get('Poste_Decideur'):
        score += 5
    if lead.get('LinkedIn_URL'):
        score += 10

    # Company info (20 points)
    if lead.get('Tel_Standard'):
        score += 5
    if lead.get('Site_Web'):
        score += 5
    if lead.get('Adresse') and lead.get('Ville'):
        score += 5
    if lead.get('Industrie'):
        score += 5

    # Business qualification (15 points)
    if lead.get('Ecommerce') == 'Oui':
        score += 5
    if lead.get('Business_Type') == 'Manufacturer':
        score += 5
    if lead.get('Tech_Stack') and lead.get('Tech_Stack') != 'unknown':
        score += 5

    return min(score, max_score)


def score_with_llm(lead, industry=''):
    """
    Use Claude Haiku to generate an ICP fit score with reasoning.

    Args:
        lead: Dictionary with all lead data
        industry: Target industry for ICP matching

    Returns:
        Dictionary with score, reasoning, and priority
    """
    if not ANTHROPIC_API_KEY:
        # Fallback: use deterministic scoring only
        data_score = compute_data_score(lead)
        return {
            'Lead_Score': data_score,
            'Score_Reasoning': 'Deterministic scoring (no LLM)',
            'Lead_Priority': 'Hot' if data_score >= 70 else ('Warm' if data_score >= 40 else 'Cold')
        }

    # Build a summary of the lead for the LLM
    lead_summary = f"""
Entreprise: {lead.get('Nom_Entreprise', 'N/A')}
Site web: {lead.get('Site_Web', 'N/A')}
Industrie: {lead.get('Industrie', 'N/A')}
Ville: {lead.get('Ville', 'N/A')}
Type: {lead.get('Business_Type', 'N/A')}
E-commerce: {lead.get('Ecommerce', 'N/A')}
Tech stack: {lead.get('Tech_Stack', 'N/A')}
Email decideur: {'Oui' if lead.get('Email_Decideur') else 'Non'}
Email verifie: {lead.get('Email_Decideur_Status', 'N/A')}
Nom decideur: {lead.get('Nom_Decideur', 'N/A')}
Poste: {lead.get('Poste_Decideur', 'N/A')}
LinkedIn: {'Oui' if lead.get('LinkedIn_URL') else 'Non'}
Telephone: {'Oui' if lead.get('Tel_Standard') else 'Non'}
Justification qualification: {lead.get('Justification', 'N/A')}
Confiance qualification: {lead.get('Confidence', 'N/A')}%
"""

    prompt = f"""Score ce lead B2B de 0 a 100 et reponds UNIQUEMENT en JSON valide.

Industrie ciblee: {industry or 'Non specifiee'}

{lead_summary}

Criteres de scoring:
- Fit ICP (40%): L'entreprise correspond-elle au profil client ideal? Fabricant/revendeur de produits, avec e-commerce, dans la bonne industrie?
- Completude donnees (30%): A-t-on toutes les infos pour contacter le decideur? (email verifie, nom, poste, LinkedIn, telephone)
- Qualite site web (20%): Site professionnel avec e-commerce actif, stack technique identifiee?
- Signaux positifs (10%): Confiance dans la qualification, coherence des donnees

Reponds avec ce JSON exact:
{{
  "score": 0-100,
  "reasoning": "2-3 phrases explicatives",
  "priority": "Hot" ou "Warm" ou "Cold"
}}

Regles:
- Hot = score >= 70 (contacter en priorite)
- Warm = score 40-69 (bon potentiel, donnees partielles)
- Cold = score < 40 (donnees insuffisantes ou mauvais fit)"""

    try:
        response = call_with_retry(
            lambda: requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 250,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            ),
            label="Anthropic score"
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get('content', [{}])[0].get('text', '{}')

            # Parse JSON (handle markdown wrapping)
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[-1].rsplit('```', 1)[0]

            result = json.loads(content)

            return {
                'Lead_Score': result.get('score', 0),
                'Score_Reasoning': result.get('reasoning', ''),
                'Lead_Priority': result.get('priority', 'Cold')
            }

        else:
            # Fallback to deterministic
            data_score = compute_data_score(lead)
            return {
                'Lead_Score': data_score,
                'Score_Reasoning': f'Deterministic fallback (LLM error {response.status_code})',
                'Lead_Priority': 'Hot' if data_score >= 70 else ('Warm' if data_score >= 40 else 'Cold')
            }

    except (json.JSONDecodeError, Exception) as e:
        data_score = compute_data_score(lead)
        return {
            'Lead_Score': data_score,
            'Score_Reasoning': f'Deterministic fallback ({str(e)[:30]})',
            'Lead_Priority': 'Hot' if data_score >= 70 else ('Warm' if data_score >= 40 else 'Cold')
        }


def score_leads(input_file, industry=''):
    """Score all leads and sort by priority"""

    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"Scoring {len(leads)} leads...\n")

    hot_count = 0
    warm_count = 0
    cold_count = 0

    for i, lead in enumerate(leads, 1):
        company = lead.get('Nom_Entreprise', 'Unknown')
        print(f"[{i}/{len(leads)}] {company}")

        scoring = score_with_llm(lead, industry)
        lead.update(scoring)

        priority = scoring['Lead_Priority']
        score = scoring['Lead_Score']

        if priority == 'Hot':
            hot_count += 1
            print(f"    Score: {score}/100 [HOT]")
        elif priority == 'Warm':
            warm_count += 1
            print(f"    Score: {score}/100 [WARM]")
        else:
            cold_count += 1
            print(f"    Score: {score}/100 [COLD]")

        # Rate limiting for LLM calls
        sleep(0.5)

    # Sort leads by score (highest first)
    leads.sort(key=lambda x: x.get('Lead_Score', 0), reverse=True)

    print(f"\nScoring complete:")
    print(f"  Hot (>= 70): {hot_count}")
    print(f"  Warm (40-69): {warm_count}")
    print(f"  Cold (< 40): {cold_count}")

    return leads


def save_results(leads, output_file):
    """Save scored leads back to file"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    print(f"Saved to: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description='Score leads using LLM-based ICP matching')
    parser.add_argument('--input', required=True, help='Input JSON file from enrichment/verification step')
    parser.add_argument('--industry', default='', help='Target industry for ICP scoring context')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    # Check API key
    print(f"API Key status:")
    print(f"   - ANTHROPIC_API_KEY: {'Configured (LLM scoring)' if ANTHROPIC_API_KEY else 'Missing (deterministic fallback)'}")
    print()

    # Score leads
    scored_leads = score_leads(input_path, industry=args.industry)

    # Save results (overwrite input)
    save_results(scored_leads, input_path)

    print(f"\nStep 4c complete")
    print(f"Output: {input_path}")
    print(f"\nNext step: Sync to HubSpot with sync_hubspot.py")

    save_tracker_snapshot("step3c_score")


if __name__ == '__main__':
    main()
