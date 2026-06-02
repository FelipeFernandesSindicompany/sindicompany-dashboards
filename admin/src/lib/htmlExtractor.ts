import { readFileSync, existsSync } from 'fs';
import path from 'path';
import type { BALEntry } from './types';
import { DOCS_DIR } from './paths';

const VALID_MONTHS = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

export interface ExtractedBAL {
  lastKey: string;
  lastMonth: string;
  data: Partial<BALEntry>;
  allKeys: string[];
}

export function extractBAL(htmlFile: string): ExtractedBAL | null {
  // On Vercel: use pre-generated snapshot (HTML files are not accessible at runtime)
  if (process.env.GITHUB_TOKEN || process.env.VERCEL) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const snapshots = require('../data/snapshots.json');
      // Direct lookup
      if (snapshots[htmlFile]) return snapshots[htmlFile] as ExtractedBAL;
      // Fallback: normalize Unicode (NFC/NFD differences between OS)
      const nfc = htmlFile.normalize('NFC');
      const nfd = htmlFile.normalize('NFD');
      for (const key of Object.keys(snapshots)) {
        if (key.normalize('NFC') === nfc || key.normalize('NFD') === nfd) {
          return snapshots[key] as ExtractedBAL;
        }
      }
      return null;
    } catch {
      return null;
    }
  }
  // Local: read from filesystem
  try {
    const htmlPath = path.join(DOCS_DIR, htmlFile);
    if (!existsSync(htmlPath)) return null;
    const content = readFileSync(htmlPath, 'utf-8');
    return extractBALFromContent(content);
  } catch {
    return null;
  }
}

/**
 * Extrai o conteúdo interno de var BAL = { ... } usando brace tracking.
 * Evita o bug do regex não-greedy que terminava no primeiro }; de outro
 * objeto JS (ex: DESP_COLORS) antes do fechamento real do BAL.
 */
function extractBalContent(content: string): string | null {
  const declMatch = content.match(/var\s+BAL\s*=\s*\{/);
  if (!declMatch || declMatch.index === undefined) return null;
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

function extractBALFromContent(content: string): ExtractedBAL | null {
  // Find all valid month keys inside var BAL = { ... }
  const blockText = extractBalContent(content);
  if (!blockText) return null;
  const keyMatches = [...blockText.matchAll(/\b([a-z]{3}\d{2})\s*:/g)];
  const allKeys = keyMatches
    .map(m => m[1])
    .filter(k => VALID_MONTHS.some(v => k.startsWith(v)));

  if (!allKeys.length) return null;

  const lastKey = allKeys[allKeys.length - 1];

  // Extract fields from the last entry
  const num = (field: string): number => {
    const m = blockText.match(new RegExp(`${lastKey}[\\s\\S]*?${field}\\s*:\\s*([\\d.-]+)`));
    return m ? parseFloat(m[1]) : 0;
  };
  const str = (field: string): string => {
    const m = blockText.match(new RegExp(`${lastKey}[\\s\\S]*?${field}\\s*:\\s*["']([^"']+)["']`));
    return m ? m[1] : '';
  };

  // Convert "mai26" → "Maio/26"
  const abbr = lastKey.slice(0, 3);
  const yr = lastKey.slice(3);
  const monthMap: Record<string, string> = {
    jan:'Jan', fev:'Fev', mar:'Mar', abr:'Abr', mai:'Mai',
    jun:'Jun', jul:'Jul', ago:'Ago', set:'Set', out:'Out', nov:'Nov', dez:'Dez',
  };
  const lastMonth = `${monthMap[abbr] || abbr}/${yr}`;

  return {
    lastKey,
    lastMonth,
    allKeys,
    data: {
      tit: str('tit'),
      tAtual: num('tAtual'),
      tCred: num('tCred'),
      tDeb: num('tDeb'),
      inad: num('inad'),
      tAnt: num('tAnt'),
    },
  };
}
