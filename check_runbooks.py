from pathlib import Path


RUNBOOK_DIR = Path("runbooks")
EXPECTED_INCIDENT_TYPES = {
    "http_5xx",
    "db_timeout",
    "oom_kill",
    "failed_deploy",
    "cascading_failure",
}


def extract_incident_type(text: str) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Incident Type" and index + 1 < len(lines):
            return lines[index + 1].strip()
    return None


def main() -> None:
    markdown_files = sorted(RUNBOOK_DIR.glob("*.md"))
    found_types = set()

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        incident_type = extract_incident_type(text)
        found_types.add(incident_type)
        status = "OK" if incident_type in EXPECTED_INCIDENT_TYPES and line_count >= 40 else "CHECK"
        print(f"{status:<5} {path.name:<28} {line_count:>3} lines  incident_type={incident_type}")

    missing = EXPECTED_INCIDENT_TYPES - found_types
    extras = found_types - EXPECTED_INCIDENT_TYPES

    if missing:
        raise SystemExit(f"Missing incident types: {', '.join(sorted(missing))}")
    if extras:
        raise SystemExit(f"Unexpected incident types: {', '.join(sorted(extras))}")
    if len(markdown_files) != len(EXPECTED_INCIDENT_TYPES):
        raise SystemExit(f"Expected {len(EXPECTED_INCIDENT_TYPES)} runbooks, found {len(markdown_files)}")

    print("\nRunbook check passed.")


if __name__ == "__main__":
    main()
