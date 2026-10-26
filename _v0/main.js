import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { sunPosition, sunVector } from './geo.js';
import { buildCIP, planToLocal } from './building.js';
import { buildTerrain, terrainMaterial, buildSiteGround, buildContext, scatterTrees, buildPalms, buildShrubs, buildPeople } from './nature.js';

const $ = (id) => document.getElementById(id);
const mobile = matchMedia('(pointer: coarse)').matches || innerWidth < 800;
let quality = mobile ? 'media' : 'alta';

// ---------- renderer, scene, camera ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1 : 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
$('app').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xc9d6df, 0.0016);
const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.5, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.495;
controls.minDistance = 6;
controls.maxDistance = 700;

// ---------- materials ----------
const manager = new THREE.LoadingManager();
manager.onProgress = (_, done, total) => ($('progress').style.width = `${(100 * done) / total}%`);
const texLoader = new THREE.TextureLoader(manager);
const maxAniso = renderer.capabilities.getMaxAnisotropy();
function pbr(name, extra = {}) {
  const load = (suffix, srgb) => {
    const t = texLoader.load(`data/tex/${name}_${suffix}.jpg`);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = Math.min(8, maxAniso);
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
  const arm = load('arm');
  return new THREE.MeshStandardMaterial({ map: load('diff', true), normalMap: load('nor'), aoMap: arm, roughnessMap: arm, metalnessMap: arm, ...extra });
}
const dry = pbr('dry_ground_01');
const lawn = pbr('leafy_grass', { color: 0xd8e6c0 });
const mats = {
  stucco: pbr('plastered_wall', { color: 0xf3f0ea }),
  wood: pbr('fine_grained_wood', { color: 0xd9a46c }),
  glass: new THREE.MeshStandardMaterial({ color: 0x1b2730, metalness: 0.95, roughness: 0.06, envMapIntensity: 1.4 }),
  glassLit: new THREE.MeshStandardMaterial({ color: 0x1b2730, metalness: 0.95, roughness: 0.06, envMapIntensity: 1.4, emissive: 0xffc98a, emissiveIntensity: 0 }),
  darkMetal: new THREE.MeshStandardMaterial({ color: 0x1c1c1e, metalness: 0.6, roughness: 0.45 }),
  roof: new THREE.MeshStandardMaterial({ color: 0xb8b4ab, roughness: 0.95 }),
  canopy: new THREE.MeshStandardMaterial({ color: 0xf5f4f0, roughness: 0.55, side: THREE.DoubleSide }),
  pv: new THREE.MeshStandardMaterial({ color: 0x0f1d3d, metalness: 0.6, roughness: 0.22 }),
  hvac: new THREE.MeshStandardMaterial({ color: 0xcfd2d4, metalness: 0.4, roughness: 0.5 }),
  pavers: pbr('grass_concrete_pavement'),
  concrete: pbr('concrete_pavement'),
  lawn,
  asphalt: pbr('asphalt_02', { color: 0xbbbbbb }),
  water: new THREE.MeshStandardMaterial({ color: 0x6b5a3e, metalness: 0.2, roughness: 0.15 }),
  neighbour: new THREE.MeshStandardMaterial({ color: 0xe9e4da, roughness: 0.9 }),
  bark: new THREE.MeshStandardMaterial({ color: 0x5b4a3a, roughness: 1 }),
  leaves: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.85 }),
  flowers: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7 }),
  palmBark: pbr('palm_tree_bark'),
};
mats.terrain = terrainMaterial(dry, lawn);
for (const m of [mats.pavers, mats.concrete, mats.lawn]) {
  m.polygonOffset = true;
  m.polygonOffsetFactor = -2;
}

// ---------- sky, sun, environment ----------
const sky = new Sky();
sky.scale.setScalar(20000);
scene.add(sky);
const skyU = sky.material.uniforms;
skyU.turbidity.value = 7;
skyU.rayleigh.value = 1.6;
skyU.mieCoefficient.value = 0.004;
skyU.mieDirectionalG.value = 0.8;

const envSky = new Sky();
envSky.scale.setScalar(20000);
const envScene = new THREE.Scene();
envScene.add(envSky);
const pmrem = new THREE.PMREMGenerator(renderer);
let envRT = null;

const sun = new THREE.DirectionalLight(0xfff2e0, 3);
sun.castShadow = true;
sun.shadow.bias = -0.0003;
sun.shadow.normalBias = 0.03;
const sc = sun.shadow.camera;
sc.left = sc.bottom = -120;
sc.right = sc.top = 120;
sc.near = 1;
sc.far = 900;
scene.add(sun, sun.target);
const hemi = new THREE.HemisphereLight(0xcfe3ff, 0x6b5a40, 0.6);
scene.add(hemi);

// Stars for the night sky.
const starGeo = new THREE.BufferGeometry();
const starPos = [];
for (let i = 0; i < 1500; i++) {
  const v = new THREE.Vector3().randomDirection();
  if (v.y < 0.05) v.y = Math.abs(v.y) + 0.05;
  starPos.push(...v.multiplyScalar(4000).toArray());
}
starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starPos, 3));
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false }));
scene.add(stars);

// ---------- post-processing ----------
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(innerWidth, innerHeight, { samples: 4, type: THREE.HalfFloatType }));
composer.addPass(new RenderPass(scene, camera));
const gtao = new GTAOPass(scene, camera, innerWidth, innerHeight);
gtao.output = GTAOPass.OUTPUT.Default;
composer.addPass(gtao);
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.15, 0.6, 0.9);
composer.addPass(bloom);
composer.addPass(new OutputPass());

function applyQuality() {
  const high = quality === 'alta';
  gtao.enabled = high;
  sun.shadow.mapSize.setScalar(high ? 4096 : 2048);
  sun.shadow.map?.dispose();
  sun.shadow.map = null;
  renderer.setPixelRatio(Math.min(devicePixelRatio, high ? 1.5 : 1));
  composer.setPixelRatio(renderer.getPixelRatio());
  $('quality').textContent = `Calidad: ${quality}`;
}

// ---------- time of day ----------
// Shareable views: ?d=2026-06-21&h=17:30&vista=plaza
const params = new URLSearchParams(location.search);
const [ph, pm] = (params.get('h') || '9:00').split(':').map(Number);
const state = { date: params.get('d') || '2026-03-20', minutes: ph * 60 + (pm || 0), playing: false };
const toDate = () => {
  const [y, m, d] = state.date.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d) + (state.minutes + 300) * 60000); // Riohacha is UTC-5
};
const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(Math.floor(min % 60)).padStart(2, '0')}`;

function sunEvents() {
  let rise = null, set = null, prev = null;
  const [y, m, d] = state.date.split('-').map(Number);
  for (let min = 0; min <= 1440; min += 2) {
    const alt = sunPosition(new Date(Date.UTC(y, m - 1, d) + (min + 300) * 60000)).altitude;
    if (prev !== null && prev < -0.83 && alt >= -0.83) rise = min;
    if (prev !== null && prev >= -0.83 && alt < -0.83) set = min;
    prev = alt;
  }
  return { rise, set };
}

let lastEnvAlt = 999, lastEnvAz = 999;
let site = new THREE.Vector3();
let streetLights = [];
function updateSun() {
  const pos = sunPosition(toDate());
  const v = new THREE.Vector3(...sunVector(pos));
  skyU.sunPosition.value.copy(v);
  envSky.material.uniforms.sunPosition.value.copy(v);
  for (const k of ['turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) envSky.material.uniforms[k].value = skyU[k].value;

  const alt = pos.altitude;
  const day = THREE.MathUtils.smoothstep(alt, -6, 8); // 0 night, 1 full day
  const golden = 1 - THREE.MathUtils.smoothstep(alt, 2, 25);
  sun.position.copy(site).addScaledVector(v, 500);
  sun.target.position.copy(site);
  sun.intensity = 3.2 * THREE.MathUtils.smoothstep(alt, -1, 10);
  sun.color.setRGB(1, 0.93 - 0.25 * golden, 0.85 - 0.45 * golden);
  hemi.intensity = 0.08 + 0.55 * day;
  hemi.color.setRGB(0.55 + 0.25 * day, 0.62 + 0.25 * day, 0.85);
  renderer.toneMappingExposure = 0.55 + 0.25 * day;
  scene.fog.color.setRGB(0.05 + 0.73 * day, 0.07 + 0.77 * day, 0.12 + 0.76 * day);
  stars.material.opacity = 1 - THREE.MathUtils.smoothstep(alt, -12, -3);

  const night = 1 - THREE.MathUtils.smoothstep(alt, -4, 4);
  mats.glassLit.emissiveIntensity = 2.2 * night;
  bloom.strength = 0.12 + 0.7 * night;
  for (const l of streetLights) l.intensity = l.userData.max * night;
  for (const m of lampHeads) m.material.emissiveIntensity = 4 * night;

  if (Math.abs(alt - lastEnvAlt) > 0.7 || Math.abs(pos.azimuth - lastEnvAz) > 2) {
    envRT?.dispose();
    envRT = pmrem.fromScene(envScene, 0, 1, 20000);
    scene.environment = envRT.texture;
    scene.environmentIntensity = 0.15 + 0.85 * day;
    lastEnvAlt = alt;
    lastEnvAz = pos.azimuth;
  }

  $('time').value = state.minutes;
  $('clock').textContent = hhmm(state.minutes);
  $('sunInfo').textContent = `Sol: altura ${alt.toFixed(1)}°, azimut ${pos.azimuth.toFixed(0)}°`;
}

// ---------- night lighting: path lamps and façade uplights ----------
const lampHeads = [];
function addLights(toL, spec) {
  const pole = new THREE.CylinderGeometry(0.06, 0.08, 4.2, 8).translate(0, 2.1, 0);
  const headMat = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0xffd9a0, emissiveIntensity: 0 });
  const walk = spec.site.walk.map(toL);
  const xs = [(walk[0][0] + walk[1][0]) / 2];
  const z0 = walk[0][1], z1 = walk[2][1];
  const spots = [];
  for (let z = z0 + 4; z < z1; z += 9) for (const dx of [-3.2, 3.2]) spots.push([xs[0] + dx, z]);
  for (const [x, z] of spots) {
    const p = new THREE.Mesh(pole, mats.darkMetal);
    p.position.set(x, 0, z);
    p.castShadow = true;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 12, 8), headMat);
    head.position.set(x, 4.25, z);
    lampHeads.push(head);
    scene.add(p, head);
  }
  // A few real lights (cheap point lights) plus emissive heads + bloom for the rest.
  for (let i = 0; i < spots.length; i += 3) {
    const l = new THREE.PointLight(0xffd29a, 0, 22, 1.6);
    l.position.set(spots[i][0], 4, spots[i][1]);
    l.userData.max = 40;
    streetLights.push(l);
    scene.add(l);
  }
  // Warm uplights washing the wood slats of the main block (south face).
  const main = spec.blocks.find((b) => b.id === 'principal').poly.map(toL);
  const zs = Math.max(...main.map((p) => p[1]));
  for (const t of [0.2, 0.5, 0.8]) {
    const x = main[0][0] + (main[1][0] - main[0][0]) * t;
    const s = new THREE.SpotLight(0xffc27a, 0, 30, 0.5, 0.6, 1.2);
    s.position.set(x, 0.3, zs + 1.6);
    s.target.position.set(x, 18, zs);
    s.userData.max = 250;
    streetLights.push(s);
    scene.add(s, s.target);
  }
}

// ---------- guided tour ----------
let tour = null;
function makeTour(toL) {
  const P = (px, py, y) => {
    const [x, z] = toL([px, py]);
    return new THREE.Vector3(x, y, z);
  };
  const cams = [P(400, 2600, 70), P(1435, 2000, 6), P(1435, 1300, 1.7), P(1300, 960, 2.2), P(1700, 1100, 3), P(900, 1150, 4), P(700, 300, 45), P(2600, 0, 60), P(2700, 1900, 55)];
  const looks = [P(1500, 900, 8), P(1450, 800, 6), P(1500, 805, 6), P(1700, 805, 5), P(2000, 1080, 4), P(750, 1250, 3), P(1500, 600, 12), P(1600, 600, 15), P(1500, 900, 6)];
  return { cam: new THREE.CatmullRomCurve3(cams, false, 'centripetal'), look: new THREE.CatmullRomCurve3(looks, false, 'centripetal'), t: 0, duration: 70 };
}
const ease = (t) => t * t * (3 - 2 * t);

// ---------- build everything ----------
async function main() {
  const [spec, terrainData, osm, groundImg] = await Promise.all([
    fetch('building.json').then((r) => r.json()),
    fetch('data/terrain.json').then((r) => r.json()),
    fetch('data/osm.json').then((r) => r.json()),
    new THREE.ImageLoader(manager).loadAsync('data/ground.jpg'),
  ]);
  const toL = planToLocal(spec);
  const [sx, sz] = toL(spec.planCenter);
  site.set(sx, 0, sz);

  const terrain = buildTerrain(terrainData, groundImg, { x: sx, z: sz }, mats);
  scene.add(terrain.mesh);
  const ground = buildSiteGround(spec, toL, mats);
  scene.add(ground.group);
  const context = buildContext(osm, terrain.heightAt, ground.lot, mats);
  scene.add(context.group);
  scene.add(buildCIP(spec, mats));
  scene.add(scatterTrees(terrain, context.blockers, ground.lot, mats, mobile ? 4000 : 10000));
  scene.add(buildPalms(spec.site.palms.map(toL), terrain.heightAt, mats));
  scene.add(buildShrubs(ground.lot, spec.site, mats));
  addLights(toL, spec);

  // Walking routes: plaza loop, main walkway, labs to auditorium.
  const R = (pts) => new THREE.CatmullRomCurve3(pts.map((p) => { const [x, z] = toL(p); return new THREE.Vector3(x, 0.05, z); }), true);
  const routes = [
    R([[1420, 1500], [1420, 960], [1700, 930], [1760, 1250], [1500, 1350]]),
    R([[1450, 1520], [1450, 950], [1300, 1000], [1200, 1200], [1350, 1400]]),
    R([[1250, 1050], [1650, 980], [1780, 1300], [1300, 1450]]),
    R([[1600, 900], [1780, 900], [1780, 1450], [1600, 1450]]),
  ];
  const people = await buildPeople(routes, manager, mobile ? 8 : 18);
  scene.add(people.group);

  const views = {
    aerea: [[sx - 75, 55, sz + 110], [sx, 6, sz - 3]],
    plaza: [[sx - 8, 1.7, sz + 22], [sx - 2, 7, sz - 10]],
    acceso: [[sx - 2, 2, sz + 34], [sx - 2, 8, sz - 15]],
    norte: [[sx + 10, 25, sz - 95], [sx, 8, sz - 5]],
    entorno: [[sx - 380, 260, sz + 420], [sx, 0, sz]],
  };
  const [cp, ct] = views[params.get('vista')] || views.aerea;
  camera.position.set(...cp);
  controls.target.set(...ct);
  applyQuality();
  updateSun();
  wireUI(toL);
  $('loading').classList.add('done');

  const clock = new THREE.Clock();
  renderer.setAnimationLoop(() => {
    const dt = Math.min(clock.getDelta(), 0.1);
    if (state.playing) {
      state.minutes += dt * 12; // 1 s = 12 min
      if (state.minutes > 20 * 60) state.minutes = 5 * 60 + 30;
      updateSun();
    }
    if (tour) {
      tour.t += dt / tour.duration;
      if (tour.t >= 1) stopTour();
      else {
        const t = ease(tour.t);
        camera.position.copy(tour.cam.getPointAt(t));
        controls.target.copy(tour.look.getPointAt(t));
      }
    }
    people.update(dt);
    controls.update();
    composer.render();
  });
}

function stopTour() {
  tour = null;
  $('tour').textContent = 'Recorrido guiado';
}

function wireUI(toL) {
  $('time').addEventListener('input', (e) => { state.minutes = Number(e.target.value); updateSun(); });
  $('date').value = state.date;
  const showEvents = () => {
    const { rise, set } = sunEvents();
    $('events').textContent = `Amanecer ${hhmm(rise)} · Atardecer ${hhmm(set)}`;
  };
  $('date').addEventListener('change', (e) => { state.date = e.target.value; updateSun(); showEvents(); });
  document.querySelectorAll('[data-date]').forEach((b) => b.addEventListener('click', () => {
    state.date = b.dataset.date;
    $('date').value = state.date;
    updateSun();
    showEvents();
  }));
  $('play').addEventListener('click', () => {
    state.playing = !state.playing;
    $('play').textContent = state.playing ? 'Pausa' : 'Ciclo del día';
  });
  $('night').addEventListener('click', () => { state.minutes = 19 * 60 + 15; updateSun(); });
  $('tour').addEventListener('click', () => {
    if (tour) return stopTour();
    tour = makeTour(toL);
    $('tour').textContent = 'Detener recorrido';
  });
  renderer.domElement.addEventListener('pointerdown', () => tour && stopTour());
  $('quality').addEventListener('click', () => {
    quality = quality === 'alta' ? 'media' : 'alta';
    applyQuality();
  });
  showEvents();
}

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
});

main().catch((err) => {
  console.error(err);
  $('loadingText').textContent = `No se pudo cargar el modelo: ${err.message}`;
});
