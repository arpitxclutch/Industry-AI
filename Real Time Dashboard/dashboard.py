from collections import deque
from datetime import datetime
from typing import Deque, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config import APP_CONFIG, MQTT_CONFIG
from mqtt_client import MQTTManager
from risk_engine import RiskEngine
from utils import events_to_dataframe, fmt_ts, now_utc, state_color, to_csv_bytes


st.set_page_config(
    page_title="Industrial Safety Dashboard",
    page_icon="🏭",
    layout="wide",
)

# Light and minimal CSS, close to default Streamlit style
LIGHT_CSS = """
<style>
.block-container {
  padding-top: 1.2rem;
  padding-bottom: 1.2rem;
}
.small-muted { color: #6b7280; font-size: 0.85rem; }
</style>
"""
st.markdown(LIGHT_CSS, unsafe_allow_html=True)


def init_state() -> None:
    if "mqtt_manager" not in st.session_state:
        st.session_state.mqtt_manager = MQTTManager()
        st.session_state.mqtt_manager.start()

    if "risk_engine" not in st.session_state:
        st.session_state.risk_engine = RiskEngine()

    if "history" not in st.session_state:
        st.session_state.history: Deque[Dict[str, object]] = deque(maxlen=APP_CONFIG.max_history_points)

    if "events" not in st.session_state:
        st.session_state.events: Deque[Dict[str, object]] = deque(maxlen=APP_CONFIG.max_event_rows)

    if "latest" not in st.session_state:
        st.session_state.latest = {
            "temperature": 0.0,
            "humidity": 0.0,
            "gas_ppm": 0,
            "motion": False,
            "flame": False,
            "risk_score": 0,
            "decision": "SAFE",
            "control": {"led": "green", "buzzer": False, "relay": True},
            "reasons": ["Waiting for first packet"],
            "timestamp": None,
        }

    if "status_messages" not in st.session_state:
        st.session_state.status_messages: Deque[str] = deque(maxlen=20)

    if "last_auto_decision" not in st.session_state:
        st.session_state.last_auto_decision = None


def process_mqtt_events() -> None:
    manager: MQTTManager = st.session_state.mqtt_manager
    risk_engine: RiskEngine = st.session_state.risk_engine

    while True:
        event = manager.get_event_nowait()
        if event is None:
            break

        if event.kind == "status":
            st.session_state.status_messages.appendleft(f"[{fmt_ts(event.timestamp)}] {event.payload.get('message')}")
            continue

        if event.kind == "sensor":
            payload = event.payload
            risk_result = risk_engine.calculate(payload)
            control = risk_engine.control_for_decision(risk_result.decision)

            record = {
                "timestamp": event.timestamp,
                "temperature": payload["temperature"],
                "humidity": payload["humidity"],
                "gas_ppm": payload["gas_ppm"],
                "motion": payload["motion"],
                "flame": payload["flame"],
                "risk_score": risk_result.risk_score,
                "decision": risk_result.decision,
            }

            st.session_state.history.append(record)
            st.session_state.events.appendleft(record)

            st.session_state.latest = {
                **payload,
                "risk_score": risk_result.risk_score,
                "decision": risk_result.decision,
                "control": control,
                "reasons": risk_result.reasons,
                "timestamp": event.timestamp,
            }

            # Auto-publish only when decision changes
            if st.session_state.last_auto_decision != risk_result.decision:
                manager.publish_control(control)
                st.session_state.last_auto_decision = risk_result.decision


def render_header() -> None:
    manager: MQTTManager = st.session_state.mqtt_manager
    latest = st.session_state.latest

    st.title(APP_CONFIG.project_title)
    st.caption("Real-time Industrial Monitoring Dashboard")

    c1, c2, c3, c4, c5 = st.columns(5)

    mqtt_ok = manager.is_connected()
    esp_ok = latest["timestamp"] is not None and (now_utc().replace(tzinfo=None) - latest["timestamp"]).seconds < 10

    c1.write(f"**Current Time**\n\n{fmt_ts(datetime.now().astimezone())}")
    c2.write(f"**MQTT Connection**\n\n{'🟢 Connected' if mqtt_ok else '⚪ Disconnected'}")
    c3.write(f"**Broker Status**\n\n{MQTT_CONFIG.broker}:{MQTT_CONFIG.port}")
    c4.write(f"**ESP32 Status**\n\n{'🟢 Online' if esp_ok else '⚪ No recent data'}")
    c5.write(f"**Last Update**\n\n{fmt_ts(latest['timestamp'])}")


def render_kpis() -> None:
    latest = st.session_state.latest
    cols = st.columns(5)

    with cols[0]:
        st.metric("Temperature", f"{latest['temperature']:.1f} °C")
        st.caption("Ambient")
    with cols[1]:
        st.metric("Humidity", f"{latest['humidity']:.1f} %")
        st.caption("Relative Humidity")
    with cols[2]:
        st.metric("Gas Level", f"{int(latest['gas_ppm'])} ppm")
        st.caption("Combustible Gas")
    with cols[3]:
        st.metric("Motion", "Detected" if latest["motion"] else "Idle")
        st.caption("PIR Sensor")
    with cols[4]:
        st.metric("Flame", "Detected" if latest["flame"] else "Clear")
        st.caption("Flame Sensor")


def build_gauge(score: int, decision: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": " / 100"},
        title={"text": f"Overall Risk<br><span style='font-size:0.8em;color:#4b5563'>{decision}</span>"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": state_color(decision)},
            "steps": [
                {"range": [0, 40], "color": "#dcfce7"},
                {"range": [40, 70], "color": "#fef9c3"},
                {"range": [70, 100], "color": "#fee2e2"},
            ],
        },
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="#ffffff",
        font=dict(color="#111827"),
        template="plotly_white",
    )
    return fig


def render_status_and_gauge() -> None:
    latest = st.session_state.latest
    c1, c2 = st.columns([2, 1])

    with c1:
        st.plotly_chart(build_gauge(latest["risk_score"], latest["decision"]), use_container_width=True, theme=None)

    with c2:
        control = latest["control"]
        with st.container(border=True):
            st.subheader("System Status")
            st.write(f"Current Alarm: **{latest['decision']}**")
            st.write(f"Relay State: **{'ON' if control['relay'] else 'OFF'}**")
            st.write(f"Buzzer State: **{'ON' if control['buzzer'] else 'OFF'}**")
            st.write(f"Current LED Color: **{control['led'].upper()}**")


def line_chart(history_df: pd.DataFrame, y_col: str, title: str, color: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history_df["timestamp"], y=history_df[y_col], mode="lines", line=dict(color=color, width=2), name=title
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color="#111827", size=16), x=0, xanchor="left"),
        height=260,
        margin=dict(l=20, r=20, t=48, b=20),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#111827"),
        xaxis=dict(showgrid=True, gridcolor="#eef2f7", color="#111827", tickfont=dict(color="#111827"), linecolor="#d1d5db"),
        yaxis=dict(showgrid=True, gridcolor="#eef2f7", color="#111827", tickfont=dict(color="#111827"), linecolor="#d1d5db"),
    )
    # Ensure the whole component canvas (not just the plot area) is opaque white,
    # so titles/labels never render against a dark surrounding theme.
    fig.update_layout(template="plotly_white")
    return fig


def render_charts() -> None:
    history = list(st.session_state.history)
    df = pd.DataFrame(history) if history else pd.DataFrame(columns=["timestamp", "temperature", "humidity", "gas_ppm"])
    c1, c2, c3 = st.columns(3)

    if not df.empty:
        c1.plotly_chart(line_chart(df, "temperature", "Temperature History", "#ef4444"), use_container_width=True, theme=None)
        c2.plotly_chart(line_chart(df, "gas_ppm", "Gas History", "#f59e0b"), use_container_width=True, theme=None)
        c3.plotly_chart(line_chart(df, "humidity", "Humidity History", "#3b82f6"), use_container_width=True, theme=None)
    else:
        c1.info("Waiting for temperature data...")
        c2.info("Waiting for gas data...")
        c3.info("Waiting for humidity data...")


def render_event_log() -> None:
    st.subheader("Live Event Log")
    df = events_to_dataframe(list(st.session_state.events))
    if not df.empty:
        show_df = df.copy()
        show_df["timestamp"] = show_df["timestamp"].astype(str)
        st.dataframe(show_df, use_container_width=True, height=260)
    else:
        st.info("No events yet.")


def render_ai_panel() -> None:
    latest = st.session_state.latest
    st.subheader("AI Decision Panel")
    c1, c2 = st.columns([1, 2])

    with c1:
        st.metric("Current Risk Score", latest["risk_score"])
        st.metric("Final Decision", latest["decision"])

    with c2:
        st.markdown("**Reasons**")
        for r in latest["reasons"]:
            st.write(f"- {r}")


def send_manual_control(command: Dict[str, object]) -> None:
    ok = st.session_state.mqtt_manager.publish_control(command)
    if ok:
        st.success(f"Published: {command}")
    else:
        st.error("Failed to publish control message.")


def render_controls() -> None:
    st.subheader("Control Panel")
    row1 = st.columns(5)
    if row1[0].button("Green"):
        send_manual_control({"led": "green", "buzzer": False, "relay": True})
    if row1[1].button("Yellow"):
        send_manual_control({"led": "yellow", "buzzer": True, "relay": True})
    if row1[2].button("Red"):
        send_manual_control({"led": "red", "buzzer": True, "relay": False})
    if row1[3].button("Emergency Stop"):
        send_manual_control({"led": "red", "buzzer": True, "relay": False})
    if row1[4].button("Reset Alarm"):
        send_manual_control({"led": "green", "buzzer": False, "relay": True})

    row2 = st.columns(4)
    if row2[0].button("Turn Buzzer On"):
        send_manual_control({
            "led": st.session_state.latest["control"]["led"],
            "buzzer": True,
            "relay": st.session_state.latest["control"]["relay"]
        })
    if row2[1].button("Turn Buzzer Off"):
        send_manual_control({
            "led": st.session_state.latest["control"]["led"],
            "buzzer": False,
            "relay": st.session_state.latest["control"]["relay"]
        })
    if row2[2].button("Relay ON"):
        send_manual_control({
            "led": st.session_state.latest["control"]["led"],
            "buzzer": st.session_state.latest["control"]["buzzer"],
            "relay": True
        })
    if row2[3].button("Relay OFF"):
        send_manual_control({
            "led": st.session_state.latest["control"]["led"],
            "buzzer": st.session_state.latest["control"]["buzzer"],
            "relay": False
        })


def render_sidebar() -> None:
    manager: MQTTManager = st.session_state.mqtt_manager
    latest = st.session_state.latest
    hist = pd.DataFrame(list(st.session_state.history))

    st.sidebar.header("Factory Information")
    st.sidebar.write(f"**Broker:** `{MQTT_CONFIG.broker}:{MQTT_CONFIG.port}`")
    st.sidebar.write(f"**Sensor Topic:** `{MQTT_CONFIG.sensor_topic}`")
    st.sidebar.write(f"**Control Topic:** `{MQTT_CONFIG.control_topic}`")
    st.sidebar.write("**ESP32:** Wokwi Simulation")
    st.sidebar.write(f"**Connection:** {'🟢 Connected' if manager.is_connected() else '⚪ Disconnected'}")
    st.sidebar.write(f"**Current Status:** {latest['decision']}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Mini Statistics")
    if not hist.empty:
        st.sidebar.write(f"**Packet Count:** {manager.packet_count()}")
        st.sidebar.write(f"**Uptime:** {manager.uptime_seconds()} s")
        st.sidebar.write(f"**Average Temperature:** {hist['temperature'].mean():.2f} °C")
        st.sidebar.write(f"**Average Gas:** {hist['gas_ppm'].mean():.2f} ppm")
        st.sidebar.write(f"**Max Temperature:** {hist['temperature'].max():.2f} °C")
        st.sidebar.write(f"**Max Gas:** {hist['gas_ppm'].max():.2f} ppm")
        st.sidebar.write(f"**Last Packet:** {fmt_ts(manager.last_packet_at())}")
    else:
        st.sidebar.info("Waiting for telemetry...")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Settings")
    if st.sidebar.button("Export Logs"):
        st.sidebar.success("Logs ready in table below for export.")

    events_df = events_to_dataframe(list(st.session_state.events))
    st.sidebar.download_button(
        label="Download CSV",
        data=to_csv_bytes(events_df),
        file_name="industrial_safety_events.csv",
        mime="text/csv",
    )

    if st.sidebar.button("Clear Logs"):
        st.session_state.events.clear()
        st.session_state.history.clear()
        st.sidebar.success("Logs cleared.")


def main() -> None:
    init_state()
    process_mqtt_events()

    # Auto refresh UI; data itself comes from MQTT callbacks in background thread
    st_autorefresh(interval=APP_CONFIG.ui_refresh_interval_ms, key="live_refresh")

    render_sidebar()
    render_header()
    st.divider()
    render_kpis()
    st.divider()
    render_status_and_gauge()
    st.divider()
    render_charts()
    st.divider()
    render_event_log()
    st.divider()
    render_ai_panel()
    st.divider()
    render_controls()


if __name__ == "__main__":
    main()