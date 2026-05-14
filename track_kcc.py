#!/usr/bin/env python3
"""KCC스위첸2차 시세 추적기 — 귀여운 핑크 디자인"""

import os, json, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET, subprocess
from datetime import datetime, timedelta
from collections import defaultdict

# ── 설정 ─────────────────────────────────────────────────────────────────────
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")
LAWD_CD       = "41570"   # 경기도 김포시
APT_NAME      = "KCC"     # 아파트명 필터
MONTHS_BACK   = 24        # 최근 24개월
TARGET_AREAS  = [59, 74, 84]
AREA_TOL      = 6
OUTPUT        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kcc_tracker.html")

# APIs — 운영키 / 개발키 두 가지 모두 시도
TRADE_URLS = [
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "http://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
]
RENT_URLS = [
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
    "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptRentDev/getRTMSDataSvcAptRentDev",
]

# ── API 호출 ─────────────────────────────────────────────────────────────────
def fetch_api(urls, ym):
    """여러 엔드포인트 중 성공한 것 반환"""
    params = {
        "serviceKey": MOLIT_API_KEY,
        "LAWD_CD":    LAWD_CD,
        "DEAL_YMD":   ym,
        "numOfRows":  "1000",
        "pageNo":     "1",
    }
    # serviceKey는 이미 인코딩돼 있으면 그대로, 아니면 urlencode
    query = urllib.parse.urlencode({k: v for k, v in params.items() if k != "serviceKey"})
    query = f"serviceKey={MOLIT_API_KEY}&{query}"

    for base in urls:
        url = f"{base}?{query}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/xml, text/xml, */*",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode("utf-8")
            # 오류 응답 걸러내기
            if "<resultCode>00</resultCode>" in raw or "<item>" in raw:
                return raw
            if "SERVICE_ACCESS_DENIED" in raw or "LIMITED_NUMBER" in raw:
                print(f"    [키 오류] {raw[raw.find('<errMsg>'):raw.find('</errMsg>')+10]}")
                return raw
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}: {base.split('/')[-1]}")
        except Exception as e:
            print(f"    오류: {e}")
    return ""

def parse_trade(xml_str):
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            name = (item.findtext("aptNm") or "").strip()
            if APT_NAME not in name: continue
            try: area = float(item.findtext("excluUseAr") or 0)
            except: area = 0
            try: price = int((item.findtext("dealAmount") or "0").replace(",","").strip())
            except: price = 0
            y = item.findtext("dealYear") or ""
            m = (item.findtext("dealMonth") or "").zfill(2)
            d = (item.findtext("dealDay") or "").zfill(2)
            rows.append({"type":"매매","name":name,"area":area,"price":price,
                         "date":f"{y}-{m}-{d}","floor":item.findtext("floor") or ""})
    except: pass
    return rows

def parse_rent(xml_str):
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            name = (item.findtext("aptNm") or "").strip()
            if APT_NAME not in name: continue
            try: area = float(item.findtext("excluUseAr") or 0)
            except: area = 0
            try: deposit = int((item.findtext("deposit") or "0").replace(",","").strip())
            except: deposit = 0
            try: monthly = int((item.findtext("monthlyRent") or "0").replace(",","").strip())
            except: monthly = 0
            y = item.findtext("dealYear") or ""
            m = (item.findtext("dealMonth") or "").zfill(2)
            d = (item.findtext("dealDay") or "").zfill(2)
            rows.append({"type":"월세" if monthly>0 else "전세","name":name,"area":area,
                         "price":deposit,"monthly":monthly,
                         "date":f"{y}-{m}-{d}","floor":item.findtext("floor") or ""})
    except: pass
    return rows

def collect_all():
    trades, rents = [], []
    now = datetime.now()
    for i in range(MONTHS_BACK):
        d = now.replace(day=1) - timedelta(days=i*28)
        ym = d.strftime("%Y%m")
        print(f"  {ym} 조회 중...", end=" ", flush=True)
        xml_t = fetch_api(TRADE_URLS, ym)
        xml_r = fetch_api(RENT_URLS,  ym)
        t = parse_trade(xml_t)
        r = parse_rent(xml_r)
        trades.extend(t)
        rents.extend(r)
        print(f"매매 {len(t)}건 / 전월세 {len(r)}건")
    return (sorted(trades, key=lambda x: x["date"]),
            sorted(rents,  key=lambda x: x["date"]))

# ── 차트 데이터 ───────────────────────────────────────────────────────────────
def group_by_month(rows, types):
    buckets = defaultdict(list)
    for r in rows:
        if r["type"] not in types: continue
        ym = r["date"][:7]
        a  = r["area"]
        matched = next((ta for ta in TARGET_AREAS if abs(a-ta)<=AREA_TOL), round(a/3)*3)
        buckets[(ym, matched)].append(r["price"])
    result = {}
    for (ym, area), prices in buckets.items():
        result.setdefault(area, {})[ym] = round(sum(prices)/len(prices))
    return result

def chart_json(grouped):
    COLORS = ["#60A5FA","#93C5FD","#34D399","#F59E0B","#A78BFA"]
    all_months = sorted({ym for v in grouped.values() for ym in v})
    datasets = []
    for i, (area, monthly) in enumerate(sorted(grouped.items())):
        c = COLORS[i % len(COLORS)]
        datasets.append({
            "label": f"{area}㎡ (약{round(area/3.3058)}평)",
            "data":  [monthly.get(ym) for ym in all_months],
            "borderColor": c, "backgroundColor": c+"33",
            "tension": 0.4, "spanGaps": True,
            "pointBackgroundColor": c, "pointRadius": 4,
        })
    return all_months, datasets

# ── HTML ──────────────────────────────────────────────────────────────────────
def generate_html(trades, rents):
    now_str  = datetime.now().strftime("%Y.%m.%d %H:%M")
    total_t  = len(trades)
    total_r  = len(rents)
    total_j  = sum(1 for r in rents if r["type"]=="전세")
    total_w  = sum(1 for r in rents if r["type"]=="월세")

    # 최근 3개월 평균 매매가
    cutoff = (datetime.now()-timedelta(days=90)).strftime("%Y-%m-%d")
    recent3 = [r for r in trades if r["date"] >= cutoff]
    avg3 = f"{round(sum(r['price'] for r in recent3)/len(recent3)):,}만원" if recent3 else "—"

    # 84㎡ 최근 최고/최저
    t84 = [r for r in trades if abs(r["area"]-84)<=AREA_TOL]
    hi84 = f"{max(r['price'] for r in t84):,}만원" if t84 else "—"
    lo84 = f"{min(r['price'] for r in t84):,}만원" if t84 else "—"

    # 차트 JSON
    t_months, t_ds   = chart_json(group_by_month(trades, ("매매",)))
    j_months, j_ds   = chart_json(group_by_month(rents,  ("전세",)))

    def ds_json(months, ds):
        return json.dumps({"labels": months, "datasets": ds}, ensure_ascii=False)

    # 테이블 행
    def trade_row(r):
        return f"""<tr>
          <td>{r['date']}</td><td>{r['area']:.0f}㎡</td>
          <td>{r['floor']}층</td>
          <td class="price-cell">{r['price']:,}<span class="unit">만원</span></td>
        </tr>"""

    def rent_row(r):
        if r["type"]=="전세":
            p = f"{r['price']:,}만원"
            cls = "blue"
        else:
            p = f"{r['price']:,}/{r.get('monthly',0):,}만원"
            cls = "green"
        return f"""<tr>
          <td>{r['date']}</td><td>{r['type']}</td><td>{r['area']:.0f}㎡</td>
          <td>{r['floor']}층</td>
          <td class="price-cell {cls}">{p}</td>
        </tr>"""

    trade_rows_html = "".join(trade_row(r) for r in trades[::-1][:50])
    rent_rows_html  = "".join(rent_row(r)  for r in rents[::-1][:50])

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>KCC스위첸2차 시세 🏠</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  :root{{
    --blue:   #2563EB;
    --blue2:  #3B82F6;
    --blue3:  #1E3A6E;
    --bg:     #0F1E3C;
    --card:   #172444;
    --card2:  #1E2F54;
    --border: #1E3A6E;
    --white:  #FFFFFF;
    --muted:  rgba(255,255,255,.45);
    --accent: #60A5FA;
  }}
  body{{font-family:'Noto Sans KR',sans-serif;background:var(--bg);color:var(--white);
        min-height:100vh;padding-bottom:env(safe-area-inset-bottom,24px);}}

  /* 헤더 */
  .header{{background:linear-gradient(135deg,#1D4ED8 0%,#2563EB 50%,#1E40AF 100%);
           padding:28px 24px 24px;padding-top:max(28px,env(safe-area-inset-top));
           position:relative;overflow:hidden;}}
  .header::before{{content:'🏠';position:absolute;right:20px;top:50%;
                   transform:translateY(-50%);font-size:72px;opacity:.15;}}
  .header::after{{content:'';position:absolute;top:0;right:0;bottom:0;
                  width:200px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.05));}}
  .header .badge{{display:inline-block;background:rgba(255,255,255,.15);
                  color:#fff;font-size:10px;font-weight:700;padding:3px 12px;
                  border-radius:20px;letter-spacing:.1em;margin-bottom:10px;
                  border:1px solid rgba(255,255,255,.2);}}
  .header h1{{font-size:22px;font-weight:900;color:#fff;line-height:1.3;
              text-shadow:0 2px 12px rgba(0,0,0,.3);}}
  .header h1 em{{font-style:normal;color:#93C5FD;}}
  .header h1 span{{display:block;font-size:13px;font-weight:400;
                   color:rgba(255,255,255,.65);margin-top:5px;}}
  .update-info{{font-size:10px;color:rgba(255,255,255,.45);margin-top:10px;}}

  /* 탭 */
  .tabs-wrap{{position:sticky;top:0;z-index:50;
              background:#0F1E3C;border-bottom:1px solid var(--border);}}
  .tabs{{display:flex;}}
  .tab{{flex:1;padding:13px 4px;font-size:12px;font-weight:700;
        color:rgba(255,255,255,.35);background:none;border:none;
        border-bottom:2.5px solid transparent;cursor:pointer;text-align:center;transition:.2s;}}
  .tab.active{{color:#60A5FA;border-bottom-color:#60A5FA;}}

  /* 컨텐츠 */
  .pane{{display:none;padding:20px 16px;}} .pane.active{{display:block;}}

  /* 스탯 카드 */
  .stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;}}
  .stat{{background:var(--card);border-radius:16px;padding:16px;
         border:1px solid var(--border);text-align:center;}}
  .stat-emoji{{font-size:24px;margin-bottom:6px;}}
  .stat-val{{font-size:20px;font-weight:900;color:#60A5FA;line-height:1;}}
  .stat-lbl{{font-size:10px;color:var(--muted);margin-top:4px;font-weight:500;}}

  /* 차트 카드 */
  .chart-card{{background:var(--card);border-radius:20px;padding:20px;
               border:1px solid var(--border);margin-bottom:16px;}}
  .chart-title{{font-size:13px;font-weight:700;color:#fff;margin-bottom:16px;
                display:flex;align-items:center;gap:8px;}}
  .chart-title::before{{content:'';display:block;width:4px;height:16px;
                         background:#60A5FA;border-radius:2px;}}

  /* 테이블 */
  .table-card{{background:var(--card);border-radius:20px;overflow:hidden;
               border:1px solid var(--border);margin-bottom:16px;}}
  .table-head{{background:linear-gradient(90deg,#1D4ED8,#2563EB);
               padding:14px 16px;font-size:12px;font-weight:700;color:#fff;}}
  table{{width:100%;border-collapse:collapse;font-size:12px;}}
  th{{background:var(--card2);color:var(--muted);font-weight:700;padding:10px 12px;
      text-align:left;font-size:11px;letter-spacing:.04em;}}
  td{{padding:10px 12px;border-bottom:1px solid var(--border);color:rgba(255,255,255,.8);}}
  tr:last-child td{{border-bottom:none;}}
  tr:hover td{{background:var(--card2);}}
  .price-cell{{font-weight:700;color:#60A5FA;}}
  .price-cell.blue{{color:#93C5FD;}}
  .price-cell.green{{color:#34D399;}}
  .unit{{font-size:10px;font-weight:400;color:var(--muted);margin-left:2px;}}

  /* 빈 상태 */
  .empty{{text-align:center;padding:40px 20px;color:var(--muted);}}
  .empty .emoji{{font-size:48px;margin-bottom:12px;}}
  .empty p{{font-size:13px;}}

  /* 섹션 타이틀 */
  .section-title{{font-size:11px;font-weight:700;color:#60A5FA;
                  letter-spacing:.1em;margin:20px 0 10px;text-transform:uppercase;
                  display:flex;align-items:center;gap:6px;}}

  @media(max-width:360px){{
    .stats{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="badge">🏠 실거래가 추적기</div>
  <h1>KCC스위첸2차
    <span>경기도 김포시 운양동 · 한강신도시</span>
  </h1>
  <div class="update-info">📅 업데이트 {now_str} · 최근 {MONTHS_BACK}개월 기준</div>
</div>

<div class="tabs-wrap">
  <div class="tabs">
    <button class="tab active" onclick="show('trade',this)">📈 매매</button>
    <button class="tab" onclick="show('rent',this)">🔑 전·월세</button>
    <button class="tab" onclick="show('table',this)">📋 전체내역</button>
  </div>
</div>

<!-- ① 매매 탭 -->
<div class="pane active" id="pane-trade">
  <div class="stats">
    <div class="stat">
      <div class="stat-emoji">🏡</div>
      <div class="stat-val">{total_t}건</div>
      <div class="stat-lbl">총 매매거래 ({MONTHS_BACK}개월)</div>
    </div>
    <div class="stat">
      <div class="stat-emoji">💰</div>
      <div class="stat-val" style="font-size:16px">{avg3}</div>
      <div class="stat-lbl">최근 3개월 평균가</div>
    </div>
    <div class="stat">
      <div class="stat-emoji">📈</div>
      <div class="stat-val" style="font-size:16px">{hi84}</div>
      <div class="stat-lbl">84㎡ 최고가 ({MONTHS_BACK}개월)</div>
    </div>
    <div class="stat">
      <div class="stat-emoji">📉</div>
      <div class="stat-val" style="font-size:16px">{lo84}</div>
      <div class="stat-lbl">84㎡ 최저가 ({MONTHS_BACK}개월)</div>
    </div>
  </div>

  <div class="chart-card">
    <div class="chart-title">매매가 월별 추이 (평형별)</div>
    <canvas id="tradeChart" height="200"></canvas>
  </div>

  <div class="section-title">🕐 최근 매매 거래</div>
  {"<div class='table-card'><table><tr><th>거래일</th><th>면적</th><th>층</th><th>거래가</th></tr>" + "".join(trade_row(r) for r in trades[::-1][:15]) + "</table></div>" if trades else "<div class='empty'><div class='emoji'>🐻</div><p>아직 거래 데이터가 없어요</p></div>"}
</div>

<!-- ② 전월세 탭 -->
<div class="pane" id="pane-rent">
  <div class="stats">
    <div class="stat">
      <div class="stat-emoji">🔑</div>
      <div class="stat-val">{total_j}건</div>
      <div class="stat-lbl">전세 거래 ({MONTHS_BACK}개월)</div>
    </div>
    <div class="stat">
      <div class="stat-emoji">🏠</div>
      <div class="stat-val">{total_w}건</div>
      <div class="stat-lbl">월세 거래 ({MONTHS_BACK}개월)</div>
    </div>
  </div>

  <div class="chart-card">
    <div class="chart-title">전세 보증금 월별 추이 (평형별)</div>
    <canvas id="jeonseChart" height="200"></canvas>
  </div>

  <div class="section-title">🕐 최근 전·월세 거래</div>
  {"<div class='table-card'><table><tr><th>거래일</th><th>유형</th><th>면적</th><th>층</th><th>가격</th></tr>" + "".join(rent_row(r) for r in rents[::-1][:15]) + "</table></div>" if rents else "<div class='empty'><div class='emoji'>🐻</div><p>아직 전·월세 데이터가 없어요</p></div>"}
</div>

<!-- ③ 전체내역 탭 -->
<div class="pane" id="pane-table">
  <div class="table-card">
    <div class="table-head">📋 매매 전체 내역 ({total_t}건)</div>
    <table>
      <tr><th>거래일</th><th>면적</th><th>층</th><th>거래가</th></tr>
      {trade_rows_html if trade_rows_html else "<tr><td colspan='4' style='text-align:center;padding:24px;color:#aaa'>데이터 없음 🐻</td></tr>"}
    </table>
  </div>
  <div class="table-card" style="margin-top:16px">
    <div class="table-head" style="background:linear-gradient(90deg,#60a5fa,#a78bfa)">
      🔑 전·월세 전체 내역 ({total_r}건)
    </div>
    <table>
      <tr><th>거래일</th><th>유형</th><th>면적</th><th>층</th><th>가격</th></tr>
      {rent_rows_html if rent_rows_html else "<tr><td colspan='5' style='text-align:center;padding:24px;color:#aaa'>데이터 없음 🐻</td></tr>"}
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

Chart.defaults.font.family = "'Noto Sans KR', sans-serif";
Chart.defaults.color = 'rgba(255,255,255,0.45)';
Chart.defaults.borderColor = '#1E3A6E';

const tradeData  = {ds_json(t_months, t_ds)};
const jeonseData = {ds_json(j_months, j_ds)};

function makeChart(id, data) {{
  const ctx = document.getElementById(id);
  if (!ctx || !data.labels.length) return;
  new Chart(ctx, {{
    type: 'line',
    data: data,
    options: {{
      responsive: true,
      interaction: {{ mode:'index', intersect:false }},
      plugins: {{
        legend: {{ labels: {{ color:'#9E8A92', font:{{size:11}}, padding:12 }} }},
        tooltip: {{
          backgroundColor:'#172444',
          titleColor:'#fff',
          bodyColor:'#60A5FA',
          borderColor:'#1E3A6E',
          borderWidth:1,
          callbacks: {{
            label: c => c.dataset.label+': '+(c.raw ? c.raw.toLocaleString()+'만원' : '-')
          }}
        }}
      }},
      scales: {{
        x: {{ ticks:{{ color:'rgba(255,255,255,.35)', maxTicksLimit:8, font:{{size:10}} }}, grid:{{color:'#1E3A6E'}} }},
        y: {{
          ticks: {{
            color:'rgba(255,255,255,.35)',
            font:{{size:10}},
            callback: v => v>=10000 ? (v/10000).toFixed(1)+'억' : v.toLocaleString()+'만'
          }},
          grid:{{color:'#1E3A6E'}}
        }}
      }}
    }}
  }});
}}

makeChart('tradeChart',  tradeData);
makeChart('jeonseChart', jeonseData);
</script>
</body>
</html>"""

# ── GitHub 업로드 ─────────────────────────────────────────────────────────────
def push_to_github():
    OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(["git","add","kcc_tracker.html","track_kcc.py"], cwd=OUTPUT_DIR, check=True)
        r = subprocess.run(["git","diff","--staged","--quiet"], cwd=OUTPUT_DIR)
        if r.returncode == 0: print("변경 없음"); return
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
    if not MOLIT_API_KEY:
        print("❌ MOLIT_API_KEY 환경변수가 없습니다.")
        print("   export MOLIT_API_KEY='발급받은키'  를 먼저 실행하세요.")
        return

    print(f"🔑 키 확인: {MOLIT_API_KEY[:8]}...{MOLIT_API_KEY[-4:]}")
    print(f"📡 국토교통부 실거래 수집 중 (최근 {MONTHS_BACK}개월)...")
    trades, rents = collect_all()
    print(f"\n✅ 수집 완료: 매매 {len(trades)}건, 전월세 {len(rents)}건")

    html = generate_html(trades, rents)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n🎀 리포트 생성: {OUTPUT}")

    push_to_github()
    IS_CI = os.environ.get("CI") == "true"
    if not IS_CI:
        subprocess.run(["open", OUTPUT])

if __name__ == "__main__":
    main()
