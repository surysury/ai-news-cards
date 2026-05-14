#!/usr/bin/env python3
"""부동산 시세 추적기 — KCC스위첸2차 · 북한산푸르지오 · 래미안베라힐즈"""

import os, json, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET, subprocess
from datetime import datetime, timedelta
from collections import defaultdict

# ── 설정 ─────────────────────────────────────────────────────────────────────
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")
MONTHS_BACK   = 24
AREA_TOL      = 6
OUTPUT        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kcc_tracker.html")

# 추적 아파트 정의
APTS = [
    {
        "id":       "kcc",
        "name":     "KCC스위첸2차",
        "filter":   "KCC",
        "lawd":     "41570",   # 경기 김포시
        "areas":    [59, 74, 84],
        "tab_icon": "🏠",
        "mode":     "both",    # 매매 + 전월세
    },
    {
        "id":       "bukhan",
        "name":     "북한산푸르지오",
        "filter":   "북한산푸르지오",
        "lawd":     "11380",   # 서울 은평구
        "areas":    [59, 74, 84, 114],
        "tab_icon": "🏔",
        "mode":     "rent",    # 전월세만
    },
    {
        "id":       "raemian",
        "name":     "래미안베라힐즈",
        "filter":   "래미안베라힐즈",
        "lawd":     "11380",   # 서울 은평구
        "areas":    [59, 74, 84, 114],
        "tab_icon": "🌿",
        "mode":     "rent",    # 전월세만
    },
]

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
RENT_URL  = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# ── API 호출 ─────────────────────────────────────────────────────────────────
def fetch(base_url, lawd, ym):
    query = (f"serviceKey={MOLIT_API_KEY}&"
             + urllib.parse.urlencode({"LAWD_CD": lawd, "DEAL_YMD": ym,
                                       "numOfRows": "1000", "pageNo": "1"}))
    url = f"{base_url}?{query}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"    오류: {e}")
        return ""

def parse_trade(xml_str, name_filter):
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            if name_filter not in (item.findtext("aptNm") or ""): continue
            try: area = float(item.findtext("excluUseAr") or 0)
            except: area = 0
            try: price = int((item.findtext("dealAmount") or "0").replace(",","").strip())
            except: price = 0
            y = item.findtext("dealYear") or ""
            m = (item.findtext("dealMonth") or "").zfill(2)
            d = (item.findtext("dealDay") or "").zfill(2)
            rows.append({"type":"매매","area":area,"price":price,
                         "date":f"{y}-{m}-{d}","floor":item.findtext("floor") or ""})
    except: pass
    return rows

def parse_rent(xml_str, name_filter):
    rows = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter("item"):
            if name_filter not in (item.findtext("aptNm") or ""): continue
            try: area = float(item.findtext("excluUseAr") or 0)
            except: area = 0
            try: deposit = int((item.findtext("deposit") or "0").replace(",","").strip())
            except: deposit = 0
            try: monthly = int((item.findtext("monthlyRent") or "0").replace(",","").strip())
            except: monthly = 0
            y = item.findtext("dealYear") or ""
            m = (item.findtext("dealMonth") or "").zfill(2)
            d = (item.findtext("dealDay") or "").zfill(2)
            rows.append({"type":"월세" if monthly>0 else "전세","area":area,
                         "price":deposit,"monthly":monthly,
                         "date":f"{y}-{m}-{d}","floor":item.findtext("floor") or ""})
    except: pass
    return rows

def collect(apt):
    trades, rents = [], []
    now = datetime.now()
    for i in range(MONTHS_BACK):
        d  = now.replace(day=1) - timedelta(days=i*28)
        ym = d.strftime("%Y%m")
        if apt["mode"] in ("both", "trade"):
            trades.extend(parse_trade(fetch(TRADE_URL, apt["lawd"], ym), apt["filter"]))
        if apt["mode"] in ("both", "rent"):
            rents.extend(parse_rent(fetch(RENT_URL, apt["lawd"], ym), apt["filter"]))
    return (sorted(trades, key=lambda x: x["date"]),
            sorted(rents,  key=lambda x: x["date"]))

# ── 차트 ─────────────────────────────────────────────────────────────────────
CHART_COLORS = ["#60A5FA","#34D399","#F59E0B","#A78BFA","#FB923C","#F472B6"]

def group_by_month(rows, types, target_areas, tol):
    buckets = defaultdict(list)
    for r in rows:
        if r["type"] not in types: continue
        ym = r["date"][:7]
        matched = next((ta for ta in target_areas if abs(r["area"]-ta)<=tol), None)
        if matched is None: continue
        buckets[(ym, matched)].append(r["price"])
    result = {}
    for (ym, area), prices in buckets.items():
        result.setdefault(area, {})[ym] = round(sum(prices)/len(prices))
    return result

def make_chart_json(grouped):
    all_months = sorted({ym for v in grouped.values() for ym in v})
    datasets = []
    for i, (area, monthly) in enumerate(sorted(grouped.items())):
        c = CHART_COLORS[i % len(CHART_COLORS)]
        datasets.append({
            "label": f"{area}㎡(약{round(area/3.3058)}평)",
            "data":  [monthly.get(ym) for ym in all_months],
            "borderColor": c, "backgroundColor": c+"22",
            "tension": 0.4, "spanGaps": True,
            "pointBackgroundColor": c, "pointRadius": 4,
        })
    return json.dumps({"labels": all_months, "datasets": datasets}, ensure_ascii=False)

# ── HTML 조각 ─────────────────────────────────────────────────────────────────
def stat_card(emoji, val, lbl, color="#60A5FA"):
    return f"""<div class="stat">
      <div class="stat-emoji">{emoji}</div>
      <div class="stat-val" style="color:{color}">{val}</div>
      <div class="stat-lbl">{lbl}</div>
    </div>"""

def chart_block(chart_id, title, json_str):
    if not json_str or json.loads(json_str)["labels"] == []:
        return ""
    return f"""<div class="chart-card">
      <div class="chart-title">{title}</div>
      <canvas id="{chart_id}" height="210"></canvas>
    </div>
    <script>makeChart('{chart_id}', {json_str});</script>"""

def table_rows_trade(rows, limit=30):
    out = []
    for r in list(reversed(rows))[:limit]:
        out.append(f"""<tr>
          <td>{r['date']}</td><td>{r['area']:.0f}㎡</td><td>{r['floor']}층</td>
          <td class="pc">{r['price']:,}<span class="unit">만원</span></td>
        </tr>""")
    return "".join(out)

def table_rows_rent(rows, limit=30):
    out = []
    for r in list(reversed(rows))[:limit]:
        if r["type"] == "전세":
            p, cls = f"{r['price']:,}만원", "pj"
        else:
            p, cls = f"{r['price']:,}/{r.get('monthly',0):,}", "pw"
        out.append(f"""<tr>
          <td>{r['date']}</td><td class="{cls}">{r['type']}</td>
          <td>{r['area']:.0f}㎡</td><td>{r['floor']}층</td>
          <td class="pc">{p}<span class="unit">만원</span></td>
        </tr>""")
    return "".join(out)

def apt_pane(apt_id, apt_name, trades, rents, target_areas, mode):
    total_t = len(trades)
    total_j = sum(1 for r in rents if r["type"]=="전세")
    total_w = sum(1 for r in rents if r["type"]=="월세")

    cutoff = (datetime.now()-timedelta(days=90)).strftime("%Y-%m-%d")
    r3 = [r for r in trades if r["date"] >= cutoff]
    avg3 = f"{round(sum(r['price'] for r in r3)/len(r3)):,}만원" if r3 else "—"

    t84 = [r for r in trades if abs(r["area"]-84) <= AREA_TOL]
    hi84 = f"{max(r['price'] for r in t84):,}만원" if t84 else "—"
    lo84 = f"{min(r['price'] for r in t84):,}만원" if t84 else "—"

    # 전세 최근 평균
    j3 = [r for r in rents if r["type"]=="전세" and r["date"] >= cutoff]
    avgj = f"{round(sum(r['price'] for r in j3)/len(j3)):,}만원" if j3 else "—"

    # 차트
    t_json  = make_chart_json(group_by_month(trades, ("매매",),  target_areas, AREA_TOL))
    j_json  = make_chart_json(group_by_month(rents,  ("전세",),  target_areas, AREA_TOL))
    w_json  = make_chart_json(group_by_month(rents,  ("월세",),  target_areas, AREA_TOL))

    # 스탯
    stats_html = '<div class="stats">'
    if mode == "both":
        stats_html += stat_card("🏡", f"{total_t}건", f"매매거래({MONTHS_BACK}개월)")
        stats_html += stat_card("💰", avg3, "최근3개월 평균매매가")
        stats_html += stat_card("📈", hi84, "84㎡ 최고가")
        stats_html += stat_card("📉", lo84, "84㎡ 최저가")
    stats_html += stat_card("🔑", f"{total_j}건", f"전세거래({MONTHS_BACK}개월)", "#93C5FD")
    stats_html += stat_card("🏠", f"{total_w}건", f"월세거래({MONTHS_BACK}개월)", "#34D399")
    if mode == "rent":
        stats_html += stat_card("💵", avgj, "최근3개월 전세평균", "#93C5FD")
    stats_html += '</div>'

    # 차트 블록
    charts = ""
    if mode == "both":
        charts += chart_block(f"{apt_id}_trade", "📈 매매가 추이 (평형별)", t_json)
    charts += chart_block(f"{apt_id}_jeonse", "🔑 전세 보증금 추이 (평형별)", j_json)
    charts += chart_block(f"{apt_id}_wolse",  "🏠 월세 보증금 추이 (평형별)", w_json)

    # 테이블
    tables = ""
    if mode == "both" and trades:
        tables += f"""<div class="sec-title">최근 매매 거래</div>
        <div class="tbl-card">
          <table><tr><th>거래일</th><th>면적</th><th>층</th><th>거래가</th></tr>
          {table_rows_trade(trades)}</table>
        </div>"""
    if rents:
        tables += f"""<div class="sec-title">최근 전·월세 거래</div>
        <div class="tbl-card">
          <table><tr><th>거래일</th><th>유형</th><th>면적</th><th>층</th><th>가격</th></tr>
          {table_rows_rent(rents)}</table>
        </div>"""

    empty = "" if (trades or rents) else '<div class="empty"><div class="e-emoji">🏗</div><p>데이터를 불러오는 중...</p></div>'

    return f'<div class="pane" id="pane-{apt_id}">{stats_html}{charts}{tables}{empty}</div>'

# ── 전체 HTML ─────────────────────────────────────────────────────────────────
def generate_html(apt_data):
    now_str  = datetime.now().strftime("%Y.%m.%d %H:%M")

    # 탭 버튼
    tab_btns = ""
    for i, (apt, _, _) in enumerate(apt_data):
        active = "active" if i == 0 else ""
        tab_btns += f'<button class="tab {active}" onclick="show(\'{apt["id"]}\',this)">{apt["tab_icon"]} {apt["name"]}</button>'

    # 탭 패널 (첫 번째만 active)
    panes = ""
    for i, (apt, trades, rents) in enumerate(apt_data):
        html = apt_pane(apt["id"], apt["name"], trades, rents, apt["areas"], apt["mode"])
        if i == 0:
            html = html.replace('class="pane"', 'class="pane active"', 1)
        panes += html

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover,maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>부동산 시세 추적기</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
:root{{
  --bg:    #0F1E3C;
  --card:  #172444;
  --card2: #1E2F54;
  --border:#1E3A6E;
  --blue:  #2563EB;
  --acc:   #60A5FA;
  --w:     #FFFFFF;
  --mu:    rgba(255,255,255,.42);
  --max:   480px;
}}
html,body{{
  background:var(--bg);color:var(--w);
  font-family:'Noto Sans KR',sans-serif;
  min-height:100vh;
  /* 모바일 중앙 고정 */
  max-width:var(--max);
  margin:0 auto;
}}

/* 헤더 */
.header{{
  background:linear-gradient(135deg,#1D4ED8,#1E40AF);
  padding:env(safe-area-inset-top,0px) 20px 20px;
  padding-top:calc(env(safe-area-inset-top,0px) + 20px);
  position:relative;overflow:hidden;
}}
.header::after{{
  content:'';position:absolute;inset:0;
  background:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.04'%3E%3Ccircle cx='30' cy='30' r='20'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
}}
.header-inner{{position:relative;z-index:1;}}
.h-badge{{display:inline-flex;align-items:center;gap:5px;
  background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.2);
  color:rgba(255,255,255,.9);font-size:10px;font-weight:700;
  padding:3px 12px;border-radius:20px;letter-spacing:.08em;margin-bottom:10px;}}
.h-title{{font-size:20px;font-weight:900;line-height:1.35;}}
.h-title em{{font-style:normal;color:#93C5FD;}}
.h-sub{{font-size:11px;color:rgba(255,255,255,.5);margin-top:8px;}}

/* 탭 */
.tabs-wrap{{
  position:sticky;top:0;z-index:50;
  background:var(--bg);border-bottom:1px solid var(--border);
  overflow-x:auto;scrollbar-width:none;
}}
.tabs-wrap::-webkit-scrollbar{{display:none;}}
.tabs{{display:flex;min-width:max-content;padding:0 4px;}}
.tab{{
  flex-shrink:0;
  padding:12px 14px;font-size:11px;font-weight:700;
  color:var(--mu);background:none;border:none;
  border-bottom:2px solid transparent;
  cursor:pointer;white-space:nowrap;transition:.2s;
}}
.tab.active{{color:var(--acc);border-bottom-color:var(--acc);}}

/* 패널 */
.pane{{display:none;padding:16px 16px 32px;}}
.pane.active{{display:block;}}

/* 스탯 */
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px;}}
.stat{{background:var(--card);border-radius:14px;padding:14px 12px;
  border:1px solid var(--border);text-align:center;}}
.stat-emoji{{font-size:22px;margin-bottom:5px;}}
.stat-val{{font-size:18px;font-weight:900;line-height:1;color:var(--acc);}}
.stat-lbl{{font-size:10px;color:var(--mu);margin-top:4px;}}

/* 차트 */
.chart-card{{background:var(--card);border-radius:16px;padding:16px;
  border:1px solid var(--border);margin-bottom:14px;}}
.chart-title{{font-size:12px;font-weight:700;color:var(--w);margin-bottom:14px;
  display:flex;align-items:center;gap:7px;}}
.chart-title::before{{content:'';width:3px;height:14px;
  background:var(--acc);border-radius:2px;flex-shrink:0;}}

/* 섹션 타이틀 */
.sec-title{{font-size:11px;font-weight:700;color:var(--acc);
  letter-spacing:.08em;margin:18px 0 10px;text-transform:uppercase;}}

/* 테이블 */
.tbl-card{{background:var(--card);border-radius:16px;overflow:hidden;
  border:1px solid var(--border);margin-bottom:14px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:var(--card2);color:var(--mu);font-weight:700;
  padding:9px 10px;text-align:left;font-size:10px;letter-spacing:.04em;}}
td{{padding:9px 10px;border-bottom:1px solid var(--border);
  color:rgba(255,255,255,.8);font-size:12px;}}
tr:last-child td{{border-bottom:none;}}
tr:hover td{{background:var(--card2);}}
.pc{{font-weight:700;color:var(--acc);}}
.pj{{color:#93C5FD;font-weight:700;}}
.pw{{color:#34D399;font-weight:700;}}
.unit{{font-size:9px;font-weight:400;color:var(--mu);margin-left:1px;}}

/* 빈 상태 */
.empty{{text-align:center;padding:40px 16px;color:var(--mu);}}
.e-emoji{{font-size:42px;margin-bottom:10px;}}
.empty p{{font-size:12px;}}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div class="h-badge">📍 부동산 시세 추적기</div>
    <div class="h-title">실거래가 <em>대시보드</em></div>
    <div class="h-sub">국토교통부 공식 데이터 · {now_str} 업데이트</div>
  </div>
</div>

<div class="tabs-wrap">
  <div class="tabs">{tab_btns}</div>
</div>

{panes}

<script>
Chart.defaults.font.family="'Noto Sans KR',sans-serif";
Chart.defaults.color="rgba(255,255,255,0.4)";
Chart.defaults.borderColor="#1E3A6E";

function show(id,btn){{
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('pane-'+id).classList.add('active');
  btn.classList.add('active');
}}

function makeChart(id,data){{
  const ctx=document.getElementById(id);
  if(!ctx||!data.labels.length)return;
  new Chart(ctx,{{
    type:'line',data:data,
    options:{{
      responsive:true,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{
        legend:{{labels:{{color:'rgba(255,255,255,.5)',font:{{size:10}},padding:10}}}},
        tooltip:{{
          backgroundColor:'#172444',titleColor:'#fff',
          bodyColor:'#60A5FA',borderColor:'#1E3A6E',borderWidth:1,
          callbacks:{{label:c=>c.dataset.label+': '+(c.raw?c.raw.toLocaleString()+'만원':'-')}}
        }}
      }},
      scales:{{
        x:{{ticks:{{color:'rgba(255,255,255,.3)',maxTicksLimit:8,font:{{size:9}}}},
            grid:{{color:'#1E3A6E'}}}},
        y:{{
          ticks:{{color:'rgba(255,255,255,.3)',font:{{size:9}},
            callback:v=>v>=10000?(v/10000).toFixed(1)+'억':v.toLocaleString()+'만'}},
          grid:{{color:'#1E3A6E'}}
        }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""

# ── 메인 ─────────────────────────────────────────────────────────────────────
def push_to_github():
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(["git","add","kcc_tracker.html","track_kcc.py"], cwd=d, check=True)
        if subprocess.run(["git","diff","--staged","--quiet"], cwd=d).returncode == 0:
            print("변경 없음"); return
        subprocess.run(["git","commit","-m",f"시세 업데이트 {datetime.now().strftime('%Y-%m-%d')}"], cwd=d, check=True)
        subprocess.run(["git","fetch","origin"], cwd=d, check=True)
        subprocess.run(["git","rebase","origin/main"], cwd=d, check=True)
        subprocess.run(["git","push"], cwd=d, check=True)
        print("👉 https://surysury.github.io/ai-news-cards/kcc_tracker.html")
    except subprocess.CalledProcessError as e:
        print(f"[업로드 실패] {e}")

def main():
    if not MOLIT_API_KEY:
        print("❌ export MOLIT_API_KEY='키' 를 먼저 실행하세요."); return

    print(f"🔑 키 확인: {MOLIT_API_KEY[:8]}...{MOLIT_API_KEY[-4:]}\n")
    apt_data = []
    for apt in APTS:
        print(f"📡 [{apt['name']}] 수집 중...")
        trades, rents = collect(apt)
        print(f"   ✅ 매매 {len(trades)}건 / 전월세 {len(rents)}건\n")
        apt_data.append((apt, trades, rents))

    html = generate_html(apt_data)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🎀 리포트 생성 완료!")

    push_to_github()
    if os.environ.get("CI") != "true":
        subprocess.run(["open", OUTPUT])

if __name__ == "__main__":
    main()
