import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ORIGIN, toLocal, sunPosition, sunVector } from './geo.js';

const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} not within ${tol} of ${b}`);

// Local time in Riohacha is UTC-5 all year (no DST).
const local = (y, m, d, h, min = 0) => new Date(Date.UTC(y, m - 1, d, h + 5, min));

test('origin maps to 0,0', () => {
  const p = toLocal(ORIGIN.lat, ORIGIN.lon);
  near(p.x, 0, 1e-9);
  near(p.z, 0, 1e-9);
});

test('north is -z, east is +x, about 111 km per degree of latitude', () => {
  const n = toLocal(ORIGIN.lat + 0.001, ORIGIN.lon);
  near(n.z, -111.2, 0.5);
  const e = toLocal(ORIGIN.lat, ORIGIN.lon + 0.001);
  near(e.x, 111.2 * Math.cos((ORIGIN.lat * Math.PI) / 180), 0.5);
});

test('June solstice noon: sun high and to the north', () => {
  const s = sunPosition(local(2026, 6, 21, 11, 53));
  near(s.altitude, 78, 1.5); // 90 - (23.44 - 11.52)
  assert.ok(s.azimuth < 30 || s.azimuth > 330, `azimuth ${s.azimuth}`);
});

test('December solstice noon: sun lower and to the south', () => {
  const s = sunPosition(local(2026, 12, 21, 11, 50));
  near(s.altitude, 55, 1.5); // 90 - (23.44 + 11.52)
  near(s.azimuth, 180, 15);
});

test('equinox: rises in the east around 06:00, sets in the west around 18:00', () => {
  const am = sunPosition(local(2026, 3, 20, 6, 0));
  const pm = sunPosition(local(2026, 3, 20, 18, 0));
  near(am.altitude, 0, 4);
  near(pm.altitude, 0, 4);
  near(am.azimuth, 90, 5);
  near(pm.azimuth, 270, 5);
});

test('sunVector: unit length, points up when sun is up', () => {
  const v = sunVector({ azimuth: 90, altitude: 30 });
  near(Math.hypot(...v), 1, 1e-9);
  assert.ok(v[0] > 0.8, 'east is +x');
  near(v[1], 0.5, 1e-9);
});
