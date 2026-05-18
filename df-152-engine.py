
# K16: Concurrent-Spawn-Mutex (fcntl-based, Trinity-CONSERVATIVE 2026-05-17)
def k16_lock_or_exit(df_name: str):
    """Acquire exclusive lock or exit(3). Prevents concurrent DF runs."""
    import fcntl, os, sys
    lock_path = f"/tmp/df-trinity-{df_name}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        sys.exit(3)


# K13: External-Anchor-Mock-RFC3161 (Trinity-CONSERVATIVE 2026-05-17)
def k13_anchor(payload_hash: str) -> dict:
    """Mock RFC3161-style timestamp anchor."""
    from datetime import datetime, timezone
    return {
        "anchor_type": "rfc3161-mock",
        "iso_ts": datetime.now(timezone.utc).isoformat(),
        "payload_hash": payload_hash,
    }


# K12: HMAC-SHA256-Provenance (Trinity-CONSERVATIVE 2026-05-17)
def k12_provenance(payload: bytes, key: bytes = b"df-trinity-conservative-v1") -> dict:
    """Returns payload_hash + HMAC-SHA256 signature."""
    import hashlib, hmac
    return {
        "payload_hash": hashlib.sha256(payload).hexdigest(),
        "hmac_sha256": hmac.new(key, payload, hashlib.sha256).hexdigest(),
    }

"""DF-152 engine for KPM-Crypto-Position-Tracker read-only wallet status."""

import re
import os
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timezone

DF_DIR = Path(__file__).parent
LOCK_DIR = Path("/tmp/df-152.lock")
DF_ID = "152"
DECISION_KEYWORDS_REGEX = re.compile(
    r"\b(entscheid[a-z]*|empfehl(?:e|en|t|st)|sollt(?:e|en|est)|recommend[a-z]*|decid[a-z]*|advis[a-z]*|propos[a-z]*)\b",
    re.IGNORECASE,
)

_LOCK_IDENTITY = f"{os.getpid()}:{time.time_ns()}"


@dataclass
class TrackerOutput:
    welle: str = "25"
    df: str = "DF-152"
    iso_timestamp: str = ""
    source: str = "mock"
    wallets_count: int = 0
    total_value_eur: float = 0
    top_holdings: list = field(default_factory=list)
    last_balance_check: str = ""
    sync_health_per_wallet: dict = field(default_factory=dict)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _file_stable(path, min_age_sec=300) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    try:
        return (time.time() - p.stat().st_mtime) >= min_age_sec
    except OSError:
        return False


def acquire_lock_with_identity() -> bool:
    now = time.time()
    stale_after_sec = 6 * 60 * 60

    try:
        LOCK_DIR.mkdir(mode=0o700)
        (LOCK_DIR / "owner").write_text(_LOCK_IDENTITY, encoding="utf-8")
        return True
    except FileExistsError:
        try:
            age = now - LOCK_DIR.stat().st_mtime
        except OSError:
            return False

        if age < stale_after_sec:
            return False

        try:
            owner = LOCK_DIR / "owner"
            if owner.exists():
                owner.unlink()
            LOCK_DIR.rmdir()
        except OSError:
            return False

        try:
            LOCK_DIR.mkdir(mode=0o700)
            (LOCK_DIR / "owner").write_text(_LOCK_IDENTITY, encoding="utf-8")
            return True
        except FileExistsError:
            return False
        except OSError:
            return False
    except OSError:
        return False


def release_lock() -> None:
    try:
        owner = LOCK_DIR / "owner"
        if owner.exists() and owner.read_text(encoding="utf-8") != _LOCK_IDENTITY:
            return
        if owner.exists():
            owner.unlink()
        LOCK_DIR.rmdir()
    except OSError:
        return


def k17_pre_action_verification(anchors) -> dict:
    env_tag = os.environ.get("DF_152_ENV_TAG", "default")
    missing = []

    for anchor in anchors:
        if isinstance(anchor, Path):
            exists = anchor.exists()
        else:
            exists = Path(str(anchor)).exists()
        if not exists:
            missing.append(str(anchor))

    return {
        "ok": len(missing) == 0,
        "missing_anchors": missing,
        "env_tag": env_tag,
    }


def _is_real_api_enabled() -> bool:
    return os.environ.get("DF_152_REAL_API_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def scan_output_for_decision_keywords(text) -> list:
    if text is None:
        return []
    return sorted({m.group(0) for m in DECISION_KEYWORDS_REGEX.finditer(str(text))})


def assert_no_decision_keywords(output) -> None:
    hits = scan_output_for_decision_keywords(output)
    if hits:
        raise ValueError(f"Q_0/K_0 violation: blocked terms in output: {hits}")


def _mock_tracker_output() -> TrackerOutput:
    now = iso_now()
    return TrackerOutput(
        iso_timestamp=now,
        source="mock",
        wallets_count=3,
        total_value_eur=0.0,
        top_holdings=[],
        last_balance_check=now,
        sync_health_per_wallet={
            "wallet_001": {"status": "ok", "checked_at": now},
            "wallet_002": {"status": "ok", "checked_at": now},
            "wallet_003": {"status": "ok", "checked_at": now},
        },
    )


def _real_tracker_output_placeholder() -> TrackerOutput:
    now = iso_now()
    return TrackerOutput(
        iso_timestamp=now,
        source="real_api_placeholder",
        wallets_count=0,
        total_value_eur=0.0,
        top_holdings=[],
        last_balance_check=now,
        sync_health_per_wallet={},
    )


def collect_tracker_output() -> TrackerOutput:
    if _is_real_api_enabled():
        return _real_tracker_output_placeholder()
    return _mock_tracker_output()


def _report_path() -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return DF_DIR / "reports" / f"df-152-{date}.json"


def main() -> int:
    if not acquire_lock_with_identity():
        return 3

    try:
        pav = k17_pre_action_verification([DF_DIR])
        if not pav.get("ok"):
            payload = {
                "df": f"DF-{DF_ID}",
                "iso_timestamp": iso_now(),
                "status": "pre_action_verification_failed",
                "k17_pre_action_verification": pav,
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            assert_no_decision_keywords(text)
            path = _report_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            return 3

        tracker = collect_tracker_output()
        if not tracker.iso_timestamp:
            tracker.iso_timestamp = iso_now()
        if not tracker.last_balance_check:
            tracker.last_balance_check = tracker.iso_timestamp

        payload = asdict(tracker)
        payload["k17_pre_action_verification"] = pav
        payload["q0_k0"] = {"decision_keywords": []}

        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        assert_no_decision_keywords(text)

        path = _report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        error_payload = {
            "df": f"DF-{DF_ID}",
            "iso_timestamp": iso_now(),
            "status": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
        try:
            text = json.dumps(error_payload, ensure_ascii=False, indent=2, sort_keys=True)
            assert_no_decision_keywords(text)
            path = _report_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        except Exception:
            pass
        return 3
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())