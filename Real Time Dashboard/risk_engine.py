from dataclasses import dataclass
from typing import Dict, List, Tuple

from config import RISK_CONFIG, STATE_TO_CONTROL


@dataclass
class RiskResult:
    risk_score: int
    decision: str
    led_color: str
    buzzer: bool
    relay: bool
    reasons: List[str]
    reason_points: List[Tuple[str, int]]


class RiskEngine:
    def __init__(self) -> None:
        self.cfg = RISK_CONFIG

    @staticmethod
    def _score_from_bands(value: float, bands: List[Tuple[float, float, int, str]]) -> Tuple[int, str]:
        for low, high, score, label in bands:
            if low <= value < high:
                return score, label
        return 0, "Unknown"

    def calculate(self, payload: Dict[str, object]) -> RiskResult:
        temperature = float(payload.get("temperature", 0))
        gas = float(payload.get("gas_ppm", 0))
        motion = bool(payload.get("motion", False))
        flame = bool(payload.get("flame", False))

        temp_score, temp_label = self._score_from_bands(temperature, self.cfg.temperature_bands)
        gas_score, gas_label = self._score_from_bands(gas, self.cfg.gas_bands)
        motion_score = self.cfg.motion_score if motion else 0
        flame_score = self.cfg.flame_score if flame else 0

        reasons: List[str] = []
        reason_points: List[Tuple[str, int]] = []

        if temp_score > 0:
            reasons.append(f"+{temp_score} {temp_label}")
            reason_points.append((temp_label, temp_score))
        if gas_score > 0:
            reasons.append(f"+{gas_score} {gas_label}")
            reason_points.append((gas_label, gas_score))
        if motion_score > 0:
            reasons.append(f"+{motion_score} Motion detected")
            reason_points.append(("Motion detected", motion_score))
        if flame_score > 0:
            reasons.append(f"+{flame_score} Flame detected")
            reason_points.append(("Flame detected", flame_score))

        total = min(100, temp_score + gas_score + motion_score + flame_score)

        if total <= self.cfg.safe_max:
            decision = "SAFE"
        elif total <= self.cfg.warning_max:
            decision = "WARNING"
        else:
            decision = "DANGER"

        control = STATE_TO_CONTROL[decision]
        return RiskResult(
            risk_score=total,
            decision=decision,
            led_color=str(control["led"]),
            buzzer=bool(control["buzzer"]),
            relay=bool(control["relay"]),
            reasons=reasons if reasons else ["No significant risk factors"],
            reason_points=reason_points,
        )

    def control_for_decision(self, decision: str) -> Dict[str, object]:
        return STATE_TO_CONTROL.get(decision, STATE_TO_CONTROL["SAFE"]).copy()