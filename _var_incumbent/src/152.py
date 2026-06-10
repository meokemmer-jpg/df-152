"""
DF-152 KPM-Crypto-Position-Tracker [CRUX-MK]
Read-Only Crypto-Wallet-Tracker.
NIEMALS Auto-Trade. NIEMALS Wallet-Write.
"""

import os
import json
import datetime
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


# ── Invarianten (K_0-Guard, unveraenderlich) ──────────────────────────────────
NEVER_AUTO_TRADE   = True   # READ-ONLY
NEVER_WALLET_WRITE = True   # READ-ONLY

REAL_API_ENV = "DF_152_REAL_API_ENABLED"


# ── Datenmodell ───────────────────────────────────────────────────────────────

@dataclass
class TokenBalance:
    symbol: str
    amount: float
    usd_price: float = 0.0

    @property
    def usd_value(self) -> float:
        return self.amount * self.usd_price


@dataclass
class WalletEntry:
    wallet_id: str
    address: str
    wallet_type: str   # "hot" | "cold_hw" | "cold_paper"
    label: str
    balances: List[TokenBalance] = field(default_factory=list)
    hw_verified: bool = False

    @property
    def is_cold_storage(self) -> bool:
        return self.wallet_type.startswith("cold")

    @property
    def total_usd_value(self) -> float:
        return sum(b.usd_value for b in self.balances)


@dataclass
class PositionReport:
    timestamp: str
    wallets: List[WalletEntry]
    total_usd_value: float
    cold_storage_verified: bool
    source: str          # "mock" | "real-api"
    real_api_used: bool

    def to_dict(self) -> dict:
        def _mask(addr: str) -> str:
            return (addr[:6] + "…" + addr[-4:]) if len(addr) > 10 else addr

        return {
            "timestamp": self.timestamp,
            "total_usd_value": self.total_usd_value,
            "cold_storage_verified": self.cold_storage_verified,
            "source": self.source,
            "real_api_used": self.real_api_used,
            "wallets": [
                {
                    "wallet_id": w.wallet_id,
                    "address_masked": _mask(w.address),
                    "wallet_type": w.wallet_type,
                    "label": w.label,
                    "is_cold_storage": w.is_cold_storage,
                    "hw_verified": w.hw_verified,
                    "total_usd_value": round(w.total_usd_value, 2),
                    "balances": [
                        {
                            "symbol": b.symbol,
                            "amount": b.amount,
                            "usd_price": b.usd_price,
                            "usd_value": round(b.usd_value, 2),
                        }
                        for b in w.balances
                    ],
                }
                for w in self.wallets
            ],
        }


# ── Kern-Tracker ──────────────────────────────────────────────────────────────

class CryptoTracker:
    """
    Read-Only KPM Crypto Position Tracker.
    Invariante: NIEMALS schreibt diese Klasse in Wallets.
    Invariante: NIEMALS loest diese Klasse Trades aus.
    """

    def __init__(
        self,
        wallets: Optional[List[WalletEntry]] = None,
        reports_dir: str = "reports",
    ) -> None:
        assert NEVER_AUTO_TRADE,   "K0-Verletzung: Auto-Trade verboten"
        assert NEVER_WALLET_WRITE, "K0-Verletzung: Wallet-Write verboten"
        self.wallets: List[WalletEntry] = wallets or []
        self.reports_dir = Path(reports_dir)

    def is_real_api_enabled(self) -> bool:
        # Nur exakt "true" aktiviert Real-Modus (case-sensitive, per ENV-Var-Rule)
        return os.environ.get(REAL_API_ENV) == "true"

    def verify_cold_storage(self) -> bool:
        """True wenn alle Cold-Storage-Wallets hw_verified=True haben."""
        cold = [w for w in self.wallets if w.is_cold_storage]
        return all(w.hw_verified for w in cold)  # vacuously True wenn leer

    def get_total_usd_value(self) -> float:
        return round(sum(w.total_usd_value for w in self.wallets), 2)

    def build_report(self) -> PositionReport:
        """Erstellt Position-Report (READ-ONLY, kein Wallet-Write)."""
        real_api = self.is_real_api_enabled()
        return PositionReport(
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            wallets=self.wallets,
            total_usd_value=self.get_total_usd_value(),
            cold_storage_verified=self.verify_cold_storage(),
            source="real-api" if real_api else "mock",
            real_api_used=real_api,
        )

    def save_report(self, report: PositionReport) -> Path:
        """Schreibt NUR den Report. Kein Wallet-Write."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        out = self.reports_dir / f"df-152-{date_str}.json"
        out.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return out

    def run(self) -> PositionReport:
        """Haupt-Einstiegspunkt: Report erstellen und speichern (READ-ONLY)."""
        report = self.build_report()
        self.save_report(report)
        return report


# ── Mock-Daten ────────────────────────────────────────────────────────────────

def mock_wallets() -> List[WalletEntry]:
    """Standard-Mock-Wallets fuer Tests und Default-Modus."""
    return [
        WalletEntry(
            wallet_id="w001",
            address="bc1qexamplebtcmainaddress001",
            wallet_type="cold_hw",
            label="Ledger-BTC-Main",
            hw_verified=True,
            balances=[TokenBalance(symbol="BTC", amount=1.5, usd_price=65_000.0)],
        ),
        WalletEntry(
            wallet_id="w002",
            address="0xABCDEF1234567890ABCDEF",
            wallet_type="hot",
            label="MetaMask-ETH-Daily",
            hw_verified=False,
            balances=[
                TokenBalance(symbol="ETH",  amount=10.0,    usd_price=3_500.0),
                TokenBalance(symbol="USDC", amount=5_000.0, usd_price=1.0),
            ],
        ),
        WalletEntry(
            wallet_id="w003",
            address="0xTREZOR00001111SAVINGSETH",
            wallet_type="cold_hw",
            label="Trezor-ETH-Savings",
            hw_verified=True,
            balances=[TokenBalance(symbol="ETH", amount=25.0, usd_price=3_500.0)],
        ),
    ]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tracker = CryptoTracker(wallets=mock_wallets())
    report  = tracker.run()
    print(f"[DF-152] total_usd_value : ${report.total_usd_value:>14,.2f}")
    print(f"[DF-152] cold_storage_ok : {report.cold_storage_verified}")
    print(f"[DF-152] source          : {report.source}")
    print(f"[DF-152] wallets tracked : {len(report.wallets)}")
# [CRUX-MK]
