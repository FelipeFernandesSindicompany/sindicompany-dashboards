// admin/scripts/generate-snapshots.mjs
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ADMIN_DIR = join(__dirname, '..');
const PROJECT_ROOT = join(ADMIN_DIR, '..');
const DOCS_DIR = join(PROJECT_ROOT, 'docs');
const CONFIG_PATH = join(PROJECT_ROOT, 'config', 'condominios.json');
const OUT_DIR = join(ADMIN_DIR, 'src', 'data');
const OUT_FILE = join(OUT_DIR, 'snapshots.json');

const VALID_MONTHS = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

/**
 * Extrai o conteúdo interno de var BAL = { ... } usando brace tracking.
 * Evita o bug do regex não-greedy que terminava no primeiro }; de qualquer
 * outro objeto JS (ex: DESP_COLORS) antes do fechamento real do BAL.
 */
function extractBalContent(content) {
  const declMatch = content.match(/var\s+BAL\s*=\s*\{/);
  if (!declMatch) return null;
  const openPos = content.indexOf('{', declMatch.index);
  if (openPos === -1) return null;
  let depth = 0;
  for (let i = openPos; i < content.length; i++) {
    if (content[i] === '{') depth++;
    else if (content[i] === '}') {
      depth--;
      if (depth === 0) return content.slice(openPos + 1, i);
    }
  }
  return null;
}

function extractBALFromContent(content) {
  const blockText = extractBalContent(content);
  if (!blockText) return null;
  const keyMatches = [...blockText.matchAll(/\b([a-z]{3}\d{2})\s*:/g)];
  const allKeys = keyMatches.map(m => m[1]).filter(k => VALID_MONTHS.some(v => k.startsWith(v)));
  if (!allKeys.length) return null;
  const lastKey = allKeys[allKeys.length - 1];
  const num = (field) => {
    const m = blockText.match(new RegExp(`${lastKey}[\\s\\S]*?${field}\\s*:\\s*([\\d.-]+)`));
    return m ? parseFloat(m[1]) : 0;
  };
  const str = (field) => {
    const m = blockText.match(new RegExp(`${lastKey}[\\s\\S]*?${field}\\s*:\\s*["']([^"']+)["']`));
    return m ? m[1] : '';
  };
  const abbr = lastKey.slice(0, 3);
  const yr = lastKey.slice(3);
  const monthMap = { jan:'Jan',fev:'Fev',mar:'Mar',abr:'Abr',mai:'Mai',jun:'Jun',jul:'Jul',ago:'Ago',set:'Set',out:'Out',nov:'Nov',dez:'Dez' };
  return {
    lastKey,
    lastMonth: `${monthMap[abbr] || abbr}/${yr}`,
    allKeys,
    data: {
      tit: str('tit'),
      tAtual: num('tAtual'),
      tCred: num('tCred'),
      tDeb: num('tDeb'),
      inad: num('inad'),
      tAnt: num('tAnt'),
    }
  };
}

// Load condominios
const config = JSON.parse(readFileSync(CONFIG_PATH, 'utf-8'));
const condominios = config.condominios.filter(c => c.ativo);

// Extract BAL from each dashboard
const snapshots = {};
let found = 0;
for (const condo of condominios) {
  const htmlPath = join(DOCS_DIR, condo.html_file);
  if (!existsSync(htmlPath)) continue;
  try {
    const content = readFileSync(htmlPath, 'utf-8');
    const bal = extractBALFromContent(content);
    if (bal) {
      snapshots[condo.html_file] = bal;
      found++;
    }
  } catch (e) {
    // skip
  }
}

// Write snapshot
mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(OUT_FILE, JSON.stringify(snapshots, null, 2), 'utf-8');
console.log(`Snapshot gerado: ${found}/${condominios.length} dashboards em ${OUT_FILE}`);
