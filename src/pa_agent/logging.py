import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Recorder:
    def __init__(self, root: Path):
        self.directory = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sequence = 0

    def event(self, event: str, **fields: object) -> dict:
        self.sequence += 1
        data = {"sequence": self.sequence, "timestamp": utc_now(), "event": event, **fields}
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=True) + "\n")
        return data
