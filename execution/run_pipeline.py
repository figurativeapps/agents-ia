"""
Master Pipeline Orchestrator
Runs the complete lead generation workflow with a single command.

Default: Direct sync to HubSpot + Excel backup
Old workflow: Use --use-excel to sync via Excel first

Usage:
    python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
    python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --no-backup
    python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --use-excel
    python execution/run_pipeline.py --industry "E-commerce" --location "Lyon" --max_leads 30 --no-hubspot --use-excel
"""

import subprocess
import argparse
import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add execution/ to path for api_utils import
sys.path.insert(0, str(Path(__file__).parent))
from api_utils import load_and_merge_tracker_snapshots, cleanup_tracker_snapshots

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')


def run_command(description, command, critical=True):
    """
    Run a shell command and handle errors

    Args:
        description: What this step does
        command: Command to run
        critical: If True, stop pipeline on error
    """
    print(f"\n{'='*60}")
    print(f"🔄 {description}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        print(result.stdout)
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Error in {description}")
        print(f"Exit code: {e.returncode}")
        print(f"Error output:\n{e.stderr}")

        if critical:
            print("\n⚠️  Critical error - stopping pipeline")
            sys.exit(1)
        else:
            print("\n⚠️  Non-critical error - continuing...")
            return False


def _load_state(state_file, industry, location, max_leads):
    """Load pipeline state from checkpoint file, or return fresh state."""
    if state_file.exists():
        with open(state_file, 'r', encoding='utf-8') as f:
            s = json.load(f)
        # Validate state matches current args
        if (s.get('industry') == industry
                and s.get('location') == location
                and s.get('max_leads') == max_leads):
            return s
    return {
        'run_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
        'industry': industry,
        'location': location,
        'max_leads': max_leads,
        'steps_completed': []
    }


def _save_checkpoint(state_file, state, step_name):
    """Mark a step as completed in the pipeline state file."""
    if step_name not in state.get('steps_completed', []):
        state.setdefault('steps_completed', []).append(step_name)
    state['last_updated'] = datetime.now().isoformat()
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _is_step_done(state, step_name):
    """Check if a step was already completed."""
    return step_name in state.get('steps_completed', [])


def main():
    parser = argparse.ArgumentParser(
        description='Run complete lead generation pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
  python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --no-backup
  python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --use-excel
  python execution/run_pipeline.py --industry "E-commerce" --location "Lyon" --max_leads 30 --no-hubspot --use-excel
        """
    )

    parser.add_argument('--industry', required=True, help='Industry/business type (e.g., "Cuisinistes")')
    parser.add_argument('--location', required=True, help='Location to search (e.g., "Bordeaux")')
    parser.add_argument('--max_leads', type=int, default=50, help='Maximum number of leads (default: 50)')
    parser.add_argument('--no-hubspot', action='store_true', help='Skip HubSpot sync')
    parser.add_argument('--use-excel', action='store_true', help='Use Excel as intermediate step before HubSpot (old workflow)')
    parser.add_argument('--no-backup', action='store_true', help='Skip Excel backup after HubSpot sync (direct mode only)')
    parser.add_argument('--scrape-only', action='store_true', help='Only run scraping (for testing)')
    parser.add_argument('--resume', action='store_true', help='Resume pipeline from last successful checkpoint')

    args = parser.parse_args()

    start_time = datetime.now()

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     🤖 AI-Powered Lead Generation Pipeline 🤖            ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    print(f"📋 Configuration:")
    print(f"   Industry:    {args.industry}")
    print(f"   Location:    {args.location}")
    print(f"   Max Leads:   {args.max_leads}")
    print(f"   HubSpot:     {'No' if args.no_hubspot else 'Yes'}")
    if args.use_excel:
        print(f"   Mode:        Excel + HubSpot (ancien workflow)")
    else:
        print(f"   Mode:        Direct HubSpot{' (sans backup Excel)' if args.no_backup else ' + backup Excel'}")

    # Project paths
    exec_dir = Path(__file__).parent
    project_root = exec_dir.parent

    # Checkpoint setup
    tmp_dir = project_root / '.tmp'
    tmp_dir.mkdir(exist_ok=True)
    state_file = tmp_dir / 'pipeline_state.json'

    if args.resume:
        state = _load_state(state_file, args.industry, args.location, args.max_leads)
        completed = state.get('steps_completed', [])
        if completed:
            print(f"\n🔄 Resuming pipeline — steps already completed: {', '.join(completed)}")
        else:
            print(f"\n🔄 No checkpoint found — starting fresh")
    else:
        state = {
            'run_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'industry': args.industry,
            'location': args.location,
            'max_leads': args.max_leads,
            'steps_completed': []
        }

    # STEP 1: Scrape Google Maps
    STEP1 = "step1_scrape"
    if args.resume and _is_step_done(state, STEP1):
        print(f"\n[RESUME] Skipping STEP 1 (already completed)")
    else:
        scrape_cmd = f'python "{exec_dir}/scrape_google_maps.py" --industry "{args.industry}" --location "{args.location}" --max_leads {args.max_leads}'
        if run_command("STEP 1: Scraping Google Maps", scrape_cmd, critical=True):
            _save_checkpoint(state_file, state, STEP1)

    if args.scrape_only:
        print("\n✅ Scraping complete (scrape-only mode)")
        return

    # STEP 2: Qualify websites (LLM classification + tech stack detection)
    STEP2 = "step2_qualify"
    if args.resume and _is_step_done(state, STEP2):
        print(f"\n[RESUME] Skipping STEP 2 (already completed)")
    else:
        qualify_cmd = f'python "{exec_dir}/qualify_site.py" --input "{project_root}/.tmp/google_maps_results.json" --industry "{args.industry}"'
        if run_command("STEP 2: Qualifying Websites (LLM)", qualify_cmd, critical=True):
            _save_checkpoint(state_file, state, STEP2)

    # STEP 3: Enrich contacts (Extended Waterfall: OSINT → Dropcontact → Hunter → Apollo)
    STEP3 = "step3_enrich"
    if args.resume and _is_step_done(state, STEP3):
        print(f"\n[RESUME] Skipping STEP 3 (already completed)")
    else:
        enrich_cmd = f'python "{exec_dir}/enrich.py" --input "{project_root}/.tmp/qualified_leads.json"'
        if run_command("STEP 3: Enriching Contacts (Waterfall)", enrich_cmd, critical=True):
            _save_checkpoint(state_file, state, STEP3)

    enriched_path = f"{project_root}/.tmp/enriched_leads.json"

    # STEP 3c: Score leads (LLM-based ICP scoring)
    STEP3C = "step3c_score"
    if args.resume and _is_step_done(state, STEP3C):
        print(f"\n[RESUME] Skipping STEP 3c (already completed)")
    else:
        score_cmd = f'python "{exec_dir}/score_lead.py" --input "{enriched_path}" --industry "{args.industry}"'
        if run_command("STEP 3c: Scoring Leads (LLM)", score_cmd, critical=False):
            _save_checkpoint(state_file, state, STEP3C)

    if args.use_excel:
        # ANCIEN FLOW : Excel puis HubSpot
        STEP4 = "step4_excel"
        if args.resume and _is_step_done(state, STEP4):
            print(f"\n[RESUME] Skipping STEP 4 (already completed)")
        else:
            save_cmd = f'python "{exec_dir}/save_to_excel.py" --input "{enriched_path}"'
            if run_command("STEP 4: Saving to Excel Database", save_cmd, critical=True):
                _save_checkpoint(state_file, state, STEP4)

        if not args.no_hubspot:
            STEP5 = "step5_hubspot"
            if args.resume and _is_step_done(state, STEP5):
                print(f"\n[RESUME] Skipping STEP 5 (already completed)")
            else:
                hubspot_cmd = f'python "{exec_dir}/sync_hubspot.py" --input "{enriched_path}"'
                if run_command("STEP 5: Syncing to HubSpot CRM", hubspot_cmd, critical=False):
                    _save_checkpoint(state_file, state, STEP5)
        else:
            print("\n⏭️  Skipping HubSpot sync (--no-hubspot flag)")
    else:
        # NOUVEAU DEFAULT : Direct HubSpot + backup Excel
        if not args.no_hubspot:
            STEP4 = "step4_hubspot"
            if args.resume and _is_step_done(state, STEP4):
                print(f"\n[RESUME] Skipping STEP 4 (already completed)")
            else:
                hubspot_cmd = f'python "{exec_dir}/sync_hubspot.py" --input "{enriched_path}" --write-log'
                if run_command("STEP 4: Syncing directly to HubSpot CRM", hubspot_cmd, critical=False):
                    _save_checkpoint(state_file, state, STEP4)

            if not args.no_backup:
                STEP5 = "step5_backup"
                if args.resume and _is_step_done(state, STEP5):
                    print(f"\n[RESUME] Skipping STEP 5 (already completed)")
                else:
                    backup_cmd = f'python "{exec_dir}/save_to_excel.py" --input "{enriched_path}" --backup-mode'
                    if run_command("STEP 5: Excel backup (post-sync)", backup_cmd, critical=False):
                        _save_checkpoint(state_file, state, STEP5)
        else:
            print("\n⚠️  HubSpot et Excel backup desactives. Donnees enrichies dans .tmp/enriched_leads.json")

    # Generate API diagnostic report
    try:
        merged_tracker = load_and_merge_tracker_snapshots()
        if merged_tracker.calls:
            report, report_path = merged_tracker.save_report(
                num_leads=args.max_leads,
                output_dir=tmp_dir
            )
            print(report)
            print(f"\n📋 Rapport diagnostic sauvegarde : {report_path}")

            # Clean up individual snapshots
            cleanup_tracker_snapshots()
    except Exception as e:
        print(f"\n⚠️  Impossible de generer le rapport diagnostic : {e}")

    # Clean up checkpoint on success
    if state_file.exists():
        state_file.unlink()

    # Final summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE!")
    print(f"{'='*60}")
    print(f"⏱️  Total time: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    print(f"📊 Results:")
    if not args.no_hubspot:
        print(f"   - HubSpot CRM: Contacts synced")
    if args.use_excel or (not args.no_hubspot and not args.no_backup):
        print(f"   - Excel database: Generate_leads.xlsx")
    print(f"   - Intermediate files: .tmp/")
    if not args.use_excel and not args.no_hubspot:
        print(f"   - Sync log: .tmp/sync_log_*.json")
    print(f"   - Diagnostic API: .tmp/api_diagnostic.txt")
    print(f"\n💡 Next steps:")
    print(f"   1. Check HubSpot CRM to review leads")
    print(f"   2. Generate PDFs: python execution/generate_pdf.py --company 'Company Name'")
    print(f"   3. Launch email campaign using cold outreach templates")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        sys.exit(1)
