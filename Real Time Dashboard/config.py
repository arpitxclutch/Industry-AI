from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class MQTTConfig:
    broker: str = "broker.hivemq.com"
    port: int = 1883
    sensor_topic: str = "factory/section1/sensors"
    control_topic: str = "factory/section1/control"
    keepalive: int = 60
    client_prefix: str = "streamlit-industrial-safety"


@dataclass(frozen=True)
class AppConfig:
    project_title: str = "Intelligent Industrial Safety and Predictive Risk Monitoring System"
    max_history_points: int = 100
    max_event_rows: int = 5000
    ui_refresh_interval_ms: int = 1000  # UI poll loop interval


@dataclass(frozen=True)
class RiskThresholds:
    temperature_bands: List[Tuple[float, float, int, str]] = field(
        default_factory=lambda: [
            (-1e9, 35, 0, "Temperature normal"),
            (35, 45, 15, "Temperature elevated"),
            (45, 55, 30, "Temperature high"),
            (55, 1e9, 50, "Temperature critical"),
        ]
    )
    gas_bands: List[Tuple[float, float, int, str]] = field(
        default_factory=lambda: [
            (-1e9, 300, 0, "Gas normal"),
            (300, 500, 20, "Gas elevated"),
            (500, 700, 40, "Gas high"),
            (700, 1e9, 60, "Gas critical"),
        ]
    )
    motion_score: int = 10
    flame_score: int = 40
    safe_max: int = 40
    warning_max: int = 70


MQTT_CONFIG = MQTTConfig()
APP_CONFIG = AppConfig()
RISK_CONFIG = RiskThresholds()

STATE_TO_CONTROL: Dict[str, Dict[str, object]] = {
    "SAFE": {"led": "green", "buzzer": False, "relay": True},
    "WARNING": {"led": "yellow", "buzzer": True, "relay": True},
    "DANGER": {"led": "red", "buzzer": True, "relay": False},
}