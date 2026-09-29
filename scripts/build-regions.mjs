#!/usr/bin/env node
/**
 * Build the NammaSafe region directory from the official LGD (Local Government
 * Directory) portal — https://lgdirectory.gov.in — using its captcha-free DWR
 * JSON-RPC endpoints, plus the community LGD mirror for village names (the LGD
 * DWR portal does not expose village lists by parent, only single-village lookups).
 *
 * Generated output (written under src/data/regions):
 *   METADATA.ts                        — source + count summary
 *   hierarchy.ts                       — states, districts, sub-districts, blocks
 *   villages/<stateCode>.ts            — per-state village chunks (lazy-loaded)
 *
 * No third-party dependencies. Requires Node.js >= 18.
 */

import { mkdirSync, existsSync, writeFileSync, createWriteStream, readFileSync } from 'node:fs';
import { copyFileSync } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { inflateSync } from 'node:zlib';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE_DIR = path.join(ROOT, 'scripts', '.cache', 'lgd');
const MIRROR_DIR = path.join(ROOT, 'scripts', '.cache', 'mirror');
const OUT_DIR = path.join(ROOT, 'src', 'data', 'regions');
const VILLAGES_OUT = path.join(OUT_DIR, 'villages');

const BASE = 'https://lgdirectory.gov.in';
const CITIZEN_PAGE = '/globalviewdistrictforcitizen.do';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) NammaSafeRegionBuilder/1.0';
const MIRROR_ZIP_URL =
  'https://github.com/planemad/india-local-government-directory/raw/main/administrative/4-village.csv.zip';

const REQUEST_GAP_MS = 160; // polite throttle between DWR calls
const CONCURRENCY = 3;

mkdirSync(CACHE_DIR, { recursive: true });
mkdirSync(MIRROR_DIR, { recursive: true });
mkdirSync(VILLAGES_OUT, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ------------------------------------------------------------------ *
 * LGD DWR client
 * ------------------------------------------------------------------ */

class LgdDwr {
  constructor() {
    this.cookie = '';
    this.token = null;
    this.page = '';
    this.lastRequestAt = 0;
  }

  async freshSession() {
    const res = await fetch(`${BASE}${CITIZEN_PAGE}`, {
      headers: { 'User-Agent': UA },
      redirect: 'follow',
    });
    if (!res.ok) throw new Error(`LGD page GET failed: ${res.status}`);
    const html = await res.text();
    const matches = res.headers.getSetCookie
      ? res.headers.getSetCookie().map((c) => c.split(';')[0]).join('; ')
      : '';
    this.cookie = matches;
    const token = (html.match(/OWASP_CSRFTOKEN=([A-Z0-9-]+)/i) || [])[1] || null;
    if (!token) throw new Error('Could not extract OWASP_CSRFTOKEN from LGD page');
    this.token = token;
    this.page = `${CITIZEN_PAGE}?OWASP_CSRFTOKEN=${encodeURIComponent(token)}`;
  }

  buildBody(scriptName, method, args) {
    const lines = [
      'callCount=1',
      `page=${encodeURIComponent(this.page)}`,
      'scriptSessionId=',
      `c0-scriptName=${scriptName}`,
      `c0-methodName=${method}`,
      'c0-id=0',
    ];
    args.forEach((a, i) => lines.push(`c0-param${i}=${a}`));
    lines.push('batchId=0');
    lines.push('instanceId=0');
    lines.push('');
    return lines.join('\n');
  }

  async throttle() {
    const wait = Math.max(0, REQUEST_GAP_MS - (Date.now() - this.lastRequestAt));
    if (wait > 0) await sleep(wait);
    this.lastRequestAt = Date.now();
  }

  async call(scriptName, method, args = []) {
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        if (attempt > 0) await this.freshSession();
        await this.throttle();
        const res = await fetch(`${BASE}/dwr/call/plaincall/${scriptName}.${method}.dwr`, {
          method: 'POST',
          headers: {
            'Content-Type': 'text/plain;charset=UTF-8',
            'User-Agent': UA,
            ...(this.cookie ? { Cookie: this.cookie } : {}),
          },
          body: this.buildBody(scriptName, method, args),
          signal: AbortSignal.timeout(20000),
        });
        const text = await res.text();
        if (text.includes('handleBatchException')) {
          const m = text.match(/message:'([^']*)/);
          throw new Error(`DWR error: ${m ? m[1] : 'unknown'}`);
        }
        const m = text.match(/handleCallback\("0","0",\[([\s\S]*)\]\);/);
        if (!m) throw new Error(`Unexpected DWR reply (status ${res.status})`);
        return new Function('return [' + m[1] + '];')();
      } catch (err) {
        if (attempt === 3) throw err;
        console.warn(`  retry ${attempt + 1} for ${scriptName}.${method}(${args.join(',')}): ${err.message}`);
        await sleep(1200 * (attempt + 1));
      }
    }
  }
}

/* ------------------------------------------------------------------ *
 * Limited-concurrency runner with on-disk resume cache
 * ------------------------------------------------------------------ */

function cachePath(kind, code) {
  const dir = path.join(CACHE_DIR, kind);
  mkdirSync(dir, { recursive: true });
  return path.join(dir, `${code}.json`);
}

function loadJson(file, fallback = null) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function saveJson(file, data) {
  writeFileSync(file, JSON.stringify(data));
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return results;
}

/* ------------------------------------------------------------------ *
 * Mirror village source
 * ------------------------------------------------------------------ */

function extractZipEntryCsv(zipBuf) {
  const size = zipBuf.length;
  let eocd = -1;
  const window = Math.min(size - 22, 65535);
  for (let i = size - 22; i >= size - 22 - window; i--) {
    if (zipBuf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error('ZIP end-of-central-directory not found');
  const entryCount = zipBuf.readUInt16LE(eocd + 10);
  const cdOffset = zipBuf.readUInt32LE(eocd + 16);

  const entries = [];
  let off = cdOffset;
  for (let i = 0; i < entryCount; i++) {
    if (zipBuf.readUInt32LE(off) !== 0x02014b50) throw new Error('Bad central directory entry');
    const nameLen = zipBuf.readUInt16LE(off + 28);
    const extraLen = zipBuf.readUInt16LE(off + 30);
    const commentLen = zipBuf.readUInt16LE(off + 32);
    entries.push({
      name: zipBuf.toString('utf8', off + 46, off + 46 + nameLen),
      method: zipBuf.readUInt16LE(off + 10),
      compSize: zipBuf.readUInt32LE(off + 20),
      localOff: zipBuf.readUInt32LE(off + 42),
    });
    off += 46 + nameLen + extraLen + commentLen;
  }

  const entry = entries.find(
    (e) => e.name.endsWith('.csv') && !e.name.includes('__MACOSX') && !e.name.includes('/._')
  );
  if (!entry) throw new Error('No CSV file found inside LGD mirror ZIP');

  const local = entry.localOff;
  const lNameLen = zipBuf.readUInt16LE(local + 26);
  const lExtraLen = zipBuf.readUInt16LE(local + 28);
  const dataStart = local + 30 + lNameLen + lExtraLen;
  const slice = zipBuf.subarray(dataStart, dataStart + entry.compSize);

  if (entry.method === 8) return inflateSync(slice).toString('utf8');
  if (entry.method === 0) return slice.toString('utf8');
  throw new Error(`Unsupported ZIP method ${entry.method}`);
}

async function ensureMirrorCsv() {
  const csvPath = path.join(MIRROR_DIR, '4-village.csv');
  if (existsSync(csvPath)) return csvPath;

  const zipPath = path.join(MIRROR_DIR, '4-village.csv.zip');
  if (!existsSync(zipPath)) {
    console.log('Downloading LGD mirror village dataset (approx 12 MB)…');
    const res = await fetch(MIRROR_ZIP_URL, { redirect: 'follow' });
    if (!res.ok) throw new Error(`Mirror download failed: ${res.status}`);
    await pipeline(res.body, createWriteStream(zipPath));
  }

  console.log('Extracting village CSV…');
  const csv = extractZipEntryCsv(readFileSync(zipPath));
  writeFileSync(csvPath, csv, 'utf8');
  return csvPath;
}

function parseCsvLine(line) {
  const out = [];
  let i = 0;
  let cell = '';
  let inQuotes = false;
  while (i < line.length) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cell += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      cell += ch;
      i++;
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      i++;
      continue;
    }
    if (ch === ',') {
      out.push(cell);
      cell = '';
      i++;
      continue;
    }
    cell += ch;
    i++;
  }
  out.push(cell);
  return out;
}

function cleanName(s) {
  return String(s).trim().replace(/\s+/g, ' ');
}

/* ------------------------------------------------------------------ *
 * Main build
 * ------------------------------------------------------------------ */

const dwr = new LgdDwr();

async function fetchStates() {
  const cached = loadJson(cachePath('states', 'states'), { states: null });
  if (cached.states) return cached.states;
  const states = await dwr.call('lgdDwrStateService', 'getAllStates');
  const cleaned = states
    .map((s) => ({ code: Number(s.stateCode), name: cleanName(s.stateNameEnglish) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  saveJson(cachePath('states', 'states'), { states: cleaned });
  return cleaned;
}

async function fetchChildren() {
  const states = await fetchStates();

  // Districts
  const districtsFor = {};
  const stateCodes = states.map((s) => s.code);
  await mapLimit(stateCodes, CONCURRENCY, async (stateCode) => {
    const file = cachePath('districts', stateCode);
    if (existsSync(file)) {
      districtsFor[stateCode] = loadJson(file);
      return;
    }
    const list = await dwr.call('lgdDwrDistrictService', 'getDistrictList', [`number:${stateCode}`]);
    const cleaned = list
      .map((d) => ({ code: Number(d.districtCode), name: cleanName(d.districtNameEnglish) }))
      .filter((d) => Number.isFinite(d.code) && d.name);
    saveJson(file, cleaned);
    districtsFor[stateCode] = cleaned;
    console.log(`  districts for ${stateCode}: ${cleaned.length}`);
  });

  const everyDistrict = Object.values(districtsFor).flat();
  const districtCount = everyDistrict.length;
  console.log(`Districts total: ${districtCount}`);

  // Sub-districts + blocks
  const subDistrictsFor = {};
  const blocksFor = {};
  await mapLimit(everyDistrict, CONCURRENCY, async (d) => {
    const distCode = d.code;
    const subFile = cachePath('subdistricts', distCode);
    if (existsSync(subFile)) {
      subDistrictsFor[distCode] = loadJson(subFile);
    } else {
      const list = await dwr.call('lgdDwrSubDistrictService', 'getSubdistrictList', [`number:${distCode}`]);
      const cleaned = list
        .map((s) => ({ code: Number(s.subdistrictCode), name: cleanName(s.subdistrictNameEnglish) }))
        .filter((x) => Number.isFinite(x.code) && x.name);
      saveJson(subFile, cleaned);
      subDistrictsFor[distCode] = cleaned;
    }

    const blockFile = cachePath('blocks', distCode);
    if (existsSync(blockFile)) {
      blocksFor[distCode] = loadJson(blockFile);
    } else {
      const list = await dwr.call('lgdDwrBlockService', 'getBlockListbyDistrict', [`number:${distCode}`]);
      const cleaned = list
        .map((b) => ({ code: Number(b.blockCode), name: cleanName(b.blockNameEnglish) }) )
        .filter((x) => Number.isFinite(x.code) && x.name);
      saveJson(blockFile, cleaned);
      blocksFor[distCode] = cleaned;
    }
  });

  return {
    states,
    districtsFor,
    subDistrictsFor,
    blocksFor,
    counts: {
      states: states.length,
      districts: districtCount,
      subDistricts: Object.values(subDistrictsFor).reduce((n, a) => n + a.length, 0),
      blocks: Object.values(blocksFor).reduce((n, a) => n + a.length, 0),
    },
  };
}

async function fetchVillages() {
  const csvPath = await ensureMirrorCsv();
  const villageCsv = readFileSync(csvPath, 'utf8');
  const lines = villageCsv.split('\n');
  const header = parseCsvLine(lines[0].replace(/^\uFEFF/, ''));
  const col = {};
  header.forEach((h, i) => {
    col[h.trim().toLowerCase()] = i;
  });

  const stateCol = col['state code'];
  const subCol = col['subdistrict code'];
  const codeCol = col['village code'];
  const nameCol = col['village name (in englsih)'];
  if (stateCol === undefined || subCol === undefined || codeCol === undefined) {
    throw new Error(`Mirror CSV columns not as expected: ${header.join(', ')}`);
  }

  const byState = new Map();
  const seen = new Set();
  let parsed = 0;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    const c = parseCsvLine(line);
    const state = Number(c[stateCol]);
    const sub = Number(c[subCol]);
    const code = Number(c[codeCol]);
    const name = cleanName(c[nameCol] !== undefined ? c[nameCol] : '');
    if (!Number.isFinite(state) || !Number.isFinite(sub) || !Number.isFinite(code) || !name) continue;
    const key = `${state}:${sub}:${code}`;
    if (seen.has(key)) continue;
    seen.add(key);

    if (!byState.has(state)) byState.set(state, new Map());
    const bySub = byState.get(state);
    if (!bySub.has(sub)) bySub.set(sub, []);
    bySub.get(sub).push([code, name]);
    parsed++;
  }

  const villagesByState = {};
  for (const [state, bySub] of byState) {
    const obj = {};
    for (const [sub, list] of bySub) obj[sub] = list.sort((a, b) => a[1].localeCompare(b[1]));
    villagesByState[state] = obj;
  }

  console.log(`Villages parsed: ${parsed} across ${byState.size} states`);
  return villagesByState;
}

function writeHierarchy({ states, districtsFor, subDistrictsFor, blocksFor }) {
  const stateArr = states.map((s) => `  { code: ${s.code}, name: ${JSON.stringify(s.name)} }`).join(',\n');
  const districtBlocks = states.map((s) => {
    const list = districtsFor[s.code] || [];
    const inner = list.map((d) => `    { code: ${d.code}, name: ${JSON.stringify(d.name)} }`).join(',\n');
    return `  ${s.code}: [\n${inner}\n  ]`;
  }).join(',\n');
  const subDistrictBlocks = Object.keys(subDistrictsFor).sort((a, b) => Number(a) - Number(b)).map((d) => {
    const list = subDistrictsFor[d] || [];
    const inner = list.map((s) => `    { code: ${s.code}, name: ${JSON.stringify(s.name)} }`).join(',\n');
    return `  ${d}: [\n${inner}\n  ]`;
  }).join(',\n');
  const blockBlocks = Object.keys(blocksFor).sort((a, b) => Number(a) - Number(b)).map((d) => {
    const list = blocksFor[d] || [];
    const inner = list.map((b) => `    { code: ${b.code}, name: ${JSON.stringify(b.name)} }`).join(',\n');
    return `  ${d}: [\n${inner}\n  ]`;
  }).join(',\n');

  const content = `import type {\n  RegionState,\n  RegionDistrict,\n  RegionSubDistrict,\n  RegionBlock,\n} from '../../types';\n
// Generated by scripts/build-regions.mjs — do not edit manually.
export const REGION_STATES: RegionState[] = [
${stateArr}
];

export const DISTRICTS_BY_STATE: Record<number, RegionDistrict[]> = {
${districtBlocks}
};

export const SUBDISTRICTS_BY_DISTRICT: Record<number, RegionSubDistrict[]> = {
${subDistrictBlocks}
};

export const BLOCKS_BY_DISTRICT: Record<number, RegionBlock[]> = {
${blockBlocks}
};
`;
  writeFileSync(path.join(OUT_DIR, 'hierarchy.ts'), content);
}

function writeVillageChunks(villagesByState, states) {
  const stateCodes = new Set(states.map((s) => s.code));
  let chunks = 0;
  const list = states.filter((s) => villagesByState[s.code]).map((s) => {
    const bySub = villagesByState[s.code];
    const blocks = Object.keys(bySub).sort((a, b) => Number(a) - Number(b)).map((sub) => {
      const places = bySub[sub]
        .map(([code, name]) => `    [${code}, ${JSON.stringify(name)}]`)
        .join(',\n');
      return `  ${sub}: [\n${places}\n  ]`;
    }).join(',\n');
    const content = `import type { RegionPlace } from '../../../types';\n
// Generated by scripts/build-regions.mjs — do not edit manually.
// State code ${s.code}: ${JSON.stringify(s.name)} — lazy chunk.
export const VILLAGES_BY_SUBDISTRICT: Record<number, RegionPlace[]> = {
${blocks}
};
`;
    writeFileSync(path.join(VILLAGES_OUT, `${s.code}.ts`), content);
    chunks++;
  });
  // Also emit empty chunk files for states with no villages so imports never fail.
  for (const s of states) {
    if (!villagesByState[s.code]) {
      const content = `import type { RegionPlace } from '../../../types';\n
// Generated by scripts/build-regions.mjs — do not edit manually.
export const VILLAGES_BY_SUBDISTRICT: Record<number, RegionPlace[]> = {};
`;
      writeFileSync(path.join(VILLAGES_OUT, `${s.code}.ts`), content);
    }
  }
  return stateCodes.size;
}

function writeVillageLoader(states) {
  const cases = states
    .map((s) => `    case ${s.code}: return import('./${s.code}');`)
    .join('\n');
  const loaderStateCodes = states.map((s) => s.code).join(', ');
  const content = `// Generated by scripts/build-regions.mjs — do not edit manually.
// Static import map so Vite/Rollup can safely code-split every village chunk.
// Valid state codes: ${loaderStateCodes}.

export const loadVillageChunk = (
  stateCode: number
): Promise<{ VILLAGES_BY_SUBDISTRICT: Record<number, [number, string][]> }> => {
  switch (stateCode) {
${cases}
    default:
      return Promise.reject(
        new Error(\`No village chunk for state code \${stateCode}\`)
      );
  }
};
`;
  writeFileSync(path.join(VILLAGES_OUT, 'villageLoaders.ts'), content);
}

function writeMetadata(counts, villageCount) {
  const { states, districts, subDistricts, blocks } = counts;
  const content = `// Generated by scripts/build-regions.mjs — do not edit manually.
export const REGIONS_META = {
  generatedAt: ${JSON.stringify(new Date().toISOString())},
  stateCount: ${states},
  districtCount: ${districts},
  subDistrictCount: ${subDistricts},
  blockCount: ${blocks},
  villageCount: ${villageCount},
  source: {
    hierarchy: 'lgdirectory.gov.in — LGD DWR live endpoints (captcha-free)',
    villages:
      'planemad/india-local-government-directory snapshot merged by LGD village code (LGD DWR does not expose village list endpoints)',
  },
} as const;
`;
  writeFileSync(path.join(OUT_DIR, 'METADATA.ts'), content);
}

async function main() {
  console.log('Connecting to LGD portal…');
  await dwr.freshSession();

  console.log('Fetching states → districts → sub-districts → blocks (resumable)…');
  const hierarchy = await fetchChildren();

  console.log('Building village chunks…');
  const villagesByState = await fetchVillages();

  writeHierarchy(hierarchy);
  writeVillageChunks(villagesByState, hierarchy.states);
  writeVillageLoader(hierarchy.states);
  writeMetadata(hierarchy.counts, Object.values(villagesByState).reduce((n, m) => n + Object.keys(m).length, 0));

  const villageRows = Object.values(villagesByState).reduce(
    (n, m) => n + Object.values(m).reduce((a, list) => a + list.length, 0),
    0
  );

  console.log('\nDone.');
  console.log(`  States:        ${hierarchy.counts.states}`);
  console.log(`  Districts:     ${hierarchy.counts.districts}`);
  console.log(`  Sub-districts: ${hierarchy.counts.subDistricts}`);
  console.log(`  Blocks:        ${hierarchy.counts.blocks}`);
  console.log(`  Villages:      ${villageRows}`);
  console.log(`  Output: ${path.relative(ROOT, OUT_DIR)}/`);
}

main().catch((err) => {
  console.error('\nBuild failed:', err.message || err);
  process.exit(1);
});