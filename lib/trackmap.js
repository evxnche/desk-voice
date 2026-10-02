// A small 1-bit map for the board's flight tracker: country borders (Natural Earth 1:50m via
// world-atlas), land dotted, sea blank, the flight's route dashed. The board draws the plane on top
// itself, so it can glide between fetches, and the country names in its own font.
// Projection: equirectangular around (lat, lon), `kmpx` km per pixel; the board uses the same maths.
import sharp from 'sharp';
import { feature } from 'topojson-client';
import world from 'world-atlas/countries-50m.json' with { type: 'json' };

const KM_PER_DEG = 111.32;
const RAD = Math.PI / 180;

// Every country's polygons once per warm instance, with a lat/lon bounding box to skip far ones.
const countries = feature(world, world.objects.countries).features.map((f) => {
  const polys = f.geometry?.type === 'Polygon' ? [f.geometry.coordinates]
    : f.geometry?.type === 'MultiPolygon' ? f.geometry.coordinates : [];
  let [w, s, e, n] = [180, 90, -180, -90];
  for (const p of polys) for (const [x, y] of p[0]) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
  return { name: f.properties.name, polys, box: [w, s, e, n] };
});

function projector(lat0, lon0, kmpx, w, h) {
  const kx = (Math.cos(lat0 * RAD) * KM_PER_DEG) / kmpx, ky = KM_PER_DEG / kmpx;
  return ([lon, lat]) => [w / 2 + (lon - lon0) * kx, h / 2 - (lat - lat0) * ky];
}

// Points along the great circle between two airports.
function greatCircle(lat1, lon1, lat2, lon2, n = 96) {
  const toV = (la, lo) => [Math.cos(la * RAD) * Math.cos(lo * RAD), Math.cos(la * RAD) * Math.sin(lo * RAD), Math.sin(la * RAD)];
  const a = toV(lat1, lon1), b = toV(lat2, lon2);
  const d = Math.acos(Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  if (d < 1e-6) return [[lon1, lat1]];
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, sa = Math.sin((1 - t) * d) / Math.sin(d), sb = Math.sin(t * d) / Math.sin(d);
    const v = [0, 1, 2].map((k) => sa * a[k] + sb * b[k]);
    pts.push([Math.atan2(v[1], v[0]) / RAD, Math.atan2(v[2], Math.hypot(v[0], v[1])) / RAD]);
  }
  return pts;
}

/**
 * {meta, bitmap}: bitmap is MONO_HLSB (w a multiple of 8), 1 = ink. meta.labels = [[name, x, y]]:
 * where to write each country's name (biggest first, none overlapping).
 */
export async function renderMap({ lat, lon, kmpx, w, h, route, via }) {
  const proj = projector(lat, lon, kmpx, w, h);
  const halfLon = (w / 2) * kmpx / (Math.cos(lat * RAD) * KM_PER_DEG) + 1, halfLat = (h / 2) * kmpx / KM_PER_DEG + 1;
  const view = [lon - halfLon, lat - halfLat, lon + halfLon, lat + halfLat];
  const paths = [], candidates = [];
  for (const c of countries) {
    const [cw, cs, ce, cn] = c.box;
    if (ce < view[0] || cw > view[2] || cn < view[1] || cs > view[3]) continue;
    let d = '', best = null;
    for (const poly of c.polys) {
      for (const ring of poly) {
        const pts = ring.map(proj);
        d += 'M' + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L') + 'Z';
      }
      // Label at the middle of the country's biggest piece that's on screen.
      const pts = poly[0].map(proj).filter(([x, y]) => x >= 0 && x < w && y >= 0 && y < h);
      if (pts.length > (best?.length ?? 2)) best = pts;
    }
    paths.push(d);
    if (best) {
      const xs = best.map((p) => p[0]), ys = best.map((p) => p[1]);
      const span = Math.max(...xs) - Math.min(...xs);
      if (span > 34) candidates.push({ name: c.name, x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2, span });
    }
  }
  let routeSvg = '';
  if (route) {
    // Through the plane (`via`) when given: real flights stray 100+ km off the airport-to-airport
    // line (winds, airways, closed airspace), and the plane should sit on the line it's drawn on.
    const [lat1, lon1, lat2, lon2] = route;
    const pts = (via ? [...greatCircle(lat1, lon1, ...via), ...greatCircle(...via, lat2, lon2)]
      : greatCircle(...route)).map(proj);
    const d = 'M' + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L');
    // White edging so the dashes stand out from the dotted land.
    routeSvg = `<path d="${d}" fill="none" stroke="#fff" stroke-width="5"/>` +
      `<path d="${d}" fill="none" stroke="#000" stroke-width="2" stroke-dasharray="6 4"/>`;
  }
  // Land grey (dotted below), borders and coasts black.
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" shape-rendering="crispEdges">` +
    `<rect width="${w}" height="${h}" fill="#fff"/>` +
    paths.map((d) => `<path d="${d}" fill="#c8c8c8" fill-rule="evenodd" stroke="#000" stroke-width="1"/>`).join('') +
    routeSvg + '</svg>';
  const { data } = await sharp(Buffer.from(svg)).greyscale().raw().toBuffer({ resolveWithObject: true });
  const bitmap = Buffer.alloc((w / 8) * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const v = data[y * w + x];
      const ink = v < 100 || (v < 240 && x % 4 === (y % 8 < 4 ? 0 : 2) && y % 4 === 0);
      if (ink) bitmap[y * (w / 8) + (x >> 3)] |= 0x80 >> (x & 7);
    }
  }
  const labels = [], boxes = [];
  for (const c of candidates.sort((a, b) => b.span - a.span)) {
    const name = c.name.length > 14 ? c.name.slice(0, 13) + '.' : c.name;
    const bw = name.length * 6 + 4, box = [Math.round(c.x - bw / 2), Math.round(c.y - 6), bw, 12];
    if (box[0] < 2 || box[0] + bw > w - 2 || box[1] < 2 || box[1] + 12 > h - 2) continue;
    if (boxes.some((b) => box[0] < b[0] + b[2] && b[0] < box[0] + bw && box[1] < b[1] + b[3] && b[1] < box[1] + 12)) continue;
    boxes.push(box);
    labels.push([name, box[0] + 2, box[1] + 2]);
    if (labels.length >= 6) break;
  }
  return { meta: { lat, lon, kmpx, w, h, labels }, bitmap };
}
