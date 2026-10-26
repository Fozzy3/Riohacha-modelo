// Site origin: SENA Centro Industrial y de Energías Alternativas, Riohacha (OSM node 7827759449).
export const ORIGIN = { lat: 11.5156959, lon: -72.869435 };

const RAD = Math.PI / 180;
const M_PER_DEG = 111195; // mean Earth radius * PI / 180

// ponytail: equirectangular projection, error < 1 cm over the ~1 km scene.
// Three.js axes: x = east, y = up, z = south.
export function toLocal(lat, lon) {
  return {
    x: (lon - ORIGIN.lon) * M_PER_DEG * Math.cos(ORIGIN.lat * RAD),
    z: -(lat - ORIGIN.lat) * M_PER_DEG,
  };
}

// NOAA solar position (accurate to ~0.1° for current dates).
// Returns degrees: azimuth clockwise from north, altitude above horizon.
export function sunPosition(date, lat = ORIGIN.lat, lon = ORIGIN.lon) {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const t = (jd - 2451545) / 36525;

  const L0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360;
  const M = 357.52911 + t * (35999.05029 - 0.0001537 * t);
  const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
  const C =
    Math.sin(M * RAD) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
    Math.sin(2 * M * RAD) * (0.019993 - 0.000101 * t) +
    Math.sin(3 * M * RAD) * 0.000289;
  const omega = 125.04 - 1934.136 * t;
  const lambda = L0 + C - 0.00569 - 0.00478 * Math.sin(omega * RAD);
  const eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60;
  const eps = eps0 + 0.00256 * Math.cos(omega * RAD);
  const decl = Math.asin(Math.sin(eps * RAD) * Math.sin(lambda * RAD));

  const y = Math.tan((eps / 2) * RAD) ** 2;
  const eqTime =
    4 / RAD *
    (y * Math.sin(2 * L0 * RAD) -
      2 * e * Math.sin(M * RAD) +
      4 * e * y * Math.sin(M * RAD) * Math.cos(2 * L0 * RAD) -
      0.5 * y * y * Math.sin(4 * L0 * RAD) -
      1.25 * e * e * Math.sin(2 * M * RAD)); // minutes

  const utcMin = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  const trueSolarMin = (((utcMin + eqTime + 4 * lon) % 1440) + 1440) % 1440;
  const hourAngle = (trueSolarMin / 4 - 180) * RAD;

  const latR = lat * RAD;
  const cosZen = Math.sin(latR) * Math.sin(decl) + Math.cos(latR) * Math.cos(decl) * Math.cos(hourAngle);
  const zen = Math.acos(Math.min(1, Math.max(-1, cosZen)));
  const az = Math.atan2(
    Math.sin(hourAngle),
    Math.cos(hourAngle) * Math.sin(latR) - Math.tan(decl) * Math.cos(latR),
  ) / RAD + 180;

  return { azimuth: az % 360, altitude: 90 - zen / RAD };
}

// Unit vector from the scene toward the sun, in three.js axes.
export function sunVector({ azimuth, altitude }) {
  const a = azimuth * RAD;
  const h = altitude * RAD;
  return [Math.cos(h) * Math.sin(a), Math.sin(h), -Math.cos(h) * Math.cos(a)];
}
