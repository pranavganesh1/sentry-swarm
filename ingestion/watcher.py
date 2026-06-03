import os
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.buffer import init_db, insert_event
from ingestion.parser import LogEvent, parse_line


LOG_FILE = Path("logs/app.log")


class LogHandler(FileSystemEventHandler):
    def __init__(self, filepath: Path, callback):
        self.filepath = filepath.resolve()
        self.callback = callback
        self._pos = self._get_file_size()

    def _get_file_size(self) -> int:
        try:
            return self.filepath.stat().st_size
        except FileNotFoundError:
            return 0

    def on_created(self, event) -> None:
        if self._is_target(event.src_path):
            self._read_new_lines()

    def on_modified(self, event) -> None:
        if self._is_target(event.src_path):
            self._read_new_lines()

    def _is_target(self, src_path: str) -> bool:
        return Path(src_path).resolve() == self.filepath

    def _read_new_lines(self) -> None:
        try:
            with self.filepath.open("r", encoding="utf-8") as log_file:
                log_file.seek(self._pos)
                new_lines = log_file.readlines()
                self._pos = log_file.tell()
        except FileNotFoundError:
            self._pos = 0
            return

        for line in new_lines:
            event = parse_line(line)
            if event:
                self.callback(event)


def on_new_event(event: LogEvent) -> None:
    insert_event(event)
    tag = f"[{event.incident_type}]" if event.incident_type else ""
    print(f"  {event.level:<5} [{event.service}] {event.message[:60]} {tag}".rstrip())


def start_watcher() -> None:
    init_db()
    LOG_FILE.parent.mkdir(exist_ok=True)

    print(f"[watcher] Watching {LOG_FILE} ...")
    handler = LogHandler(LOG_FILE, on_new_event)
    observer = Observer()
    observer.schedule(handler, path=os.fspath(LOG_FILE.parent), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_watcher()
