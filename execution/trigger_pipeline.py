"""
Trigger Pipeline on VPS — Local command that launches lead generation remotely.

Connects via SSH, pulls latest code, and runs the pipeline in background.
The VPS runs 24/7 so the process is never interrupted by sleep/shutdown.
If rate-limited, pipeline_watcher.py (cron) resumes automatically.

Usage:
    python execution/trigger_pipeline.py --industry "Saunas" --countries "Suisse,Belgique"
    python execution/trigger_pipeline.py --industry "Cuisinistes" --country "France" --max_leads 50
    python execution/trigger_pipeline.py --status
    python execution/trigger_pipeline.py --logs
    python execution/trigger_pipeline.py --setup-cron
"""

import subprocess
import argparse
import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

VPS_USER = "figurative"
VPS_HOST = "46.224.215.0"
VPS_SSH = f"{VPS_USER}@{VPS_HOST}"
VPS_PATH = "~/apps/agents-ia"
VPS_PYTHON = f"{VPS_PATH}/venv/bin/python"
VPS_PIP = f"{VPS_PATH}/venv/bin/pip"
LOG_FILE = f"{VPS_PATH}/.tmp/pipeline_output.log"
WATCHER_LOG = f"{VPS_PATH}/.tmp/watcher.log"


SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=10"]
MAX_SSH_RETRIES = 3


def ssh(cmd, capture=False, check=True):
    """Run a command on the VPS via SSH with automatic retry."""
    full = ["ssh"] + SSH_OPTS + [VPS_SSH, cmd]
    for attempt in range(1, MAX_SSH_RETRIES + 1):
        try:
            if capture:
                result = subprocess.run(full, capture_output=True, text=True, encoding="utf-8", errors="replace")
            else:
                result = subprocess.run(full, check=check)
            return result
        except subprocess.CalledProcessError:
            if attempt < MAX_SSH_RETRIES:
                import time
                print(f"  SSH connection failed, retrying ({attempt}/{MAX_SSH_RETRIES})...")
                time.sleep(3)
            else:
                raise


def cmd_deploy():
    """Pull latest code and install dependencies on VPS."""
    print(f"[1/2] Git pull on VPS...")
    ssh(f"cd {VPS_PATH} && git pull")
    print(f"[2/2] Installing dependencies...")
    ssh(f"cd {VPS_PATH} && {VPS_PIP} install -r requirements.txt -q 2>&1 | tail -3")
    print("Deploy complete.")


def cmd_run(args):
    """Launch the pipeline on VPS in background."""
    country_arg = ""
    if args.countries:
        country_arg = f'--countries "{args.countries}"'
    elif args.country:
        country_arg = f'--country "{args.country}"'
    else:
        print("Error: --country or --countries required")
        sys.exit(1)

    resume_flag = "--resume" if args.resume else ""

    pipeline_cmd = (
        f'{VPS_PYTHON} execution/run_pipeline.py '
        f'--industry "{args.industry}" '
        f'{country_arg} '
        f'--max_leads {args.max_leads} '
        f'--workers {args.workers} '
        f'{resume_flag}'
    ).strip()

    import time

    print("[1/2] Deploy (git pull + pip)...")
    ssh(f"cd {VPS_PATH} && git pull && {VPS_PIP} install -r requirements.txt -q 2>&1 | tail -3")

    time.sleep(2)

    print("[2/2] Launching pipeline...")
    ssh(
        f"cd {VPS_PATH} && pkill -f run_pipeline.py 2>/dev/null; "
        f"mkdir -p .tmp && "
        f"nohup {pipeline_cmd} > {LOG_FILE} 2>&1 &",
        check=False
    )

    print(f"\n{'='*60}")
    print(f"Pipeline launched on VPS!")
    print(f"{'='*60}")
    print(f"  Industry:  {args.industry}")
    print(f"  Countries: {args.countries or args.country}")
    print(f"  Max leads: {'unlimited' if args.max_leads >= 9999 else args.max_leads}")
    print(f"  Workers:   {args.workers}")
    print(f"\nMonitor with:")
    print(f"  python execution/trigger_pipeline.py --status")
    print(f"  python execution/trigger_pipeline.py --logs")
    print(f"  ssh {VPS_SSH} 'tail -f {LOG_FILE}'")


def cmd_status():
    """Check if a pipeline is running on VPS and show state."""
    result = ssh(f"ps aux | grep 'run_pipeline.py' | grep -v grep || echo 'NO_PROCESS'", capture=True)
    output = result.stdout.strip()

    if "NO_PROCESS" in output:
        print("No pipeline currently running on VPS.")
    else:
        print("Pipeline RUNNING on VPS:")
        print(f"  {output}")

    # Check state file
    state_result = ssh(
        f'cat {VPS_PATH}/.tmp/pipeline_state.json 2>/dev/null || echo "NO_STATE"',
        capture=True
    )
    state_out = state_result.stdout.strip()
    if "NO_STATE" not in state_out:
        import json
        try:
            state = json.loads(state_out)
            status = state.get("status", "?")
            industry = state.get("industry", "?")
            location = state.get("location", "?")
            remaining = state.get("remaining_countries", [])
            steps = state.get("steps_completed", [])
            print(f"\nPipeline state:")
            print(f"  Status:    {status}")
            print(f"  Industry:  {industry}")
            print(f"  Country:   {location}")
            if remaining:
                print(f"  Next:      {', '.join(remaining)}")
            print(f"  Steps:     {', '.join(steps) if steps else 'none'}")
            if status == "paused":
                print(f"  Reason:    {state.get('pause_reason', '?')}")
                print(f"  Paused at: {state.get('paused_at', '?')}")
        except json.JSONDecodeError:
            pass
    else:
        print("\nNo pipeline state file (no active/paused pipeline).")

    # Check last lines of log
    log_result = ssh(f"tail -5 {LOG_FILE} 2>/dev/null || echo 'NO_LOG'", capture=True)
    log_out = log_result.stdout.strip()
    if "NO_LOG" not in log_out:
        print(f"\nLast log lines:")
        for line in log_out.split("\n"):
            print(f"  {line}")


def cmd_logs(follow=False, lines=50):
    """Show pipeline logs from VPS."""
    if follow:
        print(f"Streaming logs from VPS (Ctrl+C to stop)...\n")
        try:
            subprocess.run(["ssh", VPS_SSH, f"tail -f {LOG_FILE}"])
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        result = ssh(f"tail -{lines} {LOG_FILE} 2>/dev/null || echo 'No log file found'", capture=True)
        print(result.stdout)


def cmd_setup_cron():
    """Setup the daily watcher cron job on VPS."""
    cron_line = f"0 6 * * * cd {VPS_PATH} && {VPS_PYTHON} execution/pipeline_watcher.py --mode once >> {WATCHER_LOG} 2>&1"

    # Check if cron already exists
    result = ssh("crontab -l 2>/dev/null || echo 'NO_CRON'", capture=True)
    existing = result.stdout.strip()

    if "pipeline_watcher" in existing:
        print("Watcher cron already configured:")
        for line in existing.split("\n"):
            if "pipeline_watcher" in line:
                print(f"  {line}")
        return

    if "NO_CRON" in existing:
        existing = ""

    new_crontab = f"{existing}\n{cron_line}\n" if existing else f"{cron_line}\n"

    ssh(f'echo "{new_crontab.strip()}" | crontab -')
    print(f"Cron installed: daily at 6:00 AM")
    print(f"  {cron_line}")
    print(f"\nVerify with: ssh {VPS_SSH} 'crontab -l'")


def main():
    parser = argparse.ArgumentParser(
        description="Trigger lead generation pipeline on VPS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Launch new search
  python execution/trigger_pipeline.py --industry "Saunas" --countries "Suisse,Belgique"
  python execution/trigger_pipeline.py --industry "Cuisinistes" --country "France" --max_leads 50

  # Monitor
  python execution/trigger_pipeline.py --status
  python execution/trigger_pipeline.py --logs
  python execution/trigger_pipeline.py --logs --follow

  # Setup daily watcher (once)
  python execution/trigger_pipeline.py --setup-cron

  # Resume paused pipeline
  python execution/trigger_pipeline.py --industry "Saunas" --countries "Suisse,Belgique" --resume

  # Direct SSH monitoring
  ssh {VPS_SSH} 'tail -f {LOG_FILE}'
        """
    )

    # Action modes
    parser.add_argument("--status", action="store_true", help="Check pipeline status on VPS")
    parser.add_argument("--logs", action="store_true", help="Show recent pipeline logs")
    parser.add_argument("--follow", action="store_true", help="Stream logs in real-time (with --logs)")
    parser.add_argument("--setup-cron", action="store_true", help="Install daily watcher cron on VPS")
    parser.add_argument("--deploy", action="store_true", help="Deploy code only (git pull + pip install)")

    # Pipeline args
    parser.add_argument("--industry", help="Target industry")
    parser.add_argument("--country", default="", help="Single country")
    parser.add_argument("--countries", default="", help="Comma-separated countries")
    parser.add_argument("--max_leads", type=int, default=9999, help="Max leads per country (default: 9999 = unlimited)")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (default: 1 for free-tier safety)")
    parser.add_argument("--resume", action="store_true", help="Resume paused pipeline")

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.logs:
        cmd_logs(follow=args.follow)
    elif args.setup_cron:
        cmd_setup_cron()
    elif args.deploy:
        cmd_deploy()
    elif args.industry:
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
