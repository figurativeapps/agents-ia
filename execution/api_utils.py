"""
api_utils.py — Shared retry / rate-limit utilities for the lead gen pipeline.

Usage:
    from api_utils import call_with_retry, sleep_between_calls, api_tracker
"""

import json
import time
import logging
import email.utils
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MAX_RETRIES = 4
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_BACKOFF = 2.0

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# =========================================================================== #
# API Tracker — monitors calls, 429s, errors per tool
# =========================================================================== #

# Known API limits (free tier) for recommendations
API_LIMITS = {
    "Serper Maps": {
        "monthly_quota": 2500,
        "rate_per_second": 100,
        "cost_per_unit": "search",
        "free_tier": True,
        "upgrade_url": "https://serper.dev/pricing",
        "upgrade_price": "$50/mois pour 50 000 recherches",
        "wait_recommendation": "Aucune attente necessaire (100 req/s)",
        "ideal_batch": 50,
    },
    "Serper OSINT": {
        "monthly_quota": 2500,  # Shared with Serper Maps
        "rate_per_second": 100,
        "cost_per_unit": "search",
        "free_tier": True,
        "upgrade_url": "https://serper.dev/pricing",
        "upgrade_price": "$50/mois pour 50 000 recherches (partage avec Maps)",
        "wait_recommendation": "Aucune attente necessaire",
        "ideal_batch": 50,
        "shared_with": "Serper Maps",
    },
    "Firecrawl scrape": {
        "monthly_quota": 3000,
        "rate_per_minute": 16,
        "cost_per_unit": "page scrapee",
        "free_tier": False,
        "upgrade_url": "https://firecrawl.dev/pricing",
        "upgrade_price": "$16/mois — plan Hobby (3 000 credits)",
        "wait_recommendation": "4s entre chaque appel (16 req/min Hobby)",
        "ideal_batch": 100,
    },
    "Anthropic classify": {
        "monthly_quota": None,  # Pay per token
        "rate_per_minute": 50,  # Haiku tier 1
        "cost_per_unit": "appel LLM (~300 tokens output)",
        "free_tier": False,
        "upgrade_url": "https://console.anthropic.com/settings/plans",
        "upgrade_price": "Pay-as-you-go : ~$0.001/appel avec Haiku",
        "wait_recommendation": "1s entre appels suffit",
        "ideal_batch": 50,
    },
    "Dropcontact batch": {
        "monthly_quota": 1000,  # Paid plan minimum
        "rate_per_minute": 60,
        "cost_per_unit": "contact enrichi",
        "free_tier": False,  # API requires paid plan
        "upgrade_url": "https://dropcontact.com/pricing",
        "upgrade_price": "24EUR/mois pour 1 000 credits (1 credit = 1 email trouve)",
        "wait_recommendation": "Polling async : 5s entre chaque poll, max 60s total",
        "ideal_batch": 25,
        "note": "L'API n'est pas accessible sur le plan gratuit. Budget obligatoire.",
    },
    "Hunter domain-search": {
        "monthly_quota": 25,
        "rate_per_second": 15,
        "cost_per_unit": "recherche domaine",
        "free_tier": True,
        "upgrade_url": "https://hunter.io/pricing",
        "upgrade_price": "$49/mois pour 500 recherches",
        "wait_recommendation": "Pas de souci de rate, mais 25 credits/mois = max 25 leads",
        "ideal_batch": 20,
        "bottleneck": True,
        "critical_note": "25 credits/mois GRATUIT = limite la plus contraignante du pipeline",
    },
    "Apollo people-search": {
        "monthly_quota": 10000,  # With corporate email
        "rate_per_minute": 50,
        "cost_per_unit": "recherche contact",
        "free_tier": True,
        "upgrade_url": "https://apollo.io/pricing",
        "upgrade_price": "$49/mois pour 5 000 credits mobiles + illimite email",
        "wait_recommendation": "1.5s entre appels suffit",
        "ideal_batch": 50,
        "note": "10 000 credits/mois avec email pro, 100 sans",
    },
    "MillionVerifier": {
        "monthly_quota": 100,
        "rate_per_second": 160,
        "cost_per_unit": "email verifie",
        "free_tier": True,
        "upgrade_url": "https://millionverifier.com/pricing",
        "upgrade_price": "$15/mois pour les premiers credits (pay-as-you-go)",
        "wait_recommendation": "Aucune attente necessaire (160 req/s)",
        "ideal_batch": 50,
        "note": "100 verifications gratuites/mois. Catch-all non factures.",
    },
    "HubSpot contact-search": {
        "monthly_quota": None,  # Daily limit
        "rate_per_10s": 190,  # Pro/Enterprise
        "search_rate_per_second": 5,
        "cost_per_unit": "requete API",
        "free_tier": True,
        "upgrade_url": "https://hubspot.com/pricing",
        "upgrade_price": "Free tier OK pour < 100 leads. Pro = 650 000 req/jour",
        "wait_recommendation": "0.5s entre leads suffit (search = 5 req/s max)",
        "ideal_batch": 50,
    },
    "Serper Web": {
        "monthly_quota": None,
        "rate_per_second": 100,
        "cost_per_unit": "search",
        "free_tier": True,
        "shared_with": "Serper Maps",
        "upgrade_url": "https://serper.dev/pricing",
        "upgrade_price": "$50/mois pour 50 000 recherches (partage avec Maps)",
        "wait_recommendation": "Aucune attente necessaire",
        "ideal_batch": 50,
    },
}

# For SDK-based tools (HubSpot)
for hs_tool in ["HubSpot company-search", "HubSpot company-create",
                 "HubSpot contact-create", "HubSpot contact-update",
                 "HubSpot contact-company association"]:
    API_LIMITS[hs_tool] = API_LIMITS["HubSpot contact-search"].copy()


ANTHROPIC_PRICING = {"input_per_mtok": 1.00, "output_per_mtok": 5.00}

_EMPTY_ENTRY = {
    "total": 0, "success": 0, "rate_limited": 0,
    "server_errors": 0, "client_errors": 0, "network_errors": 0,
    "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
    "first_429_at": None, "last_429_at": None,
}


class APITracker:
    """Tracks API calls, successes, 429s, errors, and cost across the pipeline. Thread-safe."""

    def __init__(self):
        self.calls = {}
        self._lock = threading.Lock()
        self._unflushed = {}  # delta since last flush
        self._flusher = None

    def record(self, label, status_code=200, is_retry=False,
               tokens_in=0, tokens_out=0):
        """Record an API call result (thread-safe). Optionally tracks token usage/cost."""
        with self._lock:
            self._record_unlocked(label, status_code, is_retry,
                                  tokens_in, tokens_out)
        _ensure_flusher(self)

    def _record_unlocked(self, label, status_code=200, is_retry=False,
                         tokens_in=0, tokens_out=0):
        if label not in self.calls:
            self.calls[label] = _EMPTY_ENTRY.copy()
        if label not in self._unflushed:
            self._unflushed[label] = _EMPTY_ENTRY.copy()

        for store in (self.calls[label], self._unflushed[label]):
            store["total"] += 1

            if status_code == 200:
                store["success"] += 1
            elif status_code == 429:
                store["rate_limited"] += 1
                now = datetime.now().isoformat()
                if not store["first_429_at"]:
                    store["first_429_at"] = now
                store["last_429_at"] = now
            elif 500 <= status_code < 600:
                store["server_errors"] += 1
            elif status_code == -1:
                store["network_errors"] += 1
            elif 400 <= status_code < 500:
                store["client_errors"] += 1

            store["tokens_in"] += tokens_in
            store["tokens_out"] += tokens_out
            cost = (tokens_in / 1_000_000 * ANTHROPIC_PRICING["input_per_mtok"]
                    + tokens_out / 1_000_000 * ANTHROPIC_PRICING["output_per_mtok"])
            store["cost_usd"] = round(store["cost_usd"] + cost, 6)

    def record_tokens(self, label, tokens_in=0, tokens_out=0):
        """Record token usage and cost for an already-tracked call (no call count increment)."""
        with self._lock:
            for store in (self.calls, self._unflushed):
                if label not in store:
                    store[label] = _EMPTY_ENTRY.copy()
                store[label]["tokens_in"] += tokens_in
                store[label]["tokens_out"] += tokens_out
                cost = (tokens_in / 1_000_000 * ANTHROPIC_PRICING["input_per_mtok"]
                        + tokens_out / 1_000_000 * ANTHROPIC_PRICING["output_per_mtok"])
                store[label]["cost_usd"] = round(store[label]["cost_usd"] + cost, 6)

    def take_unflushed(self):
        """Return and reset the unflushed delta (thread-safe)."""
        with self._lock:
            delta = self._unflushed
            self._unflushed = {}
            return delta

    def has_issues(self):
        """Check if any API had rate limits or errors."""
        for entry in self.calls.values():
            if entry["rate_limited"] > 0 or entry["server_errors"] > 0 or entry["network_errors"] > 0:
                return True
        return False

    def generate_report(self, num_leads):
        """Generate a human-readable diagnostic report with recommendations."""
        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append("  RAPPORT DIAGNOSTIC API — Pipeline Lead Generation")
        lines.append("=" * 70)
        lines.append(f"  Leads traites: {num_leads}")
        lines.append("")

        # Status table
        lines.append("  OUTIL                      | Appels | OK  | 429 | Err | Statut")
        lines.append("  " + "-" * 66)

        tools_with_issues = []
        tools_near_limit = []

        for label, entry in sorted(self.calls.items()):
            total = entry["total"]
            ok = entry["success"]
            rl = entry["rate_limited"]
            err = entry["server_errors"] + entry["network_errors"] + entry["client_errors"]

            if rl > 0:
                status_icon = "!! RATE LIMIT"
                tools_with_issues.append(label)
            elif err > 0:
                status_icon = "!  ERREURS"
                tools_with_issues.append(label)
            else:
                status_icon = "OK"

            name = label[:28].ljust(28)
            lines.append(f"  {name}| {total:>5}  | {ok:>3} | {rl:>3} | {err:>3} | {status_icon}")

            # Check if near monthly quota
            limits = API_LIMITS.get(label, {})
            quota = limits.get("monthly_quota")
            if quota and ok >= quota * 0.7:
                tools_near_limit.append((label, ok, quota))

        lines.append("")

        # Warnings for rate-limited tools
        if tools_with_issues:
            lines.append("  " + "!" * 70)
            lines.append("  OUTILS AVEC PROBLEMES :")
            lines.append("  " + "!" * 70)
            lines.append("")

            for label in tools_with_issues:
                entry = self.calls[label]
                limits = API_LIMITS.get(label, {})
                lines.append(f"  [{label}]")

                if entry["rate_limited"] > 0:
                    lines.append(f"    Rate limit (429) atteint {entry['rate_limited']} fois")
                    if entry["first_429_at"]:
                        lines.append(f"    Premier 429 a : {entry['first_429_at']}")

                if entry["server_errors"] > 0:
                    lines.append(f"    Erreurs serveur (5xx) : {entry['server_errors']}")
                if entry["network_errors"] > 0:
                    lines.append(f"    Erreurs reseau : {entry['network_errors']}")

                # Recommendations
                lines.append("")
                lines.append(f"    RECOMMANDATIONS :")
                if limits.get("wait_recommendation"):
                    lines.append(f"    - Delai : {limits['wait_recommendation']}")
                if limits.get("ideal_batch"):
                    lines.append(f"    - Batch ideal : {limits['ideal_batch']} leads par recherche")
                if limits.get("monthly_quota"):
                    lines.append(f"    - Quota mensuel (free) : {limits['monthly_quota']} {limits.get('cost_per_unit', 'credits')}")
                if limits.get("upgrade_price"):
                    lines.append(f"    - Upgrade : {limits['upgrade_price']}")
                if limits.get("upgrade_url"):
                    lines.append(f"    - URL : {limits['upgrade_url']}")
                if limits.get("critical_note"):
                    lines.append(f"    - ATTENTION : {limits['critical_note']}")
                if limits.get("note"):
                    lines.append(f"    - Note : {limits['note']}")
                lines.append("")

        # Warnings for tools near quota
        if tools_near_limit:
            lines.append("  " + "-" * 70)
            lines.append("  ATTENTION — QUOTAS PROCHES DE LA LIMITE :")
            lines.append("")
            for label, used, quota in tools_near_limit:
                pct = int(used / quota * 100)
                limits = API_LIMITS.get(label, {})
                lines.append(f"  [{label}] {used}/{quota} credits utilises ({pct}%)")
                if limits.get("upgrade_price"):
                    lines.append(f"    Upgrade : {limits['upgrade_price']}")
                if limits.get("upgrade_url"):
                    lines.append(f"    URL : {limits['upgrade_url']}")
            lines.append("")

        # Global recommendations
        lines.append("  " + "=" * 70)
        lines.append("  RECOMMANDATIONS GENERALES :")
        lines.append("  " + "=" * 70)
        lines.append("")

        # Calculate ideal batch based on most constrained tool
        min_quota = None
        constraining_tool = None
        for label, entry in self.calls.items():
            limits = API_LIMITS.get(label, {})
            quota = limits.get("monthly_quota")
            if quota and (min_quota is None or quota < min_quota):
                min_quota = quota
                constraining_tool = label

        if constraining_tool:
            limits = API_LIMITS.get(constraining_tool, {})
            lines.append(f"  Outil le plus contraignant : {constraining_tool}")
            lines.append(f"    Quota mensuel : {min_quota} {limits.get('cost_per_unit', 'credits')}")
            if min_quota and num_leads > 0:
                remaining = max(0, min_quota - self.calls[constraining_tool]["success"])
                lines.append(f"    Credits restants (estimation) : ~{remaining}")
                lines.append(f"    Recherches possibles ce mois : ~{remaining} leads")
            lines.append("")

        if num_leads > 30:
            lines.append(f"  Pour {num_leads} leads, envisagez de :")
            lines.append(f"    - Hunter.io : Passer au plan Starter ($49/mois, 500 recherches)")
            lines.append(f"    - Firecrawl : Passer au plan Hobby ($16/mois, 3 000 scrapes)")
            lines.append(f"    - MillionVerifier : Acheter un pack credits ($15 pour les premiers)")
        else:
            lines.append(f"  Pour {num_leads} leads, le free tier suffit pour la plupart des outils.")
            lines.append(f"  Seul Hunter.io (25 credits/mois gratuit) peut etre limitant.")

        lines.append("")
        lines.append(f"  Temps d'attente avant de relancer une recherche :")
        lines.append(f"    - Si aucun 429 : relancer immediatement")
        lines.append(f"    - Si 429 sur 1 outil : attendre 5-10 minutes")
        lines.append(f"    - Si 429 sur plusieurs outils : attendre 30-60 minutes")
        lines.append(f"    - Si quotas mensuels epuises : attendre le mois prochain ou upgrader")
        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    def save_report(self, num_leads, output_dir=None):
        """Save the report to .tmp/api_diagnostic.txt and return the text."""
        report = self.generate_report(num_leads)

        if output_dir is None:
            output_dir = Path(__file__).parent.parent / '.tmp'
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)

        report_path = output_dir / 'api_diagnostic.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        # Also save raw data as JSON
        data_path = output_dir / 'api_tracker.json'
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "num_leads": num_leads,
                "calls": self.calls
            }, f, ensure_ascii=False, indent=2)

        return report, report_path


class _AutoFlusher(threading.Thread):
    """Daemon thread that periodically flushes tracker delta to the monthly usage file."""

    def __init__(self, tracker, interval=60):
        super().__init__(daemon=True)
        self.tracker = tracker
        self.interval = interval

    def run(self):
        while True:
            time.sleep(self.interval)
            try:
                delta = self.tracker.take_unflushed()
                if delta:
                    _persist_monthly_usage(delta)
            except Exception:
                pass


def _ensure_flusher(tracker):
    """Start the auto-flusher thread if not already running."""
    if tracker._flusher is None or not tracker._flusher.is_alive():
        tracker._flusher = _AutoFlusher(tracker)
        tracker._flusher.start()


# Global singleton tracker
api_tracker = APITracker()


def save_tracker_snapshot(step_name):
    """Save current tracker data to .tmp/ so the pipeline orchestrator can merge them.
    Uses accumulative write: if the snapshot already exists (e.g. expansion loop calling
    the same step multiple times), the new data is ADDED to the existing snapshot.
    Also persists to the cumulative monthly usage file for the dashboard."""
    output_dir = Path(__file__).parent.parent / '.tmp'
    output_dir.mkdir(exist_ok=True)
    snapshot_path = output_dir / f'api_tracker_{step_name}.json'

    current_calls = api_tracker.calls

    existing = {}
    if snapshot_path.exists():
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                existing = json.load(f).get('calls', {})
        except (json.JSONDecodeError, OSError):
            existing = {}

    merged_calls = {}
    all_labels = set(list(existing.keys()) + list(current_calls.keys()))
    for label in all_labels:
        old = existing.get(label, {})
        new = current_calls.get(label, {})
        merged_calls[label] = _EMPTY_ENTRY.copy()
        for key in _ADDITIVE_KEYS:
            merged_calls[label][key] = round(old.get(key, 0) + new.get(key, 0), 6)
        merged_calls[label]['first_429_at'] = old.get('first_429_at') or new.get('first_429_at')
        merged_calls[label]['last_429_at'] = new.get('last_429_at') or old.get('last_429_at')

    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump({
            "step": step_name,
            "timestamp": datetime.now().isoformat(),
            "calls": merged_calls
        }, f, ensure_ascii=False, indent=2)

    delta = api_tracker.take_unflushed()
    if delta:
        _persist_monthly_usage(delta)


def _get_monthly_usage_path():
    """Return path to the current month's persistent usage file."""
    output_dir = Path(__file__).parent.parent / '.tmp'
    month_key = datetime.now().strftime("%Y-%m")
    return output_dir / f'api_usage_{month_key}.json'


_ADDITIVE_KEYS = ['total', 'success', 'rate_limited', 'server_errors',
                   'client_errors', 'network_errors', 'tokens_in', 'tokens_out', 'cost_usd']


def _persist_monthly_usage(calls_data):
    """Atomically add delta API calls to the cumulative monthly file."""
    path = _get_monthly_usage_path()
    path.parent.mkdir(exist_ok=True)

    existing = {}
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    cumulative = existing.get("calls", {})
    for label, entry in calls_data.items():
        if label not in cumulative:
            cumulative[label] = _EMPTY_ENTRY.copy()
        for key in _ADDITIVE_KEYS:
            cumulative[label][key] = round(
                cumulative[label].get(key, 0) + entry.get(key, 0), 6)

    tmp_path = path.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump({
            "month": datetime.now().strftime("%Y-%m"),
            "last_updated": datetime.now().isoformat(),
            "calls": cumulative,
        }, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def load_monthly_usage():
    """Load the current month's cumulative API usage. Returns dict of calls or empty dict."""
    path = _get_monthly_usage_path()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get("month") != datetime.now().strftime("%Y-%m"):
            return {}
        return data.get("calls", {})
    except (json.JSONDecodeError, OSError):
        return {}


def load_and_merge_tracker_snapshots():
    """Load all tracker snapshots from .tmp/ and merge into a single APITracker."""
    merged = APITracker()
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    for snapshot_file in sorted(tmp_dir.glob('api_tracker_step*.json')):
        try:
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for label, entry in data.get('calls', {}).items():
                if label not in merged.calls:
                    merged.calls[label] = _EMPTY_ENTRY.copy()
                    merged.calls[label].update(entry)
                else:
                    for key in _ADDITIVE_KEYS:
                        merged.calls[label][key] = round(
                            merged.calls[label].get(key, 0) + entry.get(key, 0), 6)
                    # Keep earliest first_429 and latest last_429
                    if entry.get('first_429_at'):
                        if not merged.calls[label].get('first_429_at') or entry['first_429_at'] < merged.calls[label]['first_429_at']:
                            merged.calls[label]['first_429_at'] = entry['first_429_at']
                    if entry.get('last_429_at'):
                        if not merged.calls[label].get('last_429_at') or entry['last_429_at'] > merged.calls[label]['last_429_at']:
                            merged.calls[label]['last_429_at'] = entry['last_429_at']
        except Exception:
            continue
    return merged


def cleanup_tracker_snapshots():
    """Remove all tracker snapshot files from .tmp/."""
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    for snapshot_file in tmp_dir.glob('api_tracker_step*.json'):
        try:
            snapshot_file.unlink()
        except Exception:
            pass


# =========================================================================== #
# Retry wrappers (updated to track calls)
# =========================================================================== #

def call_with_retry(
    fn,
    label="API call",
    max_retries=DEFAULT_MAX_RETRIES,
    base_delay=DEFAULT_BASE_DELAY,
    max_delay=DEFAULT_MAX_DELAY,
    backoff=DEFAULT_BACKOFF,
):
    """
    Call fn() and retry with exponential backoff on 429 / 5xx.

    fn must return a requests.Response object.
    On final failure, returns the last response (caller decides how to handle).
    Network exceptions are also retried.
    """
    delay = base_delay
    last_response = None

    for attempt in range(1, max_retries + 2):
        try:
            response = fn()
        except Exception as exc:
            api_tracker.record(label, status_code=-1)
            if attempt > max_retries:
                logger.error("[%s] Network error after %d attempts: %s", label, attempt, exc)
                raise
            wait = min(delay, max_delay)
            logger.warning(
                "[%s] Network error (attempt %d/%d) — retrying in %.1fs: %s",
                label, attempt, max_retries + 1, wait, exc
            )
            time.sleep(wait)
            delay *= backoff
            continue

        # Track the call
        api_tracker.record(label, status_code=response.status_code)

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        last_response = response

        if attempt > max_retries:
            # Print a visible warning on final 429 failure
            if response.status_code == 429:
                _print_rate_limit_warning(label)
            logger.error(
                "[%s] Status %d after %d attempts — giving up",
                label, response.status_code, attempt
            )
            return response

        retry_after = _parse_retry_after(response)
        wait = retry_after if retry_after else min(delay, max_delay)

        logger.warning(
            "[%s] Status %d (attempt %d/%d) — retrying in %.1fs",
            label, response.status_code, attempt, max_retries + 1, wait
        )
        time.sleep(wait)
        delay *= backoff

    return last_response


def _print_rate_limit_warning(label):
    """Print a visible console warning when rate limit is exhausted."""
    limits = API_LIMITS.get(label, {})

    print(f"\n{'!'*60}")
    print(f"  RATE LIMIT ATTEINT : {label}")
    print(f"{'!'*60}")

    if limits.get("wait_recommendation"):
        print(f"  Delai recommande : {limits['wait_recommendation']}")
    if limits.get("monthly_quota"):
        print(f"  Quota mensuel (free) : {limits['monthly_quota']} {limits.get('cost_per_unit', '')}")
    if limits.get("ideal_batch"):
        print(f"  Batch ideal : {limits['ideal_batch']} leads max par recherche")
    if limits.get("critical_note"):
        print(f"  {limits['critical_note']}")
    if limits.get("upgrade_price"):
        print(f"  Upgrade : {limits['upgrade_price']}")
    if limits.get("upgrade_url"):
        print(f"  URL : {limits['upgrade_url']}")
    print(f"{'!'*60}\n")


def _parse_retry_after(response):
    """Parse Retry-After header (seconds or HTTP-date). Returns float or None."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(header)
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None


def sleep_between_calls(seconds, label=""):
    """Explicit delay between consecutive API calls. Shows in logs."""
    if seconds <= 0:
        return
    if label:
        logger.debug("Sleeping %.2fs between %s calls", seconds, label)
    time.sleep(seconds)


def sdk_call_with_retry(fn, label="SDK call", max_retries=3, base_delay=2.0):
    """
    Retry a SDK call (e.g. HubSpot) on 429 or 5xx.
    fn: zero-argument callable.
    Returns the result, or re-raises on final failure.
    """
    delay = base_delay

    for attempt in range(1, max_retries + 2):
        try:
            result = fn()
            api_tracker.record(label, status_code=200)
            return result
        except Exception as e:
            status = getattr(e, 'status', None)
            if status:
                api_tracker.record(label, status_code=status)
            else:
                api_tracker.record(label, status_code=-1)

            if status in (429, 500, 502, 503, 504) and attempt <= max_retries:
                if status == 429:
                    _print_rate_limit_warning(label)
                retry_after = None
                if hasattr(e, 'headers') and e.headers:
                    try:
                        retry_after = float(e.headers.get('Retry-After', 0))
                    except (ValueError, TypeError):
                        pass
                wait = retry_after if retry_after else min(delay, 60.0)
                logger.warning(
                    "[%s] Status %s (attempt %d/%d) — retrying in %.1fs",
                    label, status, attempt, max_retries + 1, wait
                )
                time.sleep(wait)
                delay *= 2.0
            else:
                raise
