import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
# [CRUX-MK]
# NOTE: 'from 152 import ...' ist syntaktisch ungueltig in Python (Bezeichner
# duerfen nicht mit einer Ziffer beginnen). importlib.import_module('152') ist
# die semantisch aequivalente, laufzeitfahige Alternative.
import importlib
import os
import json
import tempfile
from pathlib import Path

_m = importlib.import_module("152")

CryptoTracker      = _m.CryptoTracker
TokenBalance       = _m.TokenBalance
WalletEntry        = _m.WalletEntry
PositionReport     = _m.PositionReport
mock_wallets       = _m.mock_wallets
NEVER_AUTO_TRADE   = _m.NEVER_AUTO_TRADE
NEVER_WALLET_WRITE = _m.NEVER_WALLET_WRITE


# ── Invarianten ───────────────────────────────────────────────────────────────

def test_invariant_never_auto_trade():
    assert NEVER_AUTO_TRADE is True

def test_invariant_never_wallet_write():
    assert NEVER_WALLET_WRITE is True


# ── TokenBalance ──────────────────────────────────────────────────────────────

def test_token_balance_usd_value():
    tb = TokenBalance(symbol="BTC", amount=2.0, usd_price=50_000.0)
    assert tb.usd_value == 100_000.0

def test_token_balance_zero_price():
    tb = TokenBalance(symbol="XYZ", amount=1_000.0, usd_price=0.0)
    assert tb.usd_value == 0.0

def test_token_balance_fractional():
    tb = TokenBalance(symbol="ETH", amount=0.5, usd_price=3_000.0)
    assert tb.usd_value == 1_500.0


# ── WalletEntry ───────────────────────────────────────────────────────────────

def test_wallet_cold_storage_detection():
    assert WalletEntry("w1", "a", "cold_hw",    "Ledger").is_cold_storage is True
    assert WalletEntry("w2", "a", "cold_paper", "Paper" ).is_cold_storage is True
    assert WalletEntry("w3", "a", "hot",        "MM"    ).is_cold_storage is False

def test_wallet_total_usd_value():
    w = WalletEntry(
        wallet_id="w1", address="0xtest", wallet_type="hot", label="Test",
        balances=[
            TokenBalance("ETH",  5.0,   3_000.0),
            TokenBalance("USDC", 500.0, 1.0),
        ],
    )
    assert w.total_usd_value == 5.0 * 3_000.0 + 500.0


# ── CryptoTracker – Cold-Storage-Verification ─────────────────────────────────

def test_cold_storage_all_verified():
    wallets = [
        WalletEntry("w1", "a1", "cold_hw", "Ledger", hw_verified=True,
                    balances=[TokenBalance("BTC", 1.0, 60_000.0)]),
    ]
    assert CryptoTracker(wallets=wallets).verify_cold_storage() is True

def test_cold_storage_unverified():
    wallets = [
        WalletEntry("w1", "a1", "cold_hw", "Ledger", hw_verified=False,
                    balances=[TokenBalance("BTC", 1.0, 60_000.0)]),
    ]
    assert CryptoTracker(wallets=wallets).verify_cold_storage() is False

def test_cold_storage_no_cold_wallets():
    # keine Cold-Wallets -> vacuously True
    wallets = [
        WalletEntry("w1", "a1", "hot", "MetaMask", hw_verified=False,
                    balances=[TokenBalance("ETH", 1.0, 3_000.0)]),
    ]
    assert CryptoTracker(wallets=wallets).verify_cold_storage() is True

def test_cold_storage_mixed_one_unverified():
    wallets = [
        WalletEntry("w1", "a1", "cold_hw", "Ledger",  hw_verified=True,
                    balances=[TokenBalance("BTC", 1.0, 60_000.0)]),
        WalletEntry("w2", "a2", "cold_hw", "Trezor",  hw_verified=False,
                    balances=[TokenBalance("ETH", 5.0, 3_000.0)]),
    ]
    assert CryptoTracker(wallets=wallets).verify_cold_storage() is False


# ── CryptoTracker – Total USD ─────────────────────────────────────────────────

def test_total_usd_value_mock_wallets():
    tracker  = CryptoTracker(wallets=mock_wallets())
    expected = (1.5 * 65_000.0          # BTC cold
                + 10.0 * 3_500.0        # ETH hot
                + 5_000.0 * 1.0         # USDC hot
                + 25.0 * 3_500.0)       # ETH cold
    assert tracker.get_total_usd_value() == round(expected, 2)

def test_total_usd_empty_wallets():
    assert CryptoTracker(wallets=[]).get_total_usd_value() == 0.0


# ── Real-API-Gating ───────────────────────────────────────────────────────────

def test_real_api_disabled_by_default():
    os.environ.pop("DF_152_REAL_API_ENABLED", None)
    assert CryptoTracker().is_real_api_enabled() is False

def test_real_api_enabled_exact_lowercase():
    os.environ["DF_152_REAL_API_ENABLED"] = "true"
    assert CryptoTracker().is_real_api_enabled() is True
    del os.environ["DF_152_REAL_API_ENABLED"]

def test_real_api_truthy_variants_rejected():
    # Nur exakt "true" darf aktivieren – alle anderen Werte werden abgelehnt
    for val in ("1", "yes", "True", "TRUE", "on", "t", "enabled"):
        os.environ["DF_152_REAL_API_ENABLED"] = val
        assert CryptoTracker().is_real_api_enabled() is False, \
            f"'{val}' sollte Real-API NICHT aktivieren"
    os.environ.pop("DF_152_REAL_API_ENABLED", None)


# ── Report-Erstellung ─────────────────────────────────────────────────────────

def test_build_report_mock_mode():
    os.environ.pop("DF_152_REAL_API_ENABLED", None)
    report = CryptoTracker(wallets=mock_wallets()).build_report()
    assert isinstance(report, PositionReport)
    assert report.source        == "mock"
    assert report.real_api_used is False
    assert report.total_usd_value > 0
    assert report.cold_storage_verified is True
    assert report.timestamp.endswith("Z")

def test_build_report_to_dict_structure():
    d = CryptoTracker(wallets=mock_wallets()).build_report().to_dict()
    for key in ("timestamp", "total_usd_value", "cold_storage_verified", "source", "wallets"):
        assert key in d
    assert len(d["wallets"]) == 3

def test_report_address_masking():
    w = WalletEntry("w1", "bc1qverylongaddress0001", "cold_hw", "Ledger",
                    hw_verified=True, balances=[TokenBalance("BTC", 1.0, 60_000.0)])
    d = CryptoTracker(wallets=[w]).build_report().to_dict()
    masked = d["wallets"][0]["address_masked"]
    assert "…" in masked
    assert masked != "bc1qverylongaddress0001"   # niemals Klartextadresse

def test_report_balance_detail():
    w = WalletEntry("w1", "0xtest", "hot", "MM",
                    balances=[TokenBalance("ETH", 2.0, 3_000.0)])
    d = CryptoTracker(wallets=[w]).build_report().to_dict()
    bal = d["wallets"][0]["balances"][0]
    assert bal["symbol"]    == "ETH"
    assert bal["amount"]    == 2.0
    assert bal["usd_value"] == 6_000.0


# ── Report-Speicherung ────────────────────────────────────────────────────────

def test_save_report_creates_json_file():
    with tempfile.TemporaryDirectory() as tmp:
        tracker = CryptoTracker(wallets=mock_wallets(), reports_dir=tmp)
        report  = tracker.build_report()
        path    = tracker.save_report(report)
        assert path.exists()
        assert path.suffix == ".json"
        assert "df-152-" in path.name

def test_save_report_valid_json_content():
    with tempfile.TemporaryDirectory() as tmp:
        tracker = CryptoTracker(wallets=mock_wallets(), reports_dir=tmp)
        path    = tracker.save_report(tracker.build_report())
        data    = json.loads(path.read_text(encoding="utf-8"))
        assert data["total_usd_value"] > 0
        assert data["source"] == "mock"
        assert len(data["wallets"]) == 3

def test_run_creates_report_and_returns_it():
    with tempfile.TemporaryDirectory() as tmp:
        tracker = CryptoTracker(wallets=mock_wallets(), reports_dir=tmp)
        report  = tracker.run()
        assert isinstance(report, PositionReport)
        files   = list(Path(tmp).glob("df-152-*.json"))
        assert len(files) == 1


# ── Mock-Wallets ──────────────────────────────────────────────────────────────

def test_mock_wallets_count_and_types():
    wallets = mock_wallets()
    assert len(wallets) == 3
    assert all(isinstance(w, WalletEntry) for w in wallets)

def test_mock_wallets_cold_storage_all_hw_verified():
    cold = [w for w in mock_wallets() if w.is_cold_storage]
    assert len(cold) >= 1
    assert all(w.hw_verified for w in cold)

def test_mock_wallets_have_balances():
    assert all(len(w.balances) >= 1 for w in mock_wallets())

