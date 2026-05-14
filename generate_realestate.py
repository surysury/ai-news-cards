#!/usr/bin/env python3
"""한국 부동산 뉴스카드 생성기 — 서울/경기 위주 · 배경이미지 오버레이 디자인"""
import feedparser, re, html, os, subprocess, json, calendar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
IS_CI      = os.environ.get("CI") == "true"

# ── RSS 피드 ──────────────────────────────────────────────────────────────────
FEEDS = [
    {"name": "매일경제",   "url": "https://www.mk.co.kr/rss/30000001/",                                           "lang": "ko"},
    {"name": "아시아경제", "url": "https://www.asiae.co.kr/rss/all.htm",                                          "lang": "ko"},
    {"name": "조선일보",   "url": "https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml", "lang": "ko"},
    {"name": "한국경제",   "url": "https://www.hankyung.com/feed/realestate",                                     "lang": "ko"},
    {"name": "Reuters",    "url": "https://feeds.reuters.com/reuters/businessNews",                               "lang": "en"},
    {"name": "Bloomberg",  "url": "https://feeds.bloomberg.com/markets/news.rss",                                 "lang": "en"},
]
MAX_PER_FEED = 10

# 부동산 키워드
RE_KW = [
    "아파트", "부동산", "전세", "월세", "매매", "분양", "청약",
    "재개발", "재건축", "리모델링", "주택", "오피스텔", "임대",
    "갭투자", "집값", "공시가", "전용면적", "단지", "입주",
    "주거", "토지", "건설", "시행사", "시공사", "조합", "조합원",
    "도시정비", "정비사업", "신도시", "택지지구",
    "real estate", "housing market", "mortgage", "property",
    "home price", "rent", "interest rate", "fed rate",
]

# 서울/경기 지역 키워드
AREA_KW = [
    "서울", "경기", "수도권", "강남", "서초", "송파", "용산", "마포",
    "성동", "광진", "노원", "도봉", "강북", "은평", "서대문", "양천",
    "영등포", "동작", "관악", "강서", "구로", "금천", "중구", "종로",
    "성북", "강동", "중랑", "동대문",
    "분당", "판교", "수원", "성남", "고양", "일산", "화성", "용인",
    "안양", "부천", "광명", "시흥", "안산", "평택", "남양주", "구리",
    "하남", "광주", "의왕", "과천", "군포", "오산", "파주",
    "김포", "양주", "가평", "양평",
]

# 카테고리 분류 키워드 → (라벨, 겨자/강조색 여부)
CATEGORY_MAP = [
    (["정책", "규제", "법안", "세금", "취득세", "종부세", "공시가", "대출규제", "LTV", "DSR"], "📋 정책"),
    (["상승", "급등", "올랐", "올라", "최고", "신고가", "뛰었"], "📈 가격상승"),
    (["하락", "급락", "내렸", "내려", "최저", "떨어", "떨어졌"], "📉 가격하락"),
    (["전세", "월세", "임대", "갱신", "역전세"], "🔑 전·월세"),
    (["분양", "청약", "입주", "모집공고", "당첨"], "🏗 분양·청약"),
    (["재개발", "재건축", "리모델링", "정비사업", "조합"], "🔨 재개발·재건축"),
    (["신도시", "택지지구", "개발", "토지"], "🌆 개발·신도시"),
]

def classify(text):
    for kws, label in CATEGORY_MAP:
        if any(k in text for k in kws):
            return label
    return "🏠 부동산"

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def strip_tags(t): return re.sub(r"<[^>]+>", "", t or "")

def contains_any(text, keywords):
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)

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

# ── Claude AI 요약 ────────────────────────────────────────────────────────────
def ai_summarize(title, summary, lang="ko"):
    api_key = os.environ.get("ANTHROPIC_API_KEY","")
    if not api_key: return title, summary
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        translate_note = "영문 기사이므로 반드시 한국어로 번역해서 요약해줘." if lang == "en" else "한국어로 요약해줘."
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role":"user","content":f"""다음 부동산 뉴스를 {translate_note} JSON만 출력해.

제목: {title}
내용: {summary}

{{"headline":"핵심 한 문장 제목 (28자 이내, 반드시 한국어, 숫자/지역명 포함하면 좋음)","summary":"핵심 내용 4줄 이내. 줄바꿈 구분. 반드시 한국어."}}"""}]
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
                search_text = raw_title + " " + raw_summary[:300]

                if not contains_any(search_text, RE_KW):
                    continue
                if feed_info["lang"] == "ko" and not contains_any(search_text, AREA_KW):
                    continue

                seen.add(link)
                headline, summary = ai_summarize(raw_title, raw_summary, lang=feed_info.get("lang","ko"))
                lines = [l.strip() for l in summary.split("\n") if l.strip()][:5]

                dt = parse_pub_date(entry)
                pub_str = ""
                if dt:
                    try: pub_str = dt.astimezone().strftime("%m.%d %H:%M")
                    except: pass

                category = classify(raw_title + " " + raw_summary[:100])

                articles.append({
                    "source":   feed_info["name"],
                    "category": category,
                    "title":    html.escape(headline),
                    "lines":    [html.escape(l) for l in lines],
                    "link":     link,
                    "image":    get_image(entry),
                    "pub":      pub_str,
                    "num":      len(articles) + 1,
                })
                count += 1
        except Exception as e:
            print(f"  [피드오류] {feed_info['name']}: {e}")
    return articles

# ── 시장 지표 ─────────────────────────────────────────────────────────────────
def make_sparkline(prices, up, width=80, height=28):
    if len(prices) < 2: return ""
    mn, mx = min(prices), max(prices)
    if mx == mn: return ""
    color = "#F5C518" if up else "#E63946"
    pts = " ".join(
        f"{round(i*(width/(len(prices)-1)),1)},{round(height-(p-mn)/(mx-mn)*height,1)}"
        for i, p in enumerate(prices)
    )
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'</svg>')

def fetch_market_indicators():
    try: import yfinance as yf
    except: return []
    indicators = [
        {"ticker": "^KS11",    "name": "KOSPI",       "category": "증시"},
        {"ticker": "^TNX",     "name": "미국 10년 국채","category": "금리"},
        {"ticker": "IYR",      "name": "미국 리츠 ETF","category": "리츠"},
        {"ticker": "VNQ",      "name": "뱅가드 리츠",  "category": "리츠"},
        {"ticker": "000720.KS","name": "현대건설",      "category": "건설주"},
        {"ticker": "047040.KS","name": "대우건설",      "category": "건설주"},
        {"ticker": "006360.KS","name": "GS건설",        "category": "건설주"},
        {"ticker": "294870.KS","name": "HDC현산",       "category": "건설주"},
    ]
    results = []
    for s in indicators:
        try:
            hist = yf.Ticker(s["ticker"]).history(period="5d")
            if hist.empty: continue
            prices = list(hist["Close"])
            price, prev = prices[-1], (prices[-2] if len(prices)>=2 else prices[-1])
            change = ((price-prev)/prev*100) if prev else 0
            is_kr  = s["ticker"].endswith(".KS")
            is_idx = s["ticker"].startswith("^")
            price_str = f"₩{price:,.0f}" if is_kr else (f"{price:,.2f}pt" if is_idx else f"${price:,.2f}")
            results.append({
                "name":s["name"],"ticker":s["ticker"].replace(".KS","").replace("^",""),
                "category":s["category"],"price":price_str,
                "change":change,"up":change>=0,"sparkline":make_sparkline(prices,change>=0),
            })
        except Exception as e:
            print(f"  [지표오류] {s['ticker']}: {e}")
    return results

# ── HTML 카드 ─────────────────────────────────────────────────────────────────
# 배경이 없을 때 사용할 그라디언트 팔레트 (서울/부동산 느낌)
BG_GRADIENTS = [
    "linear-gradient(160deg,#1a1a2e 0%,#16213e 60%,#0f3460 100%)",
    "linear-gradient(160deg,#0d1b2a 0%,#1b2838 60%,#243447 100%)",
    "linear-gradient(160deg,#1c1c1c 0%,#2d2d2d 60%,#1a1a2e 100%)",
    "linear-gradient(160deg,#12232e 0%,#203647 60%,#0f3460 100%)",
    "linear-gradient(160deg,#1a1a2e 0%,#2c3e50 100%)",
]

def make_news_card(a, total):
    idx = (a["num"] - 1) % len(BG_GRADIENTS)
    if a["image"]:
        bg_style = f"background-image:url('{a['image']}');"
        overlay  = '<div class="card-overlay"></div>'
    else:
        bg_style = f"background:{BG_GRADIENTS[idx]};"
        overlay  = ""

    lines_html = "".join(f"<li>{l}</li>" for l in a["lines"])

    # 카테고리별 색상
    cat_colors = {
        "📈 가격상승": "#F5C518",
        "📉 가격하락": "#E63946",
        "📋 정책":     "#60a5fa",
        "🔑 전·월세":  "#a78bfa",
        "🏗 분양·청약":"#34d399",
        "🔨 재개발·재건축":"#fb923c",
        "🌆 개발·신도시":"#38bdf8",
        "🏠 부동산":   "#F5C518",
    }
    cat_color = cat_colors.get(a["category"], "#F5C518")

    return f"""
<div class="slide">
  <div class="card" style="{bg_style}">
    {overlay}
    <div class="card-inner">
      <div class="card-top">
        <span class="new-badge">NEW POST</span>
        <span class="card-date">{a['pub']}</span>
      </div>
      <div class="card-category" style="color:{cat_color}">{a['category']}</div>
      <h2 class="card-title">{a['title']}</h2>
      <div class="card-divider" style="background:{cat_color}"></div>
      <ul class="card-lines">{lines_html}</ul>
      <div class="card-footer">
        <span class="source-label">{a['source']} · {a['num']}/{total}</span>
        <a class="read-more" href="{a['link']}" target="_blank">자세히 보기 →</a>
      </div>
    </div>
  </div>
</div>"""

def make_indicator_html(indicators):
    if not indicators: return '<div class="no-data">시장 데이터를 불러올 수 없습니다.</div>'
    cats = {}
    for s in indicators: cats.setdefault(s["category"],[]).append(s)
    parts = []
    for cat, items in cats.items():
        cards = ""
        for s in items:
            sign  = "+" if s["up"] else ""
            color = "#F5C518" if s["up"] else "#E63946"
            arrow = "▲" if s["up"] else "▼"
            cards += f"""
<div class="ind-card">
  <div class="ind-top">
    <div><div class="ind-name">{s['name']}</div><div class="ind-ticker">{s['ticker']}</div></div>
    <div>{s['sparkline']}</div>
  </div>
  <div class="ind-price">{s['price']}</div>
  <div class="ind-change" style="color:{color}">{arrow} {sign}{s['change']:.2f}%</div>
</div>"""
        parts.append(f'<div class="ind-group"><div class="ind-group-title">{cat}</div>'
                     f'<div class="ind-row">{cards}</div></div>')
    return "\n".join(parts)

# ── 전체 HTML ─────────────────────────────────────────────────────────────────
def generate_html(articles, indicators):
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
    ind_html = make_indicator_html(indicators)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>부동산 뉴스카드 {datetime.now().strftime('%Y.%m.%d')}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@700;900&family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Noto Sans KR',sans-serif;background:#111;min-height:100vh;padding-bottom:60px;}}

  /* 헤더 */
  .top-header{{background:#0a0a0a;color:#fff;padding:22px 24px 18px;border-bottom:1px solid #222;}}
  .top-header .date{{font-size:11px;color:#555;margin-bottom:6px;letter-spacing:.1em;text-transform:uppercase;}}
  .top-header h1{{font-family:'Noto Serif KR',serif;font-size:26px;font-weight:900;letter-spacing:-.02em;line-height:1.2;}}
  .top-header h1 em{{font-style:normal;color:#F5C518;}}
  .top-header .update-time{{font-size:11px;color:#444;margin-top:8px;}}

  /* 탭 */
  .tabs-sticky{{position:sticky;top:0;z-index:100;background:#0a0a0a;border-bottom:1px solid #222;}}
  .tabs{{display:flex;}}
  .tab{{flex:1;padding:14px 8px;font-size:13px;font-weight:700;color:#555;background:none;border:none;
        border-bottom:2px solid transparent;cursor:pointer;transition:.2s;text-align:center;}}
  .tab.active{{color:#F5C518;border-bottom-color:#F5C518;}}
  .tab .cnt{{display:inline-block;font-size:10px;background:#222;color:#666;border-radius:10px;padding:1px 7px;margin-left:4px;}}
  .tab.active .cnt{{background:#F5C518;color:#000;}}

  /* 섹션 */
  .section{{display:none;padding:20px 0 12px;}}
  .section.active{{display:block;}}

  /* 캐러셀 */
  .carousel-wrap{{position:relative;width:420px;max-width:94vw;margin:0 auto;}}
  .slider{{display:flex;overflow-x:scroll;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;
           scrollbar-width:none;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.6);}}
  .slider::-webkit-scrollbar{{display:none;}}
  .slide{{flex:0 0 100%;scroll-snap-align:start;}}
  .dots{{display:flex;gap:5px;justify-content:center;margin:14px 0 4px;flex-wrap:wrap;padding:0 16px;}}
  .dot{{width:6px;height:6px;border-radius:50%;background:#333;border:none;cursor:pointer;padding:0;transition:.2s;}}
  .dot.active{{background:#F5C518;transform:scale(1.5);}}
  .carousel-info{{text-align:center;font-size:11px;color:#444;margin-bottom:8px;}}
  .arrow{{position:absolute;top:50%;transform:translateY(-50%);background:rgba(0,0,0,.7);
          border:1px solid #333;border-radius:50%;width:36px;height:36px;display:flex;
          align-items:center;justify-content:center;cursor:pointer;font-size:14px;color:#F5C518;
          box-shadow:0 2px 12px rgba(0,0,0,.5);z-index:10;}}
  .arrow-left{{left:-18px;}} .arrow-right{{right:-18px;}}

  /* 뉴스 카드 (배경이미지 오버레이 방식) */
  .card{{position:relative;min-height:640px;display:flex;flex-direction:column;
         background-size:cover;background-position:center;background-repeat:no-repeat;
         border-radius:16px;overflow:hidden;}}
  .card-overlay{{position:absolute;inset:0;
    background:linear-gradient(180deg,
      rgba(0,0,0,.55) 0%,
      rgba(0,0,0,.30) 30%,
      rgba(0,0,0,.75) 60%,
      rgba(0,0,0,.92) 100%);}}
  .card-inner{{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;padding:22px 22px 18px;}}

  .card-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}}
  .new-badge{{font-size:9px;font-weight:900;letter-spacing:.2em;color:#000;background:#F5C518;
              padding:3px 10px;border-radius:2px;}}
  .card-date{{font-size:10px;color:rgba(255,255,255,.5);}}

  .card-category{{font-size:11px;font-weight:700;letter-spacing:.08em;margin-bottom:10px;}}
  .card-title{{font-family:'Noto Serif KR',serif;font-size:22px;font-weight:900;line-height:1.4;
               color:#fff;letter-spacing:-.02em;word-break:keep-all;margin-bottom:14px;
               text-shadow:0 2px 8px rgba(0,0,0,.6);}}
  .card-divider{{height:2px;width:40px;margin-bottom:14px;border-radius:1px;}}

  .card-lines{{list-style:none;display:flex;flex-direction:column;gap:8px;flex:1;}}
  .card-lines li{{font-size:12.5px;line-height:1.7;color:rgba(255,255,255,.85);
                  padding-left:14px;position:relative;word-break:keep-all;}}
  .card-lines li::before{{content:'·';position:absolute;left:0;color:#F5C518;font-size:18px;line-height:1.2;}}

  .card-footer{{display:flex;justify-content:space-between;align-items:center;
                margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,.12);}}
  .source-label{{font-size:10px;color:rgba(255,255,255,.4);}}
  .read-more{{font-size:11px;font-weight:700;color:#F5C518;text-decoration:none;
              border-bottom:1px solid rgba(245,197,24,.4);padding-bottom:1px;}}

  /* 시장 지표 */
  .ind-section-inner{{padding:0 20px;}}
  .ind-group{{margin-bottom:24px;}}
  .ind-group-title{{font-size:11px;font-weight:700;letter-spacing:.12em;color:#555;
                    margin-bottom:10px;text-transform:uppercase;}}
  .ind-row{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;}}
  .ind-card{{background:#1a1a1a;border-radius:12px;padding:14px;border:1px solid #2a2a2a;}}
  .ind-top{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;}}
  .ind-name{{font-size:13px;font-weight:800;color:#fff;}}
  .ind-ticker{{font-size:10px;color:#444;margin-top:2px;}}
  .ind-price{{font-size:15px;font-weight:700;color:#fff;margin-bottom:4px;}}
  .ind-change{{font-size:13px;font-weight:700;}}
  .no-data{{text-align:center;color:#444;font-size:13px;padding:40px;}}
  .market-note{{font-size:11px;color:#444;text-align:center;margin-top:4px;padding-bottom:8px;}}
  .section-label{{font-size:12px;font-weight:700;color:#F5C518;letter-spacing:.08em;
                  margin:0 20px 16px;padding-bottom:10px;border-bottom:1px solid #222;}}
</style>
</head>
<body>

<div class="top-header">
  <div class="date">{date_lbl} · {today} ({weekday})</div>
  <h1>서울·경기<br><em>부동산 뉴스카드</em></h1>
  <div class="update-time">업데이트 {now} · 정책·가격·전세·분양 소식</div>
</div>

<div class="tabs-sticky">
  <div class="tabs">
    <button class="tab active" onclick="showSection('news',this)">🏠 부동산 뉴스<span class="cnt">{total}</span></button>
    <button class="tab" onclick="showSection('market',this)">📊 시장 지표<span class="cnt">{len(indicators)}</span></button>
  </div>
</div>

<div class="section active" id="section-news">
  <div class="section-label">📰 TODAY'S REAL ESTATE NEWS</div>
  <div class="carousel-wrap">
    <button class="arrow arrow-left"  onclick="move(-1)">&#8592;</button>
    <button class="arrow arrow-right" onclick="move(+1)">&#8594;</button>
    <div class="slider" id="slider">{slides}</div>
  </div>
  <div class="dots" id="dots">{dots}</div>
  <div class="carousel-info">총 {total}개 · 스와이프 또는 화살표로 이동</div>
</div>

<div class="section" id="section-market">
  <div class="section-label">📊 MARKET INDICATORS (5일 추이)</div>
  <div class="ind-section-inner">
    {ind_html}
    <div class="market-note">※ 장 마감 후에는 전일 종가 기준 표시</div>
  </div>
</div>

<script>
let cur = 0;
const slider = document.getElementById('slider');
const dotsEl = document.getElementById('dots');
const total  = {total};
function showSection(id, btn) {{
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('section-'+id).classList.add('active');
  btn.classList.add('active');
}}
function goTo(idx) {{
  idx = Math.max(0, Math.min(total-1, idx));
  slider.scrollTo({{left:slider.clientWidth*idx, behavior:'smooth'}});
  dotsEl.querySelectorAll('.dot').forEach((d,i)=>d.classList.toggle('active',i===idx));
  cur = idx;
}}
function move(dir) {{ goTo(cur+dir); }}
slider.addEventListener('scroll', ()=>{{
  const idx = Math.round(slider.scrollLeft/slider.clientWidth);
  if(idx!==cur){{dotsEl.querySelectorAll('.dot').forEach((d,i)=>d.classList.toggle('active',i===idx));cur=idx;}}
}});
document.addEventListener('keydown', e=>{{
  if(document.getElementById('section-news').classList.contains('active')){{
    if(e.key==='ArrowLeft')move(-1); if(e.key==='ArrowRight')move(+1);
  }}
}});
</script>
</body>
</html>"""

# ── GitHub 업로드 ─────────────────────────────────────────────────────────────
def push_to_github():
    try:
        subprocess.run(["git","add","realestate_card.html","generate_realestate.py"], cwd=OUTPUT_DIR, check=True)
        r = subprocess.run(["git","diff","--staged","--quiet"], cwd=OUTPUT_DIR)
        if r.returncode == 0:
            print("변경 없음, 업로드 스킵"); return
        subprocess.run(["git","commit","-m",f"부동산 뉴스카드 업데이트 {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                       cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","fetch","origin"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","rebase","origin/main"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","push"], cwd=OUTPUT_DIR, check=True)
        print("GitHub 업로드 완료!")
        print("👉 https://surysury.github.io/ai-news-cards/realestate_card.html")
    except subprocess.CalledProcessError as e:
        print(f"[GitHub 업로드 실패] {e}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    print("🏠 부동산 뉴스 수집 중...")
    articles = fetch_articles()
    print(f"  기사: {len(articles)}개")

    print("📊 시장 지표 수집 중...")
    indicators = fetch_market_indicators()
    print(f"  지표: {len(indicators)}개 항목")

    html_content = generate_html(articles, indicators)
    output_path  = os.path.join(OUTPUT_DIR, "realestate_card.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ 부동산 뉴스카드 생성 완료!")

    if IS_CI:
        print("CI 환경 - GitHub Actions가 자동 업로드합니다.")
    else:
        push_to_github()
        subprocess.run(["open","https://surysury.github.io/ai-news-cards/realestate_card.html"])

if __name__ == "__main__":
    main()
