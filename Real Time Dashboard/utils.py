from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def state_color(decision: str) -> str:
    mapping = {
        "SAFE": "#16a34a",
        "WARNING": "#eab308",
        "DANGER": "#dc2626",
    }
    return mapping.get(decision, "#6b7280")


def bool_badge(value: bool, true_label: str = "Yes", false_label: str = "No") -> str:
    return true_label if value else false_label


def events_to_dataframe(events: List[Dict[str, object]]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(
            columns=["timestamp", "temperature", "humidity", "gas_ppm", "motion", "flame", "risk_score", "decision"]
        )
    df = pd.DataFrame(events)
    return df.sort_values("timestamp", ascending=False).reset_index(drop=True)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def decision_label(score: int) -> str:
    if score <= 40:
        return "SAFE"
    if score <= 70:
        return "WARNING"
    return "DANGER"