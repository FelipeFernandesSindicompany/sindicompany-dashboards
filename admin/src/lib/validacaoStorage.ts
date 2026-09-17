import * as fs from 'fs';
import path from 'path';
import { condoDirConciliacao } from './validacaoProcessor';

/** Espelha o layout em disco de conciliacao/storage.py (Python) — só leitura/escrita
 *  dos arquivos já gerados pelo motor, nunca reimplementa a lógica de versionamento. */

export function getLatestVersionDir(pastaDados: string, mes: string): string | null {
  const baseDir = condoDirConciliacao(pastaDados, mes);
  const pointerPath = path.join(baseDir, 'latest');
  if (!fs.existsSync(pointerPath)) return null;
  const versao = fs.readFileSync(pointerPath, 'utf-8').trim();
  const versionDir = path.join(baseDir, versao);
  return fs.existsSync(versionDir) ? versionDir : null;
}

export function readJsonIfExists<T = any>(filePath: string): T | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as T;
  } catch {
    return null;
  }
}

export interface StatusConciliacao {
  existe: boolean;
  versao: string | null;
  achadosBrutos: any[] | null;
  achadosRevisados: any[] | null;
  relatorioExiste: boolean;
  pendentes: number;
}

export function lerStatus(pastaDados: string, mes: string): StatusConciliacao {
  const versionDir = getLatestVersionDir(pastaDados, mes);
  if (!versionDir) {
    return { existe: false, versao: null, achadosBrutos: null, achadosRevisados: null, relatorioExiste: false, pendentes: 0 };
  }
  const achadosBrutos = readJsonIfExists<any[]>(path.join(versionDir, 'achados_brutos.json'));
  const achadosRevisados = readJsonIfExists<any[]>(path.join(versionDir, 'achados_revisados.json'));
  const pendentes = (achadosRevisados ?? []).filter(r => r.revisado_por === 'pendente').length;
  return {
    existe: true,
    versao: path.basename(versionDir),
    achadosBrutos,
    achadosRevisados,
    relatorioExiste: fs.existsSync(path.join(versionDir, 'relatorio_final.pdf')),
    pendentes,
  };
}

export function salvarRevisados(pastaDados: string, mes: string, revisados: any[]): { ok: boolean; erro?: string } {
  const versionDir = getLatestVersionDir(pastaDados, mes);
  if (!versionDir) return { ok: false, erro: 'Nenhuma versão encontrada — rode a extração primeiro.' };
  fs.writeFileSync(path.join(versionDir, 'achados_revisados.json'), JSON.stringify(revisados, null, 2), 'utf-8');
  return { ok: true };
}

export function caminhoRelatorio(pastaDados: string, mes: string): string | null {
  const versionDir = getLatestVersionDir(pastaDados, mes);
  if (!versionDir) return null;
  const pdfPath = path.join(versionDir, 'relatorio_final.pdf');
  return fs.existsSync(pdfPath) ? pdfPath : null;
}
