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
      const snap = snapshots[htmlFile];
      if (snap) return snap as ExtractedBAL;
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

function extractBALFromContent(content: string): ExtractedBAL | null {

  // Find all valid month keys inside var BAL = { ... }
  const balBlock = content.match(/var\s+BAL\s*=\s*\{([\s\S]*?)\n\s*\};/);
  if (!balBlock) return null;

  const blockText = balBlock[1];
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
