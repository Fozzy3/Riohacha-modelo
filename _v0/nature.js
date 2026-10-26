// Site context: terrain, ground layers, OSM roads/buildings/water, vegetation and people.
import * as THREE from 'three';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { toLocal } from './geo.js';
import { pointInPolygon, offsetPolygon, polygonShapeGeometry } from './building.js';

// Deterministic random so every visitor sees the same landscape.
let seed = 7;
const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

function imagePixels(img) {
  const c = document.createElement('canvas');
  c.width = img.width;
  c.height = img.height;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const { data } = ctx.getImageData(0, 0, c.width, c.height);
  // Sample by local meters (x east, z south) over the same bbox as the terrain.
  return (half) => (x, z) => {
    const px = Math.min(c.width - 1, Math.max(0, Math.round(((x + half) / (2 * half)) * (c.width - 1))));
    const py = Math.min(c.height - 1, Math.max(0, Math.round(((z + half) / (2 * half)) * (c.height - 1))));
    const i = (py * c.width + px) * 4;
    return [data[i] / 255, data[i + 1] / 255, data[i + 2] / 255];
  };
}

// Vegetation index from the Sentinel-2 RGB mosaic: 0 = bare/dry, 1 = green canopy.
const greenness = ([r, g, b]) => THREE.MathUtils.smoothstep((g - r) / (g + r + 1e-3) + (g - b) * 0.5, -0.02, 0.12);

export function buildTerrain(terrain, groundImg, site, mats) {
  const { size, half, h } = terrain;
  const step = (2 * half) / (size - 1);
  const raw = (x, z) => {
    const fx = Math.min(size - 1.001, Math.max(0, (x + half) / step));
    const fz = Math.min(size - 1.001, Math.max(0, (z + half) / step));
    const c = Math.floor(fx), r = Math.floor(fz), tx = fx - c, tz = fz - r;
    const at = (rr, cc) => h[rr * size + cc];
    return (at(r, c) * (1 - tx) + at(r, c + 1) * tx) * (1 - tz) + (at(r + 1, c) * (1 - tx) + at(r + 1, c + 1) * tx) * tz;
  };
  const siteH = raw(site.x, site.z);
  // Flatten the CIP platform, blend back to the real DEM between 80 and 150 m.
  const heightAt = (x, z) => {
    const d = Math.hypot(x - site.x, z - site.z);
    return (raw(x, z) - siteH) * THREE.MathUtils.smoothstep(d, 80, 150);
  };
  const sample = imagePixels(groundImg)(half);

  const segs = 256;
  const geo = new THREE.PlaneGeometry(2 * half, 2 * half, segs, segs);
  geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  const grass = new Float32Array(pos.count);
  const uv = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i);
    pos.setY(i, heightAt(x, z) - 0.05);
    grass[i] = greenness(sample(x, z));
    uv.setXY(i, x / 8, z / 8);
  }
  geo.setAttribute('grass', new THREE.BufferAttribute(grass, 1));
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, mats.terrain);
  mesh.receiveShadow = true;
  return { mesh, heightAt, sample, half };
}

// Terrain material: dry ground blended with grass by the satellite vegetation index.
export function terrainMaterial(dry, grass) {
  const m = new THREE.MeshStandardMaterial({ map: dry.map, normalMap: dry.normalMap, roughness: 1, metalness: 0 });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.grassMap = { value: grass.map };
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float grass;\nvarying float vGrass;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGrass = grass;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform sampler2D grassMap;\nvarying float vGrass;')
      .replace(
        '#include <map_fragment>',
        `vec4 dryC = texture2D(map, vMapUv);
         vec4 grsC = texture2D(grassMap, vMapUv * 0.7);
         float n = fract(sin(dot(floor(vMapUv * 0.5), vec2(12.9898, 78.233))) * 43758.5453);
         diffuseColor *= mix(dryC * vec4(1.12, 1.0, 0.9, 1.0), grsC * vec4(0.85, 0.95, 0.7, 1.0), clamp(vGrass + (n - 0.5) * 0.25, 0.0, 1.0));`,
      );
  };
  return m;
}

export function buildSiteGround(spec, toL, mats) {
  const g = new THREE.Group();
  const lot = spec.site.lot.map(toL);
  const layer = (poly, y, mat) => {
    const m = new THREE.Mesh(polygonShapeGeometry(poly, y), mat);
    m.receiveShadow = true;
    g.add(m);
  };
  layer(lot, 0.02, mats.lawn);
  layer(offsetPolygon(lot, 3.2), 0.04, mats.pavers);
  layer(spec.site.walk.map(toL), 0.06, mats.concrete);
  layer(spec.site.garden.map(toL), 0.06, mats.lawn);
  for (const l of spec.site.lawns) layer(l.map(toL), 0.03, mats.lawn);
  return { group: g, lot };
}

function ribbon(points, width, heightAt, lift) {
  const P = [], U = [], I = [];
  let dist = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[Math.max(0, i - 1)], b = points[Math.min(points.length - 1, i + 1)];
    const dx = b[0] - a[0], dz = b[1] - a[1];
    const len = Math.hypot(dx, dz) || 1;
    const nx = -dz / len, nz = dx / len;
    if (i > 0) dist += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    for (const s of [-1, 1]) {
      const x = points[i][0] + (nx * width * s) / 2, z = points[i][1] + (nz * width * s) / 2;
      P.push(x, heightAt(x, z) + lift, z);
      U.push(s < 0 ? 0 : 1, dist / width);
    }
    if (i > 0) {
      const k = i * 2;
      I.push(k - 2, k, k - 1, k - 1, k, k + 1);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(U, 2));
  geo.setIndex(I);
  geo.computeVertexNormals();
  // Ribbons are generated in either direction; make sure they face up.
  if (geo.attributes.normal.getY(0) < 0) geo.setIndex(I.map((_, j) => I[j - (j % 3) + [0, 2, 1][j % 3]]));
  geo.computeVertexNormals();
  return geo;
}

const ROAD_WIDTH = { primary: 9, trunk: 9, secondary: 8, tertiary: 7, residential: 5.5, service: 4, unclassified: 5.5 };

export function buildContext(osm, heightAt, lot, mats) {
  const group = new THREE.Group();
  const roads = [], waters = [], buildings = [], blockers = [];
  const lotGuard = offsetPolygon(lot, -15);
  for (const f of osm) {
    const pts = f.pts.map(([lat, lon]) => {
      const p = toLocal(lat, lon);
      return [p.x, p.z];
    });
    if (f.kind === 'road') {
      const w = ROAD_WIDTH[f.tag] ?? (f.tag === 'footway' || f.tag === 'path' || f.tag === 'track' ? 2.5 : 4.5);
      roads.push(ribbon(pts, w, heightAt, 0.12));
      blockers.push({ pts, r: w / 2 + 4 });
    } else if (f.kind === 'water') {
      waters.push(ribbon(pts, f.tag ? 6 : 14, heightAt, 0.05));
      blockers.push({ pts, r: 12 });
    } else if (f.kind === 'building' && pts.length > 3) {
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cz = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      if (pointInPolygon([cx, cz], lotGuard)) continue; // keep the CIP platform clear
      const levels = Number(f.levels) || (rand() < 0.75 ? 1 : 2);
      const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
      const geo = new THREE.ExtrudeGeometry(shape, { depth: levels * 3.4 + rand() * 0.8, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      geo.translate(0, Math.min(...pts.map(([x, z]) => heightAt(x, z))) - 0.2, 0);
      buildings.push(geo);
      blockers.push({ pts, r: 3, poly: true });
    }
  }
  const add = (list, mat, cast) => {
    if (!list.length) return;
    const m = new THREE.Mesh(mergeGeometries(list), mat);
    m.receiveShadow = true;
    m.castShadow = cast;
    group.add(m);
  };
  add(roads, mats.asphalt, false);
  add(waters, mats.water, false);
  add(buildings, mats.neighbour, true);
  return { group, blockers };
}

function distToPolyline(x, z, pts) {
  let best = Infinity;
  for (let i = 1; i < pts.length; i++) {
    const [ax, az] = pts[i - 1], [bx, bz] = pts[i];
    const dx = bx - ax, dz = bz - az;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1)));
    best = Math.min(best, Math.hypot(x - ax - t * dx, z - az - t * dz));
  }
  return best;
}

function canopyGeometry() {
  const parts = [];
  for (let i = 0; i < 5; i++) {
    const s = new THREE.IcosahedronGeometry(1, 2);
    const p = s.attributes.position;
    for (let k = 0; k < p.count; k++) {
      const v = new THREE.Vector3().fromBufferAttribute(p, k);
      v.multiplyScalar(0.85 + 0.3 * Math.sin(v.x * 5.1 + i) * Math.cos(v.y * 4.3 + v.z * 3.7));
      p.setXYZ(k, v.x, v.y * 0.75, v.z);
    }
    const a = (i / 5) * Math.PI * 2;
    s.scale(1.2, 1, 1.2);
    s.translate(i ? Math.cos(a) * 1.1 : 0, i ? -0.2 + rand() * 0.5 : 0.4, i ? Math.sin(a) * 1.1 : 0);
    parts.push(s);
  }
  const g = mergeVertices(mergeGeometries(parts.map((p) => p.deleteAttribute('uv').deleteAttribute('normal'))));
  g.computeVertexNormals();
  return g;
}

// Tropical dry forest scattered where the satellite image is green, away from roads/buildings/CIP.
export function scatterTrees(terrain, blockers, lot, mats, count) {
  const { heightAt, sample, half } = terrain;
  const keepOut = offsetPolygon(lot, -6);
  const spots = [];
  for (let tries = 0; spots.length < count && tries < count * 12; tries++) {
    const x = (rand() * 2 - 1) * (half - 20), z = (rand() * 2 - 1) * (half - 20);
    if (rand() > greenness(sample(x, z)) ** 1.3) continue;
    if (pointInPolygon([x, z], keepOut)) continue;
    if (blockers.some((b) => (b.poly && pointInPolygon([x, z], b.pts)) || distToPolyline(x, z, b.pts) < b.r)) continue;
    spots.push([x, z]);
  }
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.12, 0.22, 1, 6).translate(0, 0.5, 0), mats.bark, spots.length);
  const crowns = new THREE.InstancedMesh(canopyGeometry(), mats.leaves, spots.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color();
  const greens = [0x4f6b2a, 0x5d7a31, 0x6b7f35, 0x3f5a26, 0x7a8240, 0x8a8a45];
  spots.forEach(([x, z], i) => {
    const s = 0.7 + rand() * 1.1, y = heightAt(x, z), trunkH = 2 + s * 1.6;
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rand() * Math.PI * 2);
    trunks.setMatrixAt(i, m.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(s, trunkH, s)));
    crowns.setMatrixAt(i, m.compose(new THREE.Vector3(x, y + trunkH + 1.2 * s, z), q, new THREE.Vector3(2 * s, 1.6 * s, 2 * s)));
    crowns.setColorAt(i, c.setHex(greens[Math.floor(rand() * greens.length)]).multiplyScalar(0.85 + rand() * 0.3));
  });
  for (const mesh of [trunks, crowns]) mesh.castShadow = mesh.receiveShadow = true;
  const g = new THREE.Group();
  g.add(trunks, crowns);
  return g;
}

// Palm frond texture drawn on a canvas: central rib with drooping leaflets.
function frondTexture() {
  const c = document.createElement('canvas');
  c.width = 128;
  c.height = 512;
  const ctx = c.getContext('2d');
  ctx.lineCap = 'round';
  for (let y = 20; y < 500; y += 7) {
    const t = y / 512, len = 58 * Math.sin(Math.PI * Math.min(1, t * 1.1)) + 6;
    for (const s of [-1, 1]) {
      ctx.strokeStyle = `hsl(${88 + rand() * 18}, ${45 + rand() * 15}%, ${24 + rand() * 12}%)`;
      ctx.lineWidth = 3.2;
      ctx.beginPath();
      ctx.moveTo(64, y);
      ctx.quadraticCurveTo(64 + s * len * 0.6, y + 4, 64 + s * len, y + 16 + t * 14);
      ctx.stroke();
    }
  }
  ctx.strokeStyle = '#6b6a3a';
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(64, 0);
  ctx.lineTo(64, 512);
  ctx.stroke();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function buildPalms(points, heightAt, mats) {
  const g = new THREE.Group();
  const frondMat = new THREE.MeshStandardMaterial({ map: frondTexture(), alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.8 });
  for (const [x, z] of points) {
    const H = 9 + rand() * 3, lean = new THREE.Vector3(rand() - 0.5, 0, rand() - 0.5).multiplyScalar(1.2);
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 0, 0),
      new THREE.Vector3(lean.x * 0.3, H * 0.4, lean.z * 0.3),
      new THREE.Vector3(lean.x, H, lean.z),
    ]);
    const trunk = new THREE.Mesh(new THREE.TubeGeometry(curve, 20, 0.22, 10), mats.palmBark);
    trunk.castShadow = trunk.receiveShadow = true;
    const fronds = [];
    for (let i = 0; i < 16; i++) {
      const f = new THREE.PlaneGeometry(1.4, 4.2, 1, 10);
      const p = f.attributes.position;
      for (let k = 0; k < p.count; k++) {
        const along = (p.getY(k) + 2.1) / 4.2; // 0 at the crown, 1 at the tip
        p.setXYZ(k, p.getX(k), along * 4.2, -along * along * 2.2);
      }
      f.rotateX(-Math.PI / 2 + 0.55 + (i % 2) * 0.25);
      f.rotateY((i / 16) * Math.PI * 2 + rand() * 0.2);
      f.translate(lean.x, H, lean.z);
      fronds.push(f);
    }
    const crown = new THREE.Mesh(mergeGeometries(fronds), frondMat);
    crown.castShadow = true;
    const palm = new THREE.Group();
    palm.add(trunk, crown);
    palm.position.set(x, heightAt(x, z), z);
    g.add(palm);
  }
  return g;
}

// Ornamental shrubs (bougainvillea) and medium plants along the green band of the lot.
export function buildShrubs(lot, counts, mats) {
  const band = offsetPolygon(lot, 1.6);
  const per = [];
  let total = 0;
  for (let i = 0; i < band.length; i++) {
    const a = band[i], b = band[(i + 1) % band.length];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
    per.push([a, b, l]);
    total += l;
  }
  const at = (d) => {
    for (const [a, b, l] of per) {
      if (d <= l) return [a[0] + ((b[0] - a[0]) * d) / l, a[1] + ((b[1] - a[1]) * d) / l];
      d -= l;
    }
    return band[0];
  };
  const n = counts.ornamental + counts.medium;
  const bush = canopyGeometry();
  const foliage = new THREE.InstancedMesh(bush, mats.leaves, n);
  const flowers = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), mats.flowers, counts.ornamental * 6);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color();
  let fi = 0;
  for (let i = 0; i < n; i++) {
    const [x, z] = at(((i + 0.5) / n) * total);
    const ornamental = i % 4 !== 3 && fi < flowers.count;
    const s = ornamental ? 0.7 + rand() * 0.3 : 1.1 + rand() * 0.4;
    foliage.setMatrixAt(i, m.compose(new THREE.Vector3(x, 0.6 * s, z), q, new THREE.Vector3(s, s * 0.8, s)));
    foliage.setColorAt(i, c.setHex(ornamental ? 0x3e6b2c : 0x55782e));
    if (ornamental) {
      for (let k = 0; k < 6; k++) {
        const a = rand() * Math.PI * 2, r = 0.8 * s;
        flowers.setMatrixAt(fi, m.compose(new THREE.Vector3(x + Math.cos(a) * r, (0.8 + rand() * 0.6) * s, z + Math.sin(a) * r), q, new THREE.Vector3(0.38, 0.3, 0.38).multiplyScalar(s)));
        flowers.setColorAt(fi++, c.setHex(rand() < 0.7 ? 0xc2185b : 0xe0559a));
      }
    }
  }
  flowers.count = fi;
  for (const mesh of [foliage, flowers]) mesh.castShadow = mesh.receiveShadow = true;
  const g = new THREE.Group();
  g.add(foliage, flowers);
  return g;
}

// People walking loops across the plaza (Mixamo characters from the three.js examples).
export async function buildPeople(routes, manager, count) {
  const loader = new GLTFLoader(manager);
  const [xbot, michelle] = await Promise.all([loader.loadAsync('assets/Xbot.glb'), loader.loadAsync('assets/Michelle.glb')]);
  const inPlace = (clip) => {
    const c = clip.clone();
    c.tracks = c.tracks.filter((t) => !t.name.endsWith('.position'));
    return c;
  };
  const walk = inPlace(xbot.animations.find((a) => a.name === 'walk'));
  const idle = inPlace(xbot.animations.find((a) => a.name === 'idle'));
  const outfits = [0x2f4858, 0x8c3b2b, 0xd9c7a7, 0x3b5d3a, 0x6d6875, 0xe8e2d6, 0x1f3a5f];

  // Skinned bounding boxes are unreliable before the first skeleton update, so measure bone heights.
  const sourceHeight = (root) => {
    root.updateMatrixWorld(true);
    let min = Infinity, max = -Infinity;
    const v = new THREE.Vector3();
    root.traverse((o) => {
      if (!o.isBone) return;
      o.getWorldPosition(v);
      min = Math.min(min, v.y);
      max = Math.max(max, v.y);
    });
    return (max - min) * 1.08; // head-top bone sits a little below the scalp
  };
  const heights = new Map([[xbot.scene, sourceHeight(xbot.scene)], [michelle.scene, sourceHeight(michelle.scene)]]);
  const onlyExisting = (clip, root) => {
    const names = new Set();
    root.traverse((o) => names.add(o.name));
    const c = clip.clone();
    c.tracks = c.tracks.filter((t) => names.has(THREE.PropertyBinding.parseTrackName(t.name).nodeName));
    return c;
  };
  const people = [];
  for (let i = 0; i < count; i++) {
    const useMichelle = i % 3 !== 2;
    const source = (useMichelle ? michelle : xbot).scene;
    const body = SkeletonUtils.clone(source);
    body.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.frustumCulled = false;
      if (!useMichelle) {
        o.material = o.material.clone();
        o.material.color.setHex(outfits[i % outfits.length]);
      }
    });
    const holder = new THREE.Group();
    holder.add(body);
    body.scale.multiplyScalar((1.6 + rand() * 0.2) / heights.get(source));
    const mixer = new THREE.AnimationMixer(body);
    const route = routes[i % routes.length];
    const standing = i % 5 === 4;
    const action = mixer.clipAction(onlyExisting(standing ? idle : walk, body));
    action.time = rand() * 2;
    action.timeScale = 0.95 + rand() * 0.1;
    action.play();
    people.push({ holder, mixer, route, standing, t: rand(), speed: (1.15 + rand() * 0.25) / route.getLength() });
  }
  const group = new THREE.Group();
  for (const p of people) group.add(p.holder);
  const tangent = new THREE.Vector3();
  const update = (dt) => {
    for (const p of people) {
      p.mixer.update(dt);
      if (!p.standing) p.t = (p.t + p.speed * dt) % 1;
      p.route.getPointAt(p.t, p.holder.position);
      p.route.getTangentAt(p.t, tangent);
      p.holder.rotation.y = Math.atan2(tangent.x, tangent.z);
    }
  };
  return { group, update };
}
