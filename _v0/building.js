// Procedural CIP building from building.json (plan points in PDF units, heights in meters).
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

export function planToLocal(spec) {
  const [cx, cy] = spec.planCenter;
  const [ox, oz] = spec.siteOffset;
  const a = (spec.rotationDeg * Math.PI) / 180;
  return ([x, y]) => {
    const dx = (x - cx) * spec.ptToM;
    const dz = (y - cy) * spec.ptToM; // page y grows downward = south = +z
    return [ox + dx * Math.cos(a) - dz * Math.sin(a), oz + dx * Math.sin(a) + dz * Math.cos(a)];
  };
}

export function pointInPolygon([x, z], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

// ponytail: miter offset, fine for the gently concave lot outline; use clipper if outlines get spiky.
export function offsetPolygon(poly, d) {
  const n = poly.length;
  return poly.map((p, i) => {
    const prev = poly[(i - 1 + n) % n];
    const next = poly[(i + 1) % n];
    const n1 = inwardNormal(prev, p, poly);
    const n2 = inwardNormal(p, next, poly);
    const bx = n1[0] + n2[0];
    const bz = n1[1] + n2[1];
    const len = Math.hypot(bx, bz) || 1;
    const cos = (bx / len) * n1[0] + (bz / len) * n1[1];
    const k = d / Math.max(cos, 0.3);
    return [p[0] + (bx / len) * k, p[1] + (bz / len) * k];
  });
}

function inwardNormal(a, b, poly) {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const len = Math.hypot(dx, dz);
  const nx = -dz / len;
  const nz = dx / len;
  const mid = [(a[0] + b[0]) / 2 + nx * 0.05, (a[1] + b[1]) / 2 + nz * 0.05];
  return pointInPolygon(mid, poly) ? [nx, nz] : [-nx, -nz];
}

function sideKey(nx, nz) {
  const deg = ((Math.atan2(nx, -nz) * 180) / Math.PI + 360) % 360; // clockwise from north
  return DIRS[Math.round(deg / 45) % 8];
}

function bandsFor(skin, key) {
  if (skin[key]) return skin[key];
  const four = { NE: ['N', 'E'], SE: ['S', 'E'], SW: ['S', 'W'], NW: ['N', 'W'] }[key] || [];
  for (const k of four) if (skin[k]) return skin[k];
  return skin.default;
}

// Flat quad on the wall plane, outward-facing, UVs in meters / uvScale.
function quad(a, b, y0, y1, n, off, uvScale, u0 = 0) {
  const ax = a[0] + n[0] * off, az = a[1] + n[1] * off;
  const bx = b[0] + n[0] * off, bz = b[1] + n[1] * off;
  const len = Math.hypot(bx - ax, bz - az);
  const P = [ax, y0, az, bx, y0, bz, bx, y1, bz, ax, y0, az, bx, y1, bz, ax, y1, az];
  const u1 = u0 + len / uvScale, v0 = y0 / uvScale, v1 = y1 / uvScale;
  const U = [u0, v0, u1, v0, u1, v1, u0, v0, u1, v1, u0, v1];
  // Triangle normal of A0,B0,B1 is (-dz, 0, dx); flip winding if that points inward.
  if (-(bz - az) * n[0] + (bx - ax) * n[1] < 0) {
    for (const arr of [P]) for (const [i, j] of [[3, 6], [12, 15]]) for (let k = 0; k < 3; k++) [arr[i + k], arr[j + k]] = [arr[j + k], arr[i + k]];
    for (const [i, j] of [[2, 4], [8, 10]]) for (let k = 0; k < 2; k++) [U[i + k], U[j + k]] = [U[j + k], U[i + k]];
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(U, 2));
  g.computeVertexNormals();
  return g;
}

const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _s = new THREE.Vector3(), _p = new THREE.Vector3();
function boxMatrix(x, y, z, sx, sy, sz, yaw, roll = 0) {
  _e.set(0, yaw, roll, 'YXZ');
  return _m.compose(_p.set(x, y, z), _q.setFromEuler(_e), _s.set(sx, sy, sz)).clone();
}

export function polygonShapeGeometry(poly, y) {
  const shape = new THREE.Shape(poly.map(([x, z]) => new THREE.Vector2(x, -z)));
  const g = new THREE.ShapeGeometry(shape);
  g.rotateX(-Math.PI / 2);
  g.translate(0, y, 0);
  const pos = g.attributes.position;
  const uv = [];
  for (let i = 0; i < pos.count; i++) uv.push(pos.getX(i) / 4, pos.getZ(i) / 4);
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  return g;
}

export function buildCIP(spec, mat) {
  const toL = planToLocal(spec);
  const group = new THREE.Group();
  const quads = { glassA: [], glassB: [], stucco: [], roof: [], slab: [] };
  const boxes = { wood: [], dark: [], alu: [], white: [], pv: [], hvac: [] };
  let rnd = 1;
  const random = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647); // deterministic lit windows

  for (const block of spec.blocks) {
    const poly = block.poly.map(toL);
    const top = Math.max(block.top, block.roof + 0.6);
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      const n = inwardNormal(a, b, poly).map((v) => -v);
      const dx = b[0] - a[0], dz = b[1] - a[1];
      const len = Math.hypot(dx, dz);
      const ux = dx / len, uz = dz / len;
      const yaw = Math.atan2(-dz, dx);
      const at = (t, off) => [a[0] + ux * t + n[0] * off, a[1] + uz * t + n[1] * off];
      let y0 = 0;
      const bands = bandsFor(block.skin, sideKey(n[0], n[1]));
      bands.forEach((band, bi) => {
        const y1 = bi === bands.length - 1 ? top : band.to;
        const h = y1 - y0;
        if (band.type === 'stucco') {
          quads.stucco.push(quad(a, b, y0, y1, n, 0, 3));
        } else {
          // Glass behind every non-stucco band, split in 1.5 m bays so some light up at night.
          const bays = Math.max(1, Math.round(len / 1.5));
          for (let k = 0; k < bays; k++) {
            const pa = at((k * len) / bays, 0), pb = at(((k + 1) * len) / bays, 0);
            (random() < 0.55 ? quads.glassA : quads.glassB).push(quad(pa, pb, y0, y1, n, 0, 3));
            const [mx, mz] = at((k * len) / bays, 0.04);
            boxes.alu.push(boxMatrix(mx, y0 + h / 2, mz, 0.06, h, 0.1, yaw));
          }
          if (band.type === 'glassX') {
            const levels = block.floors.filter((f) => f >= y0 - 0.01 && f < y1 - 0.5).concat([y1]);
            for (let f = 0; f < levels.length - 1; f++) {
              const fh = levels[f + 1] - levels[f];
              const nb = Math.max(1, Math.round(len / 3));
              for (let k = 0; k < nb; k++) {
                const bw = len / nb;
                const [cx, cz] = at((k + 0.5) * bw, 0.08);
                const dl = Math.hypot(bw, fh), ang = Math.atan2(fh, bw);
                boxes.alu.push(boxMatrix(cx, levels[f] + fh / 2, cz, dl, 0.08, 0.08, yaw, ang));
                boxes.alu.push(boxMatrix(cx, levels[f] + fh / 2, cz, dl, 0.08, 0.08, yaw, -ang));
              }
            }
          }
          if (band.type === 'slats' || band.type === 'darkSlats') {
            const list = band.type === 'slats' ? boxes.wood : boxes.dark;
            const count = Math.floor((len - 0.3) / 0.3);
            for (let k = 0; k <= count; k++) {
              const [sx, sz] = at(0.15 + k * 0.3, 0.55);
              list.push(boxMatrix(sx, y0 + h / 2, sz, 0.07, h, 0.22, yaw));
            }
            for (const yy of [y0 + 0.05, y1 - 0.05]) {
              const [rx, rz] = at(len / 2, 0.55);
              boxes.dark.push(boxMatrix(rx, yy, rz, len, 0.1, 0.3, yaw));
            }
          }
        }
        y0 = y1;
      });
      // Slab edges at every floor and the roof.
      for (const f of block.floors.slice(1).concat([block.roof])) {
        const [sx, sz] = at(len / 2, 0.12);
        boxes.white.push(boxMatrix(sx, f, sz, len + 0.24, 0.35, 0.3, yaw));
      }
    }
    quads.roof.push(polygonShapeGeometry(poly, block.roof));
    quads.slab.push(polygonShapeGeometry(poly, 0.02));
    if (block.pv) addRoofGear(poly, block, boxes);
  }

  addCanopy(spec, toL, boxes, quads);

  const add = (geoms, material, shadow = true) => {
    if (!geoms.length) return;
    const mesh = new THREE.Mesh(mergeGeometries(geoms), material);
    mesh.castShadow = mesh.receiveShadow = shadow;
    group.add(mesh);
  };
  add(quads.glassA, mat.glassLit);
  add(quads.glassB, mat.glass);
  add(quads.stucco, mat.stucco);
  add(quads.roof, mat.roof);
  add(quads.slab, mat.roof, false);
  add(quads.canopy || [], mat.canopy);

  const unit = new THREE.BoxGeometry(1, 1, 1);
  const inst = (list, material) => {
    if (!list.length) return;
    const m = new THREE.InstancedMesh(unit, material, list.length);
    list.forEach((mx, i) => m.setMatrixAt(i, mx));
    m.castShadow = m.receiveShadow = true;
    group.add(m);
  };
  inst(boxes.wood, mat.wood);
  inst(boxes.dark, mat.darkMetal);
  inst(boxes.alu, mat.darkMetal);
  inst(boxes.white, mat.stucco);
  inst(boxes.pv, mat.pv);
  inst(boxes.hvac, mat.hvac);
  return group;
}

// PV rows tilted 10° to the south (the project funds a rooftop PV system) and a few HVAC units.
function addRoofGear(poly, block, boxes) {
  const xs = poly.map((p) => p[0]), zs = poly.map((p) => p[1]);
  const inner = offsetPolygon(poly, 2.0);
  for (let z = Math.min(...zs) + 2; z < Math.max(...zs) - 2; z += 2.6) {
    for (let x = Math.min(...xs) + 2; x < Math.max(...xs) - 2; x += 1.1) {
      if (![[x - 0.5, z - 1], [x + 0.5, z + 1], [x - 0.5, z + 1], [x + 0.5, z - 1]].every((p) => pointInPolygon(p, inner))) continue;
      _e.set(-0.17, 0, 0, 'YXZ');
      boxes.pv.push(_m.compose(_p.set(x, block.roof + 0.55, z), _q.setFromEuler(_e), _s.set(1.0, 0.04, 1.95)).clone());
    }
  }
  const cx = xs.reduce((s, v) => s + v, 0) / xs.length;
  const cz = zs.reduce((s, v) => s + v, 0) / zs.length;
  for (let i = -1; i <= 1; i++) boxes.hvac.push(boxMatrix(cx + i * 2.4, block.roof + 0.7, cz + 3, 1.8, 1.4, 1.2, 0));
}

// Folded zig-zag canopy on Y columns along the south (plaza) front.
function addCanopy(spec, toL, boxes, quads) {
  const c = spec.canopy;
  const [x0, z0] = toL(c.from), [x1] = toL(c.to);
  const folds = Math.round((x1 - x0) / c.fold);
  const step = (x1 - x0) / folds;
  const geoms = [];
  for (let i = 0; i < folds; i++) {
    const xa = x0 + i * step, xb = xa + step;
    const ha = i % 2 ? c.high : c.low, hb = i % 2 ? c.low : c.high;
    const g = new THREE.BufferGeometry();
    const P = [xa, ha, z0, xb, hb, z0, xb, hb, z0 + c.depth, xa, ha, z0, xb, hb, z0 + c.depth, xa, ha, z0 + c.depth];
    g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], 2));
    g.computeVertexNormals();
    geoms.push(g);
    if (i % 2 === 1) {
      const zc = z0 + c.depth / 2, stem = c.low - 1.4;
      boxes.white.push(boxMatrix(xa, stem / 2, zc, 0.3, stem, 0.3, 0));
      for (const s of [-1, 1]) {
        const dx = s * step * 0.9, dy = c.low - stem;
        boxes.white.push(boxMatrix(xa + dx / 2, stem + dy / 2, zc, Math.hypot(dx, dy), 0.22, 0.22, 0, Math.atan2(dy, dx)));
      }
    }
  }
  quads.canopy = geoms;
}
