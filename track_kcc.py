#!/usr/bin/env python3
"""
KCC스위첸2차 (운양동, 김포) 부동산 가격 추적기
- 국토교통부 실거래가 API: 매매 / 전월세 실거래 내역
- 네이버 부동산 API: 현재 매물 수 / 호가 (선택)

필요한 것:
  MOLIT_API_KEY = 국토교통부 공공데이터 API 키
  → https://www.data.go.kr 에서 무료 발급
  → "아파트매매 실거래자료" 서비스 신청
"""

import os, json, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from collections import defaultdict
import subprocess

# ── 설정 ─────────────────────────────────────────────────────────────────────
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "여기에_API키_입력")

LAWD_CD   = "41570"          # 경기도 김포시
APT_NAME  = "KCC"            # 아파트명 필터 (포함 여부)
OUTPUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kcc_tracker.html")

# 추적할 면적 (전용면적 기준, None이면 전체)
TARGET_AREAS = [59, 74, 84]  # 대표 평형 (근사값 ±5㎡)
AREA_TOLERANCE = 5

# 최근 몇 개월 조회 (최대 36)
MONTHS_BACK = 24

# 네이버 부동산 단지 코드 (찾으면 입력)
NAVER_COMPLEX_NO = ""  # 예: "113079"

# ── 국토교통부 실거래 API ─────────────────────────────────────────────────────
BASE_TRADE = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTrade"
BASE_RENT  = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptRent"

def fetch_molit(base_url, ym):
    """국토교통부 API 한 달치 조회"""
    params = urllib.parse.urlencode({
        "serviceKey": MOLIT_API_KEY,
        "LAWD_CD":    LAWD_CD,
        "DEAL_YMD":   ym,
        "numOfRows":  "1000",
        "pageNo":     "1",
    })
    url = f"{base_url}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"  [API 오류] {ym}: {e}")
        return ""

def parse_trade(xml_str):
    """매매 실거래 파싱"""
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            name = (item.findtext("아파트") or "").strip()
            if APT_NAME not in name:
                continue
            area_str = item.findtext("전용면적") or "0"
            try: area = float(area_str)
            except: area = 0.0
            price_str = (item.findtext("거래금액") or "0").replace(",","").strip()
            try: price = int(price_str)
            except: price = 0
            year  = item.findtext("년") or ""
            month = item.findtext("월") or ""
            day   = item.findtext("일") or ""
            floor = item.findtext("층") or ""
            rows.append({
                "type":  "매매",
                "name":  name,
                "area":  area,
                "price": price,
                "date":  f"{year}-{month.zfill(2)}-{day.zfill(2)}",
                "floor": floor,
            })
    except: pass
    return rows

def parse_rent(xml_str):
    """전월세 실거래 파싱"""
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            name = (item.findtext("아파트") or "").strip()
            if APT_NAME not in name:
                continue
            area_str = item.findtext("전용면적") or "0"
            try: area = float(area_str)
            except: area = 0.0
            deposit_str = (item.findtext("보증금액") or "0").replace(",","").strip()
            monthly_str = (item.findtext("월세금액") or "0").replace(",","").strip()
            try: deposit = int(deposit_str)
            except: deposit = 0
            try: monthly = int(monthly_str)
            except: monthly = 0
            year  = item.findtext("년") or ""
            month = item.findtext("월") or ""
            day   = item.findtext("일") or ""
            floor = item.findtext("층") or ""
            rent_type = "월세" if monthly > 0 else "전세"
            rows.append({
                "type":    rent_type,
                "name":    name,
                "area":    area,
                "price":   deposit,
                "monthly": monthly,
                "date":    f"{year}-{month.zfill(2)}-{day.zfill(2)}",
                "floor":   floor,
            })
    except: pass
    return rows

def collect_all():
    """최근 N개월 전체 수집"""
    trades, rents = [], []
    now = datetime.now()
    months = []
    for i in range(MONTHS_BACK):
        d = now - timedelta(days=30*i)
        months.append(d.strftime("%Y%m"))

    print(f"  조회 기간: {months[-1]} ~ {months[0]}")
    for ym in months:
        print(f"  {ym} 조회 중...", end=" ")
        xml_t = fetch_molit(BASE_TRADE, ym)
        xml_r = fetch_molit(BASE_RENT,  ym)
        t = parse_trade(xml_t)
        r = parse_rent(xml_r)
        trades.extend(t)
        rents.extend(r)
        print(f"매매 {len(t)}건, 전월세 {len(r)}건")

    return sorted(trades, key=lambda x: x["date"]), \
           sorted(rents,  key=lambda x: x["date"])

# ── 네이버 매물 수 ─────────────────────────────────────────────────────────────
def fetch_naver_listings():
    """네이버 부동산 현재 매물 수 / 호가 (단지코드 있을 때만)"""
    if not NAVER_COMPLEX_NO:
        return None
    import time
    time.sleep(2)
    try:
        url = f"https://new.land.naver.com/api/articles/complex/{NAVER_COMPLEX_NO}?realEstateType=APT&tradeType=A1&tag=&rentPriceMin=0&rentPriceMax=900000000&priceMin=0&priceMax=900000000&areaMin=0&areaMax=900000000&oldBuildYear&recentlyBuildYear&page=1&sameAddressGroup=true"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "referer": "https://new.land.naver.com/",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        total = data.get("articleTotalCount", 0)
        items = data.get("articleList", [])[:5]
        return {"total": total, "items": items}
    except Exception as e:
        print(f"  [네이버 매물 오류] {e}")
        return None

# ── 차트 데이터 준비 ──────────────────────────────────────────────────────────
def area_label(area):
    """면적 → 평형 라벨"""
    py = area / 3.3058
    return f"{area:.1f}㎡ (약 {py:.0f}평)"

def group_by_month_area(rows, types=("매매",)):
    """월별 × 면적별 평균가 집계"""
    buckets = defaultdict(list)
    for r in rows:
        if r["type"] not in types:
            continue
        ym   = r["date"][:7]
        area = r["area"]
        # 대표 평형 분류
        matched = None
        for ta in TARGET_AREAS:
            if abs(area - ta) <= AREA_TOLERANCE:
                matched = ta
                break
        if matched is None:
            matched = round(area)
        buckets[(ym, matched)].append(r["price"])
    result = {}
    for (ym, area), prices in buckets.items():
        result.setdefault(area, {})[ym] = round(sum(prices)/len(prices))
    return result

def make_chart_datasets(grouped):
    """Chart.js 데이터셋 생성"""
    colors = ["#F5C518","#60a5fa","#34d399","#fb923c","#a78bfa"]
    all_months = sorted({ym for v in grouped.values() for ym in v})
    datasets = []
    for i, (area, monthly) in enumerate(sorted(grouped.items())):
        color = colors[i % len(colors)]
        data  = [monthly.get(ym, None) for ym in all_months]
        label = f"{area}㎡ (약{round(area/3.3058)}평)"
        datasets.append({"label": label, "data": data,
                         "borderColor": color, "backgroundColor": color+"33",
                         "tension": 0.3, "spanGaps": True})
    return all_months, datasets

# ── HTML 생성 ─────────────────────────────────────────────────────────────────
def generate_html(trades, rents, naver):
    now_str    = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    total_trade = len(trades)
    total_rent  = len(rents)

    # 최근 10건
    recent_trades = trades[-10:][::-1]
    recent_rents  = rents[-10:][::-1]

    # 차트 데이터
    trade_grouped   = group_by_month_area(trades, ("매매",))
    jeonse_grouped  = group_by_month_area(rents,  ("전세",))
    monthly_grouped = group_by_month_area(rents,  ("월세",))

    t_months, t_ds = make_chart_datasets(trade_grouped)
    j_months, j_ds = make_chart_datasets(jeonse_grouped)

    def ds_json(months, datasets):
        return json.dumps({"labels": months, "datasets": datasets}, ensure_ascii=False)

    trade_json  = ds_json(t_months, t_ds)
    jeonse_json = ds_json(j_months, j_ds)

    # 최근 매매 평균
    last3 = [r for r in trades if r["date"] >= (datetime.now()-timedelta(days=90)).strftime("%Y-%m-%d")]
    avg3  = f"{round(sum(r['price'] for r in last3)/len(last3)):,}만원" if last3 else "데이터 없음"

    # 매물 수 표시
    naver_html = ""
    if naver:
        naver_html = f'<div class="stat-card" style="border-color:#60a5fa"><div class="stat-val" style="color:#60a5fa">{naver["total"]}건</div><div class="stat-lbl">현재 네이버 매물</div></div>'

    # 거래 테이블 행
    def trade_rows(rows):
        return "".join(f"""<tr>
            <td>{r['date']}</td>
            <td>{r['name']}</td>
            <td>{r['area']:.1f}㎡</td>
            <td>{r['floor']}층</td>
            <td style="font-weight:700;color:#F5C518">{r['price']:,}만원</td>
        </tr>""" for r in rows)

    def rent_rows(rows):
        out = []
        for r in rows:
            if r["type"] == "전세":
                price_str = f"전세 {r['price']:,}만원"
                color = "#60a5fa"
            else:
                price_str = f"월세 {r['price']:,}/{r.get('monthly',0):,}만원"
                color = "#34d399"
            out.append(f"""<tr>
                <td>{r['date']}</td>
                <td>{r['type']}</td>
                <td>{r['area']:.1f}㎡</td>
                <td>{r['floor']}층</td>
                <td style="font-weight:700;color:{color}">{price_str}</td>
            </tr>""")
        return "".join(out)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KCC스위첸2차 시세 추적</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Noto Sans KR',sans-serif;background:#0e0e0e;color:#e0e0e0;min-height:100vh;padding-bottom:60px;}}

  .header{{background:#0a0a0a;padding:24px;border-bottom:1px solid #1e1e1e;}}
  .header h1{{font-size:22px;font-weight:900;color:#fff;margin-bottom:4px;}}
  .header h1 em{{color:#F5C518;font-style:normal;}}
  .header .sub{{font-size:12px;color:#555;margin-top:6px;}}

  .section{{padding:24px;border-bottom:1px solid #1a1a1a;}}
  .section-title{{font-size:13px;font-weight:700;color:#F5C518;letter-spacing:.1em;
                  text-transform:uppercase;margin-bottom:16px;}}

  .stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:0;}}
  .stat-card{{background:#1a1a1a;border-radius:12px;padding:16px 20px;border:1px solid #2a2a2a;
              border-left:3px solid #F5C518;min-width:140px;flex:1;}}
  .stat-val{{font-size:22px;font-weight:900;color:#F5C518;}}
  .stat-lbl{{font-size:11px;color:#555;margin-top:4px;}}

  .chart-box{{background:#141414;border-radius:12px;padding:20px;border:1px solid #1e1e1e;margin-bottom:16px;}}
  .chart-box h3{{font-size:13px;color:#aaa;margin-bottom:16px;font-weight:700;}}

  table{{width:100%;border-collapse:collapse;font-size:12px;}}
  th{{background:#1a1a1a;color:#666;font-weight:700;padding:10px 12px;text-align:left;
      border-bottom:1px solid #222;letter-spacing:.05em;}}
  td{{padding:10px 12px;border-bottom:1px solid #1a1a1a;color:#ccc;}}
  tr:hover td{{background:#161616;}}

  .tabs{{display:flex;border-bottom:1px solid #1e1e1e;background:#0a0a0a;
         position:sticky;top:0;z-index:10;}}
  .tab{{flex:1;padding:14px;font-size:13px;font-weight:700;color:#444;background:none;
        border:none;border-bottom:2px solid transparent;cursor:pointer;text-align:center;}}
  .tab.active{{color:#F5C518;border-bottom-color:#F5C518;}}
  .pane{{display:none;}} .pane.active{{display:block;}}

  .update-badge{{display:inline-block;font-size:10px;background:#1a1a1a;color:#555;
                 padding:3px 10px;border-radius:20px;margin-top:8px;}}
  @media(max-width:480px){{
    .stats{{gap:8px;}}
    .stat-val{{font-size:18px;}}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>경기 김포시 운양동<br><em>KCC스위첸2차</em> 시세 추적</h1>
  <div class="sub">국토교통부 실거래가 기준 · 최근 {MONTHS_BACK}개월</div>
  <div class="update-badge">업데이트: {now_str}</div>
</div>

<div class="tabs">
  <button class="tab active" onclick="show('trade',this)">📈 매매</button>
  <button class="tab" onclick="show('rent',this)">🔑 전·월세</button>
  <button class="tab" onclick="show('table',this)">📋 거래 내역</button>
</div>

<!-- 매매 탭 -->
<div class="pane active" id="pane-trade">
  <div class="section">
    <div class="section-title">📊 시세 요약</div>
    <div class="stats">
      <div class="stat-card"><div class="stat-val">{total_trade}건</div><div class="stat-lbl">총 매매 거래 ({MONTHS_BACK}개월)</div></div>
      <div class="stat-card"><div class="stat-val">{avg3}</div><div class="stat-lbl">최근 3개월 평균가</div></div>
      {naver_html}
    </div>
  </div>
  <div class="section">
    <div class="section-title">📈 매매가 추이 (평형별)</div>
    <div class="chart-box">
      <h3>월별 평균 매매가 (만원)</h3>
      <canvas id="tradeChart" height="200"></canvas>
    </div>
  </div>
  <div class="section">
    <div class="section-title">🕐 최근 매매 거래</div>
    <table>
      <tr><th>거래일</th><th>단지명</th><th>면적</th><th>층</th><th>거래가</th></tr>
      {trade_rows(recent_trades)}
    </table>
  </div>
</div>

<!-- 전·월세 탭 -->
<div class="pane" id="pane-rent">
  <div class="section">
    <div class="section-title">📊 전월세 요약</div>
    <div class="stats">
      <div class="stat-card" style="border-color:#60a5fa">
        <div class="stat-val" style="color:#60a5fa">{sum(1 for r in rents if r['type']=='전세')}건</div>
        <div class="stat-lbl">전세 거래 ({MONTHS_BACK}개월)</div>
      </div>
      <div class="stat-card" style="border-color:#34d399">
        <div class="stat-val" style="color:#34d399">{sum(1 for r in rents if r['type']=='월세')}건</div>
        <div class="stat-lbl">월세 거래 ({MONTHS_BACK}개월)</div>
      </div>
    </div>
  </div>
  <div class="section">
    <div class="section-title">📈 전세가 추이 (평형별)</div>
    <div class="chart-box">
      <h3>월별 평균 전세 보증금 (만원)</h3>
      <canvas id="jeonseChart" height="200"></canvas>
    </div>
  </div>
  <div class="section">
    <div class="section-title">🕐 최근 전·월세 거래</div>
    <table>
      <tr><th>거래일</th><th>유형</th><th>면적</th><th>층</th><th>가격</th></tr>
      {rent_rows(recent_rents)}
    </table>
  </div>
</div>

<!-- 거래 내역 탭 -->
<div class="pane" id="pane-table">
  <div class="section">
    <div class="section-title">📋 전체 매매 거래 내역</div>
    <table>
      <tr><th>거래일</th><th>단지명</th><th>면적</th><th>층</th><th>거래가</th></tr>
      {trade_rows(trades[::-1])}
    </table>
  </div>
</div>

<script>
function show(id, btn) {{
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('pane-'+id).classList.add('active');
  btn.classList.add('active');
}}

Chart.defaults.color = '#666';
Chart.defaults.borderColor = '#1e1e1e';

const tradeData = {trade_json};
const jeonseData = {jeonse_json};

function makeChart(id, data, label) {{
  const ctx = document.getElementById(id);
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'line',
    data: data,
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#aaa', font: {{ size: 11 }} }} }},
        tooltip: {{
          callbacks: {{
            label: ctx => ctx.dataset.label + ': ' + (ctx.raw ? ctx.raw.toLocaleString() + '만원' : '-')
          }}
        }}
      }},
      scales: {{
        x: {{ ticks: {{ color: '#555', maxTicksLimit: 12 }} }},
        y: {{
          ticks: {{
            color: '#555',
            callback: v => (v/10000).toFixed(0) + '억' + (v%10000 > 0 ? (v%10000) + '' : '')
          }}
        }}
      }}
    }}
  }});
}}

makeChart('tradeChart',  tradeData,  '매매가');
makeChart('jeonseChart', jeonseData, '전세가');
</script>
</body>
</html>"""

# ── GitHub 업로드 ─────────────────────────────────────────────────────────────
def push_to_github():
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(["git","add","kcc_tracker.html","track_kcc.py"], cwd=OUTPUT_DIR, check=True)
        r = subprocess.run(["git","diff","--staged","--quiet"], cwd=OUTPUT_DIR)
        if r.returncode == 0:
            print("변경 없음, 스킵"); return
        subprocess.run(["git","commit","-m",f"KCC 시세 업데이트 {datetime.now().strftime('%Y-%m-%d')}"],
                       cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","fetch","origin"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","rebase","origin/main"], cwd=OUTPUT_DIR, check=True)
        subprocess.run(["git","push"], cwd=OUTPUT_DIR, check=True)
        print("👉 https://surysury.github.io/ai-news-cards/kcc_tracker.html")
    except subprocess.CalledProcessError as e:
        print(f"[업로드 실패] {e}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    if MOLIT_API_KEY == "여기에_API키_입력":
        print("⚠️  MOLIT_API_KEY를 설정하세요.")
        print("   1. https://www.data.go.kr 접속 → 회원가입")
        print("   2. '아파트매매 실거래자료' 검색 → 활용신청")
        print("   3. '아파트 전월세 자료' 검색 → 활용신청")
        print("   4. 발급된 키를 환경변수에 설정:")
        print("      export MOLIT_API_KEY='발급된키'")
        print("   (또는 이 파일 상단 MOLIT_API_KEY 변수에 직접 입력)")
        return

    print("📡 국토교통부 실거래 데이터 수집 중...")
    trades, rents = collect_all()
    print(f"\n✅ 수집 완료: 매매 {len(trades)}건, 전월세 {len(rents)}건")

    print("\n🌐 네이버 매물 조회 중...")
    naver = fetch_naver_listings()
    if naver:
        print(f"  현재 매물: {naver['total']}건")

    html = generate_html(trades, rents, naver)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📊 리포트 생성: {OUTPUT}")

    IS_CI = os.environ.get("CI") == "true"
    if IS_CI:
        push_to_github()
    else:
        push_to_github()
        subprocess.run(["open", OUTPUT])

if __name__ == "__main__":
    main()
