import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from config import MQTT_CONFIG


@dataclass
class MQTTEvent:
    kind: str
    timestamp: datetime
    payload: Dict[str, Any]


class MQTTManager:
    """
    Thread-safe MQTT manager.
    - Receives sensor messages in callback thread
    - Pushes normalized events to Queue for Streamlit thread
    - Handles reconnect and status tracking
    """

    def __init__(self) -> None:
        self._events: Queue[MQTTEvent] = Queue()
        self._client = mqtt.Client(
            client_id=f"{MQTT_CONFIG.client_prefix}-{uuid.uuid4().hex[:8]}",
            clean_session=True
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._lock = threading.Lock()
        self._connected = False
        self._last_packet_at: Optional[datetime] = None
        self._packet_count = 0
        self._started = False
        self._start_time = time.time()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(MQTT_CONFIG.broker, MQTT_CONFIG.port, keepalive=MQTT_CONFIG.keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def packet_count(self) -> int:
        with self._lock:
            return self._packet_count

    def last_packet_at(self) -> Optional[datetime]:
        with self._lock:
            return self._last_packet_at

    def uptime_seconds(self) -> int:
        return int(time.time() - self._start_time)

    def publish_control(self, command: Dict[str, Any]) -> bool:
        payload = json.dumps(command)
        info = self._client.publish(MQTT_CONFIG.control_topic, payload=payload, qos=0, retain=False)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def get_event_nowait(self) -> Optional[MQTTEvent]:
        try:
            return self._events.get_nowait()
        except Empty:
            return None

    # ---------- MQTT callbacks ----------
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        with self._lock:
            self._connected = rc == 0
        if rc == 0:
            client.subscribe(MQTT_CONFIG.sensor_topic, qos=0)
            self._events.put(
                MQTTEvent(kind="status", timestamp=datetime.now(), payload={"message": "Connected to broker"})
            )
        else:
            self._events.put(
                MQTTEvent(kind="status", timestamp=datetime.now(), payload={"message": f"Connect failed rc={rc}"})
            )

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        with self._lock:
            self._connected = False
        self._events.put(
            MQTTEvent(kind="status", timestamp=datetime.now(), payload={"message": f"Disconnected rc={rc}"})
        )

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        ts = datetime.now()
        try:
            raw = msg.payload.decode("utf-8", errors="ignore")
            data = json.loads(raw)
            normalized = {
                "gas_ppm": int(data.get("gas_ppm", 0)),
                "temperature": float(data.get("temperature", 0)),
                "humidity": float(data.get("humidity", 0)),
                "flame": bool(data.get("flame", False)),
                "motion": bool(data.get("motion", False)),
            }

            with self._lock:
                self._packet_count += 1
                self._last_packet_at = ts

            self._events.put(MQTTEvent(kind="sensor", timestamp=ts, payload=normalized))
        except Exception as exc:
            self._events.put(
                MQTTEvent(kind="status", timestamp=ts, payload={"message": f"Invalid message: {exc}"})
            )