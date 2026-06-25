import time
import random
import threading
from datetime import datetime

LOG_FILE = "logs/app.log"
_write_lock = threading.Lock()   # prevent interleaved partial writes from multiple threads

SPIKE_TYPES = {
    "http_5xx": [
        "ERROR [user-api] GET /api/orders 500 Internal Server Error",
        "ERROR [user-api] POST /api/checkout 503 Service Unavailable",
        "ERROR [user-api] Unhandled exception: NullPointerException at line 412",
    ],
    "db_timeout": [
        "ERROR [db-proxy] Connection timeout after 30000ms",
        "WARN  [db-proxy] Connection pool exhausted (50/50 connections used)",
        "ERROR [user-api] Failed to fetch user data: upstream db-proxy timeout",
    ],
    "oom_kill": [
        "FATAL [payment-service] OutOfMemoryError: Java heap space",
        "ERROR [payment-service] Process killed by OOM killer (RSS: 1100MB)",
        "ERROR [nginx] upstream payment-service unavailable (connection refused)",
    ],
    "failed_deploy": [
        "ERROR [auth-service] Deploy pipeline failed: exit code 1",
        "ERROR [auth-service] Pod in CrashLoopBackOff (5 restarts)",
        "ERROR [auth-service] Health check returned 503 after deploy",
        "WARN  [nginx] upstream auth-service unavailable (0 ready replicas)",
    ],
    "cascading_failure": [
        "ERROR [user-api] Connection refused: upstream auth-service unavailable",
        "FATAL [payment-service] Circuit breaker OPEN for auth-service",
        "ERROR [db-proxy] Failed to authenticate request: upstream timeout",
        "ERROR [nginx] 503 Service Unavailable - dependency auth-service down",
    ],
}

def write_log(line: str):
    with _write_lock:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {line}\n")

def fire_spike(incident_type: str, duration: int = 10):
    print(f"[stress] Firing {incident_type} for {duration}s")
    end = time.time() + duration
    templates = SPIKE_TYPES[incident_type]
    while time.time() < end:
        write_log(random.choice(templates))
        time.sleep(0.15)
    print(f"[stress] {incident_type} spike ended")

def run_stress_test():
    print("[stress] Launching 5 concurrent incident types...")
    threads = [
        threading.Thread(target=fire_spike, args=("http_5xx", 12)),
        threading.Thread(target=fire_spike, args=("db_timeout", 10)),
        threading.Thread(target=fire_spike, args=("oom_kill", 8)),
        threading.Thread(target=fire_spike, args=("failed_deploy", 10)),
        threading.Thread(target=fire_spike, args=("cascading_failure", 12)),
    ]
    for t in threads:
        t.start()
        time.sleep(1)   # slight stagger so they don't start at the exact same millisecond

    for t in threads:
        t.join()

    print("[stress] All spikes complete. Watch the orchestrator process them.")

if __name__ == "__main__":
    run_stress_test()

