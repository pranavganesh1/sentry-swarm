from ingestion.buffer import get_error_rate, get_recent_events


def main() -> None:
    events = get_recent_events(20)
    for event in events:
        tag = f" <- {event['incident_type']}" if event["incident_type"] else ""
        print(f"{event['level']:<5} [{event['service']}] {event['message'][:60]}{tag}")

    print(f"\nError rate (last 30s): {get_error_rate(30)}%")


if __name__ == "__main__":
    main()
