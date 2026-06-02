export interface Condominio {
  id: string;
  nome: string;
  empresa_gestora: AdapterType;
  pasta_dados: string;
  html_file: string;
  ativo: boolean;
  cor: string;
  unidades: number;
}

export type AdapterType =
  | 'habitacional_xlsx'
  | 'lello_xls'
  | 'lirba_pdf'
  | 'datadigitus_pdf'
  | 'iello_pdf';

export interface BALEntry {
  tit: string;
  per: string;
  tAnt: number;
  tCred: number;
  tDeb: number;
  tAtual: number;
  tDesp: number;
  inad: number;
  inadProc: number;
}

export interface CondominioStatus {
  condominio: Condominio;
  lastKey: string | null;
  lastMonth: string | null;
  lastData: BALEntry | null;
  lastImport: ImportRecord | null;
  status: 'current' | 'pending' | 'error' | 'no_data';
}

export interface ImportRecord {
  id: string;
  timestamp: string;
  condominioId: string;
  condominioNome: string;
  mes: string;
  arquivo: string;
  status: 'success' | 'error' | 'warning';
  operador: string;
  log: string[];
  error?: string;
}

export interface DetectedFile {
  id: string;
  originalName: string;
  savedPath: string;
  size: number;
  type: 'xlsx' | 'xls' | 'pdf' | 'csv' | 'unknown';
  detectedCondominioId: string | null;
  detectedCondominioNome: string | null;
  detectedMes: string | null;
  confidence: number;
  adapterSuggestion: AdapterType | null;
  /** 'month_exists' = mês já foi importado; pode ser substituído com --force */
  status: 'detected' | 'ready' | 'processing' | 'done' | 'error' | 'month_exists';
  error?: string;
  resumo?: Record<string, any> | null;
}

export interface ProcessRequest {
  fileId: string;
  condominioId: string;
  mes: string;
  savedPath: string;
  /** Quando true, sobrescreve o mês existente em vez de recusar */
  force?: boolean;
}
