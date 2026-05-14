#!/usr/bin/env python3
"""부동산 시세 추적기 — KCC스위첸2차 · 북한산푸르지오 · 래미안베라힐즈"""

import os, json, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET, subprocess
from datetime import datetime, timedelta, date
from collections import defaultdict

# ── 설정 ─────────────────────────────────────────────────────────────────────
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")
START_YM      = "202301"   # 2023년 1월부터
AREA_TOL      = 6
OUTPUT        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kcc_tracker.html")

APTS = [
    {"id":"kcc",     "name":"KCC스위첸2차",   "filter":"KCC",          "lawd":"41570","areas":[59,74,84],"tab_icon":"🏠","mode":"both"},
    {"id":"bukhan",  "name":"북한산푸르지오",  "filter":"북한산푸르지오","lawd":"11380","areas":[59,74,84,114],"tab_icon":"🏔","mode":"rent"},
    {"id":"raemian", "name":"래미안베라힐즈",  "filter":"래미안베라힐즈","lawd":"11380","areas":[59,74,84,114],"tab_icon":"🌿","mode":"rent"},
]

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
RENT_URL  = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# ── 조회 월 목록 ──────────────────────────────────────────────────────────────
def month_list():
    start = datetime.strptime(START_YM, "%Y%m")
    now   = datetime.now().replace(day=1)
    months = []
    cur = start
    while cur <= now:
        months.append(cur.strftime("%Y%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year+1, month=1)
        else:
            cur = cur.replace(month=cur.month+1)
    return months

# ── API 호출 ─────────────────────────────────────────────────────────────────
def fetch(base_url, lawd, ym):
    query = (f"serviceKey={MOLIT_API_KEY}&"
             + urllib.parse.urlencode({"LAWD_CD":lawd,"DEAL_YMD":ym,"numOfRows":"1000","pageNo":"1"}))
    try:
        req = urllib.request.Request(f"{base_url}?{query}", headers={"User-Agent":"Mozilla/5.0"})
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

def collect(apt, months):
    trades, rents = [], []
    for ym in months:
        print(f"  {ym} ...", end=" ", flush=True)
        t = parse_trade(fetch(TRADE_URL, apt["lawd"], ym), apt["filter"]) if apt["mode"] in ("both","trade") else []
        r = parse_rent(fetch(RENT_URL,  apt["lawd"], ym), apt["filter"]) if apt["mode"] in ("both","rent")  else []
        trades.extend(t); rents.extend(r)
        print(f"매매{len(t)} 전월세{len(r)}")
    return sorted(trades,key=lambda x:x["date"]), sorted(rents,key=lambda x:x["date"])

# ── 차트 ─────────────────────────────────────────────────────────────────────
CHART_COLORS = ["#3B82F6","#10B981","#F59E0B","#8B5CF6","#EF4444","#EC4899"]

def group_by_month(rows, types, target_areas):
    buckets = defaultdict(list)
    for r in rows:
        if r["type"] not in types: continue
        ym = r["date"][:7]
        matched = next((ta for ta in target_areas if abs(r["area"]-ta)<=AREA_TOL), None)
        if matched is None: continue
        buckets[(ym, matched)].append(r["price"])
    result = {}
    for (ym,area),prices in buckets.items():
        result.setdefault(area,{})[ym] = round(sum(prices)/len(prices))
    return result

def chart_json(grouped):
    all_months = sorted({ym for v in grouped.values() for ym in v})
    datasets = []
    for i,(area,monthly) in enumerate(sorted(grouped.items())):
        c = CHART_COLORS[i % len(CHART_COLORS)]
        datasets.append({
            "label": f"{area}㎡(약{round(area/3.3058)}평)",
            "data":  [monthly.get(ym) for ym in all_months],
            "borderColor":c,"backgroundColor":c+"18",
            "tension":0.4,"spanGaps":True,
            "pointBackgroundColor":c,"pointRadius":3,"pointHoverRadius":5,
        })
    return json.dumps({"labels":all_months,"datasets":datasets},ensure_ascii=False)

# ── HTML 구성 ─────────────────────────────────────────────────────────────────
def stat_html(emoji, val, lbl, color="#3B82F6"):
    return f"""<div class="stat">
      <div class="s-emoji">{emoji}</div>
      <div class="s-val" style="color:{color}">{val}</div>
      <div class="s-lbl">{lbl}</div>
    </div>"""

def trade_table(rows):
    if not rows: return ""
    rows_html = "".join(f"""<tr>
      <td>{r['date']}</td><td>{r['area']:.0f}㎡</td>
      <td>{r['floor']}층</td><td class="pc">{r['price']:,}<span class="u">만원</span></td>
    </tr>""" for r in reversed(rows))
    return f"""<div class="sec-ttl">최근 매매 거래</div>
    <div class="tbl-wrap"><table>
      <tr><th>거래일</th><th>면적</th><th>층</th><th>거래가</th></tr>
      {rows_html}
    </table></div>"""

def rent_table(rows, title="최근 전·월세 거래"):
    if not rows: return ""
    def rent_price(r):
        if r['type'] == '전세':
            return f"{r['price']:,}만원"
        return f"{r['price']:,}/{r.get('monthly',0):,}만원"
    def rent_cls(r):
        return "tj" if r['type'] == '전세' else "tw"
    rows_html = "".join(f"""<tr>
      <td>{r['date']}</td>
      <td class="{rent_cls(r)}">{r['type']}</td>
      <td>{r['area']:.0f}㎡</td><td>{r['floor']}층</td>
      <td class="pc">{rent_price(r)}</td>
    </tr>""" for r in reversed(rows))
    return f"""<div class="sec-ttl">{title}</div>
    <div class="tbl-wrap"><table>
      <tr><th>거래일</th><th>유형</th><th>면적</th><th>층</th><th>가격</th></tr>
      {rows_html}
    </table></div>"""

def apt_pane(apt, trades, rents, chart_registry):
    aid = apt["id"]
    areas = apt["areas"]
    mode  = apt["mode"]

    cutoff = (datetime.now()-timedelta(days=90)).strftime("%Y-%m-%d")
    r3     = [r for r in trades if r["date"] >= cutoff]
    avg3   = f"{round(sum(r['price'] for r in r3)/len(r3)):,}만원" if r3 else "—"
    t84    = [r for r in trades if abs(r["area"]-84)<=AREA_TOL]
    hi84   = f"{max(r['price'] for r in t84):,}만원" if t84 else "—"
    lo84   = f"{min(r['price'] for r in t84):,}만원" if t84 else "—"
    j3     = [r for r in rents if r["type"]=="전세" and r["date"] >= cutoff]
    avgj   = f"{round(sum(r['price'] for r in j3)/len(j3)):,}만원" if j3 else "—"
    total_j = sum(1 for r in rents if r["type"]=="전세")
    total_w = sum(1 for r in rents if r["type"]=="월세")

    # 스탯
    stats = '<div class="stats">'
    if mode == "both":
        stats += stat_html("🏡", f"{len(trades)}건", f"매매거래(2023~)")
        stats += stat_html("💰", avg3, "최근3개월 평균매매가")
        stats += stat_html("📈", hi84, "84㎡ 최고가")
        stats += stat_html("📉", lo84, "84㎡ 최저가")
    stats += stat_html("🔑", f"{total_j}건", "전세거래(2023~)", "#6366F1")
    stats += stat_html("🏠", f"{total_w}건", "월세거래(2023~)", "#10B981")
    if mode == "rent":
        stats += stat_html("💵", avgj, "최근3개월 전세평균", "#6366F1")
    stats += '</div>'

    # 차트 (캔버스만 배치, 데이터는 registry에 모음)
    charts = ""
    if mode == "both":
        cid = f"{aid}_trade"
        cj  = chart_json(group_by_month(trades,("매매",),areas))
        chart_registry[cid] = cj
        charts += f'<div class="chart-card"><div class="chart-ttl">📈 매매가 추이 (평형별)</div><canvas id="{cid}" height="210"></canvas></div>'

    for typ, label, cid_sfx in [("전세","🔑 전세 보증금 추이","jeonse"),("월세","🏠 월세 보증금 추이","wolse")]:
        sub = [r for r in rents if r["type"]==typ]
        if sub:
            cid = f"{aid}_{cid_sfx}"
            cj  = chart_json(group_by_month(sub,(typ,),areas))
            chart_registry[cid] = cj
            charts += f'<div class="chart-card"><div class="chart-ttl">{label} (평형별)</div><canvas id="{cid}" height="210"></canvas></div>'

    # 테이블
    tables = trade_table(trades) if mode == "both" else ""
    tables += rent_table(rents, "전·월세 전체 내역 (2023~)")

    empty = "" if (trades or rents) else '<div class="empty"><div>🏗</div><p>데이터 없음</p></div>'
    return f'<div class="pane" id="pane-{aid}">{stats}{charts}{tables}{empty}</div>'

# ── 전체 HTML ─────────────────────────────────────────────────────────────────
def generate_html(apt_data):
    now_str = datetime.now().strftime("%Y.%m.%d %H:%M")
    chart_registry = {}  # cid → json_str

    tab_btns = ""
    panes    = ""
    for i,(apt,trades,rents) in enumerate(apt_data):
        active = " active" if i==0 else ""
        tab_btns += f'<button class="tab{active}" onclick="show(\'{apt["id"]}\',this)">{apt["tab_icon"]} {apt["name"]}</button>'
        pane_html = apt_pane(apt, trades, rents, chart_registry)
        if i==0: pane_html = pane_html.replace('class="pane"','class="pane active"',1)
        panes += pane_html

    # 모든 차트 초기화 스크립트 (함수 정의 이후에 한 번에 실행)
    chart_inits = "\n".join(
        f"  makeChart('{cid}', {cj});" for cid,cj in chart_registry.items()
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover,maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>부동산 시세 추적기</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=Noto+Serif+KR:wght@600;700&display=swap');
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
:root{{
  --bg:    #F7F5F0;
  --white: #FFFFFF;
  --card:  #FFFFFF;
  --bdr:   #E8E4DC;
  --sage:  #5C7A5A;
  --sage2: #7A9C78;
  --sage3: #EBF0E8;
  --sage4: #F3F7F1;
  --dark:  #2C2C2C;
  --mid:   #6B6B6B;
  --muted: #A8A8A8;
  --rust:  #C17A5C;
  --max:   480px;
}}
html,body{{
  background:var(--bg);color:var(--dark);
  font-family:'Noto Sans KR',sans-serif;
  min-height:100vh;max-width:var(--max);margin:0 auto;
}}

/* ── 헤더 ── */
.header{{
  background:var(--white);
  padding:calc(env(safe-area-inset-top,0px) + 18px) 20px 0;
  border-bottom:1px solid var(--bdr);
}}
.h-top{{
  display:flex;justify-content:space-between;
  align-items:center;padding-bottom:14px;
}}
.h-logo{{
  font-family:'Noto Serif KR',serif;
  font-size:15px;font-weight:700;color:var(--sage);
  letter-spacing:.04em;
}}
.h-date{{font-size:10px;color:var(--muted);}}
.h-hero{{
  background:var(--sage3);border-radius:16px;
  padding:22px 20px;margin-bottom:16px;
  position:relative;overflow:hidden;
}}
.h-hero::after{{
  content:'🏠';position:absolute;
  right:16px;bottom:10px;font-size:52px;opacity:.15;
}}
.h-kicker{{
  font-size:10px;font-weight:700;color:var(--sage);
  letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px;
}}
.h-title{{
  font-family:'Noto Serif KR',serif;
  font-size:22px;font-weight:700;line-height:1.35;color:var(--dark);
}}
.h-title em{{font-style:normal;color:var(--sage);}}
.h-sub{{font-size:11px;color:var(--mid);margin-top:8px;line-height:1.5;}}

/* ── 탭 ── */
.tabs-wrap{{
  position:sticky;top:0;z-index:50;
  background:var(--white);border-bottom:1px solid var(--bdr);
  overflow-x:auto;scrollbar-width:none;
}}
.tabs-wrap::-webkit-scrollbar{{display:none;}}
.tabs{{display:flex;min-width:max-content;padding:0 4px;}}
.tab{{
  flex-shrink:0;padding:13px 15px;
  font-size:12px;font-weight:700;color:var(--muted);
  background:none;border:none;
  border-bottom:2px solid transparent;margin-bottom:-1px;
  cursor:pointer;white-space:nowrap;transition:.15s;
}}
.tab.active{{color:var(--sage);border-bottom-color:var(--sage);}}

/* ── 패널 ── */
.pane{{display:none;padding:16px 16px 48px;}}
.pane.active{{display:block;}}

/* ── 섹션 구분선 ── */
.sec-label{{
  display:flex;align-items:center;gap:10px;
  font-size:10px;font-weight:700;color:var(--muted);
  letter-spacing:.1em;text-transform:uppercase;
  margin:22px 0 12px;
}}
.sec-label::before,.sec-label::after{{
  content:'';flex:1;height:1px;background:var(--bdr);
}}

/* ── 스탯 카드 ── */
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:4px;}}
.stat{{
  background:var(--white);border-radius:14px;
  padding:14px 12px;border:1px solid var(--bdr);text-align:center;
}}
.s-emoji{{font-size:18px;margin-bottom:6px;}}
.s-val{{font-size:17px;font-weight:900;line-height:1;color:var(--sage);}}
.s-lbl{{font-size:10px;color:var(--muted);margin-top:4px;font-weight:500;}}
.stat.accent{{background:var(--sage3);border-color:var(--sage2);}}
.stat.accent .s-val{{color:var(--sage);}}

/* ── 핵심 수치 (큰 카드) ── */
.key-card{{
  background:var(--sage);border-radius:16px;
  padding:18px 20px;margin-bottom:10px;color:#fff;
  display:flex;justify-content:space-between;align-items:center;
}}
.key-card .kc-lbl{{font-size:11px;opacity:.75;margin-bottom:4px;}}
.key-card .kc-val{{font-size:22px;font-weight:900;}}
.key-card .kc-sub{{font-size:10px;opacity:.6;margin-top:2px;}}
.key-card .kc-icon{{font-size:36px;opacity:.3;}}

/* ── 차트 ── */
.chart-card{{
  background:var(--white);border-radius:16px;
  padding:18px 16px;border:1px solid var(--bdr);margin-bottom:12px;
}}
.chart-ttl{{
  font-size:12px;font-weight:700;color:var(--dark);margin-bottom:14px;
  display:flex;align-items:center;gap:8px;
}}
.chart-ttl .ct-dot{{
  width:8px;height:8px;border-radius:50%;
  background:var(--sage);flex-shrink:0;
}}

/* ── 테이블 ── */
.tbl-wrap{{
  background:var(--white);border-radius:16px;
  overflow:hidden;border:1px solid var(--bdr);margin-bottom:12px;
}}
.tbl-head{{
  background:var(--sage4);padding:12px 14px;
  font-size:11px;font-weight:700;color:var(--sage);
  letter-spacing:.04em;border-bottom:1px solid var(--bdr);
}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{
  background:var(--sage4);color:var(--muted);font-weight:700;
  padding:8px 11px;text-align:left;font-size:10px;letter-spacing:.04em;
}}
td{{padding:9px 11px;border-bottom:1px solid var(--bdr);color:var(--dark);}}
tr:last-child td{{border-bottom:none;}}
tr:hover td{{background:var(--sage4);transition:.1s;}}
.pc{{font-weight:700;color:var(--sage);}}
.tj{{
  font-size:10px;font-weight:700;color:var(--sage);
  background:var(--sage3);padding:2px 7px;border-radius:10px;
}}
.tw{{
  font-size:10px;font-weight:700;color:var(--rust);
  background:#FDF0EB;padding:2px 7px;border-radius:10px;
}}
.u{{font-size:9px;font-weight:400;color:var(--muted);margin-left:1px;}}

/* ── 빈 상태 ── */
.empty{{text-align:center;padding:48px 16px;color:var(--muted);font-size:13px;}}
</style>
</head>
<body>

<div class="header">
  <div class="h-top">
    <div class="h-logo">Real Estate Tracker</div>
    <div class="h-date">{now_str} 업데이트</div>
  </div>
  <div class="h-hero">
    <div class="h-kicker">국토교통부 공식 실거래가</div>
    <div class="h-title">아파트 시세<br><em>실거래 대시보드</em></div>
    <div class="h-sub">2023년 1월 ~ 현재 · 매주 월요일 자동 업데이트</div>
  </div>
</div>

<div class="tabs-wrap">
  <div class="tabs">{tab_btns}</div>
</div>

{panes}

<script>
Chart.defaults.font.family="'Noto Sans KR',sans-serif";
Chart.defaults.color="#A8A8A8";
Chart.defaults.borderColor="#EBF0E8";

function show(id,btn){{
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('pane-'+id).classList.add('active');
  btn.classList.add('active');
}}

function makeChart(id,data){{
  const ctx=document.getElementById(id);
  if(!ctx||!data.labels||!data.labels.length)return;
  new Chart(ctx,{{
    type:'line',data,
    options:{{
      responsive:true,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{
        legend:{{labels:{{color:'#6B6B6B',font:{{size:10}},padding:14,usePointStyle:true,pointStyleWidth:8}}}},
        tooltip:{{
          backgroundColor:'#2C2C2C',titleColor:'#fff',
          bodyColor:'#A8D8A8',borderColor:'#5C7A5A',borderWidth:1,
          padding:10,
          callbacks:{{label:c=>c.dataset.label+': '+(c.raw?c.raw.toLocaleString()+'만원':'-')}}
        }}
      }},
      scales:{{
        x:{{ticks:{{color:'#A8A8A8',maxTicksLimit:8,font:{{size:9}}}},grid:{{color:'#F3F7F1'}}}},
        y:{{
          ticks:{{color:'#A8A8A8',font:{{size:9}},
            callback:v=>v>=10000?(v/10000).toFixed(1)+'억':v.toLocaleString()+'만'}},
          grid:{{color:'#F3F7F1'}}
        }}
      }}
    }}
  }});
}}

window.addEventListener('DOMContentLoaded', () => {{
{chart_inits}
}});
</script>
</body>
</html>"""

# ── GitHub 업로드 ─────────────────────────────────────────────────────────────
def push_to_github():
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(["git","add","kcc_tracker.html","track_kcc.py"],cwd=d,check=True)
        if subprocess.run(["git","diff","--staged","--quiet"],cwd=d).returncode==0:
            print("변경없음"); return
        subprocess.run(["git","commit","-m",f"시세 업데이트 {datetime.now().strftime('%Y-%m-%d')}"],cwd=d,check=True)
        subprocess.run(["git","fetch","origin"],cwd=d,check=True)
        subprocess.run(["git","rebase","origin/main"],cwd=d,check=True)
        subprocess.run(["git","push"],cwd=d,check=True)
        print("👉 https://surysury.github.io/ai-news-cards/kcc_tracker.html")
    except subprocess.CalledProcessError as e:
        print(f"[업로드 실패] {e}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    if not MOLIT_API_KEY:
        print("❌ export MOLIT_API_KEY='키' 를 먼저 실행하세요."); return

    months = month_list()
    print(f"🔑 키 확인: {MOLIT_API_KEY[:8]}...{MOLIT_API_KEY[-4:]}")
    print(f"📅 조회 기간: {months[0]} ~ {months[-1]} ({len(months)}개월)\n")

    apt_data = []
    for apt in APTS:
        print(f"📡 [{apt['name']}] 수집 중...")
        trades, rents = collect(apt, months)
        print(f"   ✅ 매매 {len(trades)}건 / 전월세 {len(rents)}건\n")
        apt_data.append((apt, trades, rents))

    html = generate_html(apt_data)
    with open(OUTPUT,"w",encoding="utf-8") as f:
        f.write(html)
    print("✅ 리포트 생성 완료!")

    push_to_github()
    if os.environ.get("CI") != "true":
        subprocess.run(["open", OUTPUT])

if __name__ == "__main__":
    main()
