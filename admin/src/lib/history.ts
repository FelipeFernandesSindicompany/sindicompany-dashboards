import type { ImportRecord } from './types';

// ── Local FS imports (only used in dev / non-Vercel environments) ──────────────
let _readFileSync: typeof import('fs').readFileSync | null = null;
let _writeFileSync: typeof import('fs').writeFileSync | null = null;
let _existsSync: typeof import('fs').existsSync | null = null;
let _mkdirSync: typeof import('fs').mkdirSync | null = null;
let _HISTORY_PATH: string | null = null;
let _DATA_DIR: string | null = null;

function loadLocalDeps() {
  if (_readFileSync) return;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('fs') as typeof import('fs');
  const paths = require('./paths') as typeof import('./paths');
  _readFileSync = fs.readFileSync;
  _writeFileSync = fs.writeFileSync;
  _existsSync = fs.existsSync;
  _mkdirSync = fs.mkdirSync;
  _HISTORY_PATH = paths.HISTORY_PATH;
  _DATA_DIR = paths.DATA_DIR;
}

// ── GitHub-based read (production on Vercel) ───────────────────────────────────
async function readHistoryFromGitHub(): Promise<ImportRecord[]> {
  const { readFileFromGitHub } = await import('./github');
  const raw = await readFileFromGitHub('data/import_history.json');
  if (!raw) return [];
  try {
    return JSON.parse(raw) as ImportRecord[];
  } catch {
    return [];
  }
}

// ── Public API ─────────────────────────────────────────────────────────────────

/**
 * Read history. In production (GITHUB_TOKEN set), reads from GitHub.
 * In local dev, reads from the local JSON file.
 */
export async function readHistoryAsync(): Promise<ImportRecord[]> {
  if (process.env.GITHUB_TOKEN) {
    return readHistoryFromGitHub();
  }
  loadLocalDeps();
  if (!_existsSync!(_HISTORY_PATH!)) return [];
  try {
    return JSON.parse(_readFileSync!(_HISTORY_PATH!, 'utf-8')) as ImportRecord[];
  } catch {
    return [];
  }
}

/**
 * Synchronous read — local dev only.
 * On Vercel, import history is managed by GitHub Actions (see inject.yml).
 */
export function readHistory(): ImportRecord[] {
  if (process.env.GITHUB_TOKEN) {
    // In production, history writes happen inside GitHub Actions.
    // Return empty array here — use readHistoryAsync() for display.
    return [];
  }
  loadLocalDeps();
  if (!_existsSync!(_HISTORY_PATH!)) return [];
  try {
    return JSON.parse(_readFileSync!(_HISTORY_PATH!, 'utf-8')) as ImportRecord[];
  } catch {
    return [];
  }
}

export function writeHistory(records: ImportRecord[]): void {
  if (process.env.GITHUB_TOKEN) return; // writes happen in GitHub Actions
  loadLocalDeps();
  if (!_existsSync!(_DATA_DIR!)) _mkdirSync!(_DATA_DIR!, { recursive: true });
  _writeFileSync!(_HISTORY_PATH!, JSON.stringify(records, null, 2), 'utf-8');
}

export function appendHistory(record: ImportRecord): void {
  if (process.env.GITHUB_TOKEN) return; // appends happen in GitHub Actions
  const all = readHistory();
  all.unshift(record); // newest first
  writeHistory(all.slice(0, 1000)); // keep max 1000 records
}

export function getLastImportByCondominio(): Record<string, ImportRecord> {
  const all = readHistory();
  const map: Record<string, ImportRecord> = {};
  for (const r of all) {
    if (!map[r.condominioId]) {
      map[r.condominioId] = r; // first = newest (unshift order)
    }
  }
  return map;
}

export function getImportsByCondominio(condominioId: string): ImportRecord[] {
  return readHistory().filter(r => r.condominioId === condominioId);
}
