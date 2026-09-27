# The remote-control page served at http://deskpal.local/ (phone, iPad or Mac on the same Wi-Fi).
import secrets

SPOTIFY_LOGIN = secrets.VOICE_URL.replace("/api/voice", "/api/spotify") + "?action=login&k=" + secrets.VOICE_KEY

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=apple-mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-title content="Desk Pal">
<title>Desk Pal</title><style>
:root{--bg:#f4f1ea;--fg:#1d1d1b;--card:#fff;--line:#d9d4c7;--accent:#1d1d1b;--accent-fg:#f4f1ea}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#eceae4;--card:#22211e;--line:#3a3833;--accent:#eceae4;--accent-fg:#161614}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.4 ui-monospace,Menlo,monospace;padding:16px;max-width:560px;margin:auto}
h1{font-size:20px;letter-spacing:.08em;margin:4px 0 12px}h2{font-size:12px;letter-spacing:.12em;opacity:.6;margin:18px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px}
button,a.btn{font:inherit;padding:14px 8px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;text-align:center;text-decoration:none;display:block}
button.on{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
button:active{transform:scale(.97)}.row{display:flex;gap:8px}.row>*{flex:1}
input{font:inherit;width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
#st{padding:12px;border-radius:12px;background:var(--card);border:1px solid var(--line);min-height:48px;white-space:pre-line}
</style></head><body>
<h1>DESK PAL</h1><div id=st>connecting...</div>
<h2>SCREEN</h2><div class=grid id=screens></div>
<h2>FOCUS TIMER</h2><div class=grid>
<button onclick="go('/timer?minutes=25')">25 min</button><button onclick="go('/timer?minutes=50')">50 min</button>
<button onclick="go('/timer?minutes=5&label=Break')">5 min break</button></div>
<div class=row style="margin-top:8px"><input id=mins type=number min=1 max=240 placeholder="minutes">
<button onclick="go('/timer?minutes='+(+mins.value||25))">Start</button></div>
<div class=row style="margin-top:8px"><button onclick="go('/timer/pause')">Pause / resume</button><button onclick="go('/timer/cancel')">Cancel</button></div>
<h2>MUSIC</h2><div class=row><button onclick="go('/music?do=previous')">&#9198;</button>
<button onclick="go('/music?do=toggle')">&#9199;</button><button onclick="go('/music?do=next')">&#9197;</button></div>
<div style="margin-top:8px"><a class=btn href="/spotify-login">Connect Spotify</a></div>
<h2>LOCATION</h2><div id=loc style="margin-bottom:8px;opacity:.8">...</div>
<button id=locbtn style="width:100%%">Use my phone's location</button>
<h2>WI-FI</h2><div id=wifi style="margin-bottom:8px;opacity:.8">...</div>
<div class=row><input id=ssid placeholder="network name (e.g. hotspot)" autocapitalize=off autocorrect=off></div>
<div class=row style="margin-top:8px"><input id=pw type=password placeholder="password">
<button onclick="addWifi()">Save</button></div>
<h2>AGENT LIMITS</h2><div id=lim style="margin-bottom:8px;opacity:.8">...</div>
<div class=row><button onclick="claude()">Connect Claude</button><button onclick="codex()">Connect Codex</button></div>
<div id=login style="margin-top:8px"></div>
<h2>AGENT ALERTS</h2><button onclick="go('/alerts/clear')" style="width:100%%">Dismiss alerts</button>
<script>
const NAMES={limits:'Limits',room:'Today',pixel:'Pixel Pal',flights:'Flights',music:'Music'};
const sc=document.getElementById('screens');
for(const n in NAMES){const b=document.createElement('button');b.textContent=NAMES[n];b.id='s-'+n;b.onclick=()=>go('/screen?name='+n);sc.appendChild(b)}
async function go(p){await fetch(p,{method:'POST'}).catch(()=>{});refresh()}
async function refresh(){try{const s=await(await fetch('/state')).json();
for(const n in NAMES)document.getElementById('s-'+n).className=s.screen==n?'on':'';
st.textContent=[s.alert,s.timer,s.music].filter(Boolean).join('\\n')||'On: '+(NAMES[s.screen]||s.screen);
lim.textContent=s.limits.length?'Read directly from: '+s.limits.join(', '):'Not signed in: reading the relay'}catch(e){st.textContent='board not reachable'}}
async function step(p){try{return await(await fetch(p,{method:'POST'})).json()}catch(e){return{error:'board not reachable'}}}
function done(r,who){login.textContent=r.ok?who+' connected. Limits update in a few seconds.':r.error;refresh()}
async function claude(){const r=await step('/connect/claude');if(r.error)return done(r);login.textContent='';
const a=document.createElement('a');a.className='btn';a.href=r.url;a.target='_blank';a.textContent='1. Sign in to Claude';
const i=document.createElement('input');i.placeholder='2. Paste the code it shows';i.style.marginTop='8px';
const b=document.createElement('button');b.textContent='3. Save';b.style.cssText='margin-top:8px;width:100%%';
b.onclick=async()=>done(await step('/connect/claude?code='+encodeURIComponent(i.value.trim())),'Claude');login.append(a,i,b)}
async function codex(){const r=await step('/connect/codex');if(r.error)return done(r);
login.textContent='Open '+r.url+' and enter this code:';const c=document.createElement('div');
c.style.cssText='font-size:28px;letter-spacing:.1em;margin:8px 0';c.textContent=r.code;
const a=document.createElement('a');a.className='btn';a.href=r.url;a.target='_blank';a.textContent='Open the OpenAI page';
login.append(c,a);const t=setInterval(async()=>{const s=await step('/connect/codex/check');
if(!s.waiting){clearInterval(t);done(s,'Codex')}},5000)}
async function wifi(){try{const w=await(await fetch('/wifi')).json();const box=document.getElementById('wifi');
box.textContent='Connected to '+(w.connected||'?')+'. Known: '+w.home;
document.getElementById('loc').textContent=w.location?'Using: '+w.location+' (set for '+w.connected+')':'Using: your internet connection (approximate)';
for(const n of w.saved){box.append(', '+n+' ');const a=document.createElement('a');a.href='#';a.textContent='remove';
a.onclick=e=>{e.preventDefault();delWifi(n)};box.append(a)}}catch(e){}}
async function addWifi(){const s=ssid.value.trim();if(!s)return;
await fetch('/wifi/add?ssid='+encodeURIComponent(s)+'&password='+encodeURIComponent(pw.value),{method:'POST'});ssid.value=pw.value='';wifi()}
async function delWifi(s){await fetch('/wifi/remove?ssid='+encodeURIComponent(s),{method:'POST'});wifi()}
document.getElementById('locbtn').addEventListener('click',()=>{
window.location.href='https://desk-voice.vercel.app/api/locate?board='+encodeURIComponent(window.location.host)});
refresh();wifi();setInterval(refresh,3000);
</script></body></html>"""

def page():
    return PAGE.replace("%%", "%")
