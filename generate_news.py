#!/usr/bin/env python3
"""
AI 뉴스카드 생성기
- 어제 뉴스 수집
- 인스타그램 스타일 가로 스와이프 카드
- Claude API 있으면 AI 요약, 없으면 RSS 원문 사용
"""
import feedparser, re, html, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# ── 설정 ─────────────────────────────────────────────────────────────────────
FEEDS = [
    {"name": "AI타임스",    "url": "https://www.aitimes.com/rss/allArticle.xml",  "color": "#5B4CFF"},
    {"name": "인공지능신문", "url": "https://www.aitimes.kr/rss/allArticle.xml",  "color": "#00C2A8"},
    {"name": "매일경제 IT", "url": "https://www.mk.co.kr/rss/40300001/",          "color": "#E6A817"},
]
MAX_PER_FEED = 6
OUTPUT_DIR   = os.path.dirname(os.path.abspath(__file__))

# ── Claude API 요약 (API 키 있을 때만) ────────────────────────────────────────
def ai_summarize(title, summary):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return title, summary

    try:
        import anthropic, json
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""다음 뉴스 기사를 한국어로 요약해줘.

제목: {title}
내용: {summary}

아래 JSON 형식으로만 답해. 다른 말은 하지 마.
{{
  "headline": "핵심을 담은 임팩트 있는 한 문장 제목 (30자 이내)",
  "summary": "기사 핵심을 5줄 이내로 정리. 줄바꿈으로 구분."
}}"""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # JSON 블록 추출
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return data.get("headline", title), data.get("summary", summary)
        return title, summary
    except Exception as e:
        print(f"[AI 요약 실패] {e}")
        return title, summary

# ── 날짜 파싱 ─────────────────────────────────────────────────────────────────
def parse_pub_date(entry):
    pub = entry.get("published", entry.get("updated", ""))
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub)
    except:
        return None

def is_yesterday(dt):
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end   = yesterday_start.replace(hour=23, minute=59, second=59)
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return yesterday_start <= dt <= yesterday_end
    except:
        return False

# ── 이미지 추출 ───────────────────────────────────────────────────────────────
def get_image(entry):
    # 1. RSS 미디어 썸네일
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url", "")
        if url:
            return url
    # 2. media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            if m.get("type", "").startswith("image") and m.get("url"):
                return m["url"]
    # 3. enclosures
    if hasattr(entry, "enclosures") and entry.enclosures:
        for e in entry.enclosures:
            if "image" in e.get("type", "") and e.get("href"):
                return e["href"]
    # 4. summary 안 img 태그
    raw = entry.get("summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw)
    if m:
        return m.group(1)
    # 5. 기사 URL에서 og:image 추출
    link = entry.get("link", "")
    if link:
        return fetch_og_image(link)
    return ""

def fetch_og_image(url):
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            chunk = r.read(8000).decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', chunk)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', chunk)
        return m.group(1) if m else ""
    except:
        return ""

# ── RSS 수집 ──────────────────────────────────────────────────────────────────
def fetch_articles(use_yesterday=True):
    articles = []
    for feed_info in FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= MAX_PER_FEED:
                    break
                dt = parse_pub_date(entry)

                # 어제 기사 필터 (어제 기사가 없으면 최신 기사 사용)
                if use_yesterday and not is_yesterday(dt):
                    continue

                raw_title   = entry.get("title", "제목 없음")
                raw_summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", "")))
                raw_summary = raw_summary.strip()

                headline, summary = ai_summarize(raw_title, raw_summary)

                # 요약을 줄 단위로 분리 (최대 10줄)
                lines = [l.strip() for l in summary.split("\n") if l.strip()][:10]

                pub_str = ""
                if dt:
                    try:
                        local_dt = dt.astimezone()
                        pub_str = local_dt.strftime("%Y.%m.%d %H:%M")
                    except:
                        pass

                articles.append({
                    "source":    feed_info["name"],
                    "color":     feed_info["color"],
                    "title":     html.escape(headline),
                    "lines":     [html.escape(l) for l in lines],
                    "link":      entry.get("link", "#"),
                    "image":     get_image(entry),
                    "pub":       pub_str,
                    "num":       len(articles) + 1,
                })
                count += 1
        except Exception as e:
            print(f"[경고] {feed_info['name']} 오류: {e}")

    # 어제 기사가 아예 없으면 최신 기사로 fallback
    if not articles and use_yesterday:
        print("어제 기사가 없어 최신 기사를 불러옵니다.")
        return fetch_articles(use_yesterday=False)

    return articles

# ── 카드 HTML ─────────────────────────────────────────────────────────────────
def make_card(a, total):
    img_block = ""
    if a["image"]:
        img_block = f'<div class="card-img"><img src="{a["image"]}" alt="" onerror="this.parentElement.style.display=\'none\'"></div>'

    lines_html = "".join(f"<li>{l}</li>" for l in a["lines"])

    return f"""
<div class="slide" id="slide-{a['num']}">
  <div class="card">
    <div class="card-header">
      <span class="newsletter-tag">NEWSLETTER</span>
      <span class="card-date">{a['pub']}</span>
    </div>
    {img_block}
    <div class="card-body">
      <span class="source-chip" style="color:{a['color']};border-color:{a['color']}">{a['source']}</span>
      <h2 class="card-title">{a['title']}</h2>
      <ul class="card-lines">{lines_html}</ul>
    </div>
    <div class="card-footer">
      <span class="card-counter">{a['num']} / {total}</span>
      <a class="read-more" href="{a['link']}" target="_blank">자세히 보기 →</a>
    </div>
  </div>
</div>"""

# ── HTML 생성 ─────────────────────────────────────────────────────────────────
def generate_html(articles):
    today    = datetime.now().strftime("%Y년 %m월 %d일")
    weekday  = ["월","화","수","목","금","토","일"][datetime.now().weekday()]
    week_num = (datetime.now().day - 1) // 7 + 1
    date_label = f"{datetime.now().month}월 {week_num}주"

    total = len(articles)
    slides_html = "".join(make_card(a, total) for a in articles)

    def dot_class(i):
        return "dot active" if i == 0 else "dot"
    dots_html = "".join(
        f'<button class="{dot_class(i)}" onclick="goTo({i})" aria-label="{i+1}번 카드"></button>'
        for i in range(total)
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 뉴스카드 {datetime.now().strftime('%Y.%m.%d')}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700;900&family=Noto+Sans+KR:wght@400;500;700&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #e8e4df;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    font-family: 'Noto Sans KR', sans-serif;
    padding: 24px 0;
    gap: 16px;
  }}

  /* 상단 타이틀 */
  .top-bar {{
    width: 480px;
    max-width: 92vw;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 0 4px;
  }}
  .top-title {{
    font-family: 'Noto Serif KR', serif;
    font-size: 26px;
    font-weight: 900;
    color: #111;
    letter-spacing: -0.03em;
  }}
  .top-date {{
    font-size: 12px;
    color: #888;
    font-weight: 500;
  }}

  /* 슬라이더 컨테이너 */
  .slider-wrap {{
    position: relative;
    width: 480px;
    max-width: 92vw;
  }}
  .slider {{
    display: flex;
    overflow-x: scroll;
    scroll-snap-type: x mandatory;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    gap: 0;
    border-radius: 12px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.18);
  }}
  .slider::-webkit-scrollbar {{ display: none; }}

  /* 슬라이드 */
  .slide {{
    flex: 0 0 100%;
    scroll-snap-align: start;
  }}

  /* 카드 */
  .card {{
    background: #faf9f7;
    min-height: 680px;
    display: flex;
    flex-direction: column;
    border: 1px solid #ddd;
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 20px;
    border-bottom: 1.5px solid #111;
  }}
  .newsletter-tag {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: #111;
  }}
  .card-date {{
    font-size: 11px;
    color: #888;
    font-weight: 500;
  }}

  /* 이미지 */
  .card-img {{
    width: 100%;
    height: 220px;
    overflow: hidden;
    border-bottom: 1px solid #e0e0e0;
    background: #f0ede9;
  }}
  .card-img img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.4s;
  }}

  /* 본문 */
  .card-body {{
    flex: 1;
    padding: 20px 20px 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}
  .source-chip {{
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 3px 10px;
    border: 1.5px solid;
    border-radius: 20px;
    align-self: flex-start;
  }}
  .card-title {{
    font-family: 'Noto Serif KR', serif;
    font-size: 22px;
    font-weight: 900;
    line-height: 1.45;
    color: #111;
    letter-spacing: -0.02em;
    word-break: keep-all;
    border-bottom: 2px solid #111;
    padding-bottom: 14px;
  }}
  .card-lines {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 7px;
    flex: 1;
  }}
  .card-lines li {{
    font-size: 13px;
    line-height: 1.65;
    color: #333;
    padding-left: 14px;
    position: relative;
    word-break: keep-all;
  }}
  .card-lines li::before {{
    content: '·';
    position: absolute;
    left: 0;
    color: #999;
    font-size: 16px;
    line-height: 1.3;
  }}

  /* 하단 */
  .card-footer {{
    padding: 14px 20px;
    border-top: 1px solid #e0e0e0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #f5f3f0;
  }}
  .card-counter {{
    font-size: 11px;
    color: #aaa;
    font-weight: 500;
  }}
  .read-more {{
    font-size: 12px;
    font-weight: 700;
    color: #111;
    text-decoration: none;
    letter-spacing: 0.04em;
    border-bottom: 1.5px solid #111;
    padding-bottom: 1px;
    transition: opacity 0.2s;
  }}
  .read-more:hover {{ opacity: 0.5; }}

  /* 네비게이션 화살표 */
  .arrow {{
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(255,255,255,0.9);
    border: 1.5px solid #ddd;
    border-radius: 50%;
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 14px;
    color: #333;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
    transition: background 0.2s;
    z-index: 10;
    user-select: none;
  }}
  .arrow:hover {{ background: #fff; }}
  .arrow-left  {{ left: -18px; }}
  .arrow-right {{ right: -18px; }}

  /* 도트 인디케이터 */
  .dots {{
    display: flex;
    gap: 6px;
    justify-content: center;
  }}
  .dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #bbb;
    border: none;
    cursor: pointer;
    padding: 0;
    transition: background 0.2s, transform 0.2s;
  }}
  .dot.active {{
    background: #111;
    transform: scale(1.4);
  }}

  /* 총 뉴스 수 */
  .bottom-info {{
    font-size: 11px;
    color: #aaa;
    text-align: center;
  }}
</style>
</head>
<body>

<div class="top-bar">
  <span class="top-title">오늘의 AI 소식</span>
  <span class="top-date">{date_label} · {today}</span>
</div>

<div class="slider-wrap">
  <button class="arrow arrow-left"  onclick="move(-1)">&#8592;</button>
  <button class="arrow arrow-right" onclick="move(+1)">&#8594;</button>
  <div class="slider" id="slider">
    {slides_html}
  </div>
</div>

<div class="dots" id="dots">
  {dots_html}
</div>

<div class="bottom-info">총 {total}개 기사 · 스와이프하거나 화살표로 이동</div>

<script>
  const slider = document.getElementById('slider');
  const dots   = document.querySelectorAll('.dot');
  let current  = 0;
  const total  = {total};

  function updateDots(idx) {{
    dots.forEach((d, i) => d.classList.toggle('active', i === idx));
    current = idx;
  }}

  function goTo(idx) {{
    idx = Math.max(0, Math.min(total - 1, idx));
    slider.scrollTo({{ left: slider.clientWidth * idx, behavior: 'smooth' }});
    updateDots(idx);
  }}

  function move(dir) {{ goTo(current + dir); }}

  // 스크롤로 현재 인덱스 감지
  slider.addEventListener('scroll', () => {{
    const idx = Math.round(slider.scrollLeft / slider.clientWidth);
    if (idx !== current) updateDots(idx);
  }});

  // 키보드 좌우 화살표
  document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowLeft')  move(-1);
    if (e.key === 'ArrowRight') move(+1);
  }});
</script>
</body>
</html>"""

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    print("어제 AI 뉴스 수집 중...")
    articles = fetch_articles(use_yesterday=True)

    if not articles:
        print("기사를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"{len(articles)}개 기사 수집 완료")

    html_content = generate_html(articles)
    output_path  = os.path.join(OUTPUT_DIR, "news_card.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"뉴스카드 생성 완료: {output_path}")
    subprocess.run(["open", output_path])

if __name__ == "__main__":
    main()
