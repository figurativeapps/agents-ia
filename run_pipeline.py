"""
Master Pipeline Orchestrator
Runs the complete lead generation workflow with a single command.

Usage:
    python run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
    python run_pipeline.py --industry "Restaurants" --location "Paris" --max_leads 20 --skip-reviews
    python run_pipeline.py --industry "E-commerce" --location "Lyon" --max_leads 30 --no-hubspot
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
  python run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
  python run_pipeline.py --industry "Restaurants" --location "Paris" --max_leads 20
  python run_pipeline.py --industry "E-commerce" --location "Lyon" --max_leads 30 --no-hubspot
        """
    )

    parser.add_argument('--industry', required=True, help='Industry/business type (e.g., "Cuisinistes")')
    parser.add_argument('--location', required=True, help='Location to search (e.g., "Bordeaux")')
    parser.add_argument('--max_leads', type=int, default=50, help='Maximum number of leads (default: 50)')
    parser.add_argument('--no-hubspot', action='store_true', help='Skip HubSpot sync')
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

    # Project paths
    project_root = Path(__file__).parent
    exec_dir = project_root / 'execution'

    # STEP 1: Scrape Google Maps
    scrape_cmd = f'python "{exec_dir}/scrape_google_maps.py" --industry "{args.industry}" --location "{args.location}" --max_leads {args.max_leads}'
    run_command("STEP 1: Scraping Google Maps", scrape_cmd, critical=True)

    if args.scrape_only:
        print("\n✅ Scraping complete (scrape-only mode)")
        return

    # STEP 2: Qualify websites
    qualify_cmd = f'python "{exec_dir}/2_qualify_site.py" --input "{project_root}/.tmp/google_maps_results.json"'
    run_command("STEP 2: Qualifying Websites", qualify_cmd, critical=True)

    # STEP 3: Enrich contacts
    enrich_cmd = f'python "{exec_dir}/5_enrich.py" --input "{project_root}/.tmp/qualified_leads.json"'
    run_command("STEP 3: Enriching Contacts", enrich_cmd, critical=True)

    # STEP 4: Save to Excel
    save_cmd = f'python "{exec_dir}/save_to_excel.py" --input "{project_root}/.tmp/enriched_leads.json"'
    run_command("STEP 4: Saving to Excel Database", save_cmd, critical=True)

    # STEP 5: Sync to HubSpot (optional)
    if not args.no_hubspot:
        hubspot_cmd = f'python "{exec_dir}/sync_hubspot.py" --input "{project_root}/.tmp/enriched_leads.json"'
        run_command("STEP 5: Syncing to HubSpot CRM", hubspot_cmd, critical=False)
    else:
        print("\n⏭️  Skipping HubSpot sync (--no-hubspot flag)")

    # Final summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE!")
    print(f"{'='*60}")
    print(f"⏱️  Total time: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    print(f"📊 Results:")
    print(f"   - Excel database: Generate_leads.xlsx")
    print(f"   - Intermediate files: .tmp/")
    if not args.no_hubspot:
        print(f"   - HubSpot CRM: Contacts synced")
    print(f"\n💡 Next steps:")
    print(f"   1. Open Generate_leads.xlsx to review leads")
    print(f"   2. Generate PDFs: python execution/8_generate_pdf.py --company 'Company Name'")
    print(f"   3. Launch email campaign using templates in directives/email_templates.md")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        sys.exit(1)
