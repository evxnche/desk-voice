// "Use my phone's location": browsers only share GPS with https pages, and the board's own page is
// plain http on the LAN. So the remote page opens this page, which reads the location and navigates
// straight back to the board (?board=<its LAN address>) with it. Nothing is stored here.
//   GET ?board=IP                -> the page
//   GET ?action=name&lat=&lon=   -> {place} for the page to show
import { reverseGeocode } from '../lib/flights.js';

const PRIVATE = /^(192\.168|10)\.\d{1,3}\.\d{1,3}(\.\d{1,3})?$|^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/;

const PAGE = (board) => `<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Desk Pal location</title>
<style>body{font:17px/1.5 ui-monospace,Menlo,monospace;background:#f4f1ea;color:#1d1d1b;max-width:520px;margin:auto;padding:24px}
@media (prefers-color-scheme:dark){body{background:#161614;color:#eceae4}}h1{font-size:20px;letter-spacing:.08em}</style></head>
<body><h1>DESK PAL</h1><p id=m>Asking for your location…</p><script>
const board=${JSON.stringify(board)};
const m=document.getElementById('m');
if(!board){m.textContent='Open this from the Desk Pal remote page.'}
else navigator.geolocation.getCurrentPosition(async p=>{
  const lat=p.coords.latitude.toFixed(5),lon=p.coords.longitude.toFixed(5);
  m.textContent='Found you (±'+Math.round(p.coords.accuracy)+' m). Looking up the area…';
  let place='';try{place=(await(await fetch('?action=name&lat='+lat+'&lon='+lon)).json()).place}catch(e){}
  m.textContent='Sending '+(place||'your location')+' to the board…';
  location.href='http://'+board+'/location?lat='+lat+'&lon='+lon+'&place='+encodeURIComponent(place);
},e=>{m.textContent='Location not available: '+e.message+'. Allow location for this site and try again.'},
{enableHighAccuracy:true,timeout:20000,maximumAge:60000});
</script></body></html>`;

export async function GET(request) {
  const url = new URL(request.url);
  if (url.searchParams.get('action') === 'name') {
    const lat = Number(url.searchParams.get('lat')), lon = Number(url.searchParams.get('lon'));
    const place = Number.isFinite(lat) && Number.isFinite(lon) ? await reverseGeocode(lat, lon) : '';
    return Response.json({ place });
  }
  const board = url.searchParams.get('board') || '';
  return new Response(PAGE(PRIVATE.test(board) ? board : ''), { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}
