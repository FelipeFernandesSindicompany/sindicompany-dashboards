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

export interface EscopoVerificacao {
  registros: number | null;      // lançamentos/comprovantes lidos do arquivo pelo conciliador
  comprovantes: number | null;   // comprovantes anexados localizados
  regras: { chave: string; nome: string; aplicada: boolean; motivo: string | null }[];
  avisos: string[];
}

const NOMES_REGRAS: Record<string, string> = {
  receita_negativa: 'Receitas com valor negativo',
  rendimento: 'Rendimentos distribuídos entre as contas',
  sem_identificacao: 'Pagamentos sem identificação',
  parcelas: 'Duas parcelas pagas no mesmo mês',
  subcontas: 'Lançamentos nas subcontas corretas',
  previsto_realizado: 'Previsto x Realizado (Resumo de Emissão)',
  gestor: 'Checklist de gestor condominial (pontos de atenção sem regra própria)',
};

export interface StatusConciliacao {
  existe: boolean;
  escopo?: EscopoVerificacao | null;
  versao: string | null;
  achadosBrutos: any[] | null;
  achadosRevisados: any[] | null;
  relatorioExiste: boolean;
  pendentes: number;
  extracaoConcluida: boolean;   // achados_brutos.json existe E o status.json registra conclusão (versão interrompida = false)
  iniciadoEm?: string | null;
}

export function lerStatus(pastaDados: string, mes: string): StatusConciliacao {
  const versionDir = getLatestVersionDir(pastaDados, mes);
  if (!versionDir) {
    return { existe: false, versao: null, achadosBrutos: null, achadosRevisados: null, relatorioExiste: false, pendentes: 0, extracaoConcluida: false };
  }
  const achadosBrutos = readJsonIfExists<any[]>(path.join(versionDir, 'achados_brutos.json'));
  const achadosRevisados = readJsonIfExists<any[]>(path.join(versionDir, 'achados_revisados.json'));
  const pendentes = (achadosRevisados ?? []).filter(r => r.revisado_por === 'pendente').length;
  // O que foi (e o que NÃO foi) verificado nesta extração — evita ler "nenhum achado" como "tudo certo".
  const registros = readJsonIfExists<any[]>(path.join(versionDir, 'registros_comprovantes.json'));
  const rg = readJsonIfExists<any>(path.join(versionDir, 'regras_gerais.json'));
  const escopo: EscopoVerificacao | null = (registros || rg) ? {
    registros: registros ? registros.length : null,
    comprovantes: registros ? registros.filter(r => r.tipo_documento === 'comprovante_anexado').length : null,
    regras: Object.entries((rg?.status ?? {}) as Record<string, any>).map(([chave, v]) => ({
      chave, nome: NOMES_REGRAS[chave] ?? chave, aplicada: !!v.aplicada, motivo: v.motivo ?? null,
    })),
    avisos: (rg?.avisos ?? []) as string[],
  } : null;
  const stJson = readJsonIfExists<any>(path.join(versionDir, 'status.json'));
  const extracaoConcluida = achadosBrutos !== null && (!stJson || !!stJson.concluido_em);
  return {
    existe: true,
    extracaoConcluida,
    iniciadoEm: stJson?.iniciado_em ?? null,
    escopo,
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
