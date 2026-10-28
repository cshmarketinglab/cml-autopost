"""공통 유틸: 경로, 설정, 시간(KST), JSON 입출력."""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = ROOT / "queue"
OUT_DIR = ROOT / "out"
PROMPT_DIR = ROOT / "prompts"
TEMPLATE_DIR = ROOT / "templates"
HISTORY_FILE = ROOT / "history.json"

KST = timezone(timedelta(hours=9))


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_kst() -> datetime:
    override = os.environ.get("NOW_KST")  # 테스트용: "2026-10-28T20:41"
    if override:
        return datetime.fromisoformat(override).replace(tzinfo=KST)
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def at_kst(d: date, hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KST).isoformat()


def queue_path(d: date) -> Path:
    return QUEUE_DIR / f"{d.isoformat()}.json"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def is_every_n(d: date, anchor: date, n: int) -> bool:
    return n <= 1 or (d - anchor).days % n == 0
