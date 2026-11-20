import { brand, pageStyles } from "./oauth.js";

// Dashboard for GET /v1/stats. The token travels in the URL fragment
// (/stats#<token>), which browsers never send to the server, and is passed to
// the API only in the Authorization header. Charts are inline SVG drawn by
// the page script, so the CSP stays 'self' + nonce.
export function statsPage(nonce: string) {
  return `<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="robots" content="noindex"><title>Usage · AgentLayer</title><style>${pageStyles()}${STYLES}</style></head><body class="dash"><main>${brand()}
<div class="head"><div><h1>Usage</h1><p class="intro" id="sub">AgentLayer x402 MCP</p></div><div class="range" role="group" aria-label="Time range"><button type="button" data-days="7">7d</button><button type="button" data-days="30">30d</button><button type="button" data-days="90">90d</button><button type="button" data-days="365">1y</button></div></div>
<form id="auth" class="auth" hidden><label for="token">Stats token</label><div class="row"><input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="STATS_TOKEN"><button class="action primary" type="submit">Open</button></div><p class="hint left">Or open this page as /stats#&lt;token&gt;. The part after # is never sent to the server.</p></form>
<p class="status" id="status" role="status" aria-live="polite"></p>
<div id="view" hidden>
<section class="tiles" id="tiles"></section>
<section class="grid2"><div class="card"><h2>Active users per day</h2><div class="chart" id="c-active"></div></div><div class="card"><h2>Tool calls per day</h2><div class="legend"><span><i class="sw ok"></i>Succeeded</span><span><i class="sw err"></i>Failed</span></div><div class="chart" id="c-calls"></div></div></section>
<section class="grid2"><div class="card"><h2>New users per day</h2><div class="chart" id="c-new"></div></div><div class="card"><h2>Funnel <small>new users in the window</small></h2><div id="funnel"></div></div></section>
<section class="card"><h2>Tools</h2><div class="scroll"><table id="t-tools"></table></div></section>
<section class="card"><h2>Top errors</h2><div class="scroll"><table id="t-errors"></table></div></section>
<section class="grid2"><div class="card"><h2>Clients</h2><div class="scroll"><table id="t-clients"></table></div></div><div class="card"><h2>Sign-in events</h2><div class="scroll"><table id="t-auth"></table></div></div></section>
<section class="grid2"><div class="card"><h2>Wallet operations</h2><div class="scroll"><table id="t-ops"></table></div></div><div class="card"><h2>x402 payments</h2><div class="scroll"><table id="t-pay"></table></div></div></section>
<section class="grid2"><div class="card"><h2>Users by sign-in method <small>all time</small></h2><div class="scroll"><table id="t-methods"></table></div></div><div class="card"><h2>Signatures</h2><div class="scroll"><table id="t-sigs"></table></div></div></section>
<p class="footnote" id="note"></p>
</div><div class="tip" id="tip" hidden></div>
<script nonce="${nonce}">${SCRIPT}</script></main></body></html>`;
}

const STYLES = `body.dash{display:block;padding:88px 24px 120px}body.dash main{width:min(100%,1080px);margin:0 auto}.head{display:flex;gap:16px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;margin-bottom:24px}.head .intro{margin:6px 0 0}.range{display:flex;gap:2px;padding:3px;border:1px solid #e5e5e5;border-radius:10px;background:#fff}.range button{padding:6px 12px;border:0;border-radius:7px;background:none;color:#525252;font:inherit;font-size:13px;font-weight:500;cursor:pointer}.range button[aria-pressed=true]{background:#0a0a0a;color:#fff}.auth{max-width:420px;margin:40px 0}.auth label{display:block;margin-bottom:8px;font-size:13px;font-weight:500;color:#525252}.auth .row{display:flex;gap:8px}.auth input{flex:1;min-width:0;height:48px;padding:0 14px;border:1px solid #e5e5e5;border-radius:12px;background:#fff;font:inherit}.auth .action{width:auto;padding:0 20px}.hint.left{text-align:left}.status{text-align:left}.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:10px}.tile{padding:16px;border:1px solid #ececea;border-radius:14px;background:#fff}.tile b{display:block;font-size:26px;font-weight:600;letter-spacing:-.02em;line-height:1.1;font-variant-numeric:tabular-nums}.tile span{display:block;margin-top:6px;color:#737373;font-size:12.5px}.tile em{font-style:normal;color:#a3a3a3}.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:10px}.card{min-width:0;margin-bottom:10px;padding:18px 18px 14px;border:1px solid #ececea;border-radius:14px;background:#fff}.card h2{margin:0 0 12px;font-size:14px;font-weight:600}.card h2 small{margin-left:6px;color:#a3a3a3;font-size:12px;font-weight:400}.chart{height:180px}.chart svg{display:block;width:100%;height:100%;overflow:visible}.legend{display:flex;gap:14px;margin:-4px 0 8px;color:#525252;font-size:12px}.sw{display:inline-block;width:10px;height:10px;margin-right:6px;border-radius:3px;vertical-align:-1px}.sw.ok{background:#262626}.sw.err{background:#d03b3b}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th{padding:6px 10px 8px 0;color:#737373;font-size:12px;font-weight:500;text-align:left;white-space:nowrap;border-bottom:1px solid #e5e5e5}td{padding:8px 10px 8px 0;border-bottom:1px solid #f2f2f0;vertical-align:middle}tr:last-child td{border-bottom:0}td.n,th.n{text-align:right}td.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px;overflow-wrap:anywhere}td.bar{width:34%;min-width:90px}.bar i{display:block;height:8px;border-radius:0 4px 4px 0;background:#262626}.bad{color:#b42323}.empty{padding:14px 0;color:#a3a3a3;font-size:13px}.fn{display:grid;gap:10px}.fn div{display:grid;grid-template-columns:120px 1fr 64px;gap:10px;align-items:center;font-size:13px}.fn i{display:block;height:22px;border-radius:0 5px 5px 0;background:#262626;min-width:2px}.fn b{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}.fn span{color:#525252}.tip{position:fixed;z-index:5;pointer-events:none;padding:8px 10px;border-radius:9px;background:#0a0a0a;color:#fff;font-size:12px;line-height:1.45;white-space:nowrap;box-shadow:0 4px 16px rgba(0,0,0,.18)}.tip b{font-weight:600}.axis{fill:#a3a3a3;font-size:10.5px;font-family:Geist,sans-serif}.grid{stroke:#f0f0ee}.base{stroke:#d4d4d4}@media(max-width:520px){body.dash{padding:80px 16px 110px}.fn div{grid-template-columns:96px 1fr 48px}}`;

const SCRIPT = `(function(){
var $=function(id){return document.getElementById(id);},tip=$("tip"),status=$("status"),token="",days=30,data=null;
var esc=function(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});};
var fmt=function(v){if(v==null)return"—";var n=Number(v);return Math.abs(n)>=1e4?n.toLocaleString("en-US",{maximumFractionDigits:0}):n.toLocaleString("en-US",{maximumFractionDigits:2});};
var ms=function(v){return v==null?"—":Number(v)>=1000?(Number(v)/1000).toFixed(1)+" s":Math.round(v)+" ms";};
var ago=function(v){if(!v)return"—";var s=(Date.now()-new Date(v).getTime())/1000;return s<90?"just now":s<5400?Math.round(s/60)+" min ago":s<129600?Math.round(s/3600)+" h ago":Math.round(s/86400)+" d ago";};
try{token=decodeURIComponent(location.hash.replace(/^#(token=)?/,""));}catch(e){}
document.querySelectorAll("[data-days]").forEach(function(b){b.addEventListener("click",function(){days=Number(b.dataset.days);load();});});
$("auth").addEventListener("submit",function(e){e.preventDefault();token=$("token").value.trim();if(!token)return;history.replaceState(null,"","#"+encodeURIComponent(token));load();});
function setRange(){document.querySelectorAll("[data-days]").forEach(function(b){b.setAttribute("aria-pressed",String(Number(b.dataset.days)===days));});}
function load(){
  setRange();if(!token){$("auth").hidden=false;$("view").hidden=true;return;}
  status.textContent="Loading…";status.className="status busy";
  fetch("/v1/stats?days="+days,{headers:{Authorization:"Bearer "+token},cache:"no-store"}).then(function(r){
    if(r.status===401){token="";history.replaceState(null,"","#");$("auth").hidden=false;$("view").hidden=true;throw new Error("That token was not accepted.");}
    if(r.status===404)throw new Error("Statistics are turned off on this server (STATS_TOKEN is not set).");
    if(!r.ok)throw new Error("The server answered "+r.status+".");return r.json();
  }).then(function(d){data=d;status.textContent="";status.className="status";$("auth").hidden=true;$("view").hidden=false;render();}).catch(function(e){status.className="status";status.textContent=e.message||"Could not load statistics.";});
}
function series(rows,key){var by={};(rows||[]).forEach(function(r){by[r.day]=r;});var out=[],end=new Date();end.setUTCHours(0,0,0,0);for(var i=data.window_days-1;i>=0;i--){var d=new Date(end.getTime()-i*864e5).toISOString().slice(0,10);out.push({day:d,row:by[d]||{}});}return out;}
function tiles(){var d=data,f=d.funnel,usd=(d.x402_payments||[]).filter(function(p){return p.status==="settled";}).reduce(function(a,p){return a+(p.usdc||0);},0),calls=(d.tools||[]).reduce(function(a,t){return a+t.calls;},0),errs=(d.tools||[]).reduce(function(a,t){return a+t.errors;},0),conf=(d.wallet_operations||[]).filter(function(o){return o.status==="confirmed";}).reduce(function(a,o){return a+o.count;},0);
  var t=[[d.users.total,"Users","+"+fmt(d.users.new)+" new"],[d.active_users.dau,"Active today",null],[d.active_users.wau,"Active 7 days",null],[d.active_users.mau,"Active 30 days",null],[calls,"Tool calls",calls?(errs/calls*100).toFixed(1)+"% failed":null],[conf,"Transactions confirmed",null],[usd,"x402 USDC settled",null],[d.wallets.total,"Smart wallets","+"+fmt(d.wallets.new)+" new"]];
  $("tiles").innerHTML=t.map(function(x){return'<div class="tile"><b>'+fmt(x[0])+'</b><span>'+esc(x[1])+(x[2]?' <em>· '+esc(x[2])+' in '+data.window_days+'d</em>':'')+'</span></div>';}).join("");}
function bars(el,pts,stack,label){
  var w=el.clientWidth||600,h=el.clientHeight||180,pl=34,pb=20,pt=6,iw=w-pl,ih=h-pb-pt,n=pts.length;
  var tot=pts.map(function(p){return stack.reduce(function(a,s){return a+(Number(p.row[s.key])||0);},0);}),max=Math.max(1,Math.max.apply(null,tot));
  var step=Math.pow(10,Math.floor(Math.log10(max))),nice=Math.ceil(max/step)*step;if(nice/step>5)step*=2;var ticks=[];for(var v=0;v<=nice+1e-9;v+=step)ticks.push(v);if(ticks.length<2)ticks=[0,nice];var top=ticks[ticks.length-1]||1;
  var y=function(v){return pt+ih-(v/top)*ih;},slot=iw/n,bw=Math.max(1,Math.min(26,slot-(n>60?1:2))),s='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+esc(label)+'">';
  ticks.forEach(function(t){s+='<line class="'+(t===0?'base':'grid')+'" x1="'+pl+'" x2="'+w+'" y1="'+y(t)+'" y2="'+y(t)+'"/><text class="axis" x="'+(pl-6)+'" y="'+(y(t)+3.5)+'" text-anchor="end">'+fmt(t)+'</text>';});
  var every=Math.ceil(n/(w<480?4:7));
  pts.forEach(function(p,i){var x=pl+i*slot+(slot-bw)/2,acc=0,parts=[];stack.forEach(function(st,k){var v=Number(p.row[st.key])||0;if(!v)return;var y0=y(acc),y1=y(acc+v);acc+=v;var gap=k>0?2:0,hh=Math.max(1,y0-y1-gap),r=Math.min(4,bw/2),last=k===stack.length-1||!stack.slice(k+1).some(function(o){return Number(p.row[o.key]);});
      parts.push(last?'<path fill="'+st.color+'" d="M'+x+' '+(y0-gap)+'V'+(y0-gap-hh+r)+'q0 -'+r+' '+r+' -'+r+'h'+(bw-2*r)+'q'+r+' 0 '+r+' '+r+'V'+(y0-gap)+'Z"/>':'<rect fill="'+st.color+'" x="'+x+'" y="'+(y0-gap-hh)+'" width="'+bw+'" height="'+hh+'"/>');});
    var tipText="<b>"+p.day+"</b><br>"+stack.map(function(st){return esc(st.label)+": "+fmt(Number(p.row[st.key])||0);}).join("<br>");
    s+='<g>'+parts.join("")+'<rect x="'+(pl+i*slot)+'" y="'+pt+'" width="'+slot+'" height="'+ih+'" fill="transparent" data-tip="'+esc(tipText)+'"/></g>';
    if(i%every===0||i===n-1&&n<=31)s+='<text class="axis" x="'+(pl+i*slot+slot/2)+'" y="'+(h-4)+'" text-anchor="middle">'+p.day.slice(5).replace("-","/")+'</text>';});
  el.innerHTML=s+'</svg>';}
function table(id,cols,rows,empty){var el=$(id);if(!rows||!rows.length){el.innerHTML='<tr><td class="empty">'+esc(empty||"No data in this window yet.")+'</td></tr>';return;}
  var max={};cols.forEach(function(c){if(c.bar)max[c.key]=Math.max(1,Math.max.apply(null,rows.map(function(r){return Number(r[c.key])||0;})));});
  el.innerHTML='<thead><tr>'+cols.map(function(c){return'<th class="'+(c.num?'n':'')+'">'+esc(c.label)+'</th>';}).join("")+'</tr></thead><tbody>'+rows.map(function(r){return'<tr>'+cols.map(function(c){var v=r[c.key];if(c.bar)return'<td class="bar"><i style="width:'+Math.max(2,(Number(v)||0)/max[c.key]*100)+'%"></i></td>';var txt=c.f?c.f(v,r):(c.num?fmt(v):esc(v));return'<td class="'+(c.num?'n ':'')+(c.mono?'mono ':'')+(c.bad&&c.bad(r)?'bad':'')+'">'+txt+'</td>';}).join("")+'</tr>';}).join("")+'</tbody>';}
function render(){
  var d=data;$("sub").textContent="Last "+d.window_days+" days · updated "+new Date(d.generated_at).toLocaleString();
  tiles();
  bars($("c-active"),series(d.active_users.by_day),[{key:"users",color:"#262626",label:"Active users"}],"Active users per day");
  var calls=series(d.active_users.by_day).map(function(p){return{day:p.day,row:{ok:(p.row.calls||0)-(p.row.errors||0),errors:p.row.errors||0}};});
  bars($("c-calls"),calls,[{key:"ok",color:"#262626",label:"Succeeded"},{key:"errors",color:"#d03b3b",label:"Failed"}],"Tool calls per day");
  bars($("c-new"),series(d.users.new_by_day),[{key:"new_users",color:"#262626",label:"New users"}],"New users per day");
  var f=d.funnel,fs=[["New users",f.new_users],["Called a tool",f.called_a_tool],["Transacted",f.transacted]],fm=Math.max(1,f.new_users||0);
  $("funnel").innerHTML='<div class="fn">'+fs.map(function(x,i){return'<div><span>'+x[0]+'</span><i style="width:'+Math.max(1,(x[1]||0)/fm*100)+'%"></i><b>'+fmt(x[1])+(i&&f.new_users?' <small style="color:#a3a3a3;font-weight:400">'+Math.round((x[1]||0)/f.new_users*100)+'%</small>':'')+'</b></div>';}).join("")+'</div>';
  table("t-tools",[{key:"tool",label:"Tool",mono:1},{key:"calls",label:"",bar:1},{key:"calls",label:"Calls",num:1},{key:"users",label:"Users",num:1},{key:"errors",label:"Failed",num:1,f:function(v,r){return fmt(v)+(r.calls?' <span style="color:#a3a3a3">'+Math.round(v/r.calls*100)+'%</span>':'');},bad:function(r){return r.calls&&r.errors/r.calls>=.2;}},{key:"p50_ms",label:"p50",num:1,f:ms},{key:"p95_ms",label:"p95",num:1,f:ms},{key:"last_at",label:"Last call",f:ago}],d.tools);
  table("t-errors",[{key:"tool",label:"Tool",mono:1},{key:"error",label:"Error"},{key:"count",label:"Count",num:1},{key:"users",label:"Users",num:1},{key:"last_at",label:"Last",f:ago}],d.top_errors,"No failed tool calls in this window.");
  table("t-clients",[{key:"client",label:"Client"},{key:"calls",label:"",bar:1},{key:"calls",label:"Calls",num:1},{key:"users",label:"Users",num:1}],d.clients);
  table("t-auth",[{key:"event",label:"Event",mono:1},{key:"count",label:"Count",num:1},{key:"users",label:"Users",num:1},{key:"new_users",label:"New users",num:1}],d.auth);
  table("t-ops",[{key:"network",label:"Network"},{key:"status",label:"Status",bad:function(r){return r.status==="failed"||r.status==="unknown";}},{key:"count",label:"Count",num:1},{key:"users",label:"Users",num:1}],d.wallet_operations);
  table("t-pay",[{key:"status",label:"Status",bad:function(r){return r.status==="failed"||r.status==="unknown";}},{key:"count",label:"Count",num:1},{key:"users",label:"Users",num:1},{key:"usdc",label:"USDC",num:1}],d.x402_payments);
  table("t-methods",[{key:"provider",label:"Method",mono:1},{key:"users",label:"",bar:1},{key:"users",label:"Users",num:1}],d.users.by_sign_in_method);
  table("t-sigs",[{key:"k",label:"Result"},{key:"v",label:"Count",num:1}],[{k:"Signed",v:d.signatures.signed},{k:"Failed",v:d.signatures.failed}]);
  $("note").textContent=d.note||"";
}
document.addEventListener("mousemove",function(e){var t=e.target&&e.target.getAttribute&&e.target.getAttribute("data-tip");if(!t){tip.hidden=true;return;}tip.innerHTML=t;tip.hidden=false;var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();if(x+r.width>innerWidth-8)x=e.clientX-r.width-14;if(y+r.height>innerHeight-8)y=e.clientY-r.height-14;tip.style.left=x+"px";tip.style.top=y+"px";});
var rt;addEventListener("resize",function(){clearTimeout(rt);rt=setTimeout(function(){if(data)render();},150);});
load();
})();`;
