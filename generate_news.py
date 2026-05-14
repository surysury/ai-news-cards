#!/usr/bin/env python3
"""AI 뉴스카드 생성기 — AI 뉴스 + 주식 동향 2탭"""
import feedparser, re, html, os, subprocess, sys, json, calendar
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
IS_CI      = os.environ.get("CI") == "true"

# ── RSS 피드 ──────────────────────────────────────────────────────────────────
FEEDS = [
    {"name": "AI타임스",    "url": "https://www.aitimes.com/rss/allArticle.xml",  "color": "#5B4CFF"},
    {"name": "인공지능신문", "url": "https://www.aitimes.kr/rss/allArticle.xml",  "color": "#00C2A8"},
    {"name": "매일경제 IT", "url": "https://www.mk.co.kr/rss/40300001/",          "color": "#E6A817"},
]
MAX_PER_FEED = 15

# AI 관련 기사 필터 키워드 (이 중 하나라도 포함되면 포함)
AI_KW = [
    "AI", "인공지능", "머신러닝", "딥러닝", "LLM", "GPT", "챗GPT",
    "생성형", "언어모델", "파운데이션 모델", "거대언어모델",
    "오픈AI", "OpenAI", "구글", "딥마인드", "앤트로픽", "Anthropic",
    "메타 AI", "마이크로소프트", "코파일럿", "Copilot", "Gemini", "제미나이",
    "클로드", "Claude", "그록", "Grok", "라마", "Llama",
    "엔비디아", "NVIDIA", "반도체", "GPU", "NPU", "HBM", "데이터센터",
    "SK하이닉스", "삼성전자", "TSMC", "퀄컴",
    "자율주행", "로보틱스", "AI 에이전트", "AI 칩", "AI 모델",
    "미드저니", "Midjourney", "런웨이", "Runway", "소라", "Sora",
    "이미지 생성", "영상 생성", "AI 서비스", "AI 솔루션", "AI 플랫폼",
    "네이버 AI", "카카오 AI", "AI 스타트업", "AI 투자", "AI 규제",
    "챗봇", "음성인식", "컴퓨터비전", "강화학습", "파인튜닝",
]

# ── 주식 목록 ─────────────────────────────────────────────────────────────────
STOCKS = [
    {"ticker": "NVDA",      "name": "엔비디아",      "category": "반도체"},
    {"ticker": "GOOGL",     "name": "구글",           "category": "AI 빅테크"},
    {"ticker": "MSFT",      "name": "마이크로소프트", "category": "AI 빅테크"},
    {"ticker": "META",      "name": "메타",           "category": "AI 빅테크"},
    {"ticker": "AMZN",      "name": "아마존",         "category": "AI 빅테크"},
    {"ticker": "AMD",       "name": "AMD",            "category": "반도체"},
    {"ticker": "TSM",       "name": "TSMC",           "category": "반도체"},
    {"ticker": "AVGO",      "name": "브로드컴",       "category": "반도체"},
    {"ticker": "005930.KS", "name": "삼성전자",       "category": "반도체"},
    {"ticker": "000660.KS", "name": "SK하이닉스",    "category": "반도체"},
    {"ticker": "NEE",       "name": "넥스트에라",     "category": "전력"},
    {"ticker": "VST",       "name": "비스트라",       "category": "전력"},
    {"ticker": "CEG",       "name": "컨스텔레이션",   "category": "전력"},
    {"ticker": "PLTR",      "name": "팔란티어",       "category": "AI 서비스"},
    {"ticker": "SOUN",      "name": "사운드하운드",   "category": "AI 서비스"},
]

# ── 유틸 ──────────────────────────────────────────────────────────────────────
def strip_tags(t): return re.sub(r"<[^>]+>", "", t or "")

def parse_pub_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    pub = entry.get("published", entry.get("updated", ""))
    if not pub: return None
    try: return parsedate_to_datetime(pub)
    except: pass
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try: return datetime.strptime(pub[:19], fmt).replace(tzinfo=timezone.utc)
            except: pass
    except: pass
    return None

def get_image(entry):
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        u = entry.media_thumbnail[0].get("url", "")
        if u: return u
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            if m.get("type","").startswith("image") and m.get("url"): return m["url"]
    raw = entry.get("summary","") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw)
    if m: return m.group(1)
    return fetch_og_image(entry.get("link",""))

def fetch_og_image(url):
    if not url: return ""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            chunk = r.read(8000).decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', chunk)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', chunk)
        return m.group(1) if m else ""
    except: return ""

# ── Claude AI 요약 ─────────────────────────────────────────────────────────────
def ai_summarize(title, summary):
    api_key = os.environ.get("ANTHROPIC_API_KEY","")
    if not api_key: return title, summary
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role":"user","content":f"""다음 뉴스를 한국어로 요약해줘. JSON만 출력해.

제목: {title}
내용: {summary}

{{"headline":"핵심 한 문장 제목 (30자 이내)","summary":"핵심 내용 5줄 이내. 줄바꿈 구분."}}"""}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return data.get("headline", title), data.get("summary", summary)
    except Exception as e:
        print(f"  [AI요약실패] {e}")
    return title, summary

# ── 뉴스 수집 ─────────────────────────────────────────────────────────────────
def fetch_articles():
    articles, seen = [], set()
    for feed_info in FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= MAX_PER_FEED: break
                link = entry.get("link","#")
                if link in seen: continue

                raw_title   = entry.get("title","제목 없음")
                raw_summary = strip_tags(entry.get("summary", entry.get("description","")))

                # AI 관련 기사만 포함
                if not contains_any(raw_title + " " + raw_summary[:200], AI_KW):
                    continue

                seen.add(link)
                headline, summary = ai_summarize(raw_title, raw_summary)
                lines = [l.strip() for l in summary.split("\n") if l.strip()][:8]

                dt = parse_pub_date(entry)
                pub_str = ""
                if dt:
                    try: pub_str = dt.astimezone().strftime("%m.%d %H:%M")
                    except: pass

                articles.append({
                    "source": feed_info["name"],
                    "color":  feed_info["color"],
                    "title":  html.escape(headline),
                    "lines":  [html.escape(l) for l in lines],
                    "link":   link,
                    "image":  get_image(entry),
                    "pub":    pub_str,
                    "num":    len(articles) + 1,
                })
                count += 1
        except Exception as e:
            print(f"  [피드오류] {feed_info['name']}: {e}")
    return articles

# ── 주식 + 스파크라인 ──────────────────────────────────────────────────────────
def make_sparkline(prices, up, width=80, height=28):
    if len(prices) < 2: return ""
    mn, mx = min(prices), max(prices)
    if mx == mn: return ""
    color = "#1DA462" if up else "#E63946"
    pts = " ".join(
        f"{round(i*(width/(len(prices)-1)),1)},{round(height-(p-mn)/(mx-mn)*height,1)}"
        for i, p in enumerate(prices)
    )
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'</svg>')

def fetch_stocks():
    try: import yfinance as yf
    except: return []
    results = []
    for s in STOCKS:
        try:
            hist = yf.Ticker(s["ticker"]).history(period="5d")
            if hist.empty: continue
            prices = list(hist["Close"])
            price, prev = prices[-1], (prices[-2] if len(prices)>=2 else prices[-1])
            change = ((price-prev)/prev*100) if prev else 0
            is_kr  = s["ticker"].endswith(".KS")
            price_str = f"₩{price:,.0f}" if is_kr else f"${price:,.2f}"
            results.append({
                "name":      s["name"],
                "ticker":    s["ticker"].replace(".KS",""),
                "category":  s["category"],
                "price":     price_str,
                "change":    change,
                "up":        change >= 0,
                "sparkline": make_sparkline(prices, change>=0),
            })
        except Exception as e:
            print(f"  [주식오류] {s['ticker']}: {e}")
    return results

# ── HTML 조각 ──────────────────────────────────────────────────────────────────
def make_news_card(a, total):
    img_block = (f'<div class="card-img"><img src="{a["image"]}" alt="" '
                 f'onerror="this.parentElement.style.display=\'none\'"></div>') if a["image"] else ""
    lines_html = "".join(f"<li>{l}</li>" for l in a["lines"])
    return f"""
<div class="slide">
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

def make_stock_html(stocks):
    if not stocks: return '<div class="no-data">주식 데이터를 불러올 수 없습니다.</div>'
    cats = {}
    for s in stocks: cats.setdefault(s["category"],[]).append(s)
    parts = []
    for cat, items in cats.items():
        cards = ""
        for s in items:
            sign  = "+" if s["up"] else ""
            color = "#1DA462" if s["up"] else "#E63946"
            arrow = "▲" if s["up"] else "▼"
            cards += f"""
<div class="stock-card">
  <div class="stock-top">
    <div><div class="stock-name">{s['name']}</div><div class="stock-ticker">{s['ticker']}</div></div>
    <div class="stock-spark">{s['sparkline']}</div>
  </div>
  <div class="stock-price">{s['price']}</div>
  <div class="stock-change" style="color:{color}">{arrow} {sign}{s['change']:.2f}%</div>
</div>"""
        parts.append(f'<div class="stock-group"><div class="stock-group-title">{cat}</div>'
                     f'<div class="stock-row">{cards}</div></div>')
    return "\n".join(parts)

# ── 전체 HTML ──────────────────────────────────────────────────────────────────
def generate_html(articles, stocks):
    today    = datetime.now().strftime("%Y년 %m월 %d일")
    weekday  = ["월","화","수","목","금","토","일"][datetime.now().weekday()]
    week_num = (datetime.now().day-1)//7+1
    date_lbl = f"{datetime.now().month}월 {week_num}주"
    now      = datetime.now().strftime("%H:%M")
    total    = len(articles)

    slides = "".join(make_news_card(a, total) for a in articles)
    dots   = "".join(
        f'<button class="{"dot active" if i==0 else "dot"}" onclick="goTo({i})"></button>'
        for i in range(total)
    )
    stock_html = make_stock_html(stocks)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI 뉴스카드 {datetime.now().strftime('%Y.%m.%d')}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@700;900&family=Noto+Sans+KR:wght@400;500;700&display=swap');
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Noto Sans KR',sans-serif;background:#f0ede8;min-height:100vh;padding-bottom:60px;}}

  /* 헤더 */
  .top-header{{background:#111;color:#fff;padding:20px 24px 16px;}}
  .top-header .date{{font-size:11px;color:#666;margin-bottom:6px;letter-spacing:.08em;}}
  .top-header h1{{font-family:'Noto Serif KR',serif;font-size:24px;font-weight:900;letter-spacing:-.02em;}}
  .top-header h1 em{{font-style:normal;background:linear-gradient(90deg,#a78bfa,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
  .top-header .update-time{{font-size:11px;color:#555;margin-top:6px;}}

  /* 탭 */
  .tabs-sticky{{position:sticky;top:0;z-index:100;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.12);}}
  .tabs{{display:flex;border-bottom:2.5px solid #111;}}
  .tab{{flex:1;padding:14px 8px;font-size:13px;font-weight:700;color:#aaa;background:none;border:none;
        border-bottom:3px solid transparent;margin-bottom:-2.5px;cursor:pointer;transition:.2s;text-align:center;}}
  .tab.active{{color:#111;border-bottom-color:#111;}}
  .tab .cnt{{display:inline-block;font-size:10px;background:#eee;color:#888;border-radius:10px;padding:1px 7px;margin-left:4px;}}
  .tab.active .cnt{{background:#111;color:#fff;}}

  /* 섹션 */
  .section{{display:none;padding:24px 0 12px;}}
  .section.active{{display:block;}}
  .section-title{{font-family:'Noto Serif KR',serif;font-size:18px;font-weight:900;color:#111;
                  margin:0 24px 16px;padding-bottom:10px;border-bottom:2px solid #111;}}

  /* 캐러셀 */
  .carousel-wrap{{position:relative;width:480px;max-width:92vw;margin:0 auto;}}
  .slider{{display:flex;overflow-x:scroll;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;
           scrollbar-width:none;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.15);}}
  .slider::-webkit-scrollbar{{display:none;}}
  .slide{{flex:0 0 100%;scroll-snap-align:start;}}
  .dots{{display:flex;gap:5px;justify-content:center;margin:12px 0 4px;flex-wrap:wrap;padding:0 16px;}}
  .dot{{width:6px;height:6px;border-radius:50%;background:#ccc;border:none;cursor:pointer;padding:0;transition:.2s;}}
  .dot.active{{background:#111;transform:scale(1.4);}}
  .carousel-info{{text-align:center;font-size:11px;color:#aaa;margin-bottom:8px;}}
  .arrow{{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.92);
          border:1.5px solid #ddd;border-radius:50%;width:36px;height:36px;display:flex;
          align-items:center;justify-content:center;cursor:pointer;font-size:14px;color:#333;
          box-shadow:0 2px 8px rgba(0,0,0,.12);z-index:10;}}
  .arrow-left{{left:-18px;}} .arrow-right{{right:-18px;}}

  /* 뉴스 카드 */
  .card{{background:#faf9f7;min-height:620px;display:flex;flex-direction:column;border:1px solid #ddd;}}
  .card-header{{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;border-bottom:1.5px solid #111;}}
  .newsletter-tag{{font-size:10px;font-weight:700;letter-spacing:.15em;color:#111;}}
  .card-date{{font-size:11px;color:#999;}}
  .card-img{{width:100%;height:200px;overflow:hidden;border-bottom:1px solid #eee;background:#f0ede9;}}
  .card-img img{{width:100%;height:100%;object-fit:cover;display:block;}}
  .card-body{{flex:1;padding:18px 20px 10px;display:flex;flex-direction:column;gap:10px;}}
  .source-chip{{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;
                padding:3px 10px;border:1.5px solid;border-radius:20px;align-self:flex-start;}}
  .card-title{{font-family:'Noto Serif KR',serif;font-size:20px;font-weight:900;line-height:1.45;
               color:#111;letter-spacing:-.02em;word-break:keep-all;border-bottom:2px solid #111;padding-bottom:12px;}}
  .card-lines{{list-style:none;display:flex;flex-direction:column;gap:6px;flex:1;}}
  .card-lines li{{font-size:13px;line-height:1.65;color:#333;padding-left:14px;position:relative;word-break:keep-all;}}
  .card-lines li::before{{content:'·';position:absolute;left:0;color:#aaa;font-size:16px;line-height:1.3;}}
  .card-footer{{padding:12px 20px;border-top:1px solid #e8e8e8;display:flex;justify-content:space-between;
                align-items:center;background:#f5f3f0;}}
  .card-counter{{font-size:11px;color:#bbb;}}
  .read-more{{font-size:12px;font-weight:700;color:#111;text-decoration:none;border-bottom:1.5px solid #111;padding-bottom:1px;}}

  /* 주식 */
  .stock-section-inner{{padding:0 20px;}}
  .stock-group{{margin-bottom:24px;}}
  .stock-group-title{{font-size:11px;font-weight:700;letter-spacing:.1em;color:#888;margin-bottom:10px;text-transform:uppercase;}}
  .stock-row{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;}}
  .stock-card{{background:#fff;border-radius:12px;padding:14px;border:1px solid #e8e8e8;box-shadow:0 2px 8px rgba(0,0,0,.06);}}
  .stock-top{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;}}
  .stock-name{{font-size:14px;font-weight:800;color:#111;}}
  .stock-ticker{{font-size:10px;color:#bbb;margin-top:2px;}}
  .stock-price{{font-size:16px;font-weight:700;color:#111;margin-bottom:4px;}}
  .stock-change{{font-size:13px;font-weight:700;}}
  .no-data{{text-align:center;color:#aaa;font-size:13px;padding:40px;}}
  .market-note{{font-size:11px;color:#bbb;text-align:center;margin-top:4px;padding-bottom:8px;}}
</style>
</head>
<body>

<div class="top-header">
  <div class="date">{date_lbl} · {today} ({weekday})</div>
  <h1>오늘의 <em>AI 뉴스카드</em></h1>
  <div class="update-time">업데이트 {now}</div>
</div>

<div class="tabs-sticky">
  <div class="tabs">
    <button class="tab active" onclick="showSection('news',this)">🤖 AI 뉴스<span class="cnt">{total}</span></button>
    <button class="tab" onclick="showSection('stock',this)">📈 주식 동향<span class="cnt">{len(stocks)}</span></button>
  </div>
</div>

<div class="section active" id="section-news">
  <div class="section-title">🤖 오늘의 AI 뉴스</div>
  <div class="carousel-wrap">
    <button class="arrow arrow-left"  onclick="move(-1)">&#8592;</button>
    <button class="arrow arrow-right" onclick="move(+1)">&#8594;</button>
    <div class="slider" id="slider">{slides}</div>
  </div>
  <div class="dots" id="dots">{dots}</div>
  <div class="carousel-info">총 {total}개 · 스와이프 또는 화살표로 이동</div>
</div>

<div class="section" id="section-stock">
  <div class="section-title">📈 AI 주식 동향 <span style="font-size:12px;font-weight:400;color:#aaa;">(5일 추이)</span></div>
  <div class="stock-section-inner">
    {stock_html}
    <div class="market-note">※ 장 마감 후에는 전일 종가 기준 표시</div>
  </div>
</div>

<script>
let cur = 0;
const slider = document.getElementById('slider');
const dotsEl = document.getElementById('dots');
const total  = {total};

function showSection(id, btn) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('section-'+id).classList.add('active');
  btn.classList.add('active');
}}
function goTo(idx) {{
  idx = Math.max(0, Math.min(total-1, idx));
  slider.scrollTo({{left: slider.clientWidth * idx, behavior:'smooth'}});
  dotsEl.querySelectorAll('.dot').forEach((d,i) => d.classList.toggle('active', i===idx));
  cur = idx;
}}
function move(dir) {{ goTo(cur + dir); }}
slider.addEventListener('scroll', () => {{
  const idx = Math.round(slider.scrollLeft / slider.clientWidth);
  if (idx !== cur) {{ dotsEl.querySelectorAll('.dot').forEach((d,i) => d.classList.toggle('active',i===idx)); cur=idx; }}
}});
document.addEventListener('keydown', e => {{
  if (document.getElementById('section-news').classList.contains('active')) {{
    if (e.key==='ArrowLeft') move(-1);
    if (e.key==='ArrowRight') move(+1);
  }}
}});
</script>
</body>
</html>"""

# ── GitHub 업로드 ─────────────────────────────────────────────────────────────
def push_to_github():
    try:
        subprocess.run(["git","add","news_card.html","generate_news.py"], cwd=OUTPUT_DIR, check=True)
        r = subprocess.run(["git","diff","--staged","--quiet"], cwd=OUTPUT_DIR)
        if r.returncode == 0:
            print("변경 없음, 업로드 스킵")
            return
        subprocess.run(["git","commit","-m",f"뉴스카드 업데이트 {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                       cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","fetch","origin"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","rebase","origin/main"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","push"], cwd=OUTPUT_DIR, check=True)
        print("GitHub 업로드 완료!")
        print("👉 https://surysury.github.io/ai-news-cards/news_card.html")
    except subprocess.CalledProcessError as e:
        print(f"[GitHub 업로드 실패] {e}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    print("📰 뉴스 수집 중...")
    articles = fetch_articles()
    print(f"  기사: {len(articles)}개")

    print("📈 주식 데이터 수집 중...")
    stocks = fetch_stocks()
    print(f"  주식: {len(stocks)}개 종목")

    html_content = generate_html(articles, stocks)
    output_path  = os.path.join(OUTPUT_DIR, "news_card.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ 뉴스카드 생성 완료!")

    if IS_CI:
        print("CI 환경 - GitHub Actions가 자동 업로드합니다.")
    else:
        push_to_github()
        subprocess.run(["open","https://surysury.github.io/ai-news-cards/news_card.html"])

if __name__ == "__main__":
    main()
