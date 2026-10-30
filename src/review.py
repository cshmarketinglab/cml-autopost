"""검수 흐름.
  python review.py body 2026-10-28          → GitHub 이슈 본문(초안 목록) 출력
  python review.py apply 2026-10-28 < 댓글   → 댓글 명령을 큐에 반영

댓글 명령 (이슈에 댓글로):
  /approve            전부 승인
  /approve 1 3        1, 3번만 승인
  /skip 2             2번 발행 안 함
  /edit 2             (다음 줄부터 새 본문) 2번 본문 교체 + 승인
  /caption            (다음 줄부터 새 캡션) 캐러셀 캡션 교체
"""
import os
import re
import sys
from datetime import date

from common import now_kst, queue_path, read_json, write_json

TYPE_KO = {"empathy": "공감", "news": "뉴스 공감", "recruit": "모집"}


def _items(q: dict) -> list[dict]:
    items = list(q["threads"])
    if q.get("carousel"):
        items.append(q["carousel"])
    return items


def body(d: date) -> str:
    q = read_json(queue_path(d))
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    lines = [f"## {d.isoformat()} 발행 초안", ""]
    for i, t in enumerate(q["threads"], 1):
        lines += [f"### {i}. 쓰레드 · {TYPE_KO.get(t['type'], t['type'])} · {t['publish_at'][11:16]} · {len(t['text'])}자",
                  "```", t["text"], "```", ""]
    c = q.get("carousel")
    if q.get("carousel_error"):
        lines += ["> ⚠️ 오늘 캐러셀 생성 실패 — 쓰레드만 올라옵니다. 캐러셀이 필요하면 Actions에서 '다시 생성' 체크 후 재실행",
                  f"> 오류: {q['carousel_error'][:150]}", ""]
    if c:
        n = len(q["threads"]) + 1
        lines += [f"### {n}. 인스타 캐러셀 · {c['publish_at'][11:16]} · {c.get('kicker', '')} · {c['topic']}", ""]
        if c.get("news_based"):
            lines.append(f"> 📰 뉴스 기반 회차: {c['news_based']} — 숫자·조건이 들어갔는지 꼭 확인")
        if c.get("missing_photos"):
            lines.append(f"> ⚠️ 사진 {c['missing_photos']}장 못 찾음 → 해당 장은 사진 없이 렌더됨")
        if c.get("overflow_slides"):
            lines.append(f"> ⚠️ {c['overflow_slides']}번 장 글자 넘침 — 확인 필요")
        for p in c["images"]:
            lines.append(f"<img src='https://raw.githubusercontent.com/{repo}/{branch}/{p}' width='180'>")
        lines += ["", "**캡션**", "```", c["caption"], "```", ""]
    lines += [
        "---",
        "**댓글로 명령** (본인 계정 댓글만 반영)",
        "- `/approve` 전부 승인 · `/approve 1 3` 일부 승인 · `/skip 2` 발행 제외",
        "- `/edit 2` 다음 줄부터 새 본문 → 교체+승인 · `/caption` 다음 줄부터 새 캡션",
        "- 예약 시각 전 승인 → 그 시각에 발행 / 지난 뒤 승인 → 즉시 발행 / 승인 안 하면 안 올라감",
    ]
    return "\n".join(lines)


def apply(d: date, comment: str) -> str:
    qp = queue_path(d)
    q = read_json(qp)
    items = _items(q)
    first, _, rest = comment.strip().partition("\n")
    m = re.match(r"^/(approve|skip|edit|caption)\b\s*(.*)$", first.strip())
    if not m:
        return "명령 아님 — 무시"
    cmd, args = m.group(1), m.group(2)
    nums = [int(x) for x in re.findall(r"\d+", args)]

    def pick(ns):
        bad = [n for n in ns if not 1 <= n <= len(items)]
        if bad:
            raise SystemExit(f"없는 번호: {bad}")
        return [items[n - 1] for n in ns]

    targets = pick(nums) if nums else items
    if cmd == "approve":
        for it in targets:
            if it["status"] == "pending" and not it.get("approved"):
                it["approved"], it["approved_at"] = True, now_kst().isoformat()
        msg = f"승인: {nums or '전체'}"
    elif cmd == "skip":
        for it in targets:
            if it["status"] == "pending":
                it["status"] = "skipped"
        msg = f"제외: {nums or '전체'}"
    elif cmd == "edit":
        if len(nums) != 1 or not rest.strip():
            raise SystemExit("/edit 번호 다음 줄에 새 본문을 써야 함")
        it = targets[0]
        if "text" not in it:
            raise SystemExit("캐러셀 캡션은 /caption 사용")
        if len(rest.strip()) > 500:
            raise SystemExit(f"500자 초과 ({len(rest.strip())}자)")
        if it["status"] != "pending":
            raise SystemExit(f"{nums[0]}번은 이미 {it['status']} 상태")
        it["text"], it["approved"], it["approved_at"] = rest.strip(), True, now_kst().isoformat()
        msg = f"{nums[0]}번 본문 교체+승인"
    else:  # caption
        c = q.get("carousel")
        if not c or not rest.strip():
            raise SystemExit("캐러셀이 없거나 새 캡션이 비어 있음")
        c["caption"] = rest.strip()
        msg = "캡션 교체"
    write_json(qp, q)
    return msg


if __name__ == "__main__":
    action, d = sys.argv[1], date.fromisoformat(sys.argv[2])
    if action == "body":
        print(body(d))
    else:
        print(apply(d, sys.stdin.read()))
