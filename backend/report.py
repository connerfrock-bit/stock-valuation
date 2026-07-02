"""
Fair Value — QA dashboard generator.
Renders data/output.json into a single self-contained dark HTML file (data/report.html):
KPI strip, searchable/sortable ranked table with range bars, confidence meters, quality
gauges, trap-flag chips. This is the interim QA surface (BLUEPRINT §7 sanity panel) —
the pixel-fidelity React port of the design handoff remains Phase 6.
stdlib only.   python report.py
"""
import json, webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent / "data"

TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Fair Value — Nasdaq-100 QA board</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 *{box-sizing:border-box} body{margin:0;background:#0a0c10;color:#e6e9ef;font:13px Inter,system-ui,sans-serif}
 .mono{font-family:'JetBrains Mono',Consolas,monospace}
 header{display:flex;align-items:center;gap:12px;padding:12px 20px;background:#0c0f15;border-bottom:1px solid #1d222d}
 .logo{width:22px;height:22px;border-radius:5px;background:linear-gradient(135deg,#3fb950,#2a8d3c);display:flex;align-items:center;justify-content:center}
 .logo div{width:9px;height:9px;border-radius:2px;background:#0a0c10}
 h1{font-size:13px;letter-spacing:.16em;margin:0} .pill{font-family:'JetBrains Mono';font-size:9.5px;color:#9aa3b2;border:1px solid #2a3140;border-radius:4px;padding:2px 6px}
 .asof{margin-left:auto;text-align:right;line-height:1.25}.asof .l{font-size:9px;letter-spacing:.08em;color:#525c6b;text-transform:uppercase}.asof .v{font-family:'JetBrains Mono';font-size:11px;color:#9aa3b2}
 .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:#1d222d;border-bottom:1px solid #1d222d}
 .kpi{background:#0c0f15;padding:12px 18px}.kpi .l{font-size:10px;letter-spacing:.06em;color:#626b7a;text-transform:uppercase;margin-bottom:6px}
 .kpi .v{font-family:'JetBrains Mono';font-size:22px;font-weight:600;line-height:1}.kpi .s{font-size:10.5px;color:#626b7a;margin-top:4px}
 .bar{display:flex;align-items:center;gap:10px;padding:10px 20px;border-bottom:1px solid #1d222d;flex-wrap:wrap}
 input[type=text]{background:#11151d;border:1px solid #1d222d;border-radius:7px;color:#e6e9ef;padding:6px 11px;font-size:12.5px;width:260px;outline:none}
 input[type=text]:focus{border-color:#4493f8}
 .chip{font-size:11px;color:#9aa3b2;border:1px solid #2a3140;border-radius:6px;padding:4px 10px;cursor:pointer;user-select:none}
 .chip.on{background:rgba(68,147,248,.15);border-color:#4493f8;color:#fff}
 table{width:100%;border-collapse:collapse;font-size:12px}
 thead th{position:sticky;top:0;background:#0e1117;color:#626b7a;font-size:10px;text-transform:uppercase;letter-spacing:.05em;
   padding:9px 10px;border-bottom:1px solid #1d222d;cursor:pointer;text-align:right;white-space:nowrap;user-select:none;z-index:5}
 thead th:first-child,thead th:nth-child(2),thead th:nth-child(9){text-align:left}
 tbody td{padding:6px 10px;border-bottom:1px solid #14181f;text-align:right;white-space:nowrap}
 tbody td:first-child,tbody td:nth-child(2),tbody td:nth-child(9){text-align:left}
 tbody tr:hover{background:rgba(68,147,248,.06)}
 .tick{font-family:'JetBrains Mono';font-weight:600;font-size:12.5px}
 .nm{font-size:10.5px;color:#8a93a3;max-width:150px;overflow:hidden;text-overflow:ellipsis}
 .sec{font-size:8.5px;font-weight:600;border-radius:3px;padding:1px 5px;margin-left:6px}
 .g{color:#3fb950}.r{color:#f85149}.a{color:#d29922}.d{color:#626b7a}
 .rb{position:relative;width:170px;height:12px;display:inline-block;vertical-align:middle}
 .rb .track{position:absolute;inset:3px 0;background:#161b24;border-radius:3px}
 .rb .band{position:absolute;top:2px;bottom:2px;background:rgba(154,163,178,.30);border:1px solid rgba(154,163,178,.4);border-radius:2px}
 .rb .midt{position:absolute;top:0;bottom:0;width:2px;background:#cfd6e2}
 .rb .pl{position:absolute;top:-2px;bottom:-2px;width:2px;border-radius:2px;box-shadow:0 0 0 2px rgba(10,12,16,.9)}
 .cm{display:inline-flex;gap:2px;vertical-align:middle}.cm i{width:12px;height:7px;border-radius:2px;background:#1c2230}
 .qg{display:inline-flex;align-items:center;gap:6px}.qg .t{width:52px;height:5px;border-radius:3px;background:#161b24;position:relative;overflow:hidden}
 .qg .t i{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
 .fl{display:inline-block;font-size:9px;font-weight:600;border-radius:3px;padding:1px 5px;margin-right:3px}
 .fl.warn{color:#d29922;background:rgba(210,153,34,.13);border:1px solid rgba(210,153,34,.3)}
 .fl.bad{color:#f85149;background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.3)}
 footer{padding:14px 20px;color:#626b7a;font-size:11px;line-height:1.6;border-top:1px solid #1d222d}
 ::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background:#222835;border-radius:6px;border:2px solid #0a0c10}
</style></head><body>
<header><div class="logo"><div></div></div><h1>FAIR&nbsp;VALUE</h1><span class="pill">NASDAQ·100 · QA BOARD</span>
 <div class="asof"><div class="l">Data as of</div><div class="v" id="asof"></div></div></header>
<div class="kpis" id="kpis"></div>
<div class="bar">
 <input type="text" id="q" placeholder="Search ticker or company…">
 <span class="chip" id="hideFlag">Hide trap-flagged</span>
 <span style="flex:1"></span><span class="d" id="count"></span>
</div>
<table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
<footer id="foot"></footer>
<script>
const DATA=__DATA__;
const C={g:'#3fb950',r:'#f85149',a:'#d29922',hi:'#e6e9ef',mid:'#9aa3b2',dim:'#626b7a'};
const SEC={TECH:'#6ea8fe',COMM:'#b58cf0',DISC:'#f0879b',STPL:'#4fc3c9',HLTH:'#8d80e6',INDU:'#c0a062',FINL:'#d98a5b',REIT:'#c98fc0',MATL:'#9aa86b',ENGY:'#cf8f6a',UTIL:'#6fb1a0'};
const cols=[['#',null],['Company','ticker'],['Price','price'],['Fair range (low·mid·high)',null],['Upside','upside'],
 ['Agree','conf'],['Quality','quality'],['Impl vs trail g',null],['Flags',null],['Score','score']];
let sortKey='score',dir=-1,hideFlag=false;
const fmt$=v=>'$'+(v>=100?Math.round(v).toLocaleString():v.toFixed(2));
const fmtP=v=>(v>=0?'+':'')+(v*100).toFixed(1)+'%';
const upC=u=>u>0.04?'g':u<-0.04?'r':'a';
const qC=q=>q>=70?C.g:q>=48?C.a:C.r;
function alpha(h,a){const n=parseInt(h.slice(1),16);return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`}
function rb(x){const lo=Math.min(x.low,x.price)*0.9,hi=Math.max(x.high,x.price)*1.1,W=v=>Math.max(0,Math.min(100,(v-lo)/(hi-lo)*100));
 const vc=x.upside>0.04?C.g:x.upside<-0.04?C.r:C.a;
 return `<span class="rb" title="low ${fmt$(x.low)} · mid ${fmt$(x.mid)} · high ${fmt$(x.high)} · price ${fmt$(x.price)}">
  <span class="track"></span><span class="band" style="left:${W(x.low)}%;width:${W(x.high)-W(x.low)}%"></span>
  <span class="midt" style="left:${W(x.mid)}%"></span><span class="pl" style="left:${W(x.price)}%;background:${vc}"></span></span>`}
function cm(c){let s='<span class="cm">';for(let i=1;i<=5;i++)s+=`<i style="${i<=c?`background:${c>=4?C.g:c>=2?C.a:C.r}`:''}"></i>`;return s+'</span>'}
function qg(q){return `<span class="qg"><span class="t"><i style="width:${q}%;background:${qC(q)}"></i></span><span class="mono" style="color:${qC(q)}">${q}</span></span>`}
function flags(f){if(!f.length)return '<span class="d mono">—</span>';
 return f.map(x=>`<span class="fl ${/Declin|Negative|Suspect|accrual/.test(x)?'bad':'warn'}">${x}</span>`).join('')}
function ivt(x){if(x.impliedGrowth==null)return '<span class="d">n/a</span>';
 const i=(x.impliedOp&&x.impliedOp!='='?x.impliedOp:'')+Math.round(x.impliedGrowth*100)+'%';
 const t=x.trailingG==null?'n/a':Math.round(x.trailingG*100)+'%';
 const c=x.trailingG!=null&&x.impliedGrowth>x.trailingG+0.04?'r':x.trailingG!=null&&x.impliedGrowth<x.trailingG-0.04?'g':'a';
 return `<span class="mono ${c}">${i}</span> <span class="d">vs ${t}</span>`}
function render(){
 const q=document.getElementById('q').value.toLowerCase();
 let rows=DATA.companies.filter(x=>!q||x.ticker.toLowerCase().includes(q)||x.name.toLowerCase().includes(q));
 if(hideFlag)rows=rows.filter(x=>!x.flags.length);
 if(sortKey)rows=[...rows].sort((a,b)=>{const x=a[sortKey],y=b[sortKey];
   return (typeof x=='string'?x.localeCompare(y):(x??-1e18)-(y??-1e18))*dir});
 document.getElementById('count').textContent=rows.length+' / '+DATA.companies.length+' shown';
 document.getElementById('body').innerHTML=rows.map((x,i)=>{
  const sc=SEC[x.sectorShort]||'#9aa3b2';
  return `<tr><td class="d mono">${i+1}</td>
  <td><span class="tick">${x.ticker}</span><span class="sec" style="color:${sc};background:${alpha(sc,.13)};border:1px solid ${alpha(sc,.33)}">${x.sectorShort}</span><div class="nm">${x.name}</div></td>
  <td class="mono">${fmt$(x.price)}</td><td>${rb(x)}</td>
  <td class="mono ${upC(x.upside)}" style="font-weight:600">${fmtP(x.upside)}</td>
  <td>${cm(x.conf)}</td><td>${qg(x.quality)}</td><td>${ivt(x)}</td><td>${flags(x.flags)}</td>
  <td class="mono" style="color:#cfd6e2">${x.score.toFixed(3)}</td></tr>`}).join('')}
function head(){document.getElementById('head').innerHTML=cols.map(([l,k])=>
 `<th data-k="${k??''}">${l}${k==sortKey?(dir<0?' ▼':' ▲'):''}</th>`).join('');
 document.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;
  dir=k==sortKey?-dir:-1;sortKey=k;head();render()})}
function kpis(){const cs=DATA.companies;
 const uv=cs.filter(x=>x.upside>0.15).length,qp=cs.filter(x=>x.quality>=70).length;
 const med=[...cs].sort((a,b)=>a.upside-b.upside)[Math.floor(cs.length/2)].upside;
 const fl=cs.filter(x=>x.flags.length).length;
 const cells=[['Covered',cs.length,'ranked names',C.hi],['Undervalued',uv,'> 15% upside to mid',C.g],
  ['Pass quality',qp,'quality ≥ 70',C.hi],['Median upside',fmtP(med),'market-wide, to mid',med>0?C.g:C.r],
  ['Trap-flagged',fl,'≥ 1 flag',C.a]];
 document.getElementById('kpis').innerHTML=cells.map(([l,v,s,c])=>
  `<div class="kpi"><div class="l">${l}</div><div class="v" style="color:${c}">${v}</div><div class="s">${s}</div></div>`).join('')}
document.getElementById('asof').textContent=DATA.meta.asOf+' · rf '+(DATA.meta.riskFree*100).toFixed(2)+'%';
document.getElementById('q').oninput=render;
document.getElementById('hideFlag').onclick=e=>{hideFlag=!hideFlag;e.target.classList.toggle('on',hideFlag);render()};
document.getElementById('foot').innerHTML=
 `<b>Assumptions:</b> ERP ${(DATA.meta.erp*100).toFixed(1)}% · terminal g ${(DATA.meta.terminalG*100).toFixed(1)}% · risk-free ${(DATA.meta.riskFree*100).toFixed(2)}% (${DATA.meta.riskFreeSource}) · normalized-FCF base · SBC expensed · EPV = floor.<br>
  <b>Excluded (${DATA.meta.excluded.length}):</b> ${DATA.meta.excluded.map(e=>e.ticker+' ('+e.why+')').join(', ')||'none'}<br>
  Research aid, not a recommendation. Mid = weighted growth-aware engines; ranges are honest uncertainty, not precision.`;
kpis();head();render();
</script></body></html>"""


def main():
    payload = json.loads((BASE / "output.json").read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATA__", json.dumps(payload))
    out = BASE / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(payload['companies'])} companies)")
    try:
        webbrowser.open(out.as_uri())
    except Exception:
        pass


if __name__ == "__main__":
    main()
