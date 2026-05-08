import csv
import time
import random
import string
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "http://localhost:5002"
OUTPUT_FILE = Path(__file__).parent / "latency.csv"

EVENT_TYPES = [
    "NODE_ADDED",
    "NODE_REMOVED",
    "NODE_MOVED",
    "EDGE_CREATED",
    "EDGE_REMOVED",
    "PARAM_CHANGED",
    "NODE_EXECUTED",
    "EXECUTION_COMPLETED",
]

EVENTS_PER_TYPE = 100


def random_id(prefix="synthetic-node"):
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}-{suffix}"


def start_session():
    payload = {
        "user_id": 99,
        "workflow_name": "synthetic_event_stress_test"
    }

    response = requests.post(
        f"{BASE_URL}/api/log/session/start",
        json=payload,
        timeout=10
    )
    response.raise_for_status()

    data = response.json()
    session_id = data.get("session_id") or data.get("id")

    if session_id is None:
        raise RuntimeError(f"Could not find session_id in response: {data}")

    print(f"Started synthetic session: {session_id}")
    return session_id


def send_event(event_type, session_id):
    event = {
        "event_type": event_type,
        "node_id": random_id(),
        "event_data": {
            "position": {
                "x": random.random() * 500,
                "y": random.random() * 400
            },
            "synthetic": True
        },
        "event_time": datetime.now(timezone.utc).isoformat()
    }

    payload = {
        "session_id": session_id,
        "events": [event]
    }

    start = time.perf_counter()

    response = requests.post(
        f"{BASE_URL}/api/log/events",
        json=payload,
        timeout=10
    )
    response.raise_for_status()

    end = time.perf_counter()
    return (end - start) * 1000


def end_session(session_id):
    payload = {"session_id": session_id}

    try:
        response = requests.post(
            f"{BASE_URL}/api/log/session/end",
            json=payload,
            timeout=10
        )
        if response.status_code < 400:
            print("Ended synthetic session.")
    except Exception as exc:
        print(f"Warning: could not end session cleanly: {exc}")


def main():
    session_id = start_session()

    rows = []

    for event_type in EVENT_TYPES:
        print(f"Testing {event_type}...")

        for i in range(EVENTS_PER_TYPE):
            latency_ms = send_event(event_type, session_id)

            rows.append({
                "session_id": session_id,
                "event_type": event_type,
                "latency_ms": round(latency_ms, 4)
            })

            time.sleep(0.01)

        print(f"Done: {event_type}")

    end_session(session_id)

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["session_id", "event_type", "latency_ms"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved latency data to: {OUTPUT_FILE}")
    print(f"Total events sent: {len(rows)}")


if __name__ == "__main__":
    main()