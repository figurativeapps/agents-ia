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
from pathlib import Path
from datetime import datetime

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

    # STEP 1: Scrape Google Maps
    scrape_cmd = f'python "{exec_dir}/scrape_google_maps.py" --industry "{args.industry}" --location "{args.location}" --max_leads {args.max_leads}'
    run_command("STEP 1: Scraping Google Maps", scrape_cmd, critical=True)

    if args.scrape_only:
        print("\n✅ Scraping complete (scrape-only mode)")
        return

    # STEP 2: Qualify websites (LLM classification + tech stack detection)
    qualify_cmd = f'python "{exec_dir}/qualify_site.py" --input "{project_root}/.tmp/google_maps_results.json" --industry "{args.industry}"'
    run_command("STEP 2: Qualifying Websites (LLM)", qualify_cmd, critical=True)

    # STEP 3: Enrich contacts (Extended Waterfall: OSINT → Dropcontact → Hunter → Apollo)
    enrich_cmd = f'python "{exec_dir}/enrich.py" --input "{project_root}/.tmp/qualified_leads.json"'
    run_command("STEP 3: Enriching Contacts (Waterfall)", enrich_cmd, critical=True)

    enriched_path = f"{project_root}/.tmp/enriched_leads.json"

    # STEP 3b: Verify emails (MillionVerifier)
    verify_cmd = f'python "{exec_dir}/verify_email.py" --input "{enriched_path}"'
    run_command("STEP 3b: Verifying Emails", verify_cmd, critical=False)

    # STEP 3c: Score leads (LLM-based ICP scoring)
    score_cmd = f'python "{exec_dir}/score_lead.py" --input "{enriched_path}" --industry "{args.industry}"'
    run_command("STEP 3c: Scoring Leads (LLM)", score_cmd, critical=False)

    if args.use_excel:
        # ANCIEN FLOW : Excel puis HubSpot
        save_cmd = f'python "{exec_dir}/save_to_excel.py" --input "{enriched_path}"'
        run_command("STEP 4: Saving to Excel Database", save_cmd, critical=True)

        if not args.no_hubspot:
            hubspot_cmd = f'python "{exec_dir}/sync_hubspot.py" --input "{enriched_path}"'
            run_command("STEP 5: Syncing to HubSpot CRM", hubspot_cmd, critical=False)
        else:
            print("\n⏭️  Skipping HubSpot sync (--no-hubspot flag)")
    else:
        # NOUVEAU DEFAULT : Direct HubSpot + backup Excel
        if not args.no_hubspot:
            hubspot_cmd = f'python "{exec_dir}/sync_hubspot.py" --input "{enriched_path}" --write-log'
            run_command("STEP 4: Syncing directly to HubSpot CRM", hubspot_cmd, critical=False)

            if not args.no_backup:
                backup_cmd = f'python "{exec_dir}/save_to_excel.py" --input "{enriched_path}" --backup-mode'
                run_command("STEP 5: Excel backup (post-sync)", backup_cmd, critical=False)
        else:
            print("\n⚠️  HubSpot et Excel backup desactives. Donnees enrichies dans .tmp/enriched_leads.json")

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
