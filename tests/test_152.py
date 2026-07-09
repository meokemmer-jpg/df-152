import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import importlib
import json
from pathlib import Path


_m = importlib.import_module("152")

CryptoTracker = _m.CryptoTracker
TokenBalance = _m.TokenBalance
WalletEntry = _m.WalletEntry
PositionReport = _m.PositionReport
load_prices_from_json = _m.load_prices_from_json
load_wallets_from_json = _m.load_wallets_from_json
mock_wallets = _m.mock_wallets
NEVER_AUTO_TRADE = _m.NEVER_AUTO_TRADE
NEVER_WALLET_WRITE = _m.NEVER_WALLET_WRITE


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _case_files(tmp_path: Path, *, verified: bool, eth_amount: float) -> tuple[Path, Path]:
    wallets = {
        "wallets": [
            {
                "wallet_id": "cold-main",
                "address": "bc1qrealcoldwallet00000000152",
                "wallet_type": "cold_hw",
                "label": "Ledger treasury",
                "hw_verified": verified,
                "balances": [{"symbol": "BTC", "amount": 1.25}],
            },
            {
                "wallet_id": "hot-ops",
                "address": "0x152HOTOPS0000000000000000",
                "wallet_type": "hot",
                "label": "Operations",
                "hw_verified": False,
                "balances": [{"symbol": "ETH", "amount": eth_amount}],
            },
        ]
    }
    prices = {"prices_usd": {"BTC": 64000, "ETH": 3200}}
    return (
        _write_json(tmp_path / f"wallets-{verified}-{eth_amount}.json", wallets),
        _write_json(tmp_path / f"prices-{verified}-{eth_amount}.json", prices),
    )


def test_invariants_are_read_only():
    assert NEVER_AUTO_TRADE is True
    assert NEVER_WALLET_WRITE is True


def test_token_and_wallet_values_are_computed_from_balances():
    wallet = WalletEntry(
        wallet_id="w1",
        address="0xabc",
        wallet_type="hot",
        label="Ops",
        balances=[TokenBalance("ETH", 2.5, 3000.0), TokenBalance("USDC", 10.0, 1.0)],
    )

    assert wallet.is_cold_storage is False
    assert wallet.total_usd_value == 7510.0


def test_file_loader_rejects_unknown_token_price(tmp_path):
    wallet_path = _write_json(
        tmp_path / "wallets.json",
        {
            "wallets": [
                {
                    "wallet_id": "w1",
                    "address": "0xabc",
                    "wallet_type": "hot",
                    "label": "Ops",
                    "hw_verified": False,
                    "balances": [{"symbol": "DOGE", "amount": 4}],
                }
            ]
        },
    )
    price_path = _write_json(tmp_path / "prices.json", {"prices_usd": {"ETH": 3000}})

    prices = load_prices_from_json(price_path)
    try:
        load_wallets_from_json(wallet_path, prices)
    except ValueError as exc:
        assert "missing USD price for token DOGE" in str(exc)
    else:
        raise AssertionError("unknown token prices must be rejected")


def test_tracker_discriminates_adversarial_file_input(tmp_path):
    good_wallets, good_prices = _case_files(tmp_path, verified=True, eth_amount=3.0)
    bad_wallets, bad_prices = _case_files(tmp_path, verified=False, eth_amount=0.0)

    good_report = CryptoTracker.from_json_files(
        good_wallets, good_prices, reports_dir=tmp_path / "reports-good"
    ).build_report()
    bad_report = CryptoTracker.from_json_files(
        bad_wallets, bad_prices, reports_dir=tmp_path / "reports-bad"
    ).build_report()

    assert isinstance(good_report, PositionReport)
    assert good_report.source == "file-json"
    assert good_report.status == "ok"
    assert good_report.cold_storage_verified is True
    assert good_report.total_usd_value == 1.25 * 64000 + 3.0 * 3200

    assert bad_report.status == "attention"
    assert bad_report.cold_storage_verified is False
    assert bad_report.total_usd_value == 1.25 * 64000
    assert bad_report.findings == [
        "cold wallet cold-main is not hardware-verified",
        "wallet hot-ops has balances without USD value",
    ]

    assert bad_report.to_dict() != good_report.to_dict()
    assert bad_report.status != good_report.status
    assert bad_report.cold_storage_verified != good_report.cold_storage_verified
    assert bad_report.total_usd_value != good_report.total_usd_value


def test_run_writes_report_but_does_not_modify_input_files(tmp_path):
    wallet_path, price_path = _case_files(tmp_path, verified=True, eth_amount=1.0)
    before_wallet = wallet_path.read_text(encoding="utf-8")
    before_price = price_path.read_text(encoding="utf-8")

    report = CryptoTracker.from_json_files(
        wallet_path, price_path, reports_dir=tmp_path / "reports"
    ).run()
    written = list((tmp_path / "reports").glob("df-152-*.json"))

    assert report.status == "ok"
    assert len(written) == 1
    assert json.loads(written[0].read_text(encoding="utf-8"))["status"] == "ok"
    assert wallet_path.read_text(encoding="utf-8") == before_wallet
    assert price_path.read_text(encoding="utf-8") == before_price


def test_mock_wallets_remain_available_for_cli_default():
    wallets = mock_wallets()
    assert len(wallets) == 3
    assert all(isinstance(wallet, WalletEntry) for wallet in wallets)
