"""예약 시간이 지났고, 승인됐고, 아직 안 올라간 항목을 발행.
GitHub Actions 지연(수~수십 분)에 상관없이 '시간 지난 것 전부' 처리하므로 누락이 없다.
단, 예약(또는 늦은 승인) 시각에서 MAX_LATE_HOURS 넘게 지난 건 expired 처리(장애 후 몰아 올라가는 사고 방지).
늦게 승인한 글은 승인 직후 바로 발행된다."""
import os
from datetime import datetime, timedelta

from common import QUEUE_DIR, now_kst, read_json, write_json
from meta_api import ig_publish_carousel, threads_publish_text

MAX_LATE_HOURS = 3


def image_url(rel_path: str) -> str:
    base = os.environ.get("IMAGE_BASE_URL")
    if not base:
        repo = os.environ["GITHUB_REPOSITORY"]
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    return f"{base.rstrip('/')}/{rel_path}"


def _due(item: dict, now: datetime) -> str | None:
    """'go' / 'expired' / None — 미승인 건은 건드리지 않고 pending으로 둔다(늦게라도 승인하면 그때 발행)."""
    if not item or item.get("status") != "pending" or not item.get("approved"):
        return None
    at = datetime.fromisoformat(item["publish_at"])
    if now < at:
        return None
    # 늦게 승인한 경우 승인 시각 기준으로 유효기간 계산
    ref = max(at, datetime.fromisoformat(item["approved_at"])) if item.get("approved_at") else at
    if now - ref > timedelta(hours=MAX_LATE_HOURS):
        return "expired"
    return "go"


def run() -> int:
    now = now_kst()
    changed, failures = 0, 0
    # 오늘·어제 큐만 확인
    for d in {now.date(), (now - timedelta(days=1)).date()}:
        qp = QUEUE_DIR / f"{d.isoformat()}.json"
        q = read_json(qp)
        if not q:
            continue
        day_changed = 0
        items = [("threads", t) for t in q["threads"]] + ([("carousel", q["carousel"])] if q.get("carousel") else [])
        for kind, it in items:
            state = _due(it, now)
            if state == "expired":
                it["status"] = "expired"
                day_changed += 1
                continue
            if state != "go":
                continue
            try:
                if kind == "threads":
                    it["post_id"] = threads_publish_text(it["text"])
                else:
                    it["post_id"] = ig_publish_carousel([image_url(p) for p in it["images"]], it["caption"])
                it["status"] = "published"
                it["published_at"] = now.isoformat()
                print(f"✅ {d} {kind} {it.get('slot', '')} 발행 완료 ({it['post_id']})")
            except Exception as e:  # noqa: BLE001
                it["status"] = "failed"
                it["error"] = str(e)[:500]
                failures += 1
                print(f"❌ {d} {kind} {it.get('slot', '')} 실패: {e}")
            day_changed += 1
        if day_changed:
            write_json(qp, q)
            changed += day_changed
    print(f"처리 {changed}건, 실패 {failures}건")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
