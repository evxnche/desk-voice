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
<h2>VOLUME</h2><div class=row><button onclick="setVol('step=-1')">&minus;</button>
<div id=vol style="text-align:center;padding:14px 0">...</div><button onclick="setVol('step=1')">+</button></div>
<h2>TASKS</h2><div id=tasks style="margin-bottom:8px"></div>
<div class=row><input id=taskin maxlength=60 placeholder="a task">
<button onclick="planDo('task_add','text='+encodeURIComponent(taskin.value.trim()));taskin.value=''">Add</button></div>
<button onclick="planDo('tasks_clear_done','')" style="width:100%%;margin-top:8px">Clear finished tasks</button>
<h2>PROJECTS</h2><div id=projects style="margin-bottom:8px"></div>
<div class=row><input id=projin maxlength=60 placeholder="project name">
<button onclick="planDo('project','stage=idea&name='+encodeURIComponent(projin.value.trim()));projin.value=''">Add</button></div>
<h2>TRACK A FLIGHT</h2><div id=trk style="margin-bottom:8px;opacity:.8">...</div>
<div class=row><input id=fno placeholder="flight number, e.g. BA36" autocapitalize=characters autocorrect=off>
<button onclick="go('/track?f='+encodeURIComponent(fno.value.trim()))">Track</button></div>
<button onclick="go('/track?f=')" style="width:100%%;margin-top:8px">Stop tracking</button>
<h2>CALENDAR</h2><div id=cal style="margin-bottom:8px;opacity:.8">...</div>
<div id=cals></div>
<div class=row><input id=ics placeholder="private iCal link (.ics)" autocapitalize=off autocorrect=off>
<button onclick="addCal()">Add</button></div>
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
<h2>MEMORY</h2><div id=memorylist style="margin-bottom:8px"></div>
<div class=row><input id=memoryinput maxlength=140 placeholder="A preference to remember">
<button onclick="addMemory()">Save</button></div>
<button onclick="clearMemories()" style="width:100%%;margin-top:8px">Forget all memories</button>
<script>
const NAMES={plan:'Plan',pal:'Pal',limits:'Limits',room:'Today',pixel:'Game',flights:'Flights',music:'Music',track:'My flight'};
const sc=document.getElementById('screens');
for(const n in NAMES){const b=document.createElement('button');b.textContent=NAMES[n];b.id='s-'+n;b.onclick=()=>go('/screen?name='+n);sc.appendChild(b)}
async function go(p){await fetch(p,{method:'POST'}).catch(()=>{});refresh()}
async function refresh(){try{const s=await(await fetch('/state')).json();
for(const n in NAMES)document.getElementById('s-'+n).className=s.screen==n?'on':'';
st.textContent=([s.alert,s.timer,s.music,s.track].filter(Boolean).join('\\n')||'On: '+(NAMES[s.screen]||s.screen))+'\\nWake phrase: '+s.wake;
vol.textContent='volume '+s.volume+' / 10';
cal.textContent=s.calendars.length?s.calendar:'Not connected. iCloud (Mac Calendar app): right-click a calendar > Share Calendar > Public Calendar, copy the webcal:// link and paste it here. Anyone with that link can see the calendar. Add up to 3.';
const cb=document.getElementById('cals');if(cb.dataset.v!=s.calendars.join()){cb.dataset.v=s.calendars.join();cb.textContent='';
s.calendars.forEach((n,i)=>{const row=document.createElement('div');row.className='row';row.style.cssText='margin-bottom:8px;align-items:center';
const v=document.createElement('div');v.textContent='Calendar '+(i+1)+' ('+n+')';row.append(v,btn('Remove',()=>go('/calendar/remove?i='+i)));cb.appendChild(row)})}
trk.textContent=s.flight?'Following '+s.track:'Not following a flight';document.getElementById('s-track').style.display=s.flight?'':'none';
lim.textContent=s.limits.length?'Read directly from: '+s.limits.join(', '):'Not signed in: reading the relay'}catch(e){st.textContent='board not reachable'}}
async function addCal(){const v=ics.value.trim();if(!v)return;const r=await step('/calendar?ics='+encodeURIComponent(v));
if(r.error)alert(r.error);else ics.value='';refresh()}
async function setVol(q){await step('/volume?'+q);refresh()}
async function planDo(d,q){await step('/plan?do='+d+'&'+q);refreshPlan()}
function btn(label,f){const b=document.createElement('button');b.textContent=label;b.onclick=f;b.style.flex='0 0 auto';return b}
async function refreshPlan(){try{const p=await(await fetch('/plan')).json();
const tb=document.getElementById('tasks');tb.textContent='';
if(!p.tasks.length)tb.textContent='Nothing to do';
for(const t of p.tasks){const row=document.createElement('div');row.className='row';row.style.cssText='margin-bottom:8px;align-items:center';
const v=document.createElement('div');v.textContent=(t.done?'[x] ':'[ ] ')+t.t;v.style.opacity=t.done?.5:1;
row.append(v,btn(t.done?'Undo':'Done',()=>planDo('task_done','done='+(t.done?0:1)+'&text='+encodeURIComponent(t.t))),
btn('Remove',()=>planDo('task_remove','text='+encodeURIComponent(t.t))));tb.appendChild(row)}
const pb=document.getElementById('projects');pb.textContent='';
if(!p.projects.length)pb.textContent='No projects yet';
for(const pr of p.projects){const row=document.createElement('div');row.className='row';row.style.cssText='margin-bottom:8px;align-items:center';
const v=document.createElement('div');v.textContent=pr.n;const sel=document.createElement('select');
sel.style.cssText='font:inherit;padding:10px;border-radius:12px;flex:0 0 auto';
for(const s of p.stages){const o=document.createElement('option');o.value=o.textContent=s;o.selected=s==pr.s;sel.appendChild(o)}
sel.onchange=()=>planDo('project','name='+encodeURIComponent(pr.n)+'&stage='+sel.value);
row.append(v,sel,btn('Remove',()=>planDo('project_remove','name='+encodeURIComponent(pr.n))));pb.appendChild(row)}
}catch(e){document.getElementById('tasks').textContent='Tasks unavailable'}}
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
async function refreshMemories(){try{const entries=await(await fetch('/memories')).json();
const box=document.getElementById('memorylist');box.textContent='';
if(!entries.length){box.textContent='Nothing saved yet';return}
entries.forEach((entry,index)=>{const row=document.createElement('div');row.className='row';row.style.marginBottom='8px';
const value=document.createElement('div');value.textContent=entry;value.style.padding='10px 0';
const remove=document.createElement('button');remove.textContent='Forget';
remove.onclick=()=>deleteMemory(index);row.append(value,remove);box.appendChild(row)})
}catch(e){document.getElementById('memorylist').textContent='Memory unavailable'}}
async function addMemory(){const value=document.getElementById('memoryinput').value.trim();if(!value)return;
const result=await step('/memories/add?text='+encodeURIComponent(value));
if(result.ok)document.getElementById('memoryinput').value='';refreshMemories()}
async function deleteMemory(index){await step('/memories/delete?index='+index);refreshMemories()}
async function clearMemories(){await step('/memories/clear');refreshMemories()}
document.getElementById('locbtn').addEventListener('click',()=>{
window.location.href='https://desk-voice.vercel.app/api/locate?board='+encodeURIComponent(window.location.host)});
refresh();wifi();refreshMemories();refreshPlan();setInterval(refresh,3000);
</script></body></html>"""

def page():
    return PAGE.replace("%%", "%")
