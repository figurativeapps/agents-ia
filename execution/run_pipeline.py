"""
Master Pipeline Orchestrator
Runs the complete lead generation workflow with a single command.

Features:
  - Expansion loop: if dedup removes too many leads, tries alternative queries
  - Rate limit pause: saves state and exits cleanly on API quota exhaustion
  - Resume: restarts from last checkpoint (--resume)

Usage:
    python execution/run_pipeline.py --industry "Cuisinistes" --country "France" --max_leads 50
    python execution/run_pipeline.py --industry "Saunas" --countries "Suisse,Belgique" --max_leads 9999
    python execution/run_pipeline.py --resume --industry "Cuisinistes" --country "France" --max_leads 50
"""

import subprocess
import argparse
import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from api_utils import load_and_merge_tracker_snapshots, cleanup_tracker_snapshots

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

RATE_LIMIT_EXIT_CODE = 75
PYTHON = sys.executable


# ───────────────────────────────────────────────────────────────
# Command runner with rate limit detection
# ───────────────────────────────────────────────────────────────

def run_command(description, command, critical=True):
    """Run a shell command. Returns 'ok', 'error', or 'rate_limited'."""
    print(f"\n{'='*60}")
    print(f"🔄 {description}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(
            command, shell=True, check=True,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace'
        )
        print(result.stdout)

        if 'RATE LIMIT ATTEINT' in (result.stdout or ''):
            print("⚠️  Rate limit warnings detected during this step")
            return 'rate_limited'

        return 'ok'

    except subprocess.CalledProcessError as e:
        combined = (e.stdout or '') + (e.stderr or '')
        is_rate_limit = (
            '429' in combined
            or 'rate limit' in combined.lower()
            or 'RATE LIMIT' in combined
        )

        if is_rate_limit:
            print(f"\n⏸️  Rate limit detected in: {description}")
            if e.stdout:
                print(e.stdout)
            return 'rate_limited'

        print(f"❌ Error in {description}")
        print(f"Exit code: {e.returncode}")
        if e.stdout:
            print(e.stdout)
        print(f"Error output:\n{e.stderr}")

        if critical:
            print("\n⚠️  Critical error - stopping pipeline")
            sys.exit(1)

        return 'error'


# ───────────────────────────────────────────────────────────────
# Checkpoint & pause helpers
# ───────────────────────────────────────────────────────────────

def _load_state(state_file, industry, location, max_leads):
    """Load pipeline state from checkpoint file, or return fresh state."""
    if state_file.exists():
        with open(state_file, 'r', encoding='utf-8') as f:
            s = json.load(f)
        if (s.get('industry') == industry
                and s.get('location') == location
                and s.get('max_leads') == max_leads):
            return s
    return _fresh_state(industry, location, max_leads)


def _fresh_state(industry, location, max_leads):
    return {
        'run_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
        'industry': industry,
        'location': location,
        'max_leads': max_leads,
        'steps_completed': [],
        'queries_tried': [],
        'status': 'running',
    }


def _save_checkpoint(state_file, state, step_name):
    """Mark a step as completed and update multi-country progress file."""
    if step_name not in state.get('steps_completed', []):
        state.setdefault('steps_completed', []).append(step_name)
    state['last_updated'] = datetime.now().isoformat()
    state['status'] = 'running'
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    progress_file = state_file.parent / 'pipeline_progress.json'
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            progress['current_step'] = step_name
            _save_progress(progress_file, progress)
        except Exception:
            pass


def _is_step_done(state, step_name):
    return step_name in state.get('steps_completed', [])


def _pause_pipeline(state_file, state, reason, remaining_countries=None):
    """Save pipeline state as paused and exit with RATE_LIMIT_EXIT_CODE."""
    state['status'] = 'paused'
    state['pause_reason'] = reason
    state['paused_at'] = datetime.now().isoformat()
    state['last_updated'] = datetime.now().isoformat()
    if remaining_countries is not None:
        state['remaining_countries'] = remaining_countries
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    remaining = state.get('remaining_countries', [])
    countries_arg = ','.join([state['location']] + remaining) if remaining else state['location']

    progress_file = state_file.parent / 'pipeline_progress.json'
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            progress['status'] = 'paused'
            progress['pause_reason'] = reason
            _save_progress(progress_file, progress)
        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"⏸️  PIPELINE PAUSED — Rate limit on: {reason}")
    print(f"{'='*60}")
    print(f"📄 State saved to: {state_file}")
    print(f"💡 Resume with: python execution/run_pipeline.py --resume "
          f"--industry \"{state['industry']}\" --countries \"{countries_arg}\" --max_leads {state['max_leads']}")
    print(f"💡 Or let pipeline_watcher.py on VPS handle the resume automatically.")
    sys.exit(RATE_LIMIT_EXIT_CODE)


# ───────────────────────────────────────────────────────────────
# Query expansion for broader searches
# ───────────────────────────────────────────────────────────────

REGIONS = {
    'France': [
        'Ile-de-France', 'Auvergne-Rhone-Alpes', 'Provence-Alpes-Cote-d-Azur',
        'Occitanie', 'Nouvelle-Aquitaine', 'Hauts-de-France', 'Grand Est',
        'Bretagne', 'Pays de la Loire', 'Normandie', 'Bourgogne-Franche-Comte',
        'Centre-Val de Loire',
    ],
    'Belgique': ['Bruxelles', 'Wallonie', 'Flandre'],
    'Suisse': ['Geneve', 'Zurich', 'Berne', 'Lausanne', 'Bale', 'Lucerne', 'Valais', 'Tessin'],
}


def _generate_query_variants(industry, country):
    """Generate alternative search queries when the initial one yields too few new leads.
    Returns list of (query_string, source) tuples where source is 'maps' or 'web'.
    """
    variants = []

    terms = re.split(r'[/,&+]', industry)
    terms = [t.strip() for t in terms if t.strip()]

    # Phase A: Google Maps variants (different prefixes)
    prefixes = ['constructeur', 'fournisseur', 'vendeur', 'distributeur', 'magasin']
    for term in terms:
        for prefix in prefixes:
            variants.append((f'{prefix} {term} {country}', 'maps'))

    if len(terms) > 1:
        combined = ' '.join(terms)
        for prefix in prefixes:
            variants.append((f'{prefix} {combined} {country}', 'maps'))

    # Phase B: Google Maps by region
    if country in REGIONS:
        for region in REGIONS[country]:
            variants.append((f'fabricant {industry} {region}', 'maps'))

    for term in terms:
        variants.append((f'{term} professionnel {country}', 'maps'))
        variants.append((f'{term} sur mesure {country}', 'maps'))

    # Phase C: Google Web Search (catches large multi-product manufacturers)
    for term in terms:
        variants.append((f'fabricant {term} {country}', 'web'))
        variants.append((f'constructeur {term} catalogue {country}', 'web'))
        variants.append((f'{term} fabrication vente {country}', 'web'))

    if len(terms) > 1:
        combined = ' '.join(terms)
        variants.append((f'fabricant {combined} {country}', 'web'))
        variants.append((f'{combined} constructeur professionnel {country}', 'web'))

    variants.append((f'marque {industry} {country}', 'web'))
    variants.append((f'{industry} showroom revendeur {country}', 'web'))

    return variants


# ───────────────────────────────────────────────────────────────
# Expansion loop: scrape + dedup until target is reached
# ───────────────────────────────────────────────────────────────

def _run_expansion_loop(args, state, state_file, exec_dir, project_root, country):
    """Scrape Google Maps with expanding queries until we reach max_leads new leads.

    Returns the number of new leads found.
    """
    results_file = project_root / '.tmp' / 'google_maps_results.json'
    max_leads = args.max_leads
    queries_tried = state.get('queries_tried', [])
    no_hubspot = args.no_hubspot

    # Load accumulated leads if resuming
    accumulated = []
    if args.resume and results_file.exists() and queries_tried:
        with open(results_file, 'r', encoding='utf-8') as f:
            accumulated = json.load(f)
        print(f"\n🔄 Resuming with {len(accumulated)} accumulated leads, {len(queries_tried)} queries tried")

    # Phase 1: Original query
    original_query = f"fabricant {args.industry} {country}"
    if original_query not in queries_tried:
        scrape_cmd = (f'"{PYTHON}" "{exec_dir}/scrape_google_maps.py" '
                      f'--industry "{args.industry}" --location "{country}" '
                      f'--max_leads {max_leads}')
        result = run_command("STEP 1: Scraping Google Maps", scrape_cmd, critical=False)

        if result == 'rate_limited':
            _save_accumulated(results_file, accumulated)
            state['queries_tried'] = queries_tried
            _pause_pipeline(state_file, state, 'Serper Maps')

        queries_tried.append(original_query)
        state['queries_tried'] = queries_tried

        if result == 'ok' and results_file.exists():
            with open(results_file, 'r', encoding='utf-8') as f:
                batch = json.load(f)
            accumulated.extend(batch)

        # Save accumulated and dedup
        _save_accumulated(results_file, accumulated)
        accumulated = _run_dedup(exec_dir, results_file, no_hubspot)

    if len(accumulated) >= max_leads:
        accumulated = accumulated[:max_leads]
        _save_accumulated(results_file, accumulated)
        return len(accumulated)

    # Phase 2: Expansion with alternative queries (Maps + Web)
    variants = _generate_query_variants(args.industry, country)
    variants = [(q, src) for q, src in variants if q not in queries_tried]

    if variants and len(accumulated) < max_leads:
        maps_count = sum(1 for _, s in variants if s == 'maps')
        web_count = sum(1 for _, s in variants if s == 'web')
        print(f"\n🔄 {len(accumulated)}/{max_leads} new leads — expanding with {maps_count} Maps + {web_count} Web queries...")

    for variant, source in variants:
        if len(accumulated) >= max_leads:
            break

        needed = max_leads - len(accumulated)
        if source == 'web':
            scrape_cmd = (f'"{PYTHON}" "{exec_dir}/scrape_google_maps.py" '
                          f'--industry "{args.industry}" --location "{country}" '
                          f'--max_leads {needed + 10} --source web --query-override "{variant}"')
        else:
            scrape_cmd = (f'"{PYTHON}" "{exec_dir}/scrape_google_maps.py" '
                          f'--industry "{args.industry}" --location "{country}" '
                          f'--max_leads {needed + 10} --query-override "{variant}"')

        icon = "🌐" if source == "web" else "📍"
        result = run_command(f"EXPAND {icon}: {variant}", scrape_cmd, critical=False)

        queries_tried.append(variant)
        state['queries_tried'] = queries_tried

        if result == 'rate_limited':
            _save_accumulated(results_file, accumulated)
            _pause_pipeline(state_file, state, f'Serper {"Web" if source == "web" else "Maps"}')

        if result == 'ok' and results_file.exists():
            with open(results_file, 'r', encoding='utf-8') as f:
                batch = json.load(f)
            accumulated.extend(batch)

        _save_accumulated(results_file, accumulated)
        accumulated = _run_dedup(exec_dir, results_file, no_hubspot)

        if accumulated:
            print(f"    📊 Progress: {len(accumulated)}/{max_leads} new leads")

    # Trim to target
    if len(accumulated) > max_leads:
        accumulated = accumulated[:max_leads]
        _save_accumulated(results_file, accumulated)

    return len(accumulated)


def _save_progress(progress_file, progress):
    """Write the multi-country progress file (read by dashboard)."""
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _save_accumulated(results_file, leads):
    """Save accumulated leads to the results file."""
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)


def _run_dedup(exec_dir, results_file, no_hubspot):
    """Run dedup and return the deduplicated leads."""
    dedup_cmd = f'"{PYTHON}" "{exec_dir}/dedup.py" --input "{results_file}"'
    if no_hubspot:
        dedup_cmd += ' --no-hubspot'
    run_command("Deduplication", dedup_cmd, critical=False)

    with open(results_file, 'r', encoding='utf-8') as f:
        return json.load(f)


# ───────────────────────────────────────────────────────────────
# Main pipeline
# ───────────────────────────────────────────────────────────────

def _run_pipeline_for_country(args, country, remaining_countries=None):
    """Run the full pipeline for a single country. Returns lead count or exits on rate limit."""
    remaining = remaining_countries or []

    exec_dir = Path(__file__).parent
    project_root = exec_dir.parent
    tmp_dir = project_root / '.tmp'
    tmp_dir.mkdir(exist_ok=True)
    state_file = tmp_dir / 'pipeline_state.json'

    if args.resume:
        state = _load_state(state_file, args.industry, country, args.max_leads)
        completed = state.get('steps_completed', [])
        if completed:
            print(f"\n🔄 Resuming — steps done: {', '.join(completed)}")
        if state.get('status') == 'paused':
            print(f"⏸️  Was paused due to: {state.get('pause_reason', 'unknown')}")
    else:
        state = _fresh_state(args.industry, country, args.max_leads)

    state['remaining_countries'] = remaining

    # ── STEPS 1+1b: Scrape with expansion + Dedup ──
    STEP_EXPAND = "step1_expand"
    if args.resume and _is_step_done(state, STEP_EXPAND):
        print(f"\n[RESUME] Skipping STEPS 1+1b (already completed)")
        results_file = project_root / '.tmp' / 'google_maps_results.json'
        with open(results_file, 'r', encoding='utf-8') as f:
            new_lead_count = len(json.load(f))
    else:
        new_lead_count = _run_expansion_loop(args, state, state_file, exec_dir, project_root, country)
        _save_checkpoint(state_file, state, STEP_EXPAND)

    print(f"\n✅ Scraping + Dedup complete: {new_lead_count} new leads ready for qualification")

    if new_lead_count == 0:
        print("\n⚠️  No new leads found after expansion. All results were already in HubSpot.")
        if state_file.exists():
            state_file.unlink()
        return 0

    if args.scrape_only:
        print("\n✅ Scrape-only mode — stopping here")
        if state_file.exists():
            state_file.unlink()
        return new_lead_count

    # ── STEP 2: Qualify websites ──
    STEP2 = "step2_qualify"
    if args.resume and _is_step_done(state, STEP2):
        print(f"\n[RESUME] Skipping STEP 2 (already completed)")
    else:
        qualify_cmd = (f'"{PYTHON}" "{exec_dir}/qualify_site.py" '
                       f'--input "{project_root}/.tmp/google_maps_results.json" '
                       f'--industry "{args.industry}" --workers {args.workers}')
        result = run_command("STEP 2: Qualifying Websites (LLM)", qualify_cmd, critical=False)
        if result == 'rate_limited':
            _pause_pipeline(state_file, state, 'Firecrawl/Anthropic (qualification)', remaining)
        if result == 'error':
            print("\n⚠️  Qualification failed — stopping pipeline")
            sys.exit(1)
        _save_checkpoint(state_file, state, STEP2)

    # ── STEP 3: Enrich contacts ──
    STEP3 = "step3_enrich"
    if args.resume and _is_step_done(state, STEP3):
        print(f"\n[RESUME] Skipping STEP 3 (already completed)")
    else:
        enrich_cmd = f'"{PYTHON}" "{exec_dir}/enrich.py" --input "{project_root}/.tmp/qualified_leads.json"'
        result = run_command("STEP 3: Enriching Contacts (Waterfall)", enrich_cmd, critical=False)
        if result == 'rate_limited':
            _pause_pipeline(state_file, state, 'Serper OSINT (enrichment)', remaining)
        if result == 'error':
            print("\n⚠️  Enrichment failed — stopping pipeline")
            sys.exit(1)
        _save_checkpoint(state_file, state, STEP3)

    enriched_path = f"{project_root}/.tmp/enriched_leads.json"

    # ── STEP 3c: Score leads ──
    STEP3C = "step3c_score"
    if args.resume and _is_step_done(state, STEP3C):
        print(f"\n[RESUME] Skipping STEP 3c (already completed)")
    else:
        score_cmd = f'"{PYTHON}" "{exec_dir}/score_lead.py" --input "{enriched_path}" --industry "{args.industry}"'
        result = run_command("STEP 3c: Scoring Leads (LLM)", score_cmd, critical=False)
        if result == 'rate_limited':
            _pause_pipeline(state_file, state, 'Anthropic (scoring)', remaining)
        _save_checkpoint(state_file, state, STEP3C)

    # ── STEP 4+5: Sync & Backup ──
    if args.use_excel:
        STEP4 = "step4_excel"
        if not (args.resume and _is_step_done(state, STEP4)):
            save_cmd = f'"{PYTHON}" "{exec_dir}/save_to_excel.py" --input "{enriched_path}"'
            result = run_command("STEP 4: Saving to Excel Database", save_cmd, critical=False)
            if result != 'error':
                _save_checkpoint(state_file, state, STEP4)

        if not args.no_hubspot:
            STEP5 = "step5_hubspot"
            if not (args.resume and _is_step_done(state, STEP5)):
                hubspot_cmd = f'"{PYTHON}" "{exec_dir}/sync_hubspot.py" --input "{enriched_path}"'
                result = run_command("STEP 5: Syncing to HubSpot CRM", hubspot_cmd, critical=False)
                if result == 'rate_limited':
                    _pause_pipeline(state_file, state, 'HubSpot (sync)', remaining)
                if result != 'error':
                    _save_checkpoint(state_file, state, STEP5)
    else:
        if not args.no_hubspot:
            STEP4 = "step4_hubspot"
            if not (args.resume and _is_step_done(state, STEP4)):
                hubspot_cmd = f'"{PYTHON}" "{exec_dir}/sync_hubspot.py" --input "{enriched_path}" --write-log'
                result = run_command("STEP 4: Syncing directly to HubSpot CRM", hubspot_cmd, critical=False)
                if result == 'rate_limited':
                    _pause_pipeline(state_file, state, 'HubSpot (sync)', remaining)
                if result != 'error':
                    _save_checkpoint(state_file, state, STEP4)

            if not args.no_backup:
                STEP5 = "step5_backup"
                if not (args.resume and _is_step_done(state, STEP5)):
                    backup_cmd = f'"{PYTHON}" "{exec_dir}/save_to_excel.py" --input "{enriched_path}" --backup-mode'
                    result = run_command("STEP 5: Excel backup (post-sync)", backup_cmd, critical=False)
                    if result != 'error':
                        _save_checkpoint(state_file, state, STEP5)
        else:
            print("\n⚠️  HubSpot disabled. Data in .tmp/enriched_leads.json")

    # ── Report & cleanup ──
    try:
        merged_tracker = load_and_merge_tracker_snapshots()
        if merged_tracker.calls:
            report, report_path = merged_tracker.save_report(
                num_leads=new_lead_count, output_dir=tmp_dir)
            print(report)
            print(f"\n📋 Rapport diagnostic: {report_path}")
            cleanup_tracker_snapshots()
    except Exception as e:
        print(f"\n⚠️  Rapport diagnostic impossible: {e}")

    if state_file.exists():
        state_file.unlink()

    return new_lead_count


def main():
    parser = argparse.ArgumentParser(
        description='Run complete lead generation pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python execution/run_pipeline.py --industry "Saunas" --country "France" --max_leads 50
  python execution/run_pipeline.py --industry "Saunas" --countries "Suisse,Belgique" --max_leads 9999
  python execution/run_pipeline.py --resume --industry "Saunas" --country "France" --max_leads 5
        """
    )

    parser.add_argument('--industry', required=True, help='Target industry. "Fabricant" is auto-prepended.')
    parser.add_argument('--country', default='', help='Single country to search in')
    parser.add_argument('--countries', default='', help='Comma-separated list of countries (processed sequentially)')
    parser.add_argument('--location', help=argparse.SUPPRESS)
    parser.add_argument('--max_leads', type=int, default=50, help='Target number of NEW leads per country (default: 50)')
    parser.add_argument('--no-hubspot', action='store_true', help='Skip HubSpot sync')
    parser.add_argument('--use-excel', action='store_true', help='Use Excel as intermediate step (old workflow)')
    parser.add_argument('--no-backup', action='store_true', help='Skip Excel backup')
    parser.add_argument('--scrape-only', action='store_true', help='Only run scraping + dedup')
    parser.add_argument('--resume', action='store_true', help='Resume from last checkpoint')
    parser.add_argument('--workers', type=int, default=3, help='Parallel workers for qualification (default: 3)')

    args = parser.parse_args()

    # Build country list from --countries or --country
    if args.countries:
        country_list = [c.strip() for c in args.countries.split(',') if c.strip()]
    elif args.country or args.location:
        country_list = [args.country or args.location]
    else:
        parser.error("--country or --countries is required")

    # On resume, check state for remaining_countries
    if args.resume:
        state_file = Path(__file__).parent.parent / '.tmp' / 'pipeline_state.json'
        if state_file.exists():
            with open(state_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            saved_remaining = saved.get('remaining_countries', [])
            saved_current = saved.get('location', '')
            if saved_current and saved_remaining:
                country_list = [saved_current] + saved_remaining
                print(f"🔄 Resuming multi-country pipeline: {' → '.join(country_list)}")

    start_time = datetime.now()
    total_leads = 0

    # ── Multi-country progress file (persistent, read by dashboard) ──
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    tmp_dir.mkdir(exist_ok=True)
    progress_file = tmp_dir / 'pipeline_progress.json'
    progress = {
        'run_id': start_time.strftime('%Y%m%d_%H%M%S'),
        'industry': args.industry,
        'max_leads': args.max_leads,
        'countries': country_list,
        'countries_done': [],
        'countries_results': {},
        'current_country': None,
        'current_step': None,
        'status': 'running',
        'started_at': start_time.isoformat(),
        'finished_at': None,
        'total_leads': 0,
    }
    _save_progress(progress_file, progress)

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     🤖 AI-Powered Lead Generation Pipeline 🤖            ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    multi = len(country_list) > 1
    max_display = "illimité" if args.max_leads >= 9999 else f"{args.max_leads}"

    print(f"📋 Configuration:")
    print(f"   Industry:    {args.industry}")
    print(f"   Countries:   {' → '.join(country_list)}")
    print(f"   Max Leads:   {max_display} (per country)")
    print(f"   HubSpot:     {'No' if args.no_hubspot else 'Yes'}")
    print(f"   Workers:     {args.workers}")
    if args.use_excel:
        print(f"   Mode:        Excel + HubSpot (ancien workflow)")
    else:
        print(f"   Mode:        Direct HubSpot{' (sans backup Excel)' if args.no_backup else ' + backup Excel'}")

    for idx, country in enumerate(country_list):
        remaining = country_list[idx + 1:]

        if multi:
            print(f"\n{'#'*60}")
            print(f"## 🌍 COUNTRY {idx+1}/{len(country_list)}: {country.upper()}")
            if remaining:
                print(f"##    Remaining: {', '.join(remaining)}")
            print(f"{'#'*60}")

        progress['current_country'] = country
        progress['current_step'] = 'step1_expand'
        _save_progress(progress_file, progress)

        leads = _run_pipeline_for_country(args, country, remaining_countries=remaining)
        total_leads += leads

        progress['countries_done'].append(country)
        progress['countries_results'][country] = leads
        progress['total_leads'] = total_leads
        progress['current_step'] = None
        _save_progress(progress_file, progress)

        if multi:
            print(f"\n✅ {country}: {leads} leads generated")

        args.resume = False

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    progress['status'] = 'completed'
    progress['finished_at'] = end_time.isoformat()
    progress['current_country'] = None
    _save_progress(progress_file, progress)

    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE!")
    print(f"{'='*60}")
    print(f"⏱️  Total time: {duration:.1f}s ({duration/60:.1f} min)")
    print(f"📊 Total leads generated: {total_leads}")
    if multi:
        print(f"   Countries processed: {', '.join(country_list)}")
    if not args.no_hubspot:
        print(f"   - HubSpot CRM: Contacts synced")
    if args.use_excel or (not args.no_hubspot and not args.no_backup):
        print(f"   - Excel: Generate_leads.xlsx")
    print(f"\n💡 Next steps:")
    print(f"   1. Check HubSpot CRM")
    print(f"   2. Generate PDFs: python execution/generate_pdf.py --company 'Name'")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Pipeline interrupted by user")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        sys.exit(1)
