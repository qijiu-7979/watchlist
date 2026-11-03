# -*- coding: utf-8 -*-
"""
云端每日生成：只读静态看板（GitHub Actions 运行）
拉取观察池行情 + 大盘 + 预警，渲染 index.html（数据内嵌、只读）。
token 从环境变量 NEODATA_TOKEN 读取（存 repo Secret）。
"""
import os, json, datetime, re, time, sys
sys.stdout.reconfigure(encoding='utf-8')
from query import query_neodata

TOKEN = os.environ.get('NEODATA_TOKEN')
HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, 'watchlist.json')
OUT = os.path.join(HERE, 'index.html')

def q(qs):
    return query_neodata(qs, data_type='api', token=TOKEN)

def fetch_range(code, d1, d2):
    r = q(f"{code}在{d1}到{d2}的日K线行情")
    content = r['data']['apiData']['apiRecall'][0]['content']
    rows = []
    for line in content.split('\n'):
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 12:
            continue
        date = cells[0]
        if not re.match(r'\d{4}-\d{2}-\d{2}', date) or '未开盘' in line:
            continue
        try:
            chg = cells[7].rstrip('%')
            rows.append({'date': date, 'open': float(cells[1]), 'high': float(cells[2]),
                         'low': float(cells[3]), 'close': float(cells[4]),
                         'chg': float(chg) if chg not in ('--', '') else None})
        except (ValueError, IndexError):
            continue
    return rows

def update_daily(data):
    today = datetime.date.today()
    s0 = (today - datetime.timedelta(days=14)).isoformat(); s1 = today.isoformat()
    have = {(d['date'], d['code']) for d in data['daily']}
    for st in data['stocks']:
        if st['status'] != 'active':
            continue
        code = st['code']
        try:
            rows = fetch_range(code, s0, s1)
        except Exception as e:
            print(f"  {code} 抓取失败 {e}"); continue
        for r in rows:
            if r['date'] < st['entry_date']:
                continue
            key = (r['date'], code)
            if key in have:
                continue
            data['daily'].append({'date': r['date'], 'code': code, 'close': r['close'], 'chg': r['chg'], 'low': r['low']})
            have.add(key)
        er = [r for r in rows if r['date'] == st['entry_date']]
        if er:
            if st.get('entry_price') is None:
                st['entry_price'] = er[0]['close']
            if st.get('critical_price') is None and '爆量日' in (st.get('critical_desc') or ''):
                st['critical_price'] = er[0]['low']
        time.sleep(0.15)
    data['daily'].sort(key=lambda x: (x['code'], x['date']))
    data['updated'] = today.isoformat()
    return data

def get_market():
    idx = []
    t = datetime.date.today(); s = (t - datetime.timedelta(days=7)).isoformat()
    for code, name in [('000001.SH', '上证指数'), ('399001.SZ', '深证成指'), ('399006.SZ', '创业板指')]:
        try:
            rows = sorted(fetch_range(code, s, t.isoformat()), key=lambda x: x['date'])
            if rows:
                last = rows[-1]
                idx.append({'name': name, 'close': last['close'], 'chg': last['chg'], 'date': last['date']})
        except Exception:
            pass
    breadth = {}
    try:
        r = q('今日A股上涨家数、下跌家数、涨停家数、跌停家数、两市成交额统计')
        c = r['data']['apiData']['apiRecall'][0]['content']
        def grab(pat):
            m = re.search(pat, c); return int(m.group(1)) if m else None
        breadth = {'up': grab(r'上涨家数 (\d+)'), 'down': grab(r'下跌家数 (\d+)'),
                   'limit_up': grab(r'涨停家数 (\d+)'), 'limit_down': grab(r'跌停家数 (\d+)'),
                   'up_ratio': grab(r'上涨家数占比 (\d+)%')}
        m2 = re.search(r'两市合计[^\|]*\|[^\|]*\| ([\d,]+\.\d+) 亿元', c)
        breadth['amount'] = m2.group(1) if m2 else None
    except Exception:
        pass
    return {'indexes': idx, 'breadth': breadth}

def get_alerts(data):
    alerts = []
    try:
        t = datetime.date.today(); s = (t - datetime.timedelta(days=95)).isoformat()
        rows = sorted(fetch_range('000001.SH', s, t.isoformat()), key=lambda x: x['date'])
        if len(rows) >= 60:
            closes = [r['close'] for r in rows]; ma60 = sum(closes[-60:])/60
            if closes[-1] < ma60:
                alerts.append({'level': 'warn', 'text': f'大盘空头排列（上证 {closes[-1]:.0f} < MA60 {ma60:.0f}）：控制仓位、慎用左侧抄底'})
    except Exception:
        pass
    for st in data['stocks']:
        if st['status'] != 'active':
            continue
        cp = st.get('critical_price')
        ds = [d for d in data['daily'] if d['code'] == st['code']]
        if cp and ds:
            latest = ds[-1]['close']
            if latest < cp:
                alerts.append({'level': 'danger', 'text': f"{st['name']}({st['code']}) 最新 {latest} 跌破临界值 {cp}：建议退出观察"})
    if not alerts:
        alerts.append({'level': 'ok', 'text': '今日无异常预警，按既定规则执行'})
    return alerts

# 只读静态模板（数据内嵌，无写操作）
TMPL = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>观察池 · 每日复盘</title>
<style>
:root{--bg:#f3f5f9;--card:#fff;--ink:#0f172a;--body:#334155;--muted:#64748b;--faint:#94a3b8;--line:#e9edf3;--line-2:#f1f4f8;
--accent:#4f46e5;--accent-soft:#eef0fe;--up:#dc2626;--up-bg:#fef2f2;--down:#16a34a;--down-bg:#f0fdf4;
--radius:16px;--shadow:0 1px 2px rgba(16,24,40,.04),0 8px 24px rgba(16,24,40,.05)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--body);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-size:14px;line-height:1.6}
.num{font-variant-numeric:tabular-nums}.wrap{max-width:1180px;margin:0 auto;padding:24px 18px 60px}
.hero{background:linear-gradient(120deg,#0f172a,#1e293b 55%,#2b2a55);color:#fff;border-radius:20px;padding:24px 26px;box-shadow:var(--shadow)}
.hero h1{margin:0;font-size:22px}.hero .sub{margin:6px 0 0;font-size:12.5px;color:#c3c9e6}
.kpis{display:flex;gap:26px;margin-top:16px}.kpi b{display:block;font-size:24px;font-weight:700}.kpi span{font-size:11px;color:#b6bedd}
.sec{display:flex;align-items:center;gap:10px;margin:26px 0 14px}.sec h2{margin:0;font-size:16px;color:var(--ink)}.sec .line{flex:1;height:1px;background:var(--line)}
.cnt{font-size:12px;color:var(--muted);background:var(--card);border:1px solid var(--line);padding:2px 10px;border-radius:20px}
#alertBar{margin-top:18px}.alert{padding:12px 18px;border-radius:12px;font-size:13.5px;margin-bottom:10px;display:flex;gap:10px;align-items:center;font-weight:500}
.alert .dot{width:9px;height:9px;border-radius:50%;flex:none}
.alert.danger{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}.alert.danger .dot{background:#dc2626}
.alert.warn{background:#fffbeb;color:#b45309;border:1px solid #fde68a}.alert.warn .dot{background:#f59e0b}
.alert.ok{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0}.alert.ok .dot{background:#16a34a}
.grid-mkt{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:12px}
.mkt-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px;box-shadow:var(--shadow)}
.mkt-card .nm{font-size:12px;color:var(--muted)}.mkt-card .vl{font-size:20px;font-weight:700;margin-top:3px}.mkt-card .sub2{font-size:11.5px;color:var(--faint);margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}
.tbl-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13.5px}
thead th{background:#fafbfd;color:var(--muted);font-size:11.5px;font-weight:600;text-align:left;padding:13px 16px;border-bottom:1px solid var(--line)}
tbody td{padding:14px 16px;border-bottom:1px solid var(--line-2);vertical-align:middle}
tbody tr.main{cursor:pointer}tbody tr.main:hover{background:#f8faff}tbody tr.main.open{background:var(--accent-soft)}
tbody tr.main.open td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.cell-name{font-weight:600;color:var(--ink)}.cell-sub{color:var(--faint);font-size:11.5px;margin-top:2px}
.pos{color:var(--up);font-weight:600}.neg{color:var(--down);font-weight:600}.flat{color:var(--muted)}
.badge{display:inline-block;font-size:11px;border-radius:6px;padding:3px 9px;background:var(--accent-soft);color:var(--accent);border:1px solid #e0e3fd}
.badge.exit{background:var(--up-bg);color:var(--up);border-color:#fecaca}.badge.rev,.badge.live{background:var(--down-bg);color:var(--down);border-color:#bbf7d0}
.detail-row{background:#fbfcfe}.detail-row>td{padding:0}.detail-box{padding:18px 22px;border-left:3px solid var(--accent);margin:12px 0;background:#fff;border-radius:0 12px 12px 0}
.detail-meta{font-size:12.5px;color:var(--muted);margin-bottom:4px}.detail-meta b{color:var(--body)}
.spark-wrap{margin:10px 0 4px}.spark-title{font-size:11px;color:var(--faint);margin-bottom:4px}
.mini{width:100%;font-size:12px;margin-top:10px;border-collapse:collapse}.mini th{background:#f8fafc;color:var(--muted);padding:8px 10px}.mini td{padding:7px 10px;border-bottom:1px solid var(--line-2)}
.link{color:#2563eb;text-decoration:none;font-size:12px}
.events{background:#fff;border-radius:16px;padding:8px 22px 16px;box-shadow:var(--shadow)}
.ev{padding:12px 0;border-bottom:1px dashed var(--line);font-size:12.5px}.ev:last-child{border:none}
.ev-date{font-weight:600;color:var(--ink)}.tag-e{font-size:10.5px;font-weight:600;border-radius:5px;padding:2px 7px;margin-right:8px;color:#fff}
.t-entry{background:var(--accent)}.t-exit{background:var(--up)}.t-revoke{background:var(--down)}.t-note{background:var(--faint)}
.note{color:var(--muted);font-size:12.5px;padding:16px 20px}.footer{color:var(--faint);font-size:12px;text-align:center;margin-top:30px;line-height:1.8}
.hidden{display:none!important}
.m-list{display:none}
@media(max-width:760px){
  table.resp thead{display:none}table.resp,table.resp tbody,table.resp tr,table.resp td{display:block;width:100%}
  table.resp tr.main{border:1px solid var(--line);border-radius:12px;margin-bottom:12px;padding:6px 2px}
  table.resp tr.main td{border:none;padding:7px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px}
  table.resp tr.main td:before{content:attr(data-l);color:var(--faint);font-size:11.5px}
}
</style></head><body><div class="wrap">
<header class="hero"><h1>📋 观察池 · 每日复盘</h1>
<p class="sub">数据更新至 <b id="upd">-</b> · 红涨绿跌 · 只读分享版</p>
<div class="kpis"><div class="kpi"><b id="nActive" class="num">0</b><span>在池</span></div>
<div class="kpi"><b id="nExit" class="num">0</b><span>已退出</span></div>
<div class="kpi"><b id="nDaily" class="num">0</b><span>表现记录</span></div>
<div class="kpi"><b id="nEvent" class="num">0</b><span>事件</span></div></div></header>
<div id="alertBar"></div>
<div class="sec"><h2>行情概览</h2><span class="line"></span><span id="mktDate" style="font-size:12px;color:var(--muted)"></span></div>
<div class="grid-mkt" id="mktGrid"></div>
<div class="sec"><h2>在池标的</h2><span class="cnt" id="cActive">0</span><span class="line"></span></div>
<div class="card tbl-scroll" id="activeTbl"></div>
<div class="sec"><h2>已退出标的</h2><span class="cnt" id="cExit">0</span><span class="line"></span></div>
<div class="card tbl-scroll" id="exitTbl"></div>
<div class="sec"><h2>事件日志</h2><span class="line"></span></div>
<div class="events" id="events"></div>
<div class="footer">每日自动生成 · 数据：NeoData · 红涨绿跌 · 仅供学习复盘，不构成投资建议</div>
</div>
<script>
const DATA=__DATA__,DASH=__DASH__;
const $=id=>document.getElementById(id);
function qx(c){return 'https://gu.qq.com/'+(c[0]==='6'?'sh':'sz')+c+'/gp';}
function cls(v){return v>0?'pos':(v<0?'neg':'flat');}
function fmt(v,d=2){return v==null?'-':Number(v).toFixed(d);}
function pct(v){return v==null?'-':(v>0?'+':'')+Number(v).toFixed(2)+'%';}
function dailyOf(c){return DATA.daily.filter(d=>d.code===c).sort((a,b)=>a.date<b.date?-1:1);}
function spark(ds,entry){
  if(!ds.length)return '';
  const pts=(entry)?[{close:entry}].concat(ds):ds;
  const vals=pts.map(p=>p.close).filter(v=>v!=null);if(vals.length<2)return '';
  const w=260,h=46,min=Math.min(...vals),max=Math.max(...vals),rg=(max-min)||1,step=w/(vals.length-1);
  const up=vals[vals.length-1]>=(entry||vals[0]),color=up?'#dc2626':'#16a34a';
  let d='';vals.forEach((v,i)=>{const x=(i*step).toFixed(1),y=(h-4-(v-min)/rg*(h-10)).toFixed(1);d+=(i?' L':'M')+x+' '+y;});
  const lx=((vals.length-1)*step).toFixed(1);
  return `<div class="spark-wrap"><div class="spark-title">入池后走势（${vals.length} 个交易日）</div><svg width="${w}" height="${h+6}" viewBox="0 0 ${w} ${h+6}" style="max-width:100%"><path d="${d} L${lx} ${h} L0 ${h} Z" fill="${color}" opacity=".12"/><path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"/><circle cx="${lx}" cy="${(h-4-(vals[vals.length-1]-min)/rg*(h-10)).toFixed(1)}" r="3" fill="${color}"/></svg></div>`;
}
function rowHtml(st){
  const ds=dailyOf(st.code),latest=ds.length?ds[ds.length-1]:null;
  const lc=latest?latest.chg:null,entry=st.entry_price,lclose=latest?latest.close:entry;
  const cum=(entry&&lclose)?(lclose/entry-1)*100:null,live=st.status==='active';
  const stTxt=live?'在池':(st.exit&&st.exit.revoked?'已撤回':'已退出');
  const stCls=live?'badge live':(st.exit&&st.exit.revoked?'badge rev':'badge exit');
  let h=`<tr class="main" id="r-${st.code}" onclick="toggle('${st.code}')">
    <td data-l="标的"><div><div class="cell-name">${st.name}</div><div class="cell-sub num">${st.code}</div></div></td>
    <td data-l="入池日期"><div><span class="num">${st.entry_date}</span><div class="cell-sub">${ds.length} 个交易日</div></div></td>
    <td data-l="形态/板块"><div><span class="badge">${st.setup||'—'}</span><div class="cell-sub">${st.board||''}</div></div></td>
    <td data-l="入池价" class="num">${fmt(entry)}</td>
    <td data-l="最新/当日"><div class="${cls(lc)}"><span class="num">${fmt(lclose)}</span><div class="cell-sub ${cls(lc)} num">${pct(lc)}</div></div></td>
    <td data-l="入池后累计" class="${cls(cum)} num">${pct(cum)}</td>
    <td data-l="状态"><span class="${stCls}">${stTxt}</span></td>
    <td data-l="行情"><a class="link" href="${qx(st.code)}" target="_blank">行情 ↗</a></td></tr>`;
  let mini=`<div class="detail-box"><div class="detail-meta">临界：<b>${st.critical_desc||'—'}${st.critical_price?'（'+fmt(st.critical_price)+'）':''}</b> · 介入：${st.entry_condition||'—'}</div>`;
  mini+=spark(ds,entry);
  mini+=`<table class="mini"><thead><tr><th>日期</th><th>收盘</th><th>当日</th><th>最低</th><th>累计</th></tr></thead><tbody>`;
  ds.slice().reverse().forEach(d=>{const c=(entry&&d.close)?(d.close/entry-1)*100:null;
    mini+=`<tr><td class="num">${d.date}</td><td class="num">${fmt(d.close)}</td><td class="${cls(d.chg)} num">${pct(d.chg)}</td><td class="num">${fmt(d.low)}</td><td class="${cls(c)} num">${pct(c)}</td></tr>`;});
  mini+='</tbody></table></div>';
  return h+`<tr class="detail-row hidden" id="d-${st.code}"><td colspan="8">${mini}</td></tr>`;
}
function toggle(c){$('d-'+c).classList.toggle('hidden');}
function tbl(list,empty){
  if(!list.length)return `<p class="note">${empty}</p>`;
  return `<table class="resp"><thead><tr><th>标的</th><th>入池日期</th><th>形态/板块</th><th>入池价</th><th>最新/当日</th><th>入池后累计</th><th>状态</th><th>行情</th></tr></thead><tbody>${list.map(rowHtml).join('')}</tbody></table>`;
}
function render(){
  const act=DATA.stocks.filter(s=>s.status==='active'),ex=DATA.stocks.filter(s=>s.status!=='active');
  $('activeTbl').innerHTML=tbl(act,'暂无在池标的');$('exitTbl').innerHTML=tbl(ex,'暂无退出标的');
  $('nActive').textContent=act.length;$('nExit').textContent=ex.length;$('nDaily').textContent=DATA.daily.length;$('nEvent').textContent=DATA.events.length;
  $('cActive').textContent=act.length;$('cExit').textContent=ex.length;$('upd').textContent=DATA.updated||'-';
  $('events').innerHTML=DATA.events.slice().reverse().map(e=>{
    const t=e.type==='entry'?['t-entry','入池']:e.type==='exit'?['t-exit','退出']:e.type==='revoke'?['t-revoke','撤回']:['t-note','备注'];
    return `<div class="ev"><span class="tag-e ${t[0]}">${t[1]}</span><span class="ev-date num">${e.date}</span><div>${e.name||''}（${e.code}）· ${e.note||e.reason||''}${e.trigger?(' · 触发：'+e.trigger):''}</div></div>`;}).join('')||'<p class="note">暂无</p>';
}
(function(){
  const m=DASH.market||{},idx=m.indexes||[],b=m.breadth||{};
  $('alertBar').innerHTML=(DASH.alerts||[]).map(a=>`<div class="alert ${a.level}"><span class="dot"></span><span>${a.text}</span></div>`).join('');
  let mh=idx.map(i=>`<div class="mkt-card"><div class="nm">${i.name}</div><div class="vl ${cls(i.chg)} num">${fmt(i.close)}</div><div class="sub2 ${cls(i.chg)} num">${pct(i.chg)}</div></div>`).join('');
  mh+=`<div class="mkt-card"><div class="nm">上涨 / 下跌家数</div><div class="vl num">${b.up??'-'}/${b.down??'-'}</div><div class="sub2">涨停 ${b.limit_up??'-'} · 跌停 ${b.limit_down??'-'}</div></div>`;
  mh+=`<div class="mkt-card"><div class="nm">上涨占比 / 成交额</div><div class="vl num">${b.up_ratio!=null?b.up_ratio+'%':'-'}</div><div class="sub2 num">${b.amount?b.amount+' 亿':'-'}</div></div>`;
  $('mktGrid').innerHTML=mh;if(idx.length)$('mktDate').textContent='截至 '+idx[0].date;
  render();
})();
</script></body></html>"""

def main():
    data = json.load(open(JSON_PATH, encoding='utf-8'))
    data = update_daily(data)
    json.dump(data, open(JSON_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    dash = {'market': get_market(), 'alerts': get_alerts(data)}
    html = TMPL.replace('__DATA__', json.dumps(data, ensure_ascii=False)).replace('__DASH__', json.dumps(dash, ensure_ascii=False))
    open(OUT, 'w', encoding='utf-8').write(html)
    print('生成 index.html 完成；在池', sum(1 for s in data['stocks'] if s['status']=='active'), '只；更新至', data['updated'])

if __name__ == '__main__':
    main()
