import random
import time
from datetime import datetime
from pathlib import Path

from faker import Faker

fake = Faker()

LOG_FILE = Path("logs/app.log")
SERVICES = ["auth-service", "payment-service", "user-api", "db-proxy", "nginx"]
NORMAL_INTERVAL = 0.3
SPIKE_EVERY = 60
SPIKE_DURATION = 10


def svc():
    return random.choice(SERVICES)


NORMAL_TEMPLATES = [
    lambda: f"INFO  [{svc()}] GET /api/{fake.uri_page()} 200 {random.randint(12, 120)}ms",
    lambda: f"INFO  [{svc()}] POST /api/{fake.uri_page()} 201 {random.randint(20, 200)}ms",
    lambda: f"DEBUG [{svc()}] DB query completed in {random.randint(5, 80)}ms",
    lambda: f"INFO  [{svc()}] User {fake.uuid4()[:8]} authenticated successfully",
    lambda: f"INFO  [{svc()}] Cache hit for key session:{fake.uuid4()[:8]}",
]

SPIKE_TYPES = {
    "http_5xx": [
        lambda: f"ERROR [{svc()}] GET /api/{fake.uri_page()} 500 Internal Server Error",
        lambda: f"ERROR [{svc()}] POST /api/{fake.uri_page()} 503 Service Unavailable",
        lambda: f"ERROR [{svc()}] Unhandled exception: NullPointerException at line {random.randint(100, 800)}",
    ],
    "db_timeout": [
        lambda: "ERROR [db-proxy] Connection timeout after 30000ms",
        lambda: "ERROR [db-proxy] Query exceeded max execution time: SELECT * FROM orders WHERE...",
        lambda: f"WARN  [db-proxy] Connection pool exhausted ({random.randint(50, 100)}/50 connections used)",
        lambda: "ERROR [user-api] Failed to fetch user data: upstream db-proxy timeout",
    ],
    "oom_kill": [
        lambda: "FATAL [payment-service] OutOfMemoryError: Java heap space",
        lambda: f"ERROR [payment-service] Process killed by OOM killer (RSS: {random.randint(900, 1200)}MB)",
        lambda: f"WARN  [payment-service] Memory usage at {random.randint(85, 99)}% - approaching limit",
        lambda: "ERROR [nginx] upstream payment-service unavailable (connection refused)",
    ],
    "failed_deploy": [
        lambda: "ERROR [auth-service] Deploy pipeline failed: exit code 1",
        lambda: f"ERROR [auth-service] Pod in CrashLoopBackOff ({random.randint(3, 8)} restarts)",
        lambda: "ERROR [auth-service] Health check returned 503 after deploy",
        lambda: "WARN  [nginx] upstream auth-service unavailable (0 ready replicas)",
    ],
    "cascading_failure": [
        lambda: f"ERROR [{svc()}] Connection refused: upstream auth-service unavailable",
        lambda: f"FATAL [{svc()}] Circuit breaker OPEN for auth-service",
        lambda: f"ERROR [{svc()}] Failed to authenticate request: upstream timeout",
        lambda: f"ERROR [{svc()}] 503 Service Unavailable - dependency auth-service down",
    ],
}


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log(line):
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp()}] {line}\n")


def normal_traffic():
    template = random.choice(NORMAL_TEMPLATES)
    write_log(template())


def spike_traffic(spike_type):
    templates = SPIKE_TYPES[spike_type]
    template = random.choice(templates)
    write_log(template())


def run():
    LOG_FILE.parent.mkdir(exist_ok=True)

    print(f"[generator] Starting log generator -> {LOG_FILE}")
    print(f"[generator] Spike every {SPIKE_EVERY}s, lasting {SPIKE_DURATION}s")

    spike_at = time.time() + SPIKE_EVERY
    in_spike = False
    spike_end = 0
    current_spike = None

    while True:
        now = time.time()

        if not in_spike and now >= spike_at:
            current_spike = random.choice(list(SPIKE_TYPES.keys()))
            in_spike = True
            spike_end = now + SPIKE_DURATION
            spike_at = now + SPIKE_EVERY
            print(f"[generator] Spike started: {current_spike}")

        if in_spike and now >= spike_end:
            in_spike = False
            print(f"[generator] Spike ended: {current_spike}")

        if in_spike:
            spike_traffic(current_spike)
            time.sleep(0.1)
        else:
            normal_traffic()
            time.sleep(NORMAL_INTERVAL)


if __name__ == "__main__":
    run()
