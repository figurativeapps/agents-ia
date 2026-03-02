"""
Pipeline Watcher — VPS cron script that monitors paused pipelines.

Checks daily if a pipeline is paused due to rate limits.
Tests API availability, resumes the pipeline if limits are reset.

Usage:
    python pipeline_watcher.py --mode once       # single check (for cron)
    python pipeline_watcher.py --mode poll        # continuous (check every --interval seconds)

Cron example (daily at 6am):
    0 6 * * * cd /path/to/agents_ia && python execution/pipeline_watcher.py --mode once >> /var/log/pipeline_watcher.log 2>&1
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pipeline_watcher")

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / '.tmp' / 'pipeline_state.json'

API_TEST_MAP = {
    'Serper Maps': 'serper',
    'Serper OSINT (enrichment)': 'serper',
    'Firecrawl/Anthropic (qualification)': 'firecrawl',
    'Anthropic (scoring)': 'anthropic',
    'HubSpot (sync)': 'hubspot',
}


def _test_serper():
    """Lightweight Serper API test (uses 1 credit)."""
    api_key = os.getenv('SERPER_API_KEY')
    if not api_key:
        return False, "SERPER_API_KEY not set"
    try:
        resp = requests.post(
            "https://google.serper.dev/maps",
            headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'},
            json={"q": "test", "num": 1},
            timeout=15
        )
        if resp.status_code == 200:
            return True, "OK"
        return False, f"Status {resp.status_code}"
    except Exception as e:
        return False, str(e)[:80]


def _test_firecrawl():
    """Lightweight Firecrawl test."""
    api_key = os.getenv('FIRECRAWL_API_KEY')
    if not api_key:
        return False, "FIRECRAWL_API_KEY not set"
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v0/scrape",
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={"url": "https://example.com"},
            timeout=20
        )
        if resp.status_code == 200:
            return True, "OK"
        if resp.status_code == 429:
            return False, "Rate limited (429)"
        return True, f"Status {resp.status_code} (may still work)"
    except Exception as e:
        return False, str(e)[:80]


def _test_anthropic():
    """Lightweight Anthropic test."""
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return False, "ANTHROPIC_API_KEY not set"
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "ping"}]
            },
            timeout=15
        )
        if resp.status_code == 200:
            return True, "OK"
        if resp.status_code == 429:
            return False, "Rate limited (429)"
        return True, f"Status {resp.status_code}"
    except Exception as e:
        return False, str(e)[:80]


def _test_hubspot():
    """Lightweight HubSpot test."""
    api_key = os.getenv('HUBSPOT_API_KEY')
    if not api_key:
        return False, "HUBSPOT_API_KEY not set"
    try:
        from hubspot import HubSpot
        client = HubSpot(access_token=api_key)
        client.crm.contacts.basic_api.get_page(limit=1)
        return True, "OK"
    except Exception as e:
        status = getattr(e, 'status', None)
        if status == 429:
            return False, "Rate limited (429)"
        return False, str(e)[:80]


API_TESTERS = {
    'serper': _test_serper,
    'firecrawl': _test_firecrawl,
    'anthropic': _test_anthropic,
    'hubspot': _test_hubspot,
}


def check_and_resume():
    """Check for paused pipeline and resume if API is available again.

    Returns True if pipeline was resumed, False otherwise.
    """
    if not STATE_FILE.exists():
        logger.info("No pipeline state file found — nothing to do")
        return False

    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)

    if state.get('status') != 'paused':
        logger.info(f"Pipeline status is '{state.get('status', 'unknown')}' — not paused")
        return False

    pause_reason = state.get('pause_reason', 'unknown')
    paused_at = state.get('paused_at', '?')
    industry = state.get('industry', '')
    location = state.get('location', '')
    max_leads = state.get('max_leads', 50)
    remaining_countries = state.get('remaining_countries', [])

    logger.info(f"Found paused pipeline:")
    logger.info(f"  Reason:   {pause_reason}")
    logger.info(f"  Paused:   {paused_at}")
    logger.info(f"  Industry: {industry}")
    logger.info(f"  Country:  {location}")
    if remaining_countries:
        logger.info(f"  Next:     {', '.join(remaining_countries)}")
    logger.info(f"  Target:   {max_leads} leads")

    api_type = API_TEST_MAP.get(pause_reason, 'serper')
    tester = API_TESTERS.get(api_type)

    if not tester:
        logger.warning(f"No test available for API: {pause_reason}")
        return False

    logger.info(f"Testing {api_type} API availability...")
    available, detail = tester()

    if not available:
        logger.info(f"API still unavailable: {detail}")
        logger.info(f"Will retry on next check.")
        return False

    logger.info(f"API is available again: {detail}")
    logger.info(f"Resuming pipeline...")

    exec_dir = PROJECT_ROOT / 'execution'
    countries_arg = ','.join([location] + remaining_countries) if remaining_countries else location
    resume_cmd = (
        f'python "{exec_dir}/run_pipeline.py" '
        f'--resume '
        f'--industry "{industry}" '
        f'--countries "{countries_arg}" '
        f'--max_leads {max_leads}'
    )

    logger.info(f"Command: {resume_cmd}")

    try:
        result = subprocess.run(
            resume_cmd, shell=True, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=3600
        )
        logger.info(f"Pipeline finished with exit code: {result.returncode}")
        if result.stdout:
            for line in result.stdout.strip().split('\n')[-20:]:
                logger.info(f"  | {line}")

        if result.returncode == 75:
            logger.info("Pipeline paused again (rate limit). Will retry on next check.")
            return False
        elif result.returncode == 0:
            logger.info("Pipeline completed successfully!")
            return True
        else:
            logger.error(f"Pipeline failed with code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split('\n')[-10:]:
                    logger.error(f"  | {line}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 1 hour")
        return False
    except Exception as e:
        logger.error(f"Failed to resume pipeline: {e}")
        return False


def poll(interval_seconds=86400):
    """Continuous polling loop. Default: check every 24 hours."""
    logger.info(f"Starting pipeline watcher (interval: {interval_seconds}s / {interval_seconds/3600:.1f}h)")

    while True:
        try:
            check_and_resume()
        except KeyboardInterrupt:
            logger.info("Watcher stopped by user")
            break
        except Exception as e:
            logger.error(f"Watcher error: {e}")

        logger.info(f"Next check in {interval_seconds}s...")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("Watcher stopped by user")
            break


def main():
    parser = argparse.ArgumentParser(description='Watch for paused pipelines and resume when APIs are available')
    parser.add_argument(
        '--mode', default='once', choices=['poll', 'once'],
        help="'once' for single check (cron), 'poll' for continuous loop"
    )
    parser.add_argument(
        '--interval', type=int, default=86400,
        help='Polling interval in seconds (default: 86400 = 24h)'
    )

    args = parser.parse_args()

    if args.mode == 'poll':
        poll(args.interval)
    else:
        check_and_resume()


if __name__ == '__main__':
    main()
