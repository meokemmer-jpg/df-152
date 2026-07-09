"""
DF-152 KPM-Crypto-Position-Tracker [CRUX-MK]
Read-only crypto wallet position tracker.

The tracker reads wallet and price snapshots from JSON files, calculates a
portfolio report, and writes only report files. It never trades and never writes
back to wallet source data.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, Optional


NEVER_AUTO_TRADE = True
NEVER_WALLET_WRITE = True

REAL_API_ENV = "DF_152_REAL_API_ENABLED"
ALLOWED_WALLET_TYPES = {"hot", "cold_hw", "cold_paper"}


@dataclass(frozen=True)
class TokenBalance:
    symbol: str
    amount: float
    usd_price: float = 0.0

    @property
    def usd_value(self) -> float:
        return self.amount * self.usd_price


@dataclass(frozen=True)
class WalletEntry:
    wallet_id: str
    address: str
    wallet_type: str
    label: str
    balances: List[TokenBalance] = field(default_factory=list)
    hw_verified: bool = False

    @property
    def is_cold_storage(self) -> bool:
        return self.wallet_type.startswith("cold")

    @property
    def total_usd_value(self) -> float:
        return sum(balance.usd_value for balance in self.balances)


@dataclass(frozen=True)
class PositionReport:
    timestamp: str
    wallets: List[WalletEntry]
    total_usd_value: float
    cold_storage_verified: bool
    source: str
    real_api_used: bool
    status: str
    findings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def mask_address(address: str) -> str:
            if len(address) <= 10:
                return address
            return f"{address[:6]}...{address[-4:]}"

        return {
            "timestamp": self.timestamp,
            "total_usd_value": self.total_usd_value,
            "cold_storage_verified": self.cold_storage_verified,
            "source": self.source,
            "real_api_used": self.real_api_used,
            "status": self.status,
            "findings": list(self.findings),
            "wallets": [
                {
                    "wallet_id": wallet.wallet_id,
                    "address_masked": mask_address(wallet.address),
                    "wallet_type": wallet.wallet_type,
                    "label": wallet.label,
                    "is_cold_storage": wallet.is_cold_storage,
                    "hw_verified": wallet.hw_verified,
                    "total_usd_value": round(wallet.total_usd_value, 2),
                    "balances": [
                        {
                            "symbol": balance.symbol,
                            "amount": balance.amount,
                            "usd_price": balance.usd_price,
                            "usd_value": round(balance.usd_value, 2),
                        }
                        for balance in wallet.balances
                    ],
                }
                for wallet in self.wallets
            ],
        }


def _read_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"input file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg}") from exc


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _require_sequence(value: object, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def load_prices_from_json(path: str | Path) -> dict[str, float]:
    raw = _require_mapping(_read_json_file(Path(path)), "price snapshot")
    prices_raw = _require_mapping(raw.get("prices_usd"), "prices_usd")
    prices: dict[str, float] = {}
    for symbol, price in prices_raw.items():
        token = _text(symbol, "price symbol").upper()
        numeric_price = _number(price, f"prices_usd.{token}")
        if numeric_price < 0:
            raise ValueError(f"prices_usd.{token} must not be negative")
        prices[token] = numeric_price
    return prices


def load_wallets_from_json(path: str | Path, prices: Mapping[str, float]) -> List[WalletEntry]:
    raw = _require_mapping(_read_json_file(Path(path)), "wallet snapshot")
    wallets_raw = _require_sequence(raw.get("wallets"), "wallets")
    wallets: List[WalletEntry] = []

    for index, wallet_raw in enumerate(wallets_raw):
        wallet = _require_mapping(wallet_raw, f"wallets[{index}]")
        wallet_type = _text(wallet.get("wallet_type"), f"wallets[{index}].wallet_type")
        if wallet_type not in ALLOWED_WALLET_TYPES:
            raise ValueError(f"wallets[{index}].wallet_type is unsupported: {wallet_type}")

        balances: List[TokenBalance] = []
        for balance_index, balance_raw in enumerate(
            _require_sequence(wallet.get("balances"), f"wallets[{index}].balances")
        ):
            balance = _require_mapping(
                balance_raw, f"wallets[{index}].balances[{balance_index}]"
            )
            symbol = _text(
                balance.get("symbol"),
                f"wallets[{index}].balances[{balance_index}].symbol",
            ).upper()
            amount = _number(
                balance.get("amount"),
                f"wallets[{index}].balances[{balance_index}].amount",
            )
            if amount < 0:
                raise ValueError(
                    f"wallets[{index}].balances[{balance_index}].amount must not be negative"
                )
            if symbol not in prices:
                raise ValueError(f"missing USD price for token {symbol}")
            balances.append(TokenBalance(symbol=symbol, amount=amount, usd_price=prices[symbol]))

        wallets.append(
            WalletEntry(
                wallet_id=_text(wallet.get("wallet_id"), f"wallets[{index}].wallet_id"),
                address=_text(wallet.get("address"), f"wallets[{index}].address"),
                wallet_type=wallet_type,
                label=_text(wallet.get("label"), f"wallets[{index}].label"),
                balances=balances,
                hw_verified=_bool(wallet.get("hw_verified"), f"wallets[{index}].hw_verified"),
            )
        )
    return wallets


def mock_wallets() -> List[WalletEntry]:
    return [
        WalletEntry(
            wallet_id="w001",
            address="bc1qexamplebtcmainaddress001",
            wallet_type="cold_hw",
            label="Ledger-BTC-Main",
            hw_verified=True,
            balances=[TokenBalance(symbol="BTC", amount=1.5, usd_price=65000.0)],
        ),
        WalletEntry(
            wallet_id="w002",
            address="0xABCDEF1234567890ABCDEF",
            wallet_type="hot",
            label="MetaMask-ETH-Daily",
            hw_verified=False,
            balances=[
                TokenBalance(symbol="ETH", amount=10.0, usd_price=3500.0),
                TokenBalance(symbol="USDC", amount=5000.0, usd_price=1.0),
            ],
        ),
        WalletEntry(
            wallet_id="w003",
            address="0xTREZOR00001111SAVINGSETH",
            wallet_type="cold_hw",
            label="Trezor-ETH-Savings",
            hw_verified=True,
            balances=[TokenBalance(symbol="ETH", amount=25.0, usd_price=3500.0)],
        ),
    ]


class CryptoTracker:
    """
    Read-only KPM crypto position tracker.
    """

    def __init__(
        self,
        wallets: Optional[List[WalletEntry]] = None,
        reports_dir: str | Path = "reports",
        wallet_snapshot_path: str | Path | None = None,
        price_snapshot_path: str | Path | None = None,
    ) -> None:
        assert NEVER_AUTO_TRADE, "K0 violation: auto-trading is forbidden"
        assert NEVER_WALLET_WRITE, "K0 violation: wallet writes are forbidden"
        self.wallets = wallets
        self.reports_dir = Path(reports_dir)
        self.wallet_snapshot_path = Path(wallet_snapshot_path) if wallet_snapshot_path else None
        self.price_snapshot_path = Path(price_snapshot_path) if price_snapshot_path else None

    @classmethod
    def from_json_files(
        cls,
        wallet_snapshot_path: str | Path,
        price_snapshot_path: str | Path,
        reports_dir: str | Path = "reports",
    ) -> "CryptoTracker":
        prices = load_prices_from_json(price_snapshot_path)
        wallets = load_wallets_from_json(wallet_snapshot_path, prices)
        return cls(
            wallets=wallets,
            reports_dir=reports_dir,
            wallet_snapshot_path=wallet_snapshot_path,
            price_snapshot_path=price_snapshot_path,
        )

    def is_real_api_enabled(self) -> bool:
        return os.environ.get(REAL_API_ENV) == "true"

    def _wallets(self) -> List[WalletEntry]:
        if self.wallets is not None:
            return list(self.wallets)
        if self.wallet_snapshot_path is None or self.price_snapshot_path is None:
            return []
        prices = load_prices_from_json(self.price_snapshot_path)
        return load_wallets_from_json(self.wallet_snapshot_path, prices)

    def verify_cold_storage(self) -> bool:
        cold_wallets = [wallet for wallet in self._wallets() if wallet.is_cold_storage]
        return all(wallet.hw_verified for wallet in cold_wallets)

    def get_total_usd_value(self) -> float:
        return round(sum(wallet.total_usd_value for wallet in self._wallets()), 2)

    def assess_findings(self, wallets: Iterable[WalletEntry]) -> List[str]:
        findings: List[str] = []
        for wallet in wallets:
            if wallet.is_cold_storage and not wallet.hw_verified:
                findings.append(f"cold wallet {wallet.wallet_id} is not hardware-verified")
            if wallet.total_usd_value == 0 and wallet.balances:
                findings.append(f"wallet {wallet.wallet_id} has balances without USD value")
        return findings

    def build_report(self) -> PositionReport:
        wallets = self._wallets()
        real_api = self.is_real_api_enabled()
        findings = self.assess_findings(wallets)
        cold_storage_verified = all(
            wallet.hw_verified for wallet in wallets if wallet.is_cold_storage
        )
        return PositionReport(
            timestamp=_dt.datetime.utcnow().isoformat() + "Z",
            wallets=wallets,
            total_usd_value=round(sum(wallet.total_usd_value for wallet in wallets), 2),
            cold_storage_verified=cold_storage_verified,
            source="real-api" if real_api else "file-json",
            real_api_used=real_api,
            status="ok" if not findings else "attention",
            findings=findings,
        )

    def save_report(self, report: PositionReport) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        date_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
        output_path = self.reports_dir / f"df-152-{date_str}.json"
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path

    def run(self) -> PositionReport:
        report = self.build_report()
        self.save_report(report)
        return report


def __df_guarded_entry() -> int:
    tracker = CryptoTracker(wallets=mock_wallets())
    report = tracker.run()
    print(f"[DF-152] total_usd_value : ${report.total_usd_value:>14,.2f}")
    print(f"[DF-152] cold_storage_ok : {report.cold_storage_verified}")
    print(f"[DF-152] source          : {report.source}")
    print(f"[DF-152] status          : {report.status}")
    print(f"[DF-152] wallets tracked : {len(report.wallets)}")
    return 0


if __name__ == "__main__":
    try:
        from _df_common.df_foundation import run_guarded as _run_guarded
    except Exception:
        raise SystemExit(__df_guarded_entry())
    raise SystemExit(_run_guarded("df-152", __df_guarded_entry))
