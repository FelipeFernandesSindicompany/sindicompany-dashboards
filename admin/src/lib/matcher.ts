import type { Condominio, AdapterType, DetectedFile } from './types';

function normalize(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const MONTH_NAMES: Record<string, number> = {
  janeiro: 1, fevereiro: 2, marco: 3, abril: 4, maio: 5, junho: 6,
  julho: 7, agosto: 8, setembro: 9, outubro: 10, novembro: 11, dezembro: 12,
  jan: 1, fev: 2, mar: 3, abr: 4, mai: 5, jun: 6,
  jul: 7, ago: 8, set: 9, out: 10, nov: 11, dez: 12,
};

export function detectMonth(filename: string): string | null {
  const name = filename.toUpperCase().replace(/[_\-.\s]/g, '_');

  // YYYY-MM or YYYY_MM
  let m = name.match(/(\d{4})[_-](\d{2})(?:[_-]|\.|$)/);
  if (m) {
    const month = parseInt(m[2]);
    if (month >= 1 && month <= 12) return `${m[1]}-${m[2].padStart(2, '0')}`;
  }

  // MM.YYYY or MM_YYYY
  m = name.match(/(\d{2})[._](\d{4})/);
  if (m) {
    const month = parseInt(m[1]);
    if (month >= 1 && month <= 12) return `${m[2]}-${m[1].padStart(2, '0')}`;
  }

  // Month name + year
  const lower = normalize(filename);
  const yearM = lower.match(/\b(202[4-9]|203\d)\b/);
  if (yearM) {
    for (const [name, num] of Object.entries(MONTH_NAMES)) {
      if (lower.includes(name)) {
        return `${yearM[1]}-${String(num).padStart(2, '0')}`;
      }
    }
  }

  return null;
}

export function detectAdapter(filename: string): AdapterType | null {
  const ext = filename.split('.').pop()?.toLowerCase();
  if (!ext) return null;

  if (ext === 'xlsx') {
    if (/prestacao[_\s]contas[_\s]\d+[_\s]\d{4}/i.test(filename)) return 'habitacional_xlsx';
    return 'habitacional_xlsx';
  }
  if (ext === 'xls') {
    if (/prestacaocontas/i.test(filename)) return 'lello_xls';
    return 'lello_xls';
  }
  if (ext === 'pdf' || ext === 'PDF') return 'lirba_pdf'; // most common
  return null;
}

export function matchCondominio(
  filename: string,
  condominios: Condominio[]
): { condominio: Condominio | null; confidence: number } {
  const normFile = normalize(filename);
  let bestMatch: Condominio | null = null;
  let bestScore = 0;

  for (const c of condominios) {
    const normName = normalize(c.nome);
    const parts = normName.split(' ').filter(p => p.length > 3);
    let score = 0;

    if (normFile.includes(normName)) {
      score = 100;
    } else {
      let matchedParts = 0;
      for (const part of parts) {
        if (normFile.includes(part)) matchedParts++;
      }
      if (parts.length > 0) score = Math.floor((matchedParts / parts.length) * 80);
    }

    if (score > bestScore) {
      bestScore = score;
      bestMatch = c;
    }
  }

  return {
    condominio: bestScore >= 40 ? bestMatch : null,
    confidence: bestScore,
  };
}

export function buildDetectedFile(
  id: string,
  originalName: string,
  savedPath: string,
  size: number,
  condominios: Condominio[]
): DetectedFile {
  const ext = originalName.split('.').pop()?.toLowerCase() ?? '';
  const typeMap: Record<string, DetectedFile['type']> = {
    xlsx: 'xlsx', xls: 'xls', pdf: 'pdf', csv: 'csv',
  };

  const detectedMes = detectMonth(originalName);
  const { condominio, confidence } = matchCondominio(originalName, condominios);
  const adapterSuggestion = detectAdapter(originalName);

  return {
    id,
    originalName,
    savedPath,
    size,
    type: typeMap[ext] ?? 'unknown',
    detectedCondominioId: condominio?.id ?? null,
    detectedCondominioNome: condominio?.nome ?? null,
    detectedMes,
    confidence,
    adapterSuggestion,
    status: condominio && detectedMes ? 'ready' : 'detected',
  };
}
