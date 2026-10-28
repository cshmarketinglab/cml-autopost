"""캐러셀 원고 + 사진 → 1080x1350 JPG (Playwright 헤드리스 크롬).

레이아웃 순서 (레퍼런스: 매거진형)
  1      cover     전면 사진 + 하단 그라데이션 + 시리즈 라벨 + 큰 제목
  2      polaroid  기울어진 폴라로이드 사진 + 본문 (6번째 장도, 긴 캐러셀일 때)
  나머지  article   상단 사진 + 검정 패널 본문
  n-1    article   마지막 본문은 '오늘의 숙제' 라벨
  본문 배경: 표지 다음 장은 검정 고정, 나머지는 검정/베이지 50:50 무작위
  n      outro     검정 배경 워드마크
"""
import html
import random
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import TEMPLATE_DIR

FIT_JS = """
() => {
  const box = document.querySelector('.text');
  if (!box) return 0;
  let size = parseFloat(getComputedStyle(box.querySelector('p') || box).fontSize), guard = 0;
  const ps = box.querySelectorAll('p');
  while (box.scrollHeight > box.clientHeight + 1 && size > 30 && guard++ < 20) {
    size -= 1;
    ps.forEach(p => { p.style.fontSize = size + 'px'; p.style.marginBottom = Math.round(size * 1.0) + 'px'; });
  }
  return box.scrollHeight > box.clientHeight + 1 ? -size : size;
}
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def _paragraphs(body: str) -> str:
    """'\\n\\n' 문단 구분, **강조** → 굵게+밑줄"""
    out = []
    for para in re.split(r"\n\s*\n", (body or "").strip()):
        t = _esc(para.strip()).replace("\n", " ")
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        out.append(f"<p>{t}</p>")
    return "".join(out)


def _photo(path: str | None, extra: str = "") -> str:
    if not path:
        return f"<div class='photo {extra}'></div>"
    return f"<div class='photo grain {extra}'><img src='{Path(path).resolve().as_uri()}'></div>"


def _logo(kind: str, color: str, cls: str = "logo") -> str:
    """templates/logo/{mark|full}-{white|black}.png"""
    return f"<img class='{cls}' src='logo/{kind}-{color}.png' alt='CML'>"


def _foot(design: dict, light: bool = False) -> str:
    return f"<div class='foot'>{_logo('mark', 'black' if light else 'white')}</div>"


ICONS = {
    "save": "<svg viewBox='0 0 24 24'><path d='M6 3h12v18l-6-4.5L6 21z'/></svg>",
    "follow": "<svg viewBox='0 0 24 24'><circle cx='9' cy='8' r='4'/><path d='M2 21c0-4 3-7 7-7s7 3 7 7M19 8v6M16 11h6'/></svg>",
    "like": "<svg viewBox='0 0 24 24'><path d='M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z'/></svg>",
    "share": "<svg viewBox='0 0 24 24'><path d='M21 3 10 14M21 3l-7 18-4-7-7-4z'/></svg>",
}


def _outro_cta(design: dict) -> str:
    o = design["outro"]
    btns = "".join(
        f"<span class='btn {'fill' if i == 0 else ''}'>{ICONS.get(b['icon'], '')}{_esc(b['label'])}</span>"
        for i, b in enumerate(o["buttons"]))
    note = f"<div class='note'>{_esc(o['note'])}</div>" if o.get("note") else ""
    return f"<div class='cta'><div class='headline'>{_esc(o['headline'])}</div><div class='btns'>{btns}</div>{note}</div>"


def build_slides(doc: dict, design: dict) -> list[tuple[str, str]]:
    """[(css class, inner html)]"""
    slides = []
    c = doc["cover"]
    title = "<br>".join(_esc(x) for x in c["title"].split("\n"))
    slides.append(("cover" + ("" if c.get("photo") else " nophoto"), f"""
      {_photo(c.get('photo'))}<div class='shade'></div>
      <div class='head'>{_logo('mark', 'white')}
        <span class='spaced'>{_esc(design['cover_label'])}</span></div>
      <div class='titles'><div class='kicker'>{_esc(doc['kicker'])}</div><h1>{title}</h1></div>"""))

    sections = doc["sections"]
    # 본문 배경: 표지 다음 장은 항상 검정, 나머지는 검정/베이지 50:50 (같은 원고면 같은 결과)
    rng = random.Random(doc.get("kicker", "") + doc["cover"].get("title", ""))
    for i, s in enumerate(sections):
        light = False if i == 0 else rng.random() < 0.5
        theme = " light" if light else ""
        label = (f"<div class='label spaced'>{_esc(design['insight_label'])}</div>"
                 if i == len(sections) - 1 else "")
        text = f"{label}<h2>{_esc(s['heading'])}</h2><div class='text'>{_paragraphs(s['body'])}</div>"
        if i in (0, 4) and i != len(sections) - 1:  # 폴라로이드: 첫 팁 + 긴 캐러셀이면 5번째 팁
            slides.append(("article polaroid" + theme, f"""
              <div class='stage'><div class='frame'>{_photo(s.get('photo'))}
                {_logo('mark', 'black', 'sign')}</div></div>
              <div class='panel'>{text}</div>{_foot(design, light=light)}"""))
        else:
            slides.append(("article" + theme, f"""{_photo(s.get('photo'))}
              <div class='panel'>{text}</div>{_foot(design, light=light)}"""))

    slides.append(("outro", f"""{_logo('full', 'white', 'logo-full')}
      {_outro_cta(design)}"""))
    return slides


def _page(cls: str, inner: str) -> str:
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<link rel='stylesheet' href='carousel.css'></head>"
            f"<body><div class='slide {cls}'>{inner}</div></body></html>")


def render_carousel(doc: dict, design: dict, out_dir: Path) -> tuple[list[str], list[int]]:
    """반환: (이미지 경로들, 글자가 넘쳐 잘린 슬라이드 번호들)"""
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = build_slides(doc, design)
    paths, overflow = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for i, (cls, inner) in enumerate(slides, start=1):
            tmp = TEMPLATE_DIR / f"_render_{i:02d}.html"  # 폰트·CSS 상대경로 때문에 templates 폴더에서 렌더
            tmp.write_text(_page(cls, inner), encoding="utf-8")
            try:
                page.goto(tmp.resolve().as_uri(), wait_until="load")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(150)
                if page.evaluate(FIT_JS) < 0:
                    overflow.append(i)
                fp = out_dir / f"{i:02d}.jpg"
                page.screenshot(path=str(fp), type="jpeg", quality=90)
                paths.append(str(fp))
            finally:
                tmp.unlink(missing_ok=True)
        browser.close()
    return paths, overflow
