import type { Condominio } from './types';

// Em produção (Vercel), lê o JSON bundled no build.
// Em desenvolvimento local, lê do filesystem.
let _cache: Condominio[] | null = null;

function loadCondominios(): Condominio[] {
  // Local PM2: always read from filesystem so pm2 restart picks up changes (no rebuild needed)
  if (process.env.SINDICOMPANY_PM2) {
    const { readFileSync } = require('fs');
    const { CONFIG_PATH } = require('./paths');
    const raw = readFileSync(CONFIG_PATH, 'utf-8');
    const parsed = JSON.parse(raw);
    return (parsed.condominios as Condominio[]).filter((c: Condominio) => c.ativo);
  }
  try {
    // Vercel / CI: use bundled JSON (rebuilt on every push)
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const data = require('../../../config/condominios.json');
    return (data.condominios as Condominio[]).filter((c: Condominio) => c.ativo);
  } catch {
    // Dev fallback
    const { readFileSync } = require('fs');
    const { CONFIG_PATH } = require('./paths');
    const raw = readFileSync(CONFIG_PATH, 'utf-8');
    const parsed = JSON.parse(raw);
    return (parsed.condominios as Condominio[]).filter((c: Condominio) => c.ativo);
  }
}

export function getCondominios(): Condominio[] {
  if (_cache) return _cache;
  _cache = loadCondominios();
  return _cache;
}

export function getCondominio(id: string): Condominio | undefined {
  return getCondominios().find(c => c.id === id);
}

export const ADAPTER_LABELS: Record<string, string> = {
  habitacional_xlsx: 'Habitacional XLSX',
  lello_xls: 'Lello XLS',
  lirba_pdf: 'Lirba PDF',
  datadigitus_pdf: 'DataDigitus PDF',
  iello_pdf: 'Iello PDF',
};

export const ADAPTER_COLORS: Record<string, string> = {
  habitacional_xlsx: '#3B82F6',
  lello_xls: '#8B5CF6',
  lirba_pdf: '#10B981',
  datadigitus_pdf: '#F59E0B',
  iello_pdf: '#EC4899',
};

export const ACCEPTED_EXTENSIONS: Record<string, string[]> = {
  habitacional_xlsx: ['.xlsx'],
  lello_xls: ['.xls', '.xlsx'],
  lirba_pdf: ['.pdf'],
  datadigitus_pdf: ['.pdf'],
  iello_pdf: ['.pdf'],
};
