"""Realistic supply/exhaust ventilation unit (PV) telemetry emulator for ThingsBoard."""

from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TB_HOST = os.getenv("TB_HOST", "localhost")
TB_MQTT_PORT = int(os.getenv("TB_MQTT_PORT", "1883"))
TB_DEVICE_TOKEN = os.getenv("TB_DEVICE_TOKEN", "")
TB_DEVICE_NAME = os.getenv("TB_DEVICE_NAME", "PV-01")
SEND_INTERVAL_SEC = float(os.getenv("SEND_INTERVAL_SEC", "2"))
FILTER_GROWTH_PA_PER_MIN = float(os.getenv("FILTER_GROWTH_PA_PER_MIN", "5"))

if not TB_DEVICE_TOKEN or TB_DEVICE_TOKEN == "PASTE_DEVICE_ACCESS_TOKEN":
    raise SystemExit(
        "TB_DEVICE_TOKEN is not configured. Create a ThingsBoard device and put its access token in .env."
    )


@dataclass
class PVState:
    supply_temp: float = 18.0
    humidity: float = 48.0
    filter_dp: float = 180.0
    heating_valve: float = 20.0
    cooling_valve: float = 0.0
    fan_supply_rpm: float = 0.0
    fan_exhaust_rpm: float = 0.0
    running: bool = True


state = PVState()
random.seed(42)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def telemetry(elapsed_s: float, dt: float) -> dict[str, object]:
    # Outdoor temperature changes slowly instead of jumping randomly.
    outdoor_temp = (
        6.0
        + 4.0 * math.sin(2 * math.pi * elapsed_s / 900.0)
        + 0.4 * math.sin(2 * math.pi * elapsed_s / 180.0)
        + random.gauss(0, 0.08)
    )
    setpoint = 21.5 + (1.0 if int(elapsed_s // 300) % 2 else 0.0)

    # A periodic short fan fault is included only to demonstrate alarm handling.
    fault_cycle = elapsed_s % 180.0
    fan_fault = 110.0 <= fault_cycle < 122.0
    running = not fan_fault

    if running:
        state.fan_supply_rpm += (1450 - state.fan_supply_rpm) * 0.25 + random.gauss(0, 5)
        state.fan_exhaust_rpm += (1320 - state.fan_exhaust_rpm) * 0.25 + random.gauss(0, 5)

        error = setpoint - state.supply_temp
        if error >= 0:
            state.heating_valve += 2.2 * error * dt / 2.0
            state.cooling_valve -= 2.0 * dt
        else:
            state.cooling_valve += -2.2 * error * dt / 2.0
            state.heating_valve -= 2.0 * dt

        state.heating_valve = clamp(state.heating_valve, 0, 100)
        state.cooling_valve = clamp(state.cooling_valve, 0, 100)

        if state.heating_valve > 1:
            target_temp = outdoor_temp + (setpoint - outdoor_temp) * min(state.heating_valve / 100, 1)
        elif state.cooling_valve > 1:
            target_temp = outdoor_temp - (outdoor_temp - setpoint) * min(state.cooling_valve / 100, 1)
        else:
            target_temp = outdoor_temp

        # First-order thermal inertia: supply temperature approaches the target gradually.
        state.supply_temp += (target_temp - state.supply_temp) * (0.10 * dt / 2.0)
        state.supply_temp += random.gauss(0, 0.04)

        outdoor_humidity = 55 + 12 * math.sin(2 * math.pi * elapsed_s / 700.0) + random.gauss(0, 0.2)
        heating_drying = state.heating_valve / 100 * 8
        state.humidity += (outdoor_humidity - heating_drying - state.humidity) * 0.04 + random.gauss(0, 0.08)
    else:
        # During the fault the fans stop and the dampers close.
        state.fan_supply_rpm += (0 - state.fan_supply_rpm) * 0.5
        state.fan_exhaust_rpm += (0 - state.fan_exhaust_rpm) * 0.5
        state.heating_valve += (0 - state.heating_valve) * 0.5
        state.cooling_valve += (0 - state.cooling_valve) * 0.5
        state.supply_temp += (outdoor_temp - state.supply_temp) * 0.015 + random.gauss(0, 0.03)

    # Filter pressure drop rises slowly with simulated dirt accumulation.
    # The accelerated rate is configurable so the effect is visible during a short demo.
    state.filter_dp += FILTER_GROWTH_PA_PER_MIN * dt / 60.0
    state.filter_dp += max(0, state.fan_supply_rpm / 1450.0 - 0.5) * 0.04

    filter_clogged = state.filter_dp >= 230.0
    alarm = fan_fault or state.filter_dp >= 250.0

    # Damper opens more as the fan approaches nominal speed.
    damper = clamp(30 + 45 * state.fan_supply_rpm / 1450.0, 0, 100)

    return {
        "outdoor_temperature": round(outdoor_temp, 2),
        "supply_temperature": round(state.supply_temp, 2),
        "temperature_setpoint": round(setpoint, 2),
        "supply_fan_rpm": round(max(0, state.fan_supply_rpm), 1),
        "exhaust_fan_rpm": round(max(0, state.fan_exhaust_rpm), 1),
        "filter_differential_pressure": round(state.filter_dp, 1),
        "damper_position": round(damper, 1),
        "heating_valve_position": round(state.heating_valve, 1),
        "cooling_valve_position": round(state.cooling_valve, 1),
        "humidity": round(clamp(state.humidity, 0, 100), 1),
        "running": running,
        "alarm": alarm,
        "filter_clogged": filter_clogged,
        "fan_fault": fan_fault,
    }


def main() -> None:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{TB_DEVICE_NAME}-emulator",
    )
    client.username_pw_set(TB_DEVICE_TOKEN)

    connected = False

    def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties):
        nonlocal connected
        connected = reason_code.is_failure is False
        print(f"MQTT connected={connected}, reason={reason_code}")

    def on_disconnect(client: mqtt.Client, userdata, disconnect_flags, reason_code, properties):
        nonlocal connected
        connected = False
        print(f"MQTT disconnected, reason={reason_code}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print(f"Connecting to ThingsBoard MQTT at {TB_HOST}:{TB_MQTT_PORT} as device {TB_DEVICE_NAME} ...")
    client.connect(TB_HOST, TB_MQTT_PORT, keepalive=60)
    client.loop_start()

    start = time.monotonic()
    last = start
    try:
        while True:
            now = time.monotonic()
            dt = max(0.1, min(now - last, 5.0))
            last = now
            elapsed = now - start

            payload = telemetry(elapsed, dt)
            info = client.publish("v1/devices/me/telemetry", payload=json.dumps(payload), qos=1)

            if info.rc == mqtt.MQTT_ERR_SUCCESS and connected:
                print(
                    f"T_out={payload['outdoor_temperature']:>5} °C | "
                    f"T_supply={payload['supply_temperature']:>5} °C | "
                    f"SP={payload['temperature_setpoint']:>4} °C | "
                    f"fan={payload['supply_fan_rpm']:>5} rpm | "
                    f"dP={payload['filter_differential_pressure']:>5} Pa | "
                    f"heat={payload['heating_valve_position']:>5}% | "
                    f"run={payload['running']} alarm={payload['alarm']}"
                )
            else:
                print(f"Publish failed: rc={info.rc}")

            time.sleep(SEND_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("Stopping emulator...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
