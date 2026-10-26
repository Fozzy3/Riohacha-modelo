// Visor del CIP La Guajira: modelo con luz horneada en Cycles + datos BIM por elemento.
import * as THREE from 'three/webgpu';
import { backgroundIntensity, cameraPosition, equirectUV, fog, positionWorld, rangeFogFactor, texture, vec3 } from 'three/tsl';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { LineSegments2 } from 'three/addons/lines/webgpu/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { sunPosition } from './geo.js';

const $ = (id) => document.getElementById(id);

// Project frame (X east, Y north, Z up) -> three.js (x, y up, z south): (X, Z, -Y)
const P = (x, y, z) => new THREE.Vector3(x, z, -y);
const VIEWS = {
  'Aérea': [P(-62, -98, 46), P(12, -14, 6)],
  'Plaza': [P(9.5, -47, 1.65), P(11, -12, 9)],
  'Acceso sur': [P(11.5, -68, 1.65), P(12, -24, 7)],
  'Laboratorios': [P(8, -36, 1.65), P(-20, -30, 3.5)],
  'Noreste': [P(82, 38, 22), P(32, -6, 6)],
};
const STATES = { dia: 'Día', atardecer: 'Atardecer', noche: 'Noche' };
// Versions: the approved project (2021 drawings) and the approximate 2025 lot variant (Informe de avance DEARCA),
// each with its own assets folder; ?version=lote2025
const BASE = new URLSearchParams(location.search).get('version') === 'lote2025' ? 'lote2025/' : '';
const VIEW_LABEL = { aerea_suroeste: 'Aérea', 'plaza_andén': 'Plaza', acceso_sur: 'Acceso sur', laboratorios: 'Laboratorios',
  semisotano: 'Semisótano', noreste: 'Noreste' };
let NORTE = 0; // bearing of the project north (variant: 40.1° clockwise from true north)
let WALK_ZONE = null; // variant: walkable plaza polygon (the rest of the lot is 4 m lower)
const BLOCKS = { A: 'Principal', B: 'Bloque B', C: 'Laboratorios', D: 'Auditorio' };
const CLASS_NAME = {
  IfcShadingDevice: 'Cortasol', IfcWall: 'Muro', IfcPlate: 'Vidrio', IfcMember: 'Perfilería', IfcSlab: 'Losa o piso',
  IfcColumn: 'Columna', IfcRoof: 'Cubierta', IfcGeographicElement: 'Zona verde', IfcSpace: 'Espacio',
};
const cop = (v) => '$ ' + Math.round(v).toLocaleString('es-CO');
const num = (v) => Number(v).toLocaleString('es-CO', { maximumFractionDigits: 2 });
const safe = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const nodeName = (s) => s.replace(/\s/g, '_').replace(/[[\].:/]/g, ''); // GLTFLoader sanitises node names

// ---------- renderer and scene ----------
const renderer = new THREE.WebGPURenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.AgXToneMapping;
$('vista').appendChild(renderer.domElement);

const scene = new THREE.Scene();
// Coastal haze: blends the terrain edge into the sky like the aerial perspective of the Cycles renders.
// Colours are in scene radiance units, taken from each state's sky (see applyState).
const RADIANCE = 40; // day radiance scale of the impostors (export_vegetation.py)
// The haze takes the colour of the sky just above the horizon in each direction, so the ground meets the sky
// without a seam (a single colour showed as a bright band on the side away from the sun).
const HAZE_RISE = 0.03; // the haze is the sky ~1.7° above the horizon
const fogSky = texture(new THREE.DataTexture(new Uint16Array(4), 1, 1, THREE.RGBAFormat, THREE.HalfFloatType),
  equirectUV(positionWorld.sub(cameraPosition).mul(vec3(1, 0, 1)).normalize().add(vec3(0, HAZE_RISE, 0))));
scene.fogNode = fog(fogSky.mul(backgroundIntensity), rangeFogFactor(350, 1600));
const apron = new THREE.Mesh(new THREE.CircleGeometry(6000, 64).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial());
const APRON_TINT = new THREE.Color(0.40, 0.27, 0.16); // dry ground far away, relative to the haze
let dayHaze = null, dayScale = null; // day haze and bake scales: reference for the billboards of the other states
const impostorMats = [];
apron.position.set(12, -0.8, 20);
scene.add(apron);
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.3, 8000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.495;
controls.minDistance = 2;
controls.maxDistance = 900;

const manager = new THREE.LoadingManager();
manager.onProgress = (_, done, total) => ($('progreso').style.width = `${(100 * done) / total}%`);
const gltfLoader = new GLTFLoader(manager).setMeshoptDecoder(MeshoptDecoder).setPath(BASE); // meshopt geometry
const texLoader = new THREE.TextureLoader(manager).setPath(BASE);
const hdrLoader = new HDRLoader(manager).setPath(BASE);
const groundGrain = new THREE.TextureLoader(manager).load('textures/suelo_detalle.webp'); // shared by both versions
groundGrain.wrapS = groundGrain.wrapT = THREE.RepeatWrapping;
groundGrain.repeat.set(1100 / 5, 1100 / 5); // 5 m tiles over the 1100 m terrain grid (its UV spans 0-1)
groundGrain.anisotropy = 8;

// ---------- data ----------
const data = {};
let meshes = [];
const baked = new Map(); // mesh -> {mat for each light state}

async function loadJSON(path) {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function bakedMaterial(source, manifest, state, mesh) {
  const entry = manifest.mapas[mesh.userData.blenderName];
  const vertex = manifest.vertices.find((v) => nodeName(v.objeto) === mesh.name);
  if (vertex) {
    // louvers: albedo x per-vertex light x scale
    return new THREE.MeshBasicMaterial({ map: source.map, vertexColors: true,
      color: source.color.clone().multiplyScalar(vertex.escala) });
  }
  if (!entry) return null;
  const lm = texLoader.load(`luz/${state}/${entry.archivo}`);
  // "Lightmap" is the second UV set, or the only one on context meshes generated without texture UVs
  lm.channel = mesh.geometry.attributes.uv1 ? 1 : 0;
  lm.flipY = false;
  lm.colorSpace = THREE.SRGBColorSpace;
  // Cycles diffuse light passes: outgoing = albedo x bake. MeshBasicMaterial divides the light map by pi.
  // Context meshes (terrain, roads, neighbours) were baked with their albedo: show the bake alone.
  const ownColor = entry.con_color;
  // The terrain colour is a 10 m/px satellite image: a tiling grain of dry ground (linear, mean 0.5, so colour x2)
  // breaks it up close; mipmaps average it out far away. The neighbours were baked with near-white plaster (0.92):
  // toned down to weathered walls and roofs.
  const [map, tone] = { Terreno: [groundGrain, new THREE.Color(2, 2, 2)],
    'Edificios vecinos': [null, new THREE.Color(0.68, 0.66, 0.63)] }[mesh.userData.blenderName] ?? [];
  return new THREE.MeshBasicMaterial({ map: map ?? (ownColor ? null : source.map),
    color: tone ?? (ownColor || source.map ? 0xffffff : source.color),
    lightMap: lm, lightMapIntensity: entry.escala * Math.PI });
}

function surfaceMaterial(source, state) {
  const name = source.name || '';
  if (name.startsWith('Vidrio')) {
    // tinted, reflective façade glass: dark body, sky reflections, interiors faintly visible; lit interiors at night
    // (4000 K luminaires, estado.py), in scene radiance units
    return new THREE.MeshStandardMaterial({ color: 0x1c272c, metalness: 0.55, roughness: 0.03, transparent: true,
      // at night, clearer so the baked lit ceilings behind show through; a faint warm glow stands in for the interiors
      opacity: state === 'noche' ? 0.4 : 0.78, envMapIntensity: 1.2, depthWrite: false,
      emissive: state === 'noche' ? new THREE.Color(1.0, 0.80, 0.62).multiplyScalar(NIGHT_GLASS) : 0x000000 });
  }
  if (name.startsWith('Aluminio')) return new THREE.MeshStandardMaterial({ color: 0x0a0a0b, metalness: 1, roughness: 0.35 });
  return null;
}

// Mean radiance of the sky just above the horizon (equirectangular, half-float rows from the top).
function horizon(env) {
  const { data, width, height } = env.image;
  const row = Math.floor(height * 0.488), c = [0, 0, 0];
  const f = env.type === THREE.HalfFloatType ? THREE.DataUtils.fromHalfFloat : (v) => v;
  for (let x = 0; x < width; x++) for (let k = 0; k < 3; k++) c[k] += f(data[(row * width + x) * 4 + k]) / width;
  return new THREE.Color(...c);
}

async function applyState(state) {
  const manifest = await loadJSON(`luz/${state}/manifest.json`);
  const env = await hdrLoader.loadAsync(`luz/${state}/cielo.hdr`);
  env.mapping = THREE.EquirectangularReflectionMapping;
  // below the horizon the Cycles sky is black "ground": the haze row at the horizon, so the far ground and the
  // background meet the sky without a dark strip, turning into dry ground lower down (reflections, light from below).
  // Rows run from the zenith down.
  const { data, width, height } = env.image, row = Math.round(height * (0.5 - Math.asin(HAZE_RISE) / Math.PI));
  const half = env.type === THREE.HalfFloatType, ground = APRON_TINT.toArray();
  const get = half ? THREE.DataUtils.fromHalfFloat : (v) => v, put = half ? THREE.DataUtils.toHalfFloat : (v) => v;
  // haze down to 5° below the horizon (the apron's edge dips less than that), then 5° of blend into ground
  const n = width * 4, src = Array.from(data.subarray(row * n, (row + 1) * n), get);
  const blend = Math.round(height / 36), flat = height / 2 + blend, last = flat + blend;
  for (let y = row + 1; y < height; y++) {
    if (y <= flat) data.copyWithin(y * n, row * n, (row + 1) * n);
    else if (y > last) data.copyWithin(y * n, last * n, (last + 1) * n);
    else for (let i = 0; i < n; i++) {
      data[y * n + i] = i % 4 === 3 ? data[row * n + i] : put(src[i] * (1 + (ground[i % 4] - 1) * (y - flat) / blend));
    }
  }
  scene.background = env;
  scene.environment = env;
  renderer.toneMappingExposure = 2 ** manifest.exposicion; // per-state camera exposure of the renders
  const haze = horizon(env).multiplyScalar(2); // the day haze was tuned at twice the horizon sky
  dayHaze ??= haze.clone();
  fogSky.value = env;
  apron.material.color.copy(haze).multiply(APRON_TINT);
  // billboards were rendered under the day sky: scale them by the light on the context in this state relative to the
  // day (mean of the ground and neighbour bakes; the horizon alone made them brighter at sunset than at noon), with a
  // softened tint of this horizon
  const k = (name) => manifest.mapas[name]?.escala ?? 1;
  dayScale ??= { ground: k('Terreno'), houses: k('Edificios vecinos') };
  const light = RADIANCE * (k('Terreno') / dayScale.ground + k('Edificios vecinos') / dayScale.houses) / 2;
  const tint = [haze.r / dayHaze.r, haze.g / dayHaze.g, haze.b / dayHaze.b].map(Math.sqrt);
  const lum = 0.2126 * tint[0] + 0.7152 * tint[1] + 0.0722 * tint[2];
  const veg = new THREE.Color(...tint.map((c) => (light * c) / lum));
  impostorMats.forEach((m) => m.color.copy(veg));
  setSun(state);
  for (const mesh of meshes) {
    let set = baked.get(mesh);
    if (!set) baked.set(mesh, (set = { source: mesh.material }));
    set[state] ??= bakedMaterial(set.source, manifest, state, mesh) || surfaceMaterial(set.source, state) || set.source;
    mesh.material = set[state];
    const luz = mesh.geometry.attributes[`_luz_${state}`]; // louvers: per-vertex light of this state
    if (luz) mesh.geometry.setAttribute('color', luz);
  }
  document.querySelectorAll('#estados button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.estado === state));
  if (cut.enabled) sectionLook(true);
}

// ---------- vegetation ----------
// Real-time sun only for vegetation (buildings and ground are baked). Same direction as the bake; intensity
// matched to the baked irradiance scale (sunlit ~40 x pi).
// Sky light comes from the HDR environment.
const SUN = { dia: { az: 233.4, alt: 31.3, sol: 100 }, atardecer: { az: 244.7, alt: 5.9, sol: 25 },
  noche: { az: 0, alt: -20, sol: 0 } };
const NIGHT_GLASS = 0.025; // radiance of the lit interiors seen through the glass (0.08 clipped to flat white)
const sun = new THREE.DirectionalLight(0xfff1dc, 1);
scene.add(sun, sun.target);
// 3D meshes only for the project's own plants (inside the lot); the context forest is billboards (mobile budget).
const inLot = (x, y) => x > -48 && x < 61 && y > -62 && y < 17;
const SITE = P(12, -20, 0);

function setSunAt(az, alt, intensity) {
  const a = THREE.MathUtils.degToRad(az - NORTE), h = THREE.MathUtils.degToRad(alt); // true azimuth -> project
  sun.position.copy(SITE).add(P(Math.sin(a) * Math.cos(h), Math.cos(a) * Math.cos(h), Math.sin(h)).multiplyScalar(300));
  sun.target.position.copy(SITE);
  sun.intensity = intensity;
  // beam colour through the air mass: optical depth per channel, fitted to the sun of the baked sky (1 : 0.53 : 0.14
  // at 5.9°); about white at noon
  const tr = [0.15, 0.22, 0.38].map((tau) => Math.exp(-tau * Math.min(40, 1 / Math.max(Math.sin(h), 0.025))));
  sun.color.setRGB(1, tr[1] / tr[0], tr[2] / tr[0]);
}
const setSun = (state) => setSunAt(SUN[state].az, SUN[state].alt, SUN[state].sol);

async function loadVegetation() {
  const [inst, meta, plants] = await Promise.all([loadJSON('vegetacion/instancias.json'), loadJSON('vegetacion/impostores.json'),
    gltfLoader.loadAsync('vegetacion/plantas.glb')]);
  plants.scene.updateMatrixWorld(true);
  const species = {};
  plants.scene.traverse((o) => {
    if (!o.isMesh) return;
    const node = o.parent && !o.parent.isScene && o.parent !== plants.scene ? o.parent : o;
    if (node.name.startsWith('Palmera')) return; // palms stay as they are (world coordinates)
    const key = node.name.replace(/^especie_/, '');
    // leaf cards: cutout instead of blending (no per-instance sorting artefacts, cheaper)
    if (o.material.transparent) Object.assign(o.material, { transparent: false, alphaTest: 0.5 });
    // positions are quantized int16 (meshopt): baking the node matrix into them overflows, so it goes per instance
    (species[key] ??= []).push([o.geometry, o.material, o.matrixWorld.clone()]);
  });
  plants.scene.children = plants.scene.children.filter((c) => c.name.startsWith('Palmera'));
  plants.scene.traverse((o) => {
    if (o.isMesh && o.material.name.startsWith('Corteza')) o.material.color.set(0x9e8c78); // Blender tint is not in glTF
    o.castShadow = true;
  });
  scene.add(plants.scene);

  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  for (const [name, list] of Object.entries(inst)) {
    const near = list.filter(([x, y]) => inLot(x, y));
    const far = list.filter(([x, y]) => !inLot(x, y));
    for (const [geo, mat, local] of near.length ? species[name] || [] : []) { // WebGPU rejects empty instance buffers
      const im = new THREE.InstancedMesh(geo, mat, near.length);
      im.castShadow = true;
      near.forEach(([x, y, z, r, s], i) => im.setMatrixAt(i, m.compose(P(x, y, z), q.setFromAxisAngle(up, r), new THREE.Vector3(s, s, s)).multiply(local)));
      scene.add(im);
    }
    if (!meta[name] || !far.length) continue;
    // shrub_02 is mostly bare stems: far away it reads as grey sticks, so its billboard is the dense small Searsia
    // scaled to the same size
    const bb = name.startsWith('shrub_02') ? 'searsia_lucida_e' : name;
    const { lado, base } = meta[bb], k = meta[name].lado / lado;
    const quad = new THREE.PlaneGeometry(lado, lado).translate(0, lado / 2 + base, 0);
    const cross = new THREE.BufferGeometry();
    const parts = [quad, quad.clone().rotateY(Math.PI / 2)];
    const merged = parts.map((p) => p.toNonIndexed());
    cross.setAttribute('position', new THREE.Float32BufferAttribute(merged.flatMap((g) => [...g.attributes.position.array]), 3));
    cross.setAttribute('uv', new THREE.Float32BufferAttribute(merged.flatMap((g) => [...g.attributes.uv.array]), 2));
    const tex = texLoader.load(`vegetacion/impostor_${bb}.webp`);
    tex.colorSpace = THREE.SRGBColorSpace;
    // impostors store linear radiance / 40 (export_vegetation.py): scale back, then fog and tone mapping as usual
    const mat = new THREE.MeshBasicMaterial({ map: tex, alphaTest: 0.5, side: THREE.DoubleSide,
      color: impostorMats[0]?.color ?? new THREE.Color(RADIANCE, RADIANCE, RADIANCE) });
    impostorMats.push(mat);
    const im = new THREE.InstancedMesh(cross, mat, far.length);
    far.forEach(([x, y, z, r, s], i) => im.setMatrixAt(i, m.compose(P(x, y, z), q.setFromAxisAngle(up, r), new THREE.Vector3(s * k, s * k, s * k))));
    scene.add(im);
  }
}

// ---------- picking and highlight ----------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const highlight = new THREE.Group();
scene.add(highlight);
// highlight colours are shown as they are, whatever the exposure of the light state
const highlightMat = new THREE.MeshBasicMaterial({ color: 0xffcf5a, transparent: true, opacity: 0.55, depthTest: true,
  polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, toneMapped: false });

function eidOf(hit) {
  const attr = hit.object.geometry.attributes._eid;
  return attr ? Math.round(attr.getX(hit.face.a)) : null;
}

function highlightEids(eids) {
  highlight.clear();
  const wanted = new Set(eids);
  const box = new THREE.Box3();
  for (const mesh of meshes) {
    const g = mesh.geometry;
    const eid = g.attributes._eid;
    if (!eid || !mesh.visible) continue;
    const pos = g.attributes.position;
    const index = g.index ? g.index.array : null;
    const tris = index ? index.length / 3 : pos.count / 3;
    const out = [];
    for (let t = 0; t < tris; t++) {
      const a = index ? index[3 * t] : 3 * t;
      if (!wanted.has(Math.round(eid.getX(a)))) continue;
      for (let k = 0; k < 3; k++) {
        const v = index ? index[3 * t + k] : 3 * t + k;
        out.push(pos.getX(v), pos.getY(v), pos.getZ(v));
      }
    }
    if (!out.length) continue;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(out, 3));
    const m = new THREE.Mesh(geo, highlightMat);
    m.matrixAutoUpdate = false;
    m.matrix.copy(mesh.matrixWorld);
    highlight.add(m);
    geo.computeBoundingBox();
    box.union(geo.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
  }
  return box;
}

renderer.domElement.addEventListener('pointerdown', (e) => (pointer.down = [e.clientX, e.clientY]));
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!pointer.down || Math.hypot(e.clientX - pointer.down[0], e.clientY - pointer.down[1]) > 4) return; // it was a drag
  pointer.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(meshes.filter((m) => m.visible), false).find((h) => !cutAway(h));
  const eid = hit && eidOf(hit);
  if (eid == null) return;
  highlightEids([eid]);
  showElement(data.eid[eid]);
});

// ---------- panels ----------
function tab(name) {
  document.querySelectorAll('#pestanas button').forEach((b) => b.setAttribute('aria-selected', b.dataset.pestana === name));
  for (const id of ['elemento', 'espacios', 'presupuesto']) $(id).hidden = id !== name;
}
document.querySelectorAll('#pestanas button').forEach((b) => b.addEventListener('click', () => tab(b.dataset.pestana)));

function budgetItemsHTML(codes) {
  return codes.map((c) => {
    const it = data.presupuesto.items[c];
    if (!it) return '';
    return `<div class="item"><b>${c}</b> ${safe(it.descripcion)}<br>
      <small>${num(it.cantidad)} ${safe(it.unidad)} × ${cop(it.vr_unitario)} = <b>${cop(it.vr_total)}</b></small></div>`;
  }).join('');
}

function showElement(guid) {
  const el = data.elementos[guid];
  if (!el) return;
  const f = el.fuente || {};
  const sup = f.EsSupuesto && f.Supuesto ? data.supuestos[f.Supuesto] : null;
  const spec = el.especificacion ? data.especificaciones[el.especificacion] : null;
  $('elemento').innerHTML = `
    <h2>${safe(CLASS_NAME[el.clase] || el.clase)}<span class="etiqueta">${safe(BLOCKS[el.bloque] || el.bloque || 'Sitio')}</span></h2>
    <p class="sub">${safe(el.nombre)} · ${safe(el.nivel)}</p>
    <dl><dt>Material</dt><dd>${safe(el.material || '—')}</dd><dt>Clase IFC</dt><dd>${safe(el.clase)}${el.tipo ? ' · ' + safe(el.tipo) : ''}</dd>
      <dt>GlobalId</dt><dd><code>${safe(guid)}</code></dd></dl>
    ${el.items ? `<h3>Presupuesto</h3>${budgetItemsHTML(el.items)}` : ''}
    ${spec ? `<h3>Especificación técnica ${safe(spec.item)}</h3><details><summary>${safe(spec.titulo)}</summary>
      <p>${safe(spec.descripcion)}</p>${spec.pago ? `<p><b>Pago:</b> ${safe(spec.pago)}</p>` : ''}</details>` : ''}
    <h3>Fuente</h3><dl><dt>Lámina</dt><dd>${safe(f.Lamina || '—')}</dd><dt>Capa</dt><dd>${safe(f.Capa || '—')}</dd></dl>
    ${sup ? `<h3>Supuesto ${safe(f.Supuesto)}</h3><div class="supuesto"><b>${safe(sup.tema)}.</b> ${safe(sup.supuesto)}</div>` : ''}`;
  tab('elemento');
}

// ---------- spaces: highlight, cut at their floor and fly over them ----------
const LEVEL_Z = { 'Nivel 1': 0.40, 'Nivel 2': 4.00, 'Nivel 3': 7.80, 'Nivel 4': 11.60, 'Nivel 5': 15.40 };
let huellas = {}; // block -> ground-floor outline (project m)
// additive: the selected space glows like a lit room
const spaceFill = new THREE.MeshBasicMaterial({ color: 0xffcf5a, transparent: true, opacity: 0.18, depthWrite: false,
  blending: THREE.AdditiveBlending,
  side: THREE.DoubleSide, toneMapped: false });
const spaceFloor = new THREE.MeshBasicMaterial({ color: 0xffd76e, transparent: true, opacity: 0.6, depthWrite: false,
  blending: THREE.AdditiveBlending,
  side: THREE.DoubleSide, toneMapped: false });
const spaceEdges = new THREE.Line2NodeMaterial({ color: 0xffe066, linewidth: 4, depthTest: false, toneMapped: false });

// A space drawn from its plan rings (floor 1) or, upper floors without plan sheets (S4), the floor plate of its
// block(s) ("A/B": both).
function addSpace(group, s, strong) {
  const g = s.geometria;
  if (!g) {
    s.bloque.split('/').filter((b) => huellas[b]).forEach((b) => addOutline(group, [huellas[b]], LEVEL_Z[s.nivel] ?? 0.4, 3.2, strong));
    return;
  }
  addOutline(group, g.anillos, g.z0, Math.min(g.alto, 3.2), strong);
}

function addOutline(group, rings, z0, h, strong) {
  const shape = new THREE.Shape(rings[0].map(([x, y]) => new THREE.Vector2(x, y)));
  shape.holes = rings.slice(1).map((r) => new THREE.Path(r.map(([x, y]) => new THREE.Vector2(x, y))));
  // shape plane (x, y) -> three.js (x, z = -y) after rotateX(-90°); extrusions go up
  group.add(new THREE.Mesh(new THREE.ShapeGeometry(shape).rotateX(-Math.PI / 2).translate(0, z0 + 0.04, 0), spaceFloor));
  if (strong) {
    group.add(new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false }).rotateX(-Math.PI / 2)
      .translate(0, z0, 0), spaceFill));
  }
  const seg = [];
  for (const ring of rings) {
    ring.forEach(([x, y], i) => {
      const [x2, y2] = ring[(i + 1) % ring.length];
      seg.push(x, z0 + 0.06, -y, x2, z0 + 0.06, -y2);
      if (strong) seg.push(x, z0 + h, -y, x2, z0 + h, -y2);
    });
  }
  group.add(new LineSegments2(new LineSegmentsGeometry().setPositions(seg), spaceEdges));
}

const cutAt = (nivel) => document.querySelector(`[data-corte="${nivel.replace('Nivel', 'Piso')}"]`)?.click();

function frameTop(box) {
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() * 0.55 + 8;
  flyTo(c.clone().add(new THREE.Vector3(r * 0.3, r, r * 0.7)), c); // from above, slightly from the south-east
}

function selectSpaces(list, nivel) {
  if (walking) setWalk(false);
  highlight.clear();
  list.forEach((s) => addSpace(highlight, s, list.length === 1));
  cutAt(nivel);
  frameTop(new THREE.Box3().setFromObject(highlight));
}

function renderSpaces() {
  const spaces = Object.entries(data.elementos).filter(([, e]) => e.clase === 'IfcSpace');
  const byLevel = {};
  for (const [guid, s] of spaces) (byLevel[s.nivel] ??= []).push([guid, s]);
  $('espacios').innerHTML = Object.keys(byLevel).sort().map((lvl) => `<h3 class="nivel" data-nivel="${safe(lvl)}" title="Ver la planta">${safe(lvl)}</h3>` + byLevel[lvl].map(([guid, s]) => {
    const area = s.espacio?.AreaNetaM2 ? `${num(s.espacio.AreaNetaM2)} m²` : 'sin plano';
    return `<div class="fila" data-espacio="${guid}"><span>${safe(s.nombre_largo || s.nombre)}</span><small class="num">${area}</small></div>`;
  }).join('')).join('');
  $('espacios').querySelectorAll('[data-espacio]').forEach((row) => row.addEventListener('click', () => {
    const s = data.elementos[row.dataset.espacio];
    selectSpaces([s], s.nivel);
    showSpace(row.dataset.espacio);
  }));
  $('espacios').querySelectorAll('[data-nivel]').forEach((h) => h.addEventListener('click', () =>
    selectSpaces(byLevel[h.dataset.nivel].map(([, s]) => s), h.dataset.nivel)));
}

function showSpace(guid) {
  const s = data.elementos[guid];
  const e = s.espacio || {}, m = s.mobiliario, d = s.dotacion;
  const sup = e.EsSupuesto === 'True' && e.Supuesto ? data.supuestos[e.Supuesto] : null;
  $('elemento').innerHTML = `
    <h2>${safe(s.nombre_largo || s.nombre)}<span class="etiqueta">${safe(BLOCKS[s.bloque] || s.bloque)}</span></h2>
    <p class="sub">${safe(s.nivel)}${e.AreaNetaM2 ? ' · ' + num(e.AreaNetaM2) + ' m² netos' : ''}</p>
    ${s.geometria ? '' : '<p class="sub">Ubicación aproximada: se resalta la planta del bloque, porque faltan las láminas de los pisos altos (A-101 a A-105, supuesto S4).</p>'}
    ${m ? `<h3>Mobiliario (${num(m.TotalMuebles)} piezas)</h3><p class="sub">${safe(m.Detalle).replaceAll('; ', '<br>')}</p>` : ''}
    ${d ? `<h3>Dotación de equipos · ${safe(d.Grupo)}</h3><p><b>${num(d.NumeroEquipos)} equipos · ${cop(d.ValorTotalCOP)}</b></p>
      <p class="sub">${safe(d.Equipos).replaceAll('; ', '<br>')}</p>` : ''}
    ${sup ? `<h3>Supuesto ${safe(e.Supuesto)}</h3><div class="supuesto"><b>${safe(sup.tema)}.</b> ${safe(sup.supuesto)}</div>` : ''}`;
  tab('elemento');
}

function renderBudget() {
  const byItem = {};
  data.eid.forEach((guid, i) => (data.elementos[guid]?.items || []).forEach((c) => (byItem[c] ??= []).push(i)));
  const chapters = data.presupuesto.capitulos;
  const items = Object.entries(data.presupuesto.items);
  const total = items.reduce((s, [, it]) => s + (it.vr_total || 0), 0);
  $('presupuesto').innerHTML = `<p class="sub">Costo directo de infraestructura: <b>${cop(total)}</b>. Los ítems con 🔗 están enlazados a elementos del modelo:
    al tocarlos se resaltan en 3D.</p>` + Object.entries(chapters).map(([n, name]) => {
    const its = items.filter(([, it]) => String(it.capitulo) === n);
    const sum = its.reduce((s, [, it]) => s + (it.vr_total || 0), 0);
    return `<details><summary>${n}. ${safe(name)} <span class="num">· ${cop(sum)}</span></summary>` + its.map(([c, it]) =>
      `<div class="fila" data-item="${c}"><span>${byItem[c] ? '🔗 ' : ''}<b>${c}</b> ${safe(it.descripcion)}</span><small class="num">${cop(it.vr_total)}</small></div>`).join('') + '</details>';
  }).join('');
  $('presupuesto').querySelectorAll('[data-item]').forEach((row) => row.addEventListener('click', () => {
    const c = row.dataset.item;
    if (byItem[c]) frame(highlightEids(byItem[c]));
    $('elemento').innerHTML = `<h2>Ítem ${c}</h2><p class="sub">${byItem[c] ? byItem[c].length + ' elementos resaltados' : 'Sin elementos en el modelo (ítem no geométrico o interior)'}</p>${budgetItemsHTML([c])}`;
  }));
}

// ---------- per-floor section ----------
// Horizontal cut 1.2 m above the chosen floor (levels from section A-106); only the four blocks are cut.
const FLOORS = { 'Piso 1': 0.40, 'Piso 2': 4.00, 'Piso 3': 7.80, 'Piso 4': 11.60, 'Piso 5': 15.40 };
const cut = new THREE.ClippingGroup();
cut.clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, -1, 0), 0)];
cut.enabled = false;
scene.add(cut);
const cutAway = (hit) => cut.enabled && hit.point.y > cut.clippingPlanes[0].constant && hit.object.userData.bloque in BLOCKS;

// Cut floors read like a plan: the bake leaves deep interiors almost black, so the blocks switch to their plain
// materials lit by the sky (as in the sun study) while a cut is on.
function sectionLook(on) {
  if (study) return; // the sun study already uses the plain materials
  for (const mesh of meshes) {
    if (!(mesh.userData.bloque in BLOCKS)) continue;
    const set = baked.get(mesh);
    mesh.material = on ? (set.estudio ??= surfaceMaterial(set.source, 'dia') || set.source) : set[lightState];
  }
}

// ---------- sun study ----------
// Real-time sun for any date and hour (geo.js, NOAA) with shadow maps and the plain glTF materials instead of the
// bake. Beam intensity follows the air mass (Meinel), relative to the day state the vegetation was tuned to.
const beam = (alt) => (alt <= 0 ? 0 : 0.7 ** ((1 / Math.sin(THREE.MathUtils.degToRad(alt))) ** 0.678));
let lightState = 'dia', study = false;
const STUDY_ALBEDO = { 'Terreno': 0xa88f6a, 'Vías': 0x5a5a5a, 'Edificios vecinos': 0xd8d4cc };
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -90, right: 90, top: 90, bottom: -90, near: 100, far: 500 });
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.04;

function updateStudy() {
  const h = Number($('hora').value);
  const hh = String(Math.floor(h)).padStart(2, '0'), mm = String(Math.round((h % 1) * 60)).padStart(2, '0');
  const { azimuth, altitude } = sunPosition(new Date(`${$('fecha').value}T${hh}:${mm}:00-05:00`)); // Colombia, UTC-5
  setSunAt(azimuth, altitude, (SUN.dia.sol * beam(altitude)) / beam(SUN.dia.alt));
  scene.environmentIntensity = scene.backgroundIntensity = THREE.MathUtils.clamp((altitude + 4) / 30, 0.02, 1);
  $('solDato').textContent = `${hh}:${mm} · azimut ${Math.round(azimuth)}° · altura ${Math.round(altitude)}°`;
}

async function setStudy(on) {
  study = on;
  $('estudio').setAttribute('aria-pressed', on);
  $('solar').hidden = !on;
  renderer.shadowMap.enabled = on;
  sun.castShadow = on;
  if (!on) {
    scene.environmentIntensity = scene.backgroundIntensity = 1;
    return applyState(lightState);
  }
  await applyState('dia'); // the day sky lights the scene
  for (const mesh of meshes) {
    const set = baked.get(mesh);
    // context meshes have no exportable material (their colour lives in the bake): plain albedo instead
    const plain = STUDY_ALBEDO[mesh.userData.blenderName];
    mesh.material = set.estudio ??= plain ? new THREE.MeshStandardMaterial({ color: plain, roughness: 1 })
      : surfaceMaterial(set.source, 'dia') || set.source;
    mesh.castShadow = mesh.receiveShadow = true;
  }
  document.querySelectorAll('#estados button').forEach((b) => b.setAttribute('aria-pressed', false));
  updateStudy();
}

// ---------- walk ----------
// First person at eye height on the flat lot (plaza level 0.20, S24), outside the blocks.
// W A S D or arrows to move, Shift to run, drag to look.
const EYE = 0.20 + 1.65;
const keys = new Set();
addEventListener('keydown', (e) => !e.target.closest('input') && keys.add(e.code));
addEventListener('keyup', (e) => keys.delete(e.code));
let walking = false, footprints = [];

function insidePolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
const blocked = (p) => (WALK_ZONE ? !insidePolygon(p.x, -p.z, WALK_ZONE) : Math.hypot(p.x - SITE.x, p.z - SITE.z) > 70)
  || footprints.some((f) => insidePolygon(p.x, -p.z, f));

function walkStep(dt) {
  const f = controls.target.clone().sub(camera.position).setY(0).normalize();
  const d = new THREE.Vector3(), right = new THREE.Vector3(-f.z, 0, f.x);
  if (keys.has('KeyW') || keys.has('ArrowUp')) d.add(f);
  if (keys.has('KeyS') || keys.has('ArrowDown')) d.sub(f);
  if (keys.has('KeyD') || keys.has('ArrowRight')) d.add(right);
  if (keys.has('KeyA') || keys.has('ArrowLeft')) d.sub(right);
  if (!d.lengthSq() || blocked(camera.position.clone().addScaledVector(d.normalize(), 0.6))) return;
  d.multiplyScalar((keys.has('ShiftLeft') || keys.has('ShiftRight') ? 4 : 1.4) * dt);
  camera.position.add(d);
  controls.target.add(d);
}

function setWalk(on) {
  walking = on;
  $('caminar').setAttribute('aria-pressed', on);
  // looking around = orbiting a target 1 cm ahead of the eye
  Object.assign(controls, on
    ? { minDistance: 0.01, maxDistance: 0.01, enableZoom: false, enablePan: false, maxPolarAngle: Math.PI * 0.9, rotateSpeed: 0.4 }
    : { minDistance: 2, maxDistance: 900, enableZoom: true, enablePan: true, maxPolarAngle: Math.PI * 0.495, rotateSpeed: 1 });
  flight = null;
  if (on) {
    const [p] = VIEWS['Plaza']; // on the plaza, looking north at the main block
    camera.position.set(p.x, EYE, p.z);
    controls.target.set(p.x, EYE, p.z - 0.01);
  } else flyTo(...VIEWS['Aérea']);
}

// ---------- camera ----------
let flight = null;
function flyTo(pos, target, seconds = 1.6) {
  flight = { from: camera.position.clone(), to: pos.clone(), tFrom: controls.target.clone(), tTo: target.clone(), t: 0, d: seconds };
}
function frame(box) {
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() * 0.6 + 4;
  const dir = camera.position.clone().sub(controls.target).normalize();
  flyTo(c.clone().addScaledVector(dir, r * 1.6), c);
}

function buildToolbar(states) {
  $('vistas').innerHTML = '<span>Vista</span>' + Object.keys(VIEWS).map((v) => `<button data-vista="${v}">${v}</button>`).join('');
  $('vistas').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    if (walking) setWalk(false);
    flyTo(...VIEWS[b.dataset.vista]);
  }));
  $('estados').innerHTML = '<span>Luz</span>' + Object.entries(STATES).map(([k, v]) =>
    `<button data-estado="${k}" ${states.includes(k) ? '' : 'disabled title="Pendiente de hornear"'}>${v}</button>`).join('');
  $('estados').querySelectorAll('button:not(:disabled)').forEach((b) => b.addEventListener('click', () => {
    lightState = b.dataset.estado;
    return study ? setStudy(false) : applyState(lightState);
  }));
  $('bloques').innerHTML = '<span>Bloques</span>' + Object.entries(BLOCKS).map(([k, v]) =>
    `<button data-bloque="${k}" aria-pressed="true">${v}</button>`).join('');
  $('bloques').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', on);
    meshes.filter((m) => m.userData.bloque === b.dataset.bloque).forEach((m) => (m.visible = on));
  }));
  $('cortes').innerHTML = '<span>Corte</span>' + ['Sin corte', ...Object.keys(FLOORS)].map((f, i) =>
    `<button data-corte="${f}" aria-pressed="${i === 0}" title="${i ? `Planta del ${f.toLowerCase()}` : 'Edificio completo'}">${f.replace('Piso ', 'P')}</button>`).join('');
  $('cortes').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    const level = FLOORS[b.dataset.corte];
    cut.enabled = level !== undefined;
    if (cut.enabled) cut.clippingPlanes[0].constant = level + 1.2;
    sectionLook(cut.enabled);
    $('cortes').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  }));
  $('estudio').addEventListener('click', () => setStudy(!study));
  $('fecha').addEventListener('input', updateStudy);
  $('hora').addEventListener('input', updateStudy);
  $('caminar').addEventListener('click', () => setWalk(!walking));
}

// ---------- start ----------
async function main() {
  const [elementos, eid, presupuesto, especificaciones, supuestos] = await Promise.all(
    ['elementos', 'eid', 'presupuesto', 'especificaciones', 'supuestos'].map((n) => loadJSON(`data/${n}.json`)));
  Object.assign(data, { elementos, eid, presupuesto, especificaciones, supuestos });
  // a version is ready once at least one light state is baked (the bake also writes modelo.glb)
  const states = [];
  for (const s of Object.keys(STATES)) if ((await fetch(`${BASE}luz/${s}/manifest.json`, { method: 'HEAD' })).ok) states.push(s);
  if (!states.length) throw new Error('esta versión todavía se está horneando en Blender; vuelva a intentar más tarde');
  const gltf = await gltfLoader.loadAsync('modelo.glb');
  scene.add(gltf.scene);
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const parent = o.parent && o.parent !== gltf.scene && !o.parent.isScene ? o.parent : o;
    o.userData.blenderName = parent.name; // multi-primitive meshes are children of the node
    o.name = parent.name;
    o.userData.bloque = (parent.name.split('|')[1] || '').trim();
    meshes.push(o);
  });
  // manifest keys are Blender names (spaces); compare sanitised
  const sample = await loadJSON(`luz/${states[0]}/manifest.json`);
  const byNode = Object.fromEntries(Object.keys(sample.mapas).map((k) => [nodeName(k), k]));
  meshes.forEach((m) => (m.userData.blenderName = byNode[m.name] ?? m.userData.blenderName));
  // apron under the lowest terrain point, like the Blender scene (above it, it covers the hollows)
  const terrain = meshes.find((m) => m.userData.blenderName === 'Terreno');
  apron.position.y = new THREE.Box3().setFromObject(terrain).min.y - 0.5;
  meshes.filter((m) => m.userData.bloque in BLOCKS).forEach((m) => cut.attach(m));
  cut.attach(highlight);
  huellas = await loadJSON('data/huellas.json');
  footprints = Object.values(huellas);
  if (BASE) {
    const sitio = await loadJSON('data/sitio.json');
    NORTE = sitio.norte;
    WALK_ZONE = sitio.plaza;
    for (const k of Object.keys(VIEWS)) delete VIEWS[k];
    for (const [k, [p, t]] of Object.entries(sitio.vistas)) VIEWS[VIEW_LABEL[k] ?? k] = [P(...p), P(...t)];
  }
  document.querySelectorAll('#versiones a').forEach((a) => a.setAttribute('aria-current', a.dataset.base === BASE));
  $('descargaIfc').href = `${BASE}cip.ifc`;

  await renderer.init();
  await applyState(states[0]);
  await loadVegetation();
  buildToolbar(states);
  renderSpaces();
  renderBudget();
  const [p, t] = VIEWS['Aérea'];
  camera.position.copy(p);
  controls.target.copy(t);
  $('carga').classList.add('listo');

  const clock = new THREE.Clock();
  renderer.setAnimationLoop(() => {
    const dt = clock.getDelta();
    if (flight) {
      flight.t = Math.min(1, flight.t + dt / flight.d);
      const k = flight.t * flight.t * (3 - 2 * flight.t);
      camera.position.lerpVectors(flight.from, flight.to, k);
      controls.target.lerpVectors(flight.tFrom, flight.tTo, k);
      if (flight.t >= 1) flight = null;
    }
    if (walking) walkStep(dt);
    controls.update();
    renderer.render(scene, camera);
  });
}

// clean view: only the 3D model (button or Esc toggles the panels)
function setClean(on) {
  document.body.classList.toggle('limpia', on);
  $('limpia').setAttribute('aria-pressed', on);
  $('limpia').textContent = on ? 'Mostrar controles' : 'Vista limpia';
}
$('limpia').addEventListener('click', () => setClean(!document.body.classList.contains('limpia')));
addEventListener('keydown', (e) => { if (e.key === 'Escape') setClean(false); });

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

main().catch((err) => {
  console.error(err);
  $('cargaTexto').innerHTML = `No se pudo cargar el modelo: ${safe(err.message)}.${BASE ? ' <a href="./">Ver la versión aprobada</a>' : ''}`;
});
