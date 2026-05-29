import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import path from 'path';
import type { ImportRecord } from './types';
import { HISTORY_PATH, DATA_DIR } from './paths';

function ensureDataDir() {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
}

export function readHistory(): ImportRecord[] {
  if (!existsSync(HISTORY_PATH)) return [];
  try {
    return JSON.parse(readFileSync(HISTORY_PATH, 'utf-8')) as ImportRecord[];
  } catch {
    return [];
  }
}

export function writeHistory(records: ImportRecord[]): void {
  ensureDataDir();
  writeFileSync(HISTORY_PATH, JSON.stringify(records, null, 2), 'utf-8');
}

export function appendHistory(record: ImportRecord): void {
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
