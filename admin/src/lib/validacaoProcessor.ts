import { spawn } from 'child_process';
import { unlinkSync } from 'fs';
import { PROJECT_ROOT } from './paths';
import path from 'path';
import type { Condominio } from './types';

export interface EtapaResult {
  success: boolean;
  log: string[];
  error?: string;
}

/**
 * Roda uma etapa do motor de conciliação (scripts/gerar_relatorio_conciliacao.py)
 * — mesmo padrão de spawn de processor.ts::injectarMes(), reaproveitado aqui
 * em vez de duplicado, só que genérico para as 3 etapas (extrair/interpretar/render).
 */
export async function rodarEtapaConciliacao(args: {
  condominioId: string;
  mes: string; // 'YYYY-MM'
  etapa: 'extrair' | 'interpretar' | 'render';
  arquivo?: string; // caminho absoluto, obrigatório só em 'extrair'
}): Promise<EtapaResult> {
  const script = path.join(PROJECT_ROOT, 'scripts', 'gerar_relatorio_conciliacao.py');
  const cliArgs = [
    script,
    '--condominio', args.condominioId,
    '--mes', args.mes,
    '--etapa', args.etapa,
    ...(args.arquivo ? ['--arquivo', args.arquivo] : []),
  ];

  const allLines: string[] = [];
  const processChunk = (data: Buffer) => {
    data.toString('utf-8').split('\n').forEach(raw => {
      const line = raw.trim();
      if (line) allLines.push(line);
    });
  };

  return new Promise<EtapaResult>((resolve) => {
    let settled = false;
    const settle = (result: EtapaResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      resolve(result);
    };

    const child = spawn('python', cliArgs, {
      cwd: PROJECT_ROOT,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' },
    });

    child.stdout.on('data', processChunk);
    child.stderr.on('data', processChunk);

    // Extração de pastas de 300+ páginas pode demorar — 45 min de teto (a Pasta Digital do Onze 22, 542 páginas, leva ~11 min na primeira leitura).
    const timeoutId = setTimeout(() => {
      child.kill('SIGTERM');
      setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* ignore */ } }, 2000);
      settle({ success: false, log: allLines, error: 'Timeout de 45 minutos excedido' });
    }, 2_700_000);

    child.on('close', (code) => {
      const success = code === 0 && !allLines.some(l => l.includes('[ERRO]'));
      settle({
        success,
        log: allLines,
        ...(!success ? { error: allLines.find(l => l.includes('[ERRO]')) ?? `Processo encerrado com código ${code}` } : {}),
      });
    });

    child.on('error', (err) => {
      settle({ success: false, log: allLines, error: err.message });
    });
  });
}

/** Condomínios com conciliador implementado — mesma lista de conciliacao/__init__.py::CONCILIADORES. */
export const EMPRESAS_COM_CONCILIACAO = ['addomus_pdf', 'lirba_pdf', 'habitacional_xlsx', 'datadigitus_pdf', 'gk_pdf', 'manager_adm_pdf', 'consvicta_pdf', 'lfc_xlsx', 'lello_xls', 'alliz_pdf', 'auxiliadora_xls', 'ucondo_pdf', 'convivium_pdf', 'iello_pdf', 'lello_pdf'];

/**
 * "lirba_pdf" não é um formato único — adapters/lirba_pdf.py tem 4
 * sub-parsers (posicao_financeira/total_da_conta/webware/gcont), cada um pra
 * um layout de PDF diferente. conciliacao/lirba_pdf.py foi validado contra
 * "posicao_financeira" (piloto: 730 Padre Carvalho) e "total_da_conta"
 * (pilotos: Central das Artes e Residencial Blue Sky — mesma "Demonstrativo
 * de Despesas"/"Comprovante de Despesa" do ContasData, só a tabela-resumo
 * usada pelo adapter de demonstrativo muda). "webware" e "gcont" ainda não
 * têm extrator de comprovantes correspondente, então continuam fora.
 */
const SUBFORMATOS_LIRBA_VALIDADOS = new Set(['posicao_financeira', 'total_da_conta']);
/**
 * Club Park Butantã é cadastrado como "lirba_pdf" mas o PDF real é do
 * sistema GCONT (formato totalmente diferente) — tem um conciliador
 * ESPECÍFICO por condomínio (conciliacao/condominios/club_park_butanta.py,
 * despacho por id, não por empresa_gestora/extract_cats). Validado com 4
 * meses reais.
 */
const CONDOMINIOS_LIRBA_COM_CONCILIADOR_ESPECIFICO = new Set(['club_park_butanta', 'nyc']);
export function condominioSuportado(condo: Pick<Condominio, 'id' | 'empresa_gestora' | 'parser_config'>): boolean {
  if (!EMPRESAS_COM_CONCILIACAO.includes(condo.empresa_gestora)) return false;
  if (condo.empresa_gestora === 'lirba_pdf') {
    if (CONDOMINIOS_LIRBA_COM_CONCILIADOR_ESPECIFICO.has(condo.id)) return true;
    return SUBFORMATOS_LIRBA_VALIDADOS.has(condo.parser_config?.extract_cats ?? '');
  }
  return true;
}

export function condoDirConciliacao(pastaDados: string, mes: string): string {
  return path.join(PROJECT_ROOT, pastaDados, 'conciliacao', mes);
}


/**
 * Tarefa de validação em segundo plano: extrair + interpretar numa só execução no SERVIDOR.
 * Antes, a página encadeava as duas etapas depois de uma requisição de vários minutos; se a conexão caía
 * (túnel, página atualizada) a 2ª etapa se perdia e a tela mostrava dezenas de achados "pendentes" sem texto,
 * ou "nenhuma divergência" com a extração ainda em andamento. Agora a página só acompanha o estado por polling.
 * O estado fica em globalThis (as rotas da API podem ser empacotadas em módulos separados).
 */
export interface JobValidacao {
  estado: 'rodando' | 'concluido' | 'erro';
  etapa: 'extrair' | 'interpretar';
  iniciadoEm: string;
  terminadoEm?: string;
  log: string[];
  erro?: string;
}

const jobs: Map<string, JobValidacao> = ((globalThis as any).__jobsValidacao ??= new Map<string, JobValidacao>());

export function jobDe(condominioId: string, mes: string): JobValidacao | null {
  return jobs.get(`${condominioId}|${mes}`) ?? null;
}

export function iniciarJobValidacao(args: { condominioId: string; mes: string; arquivoTmp: string }): { ok: boolean; erro?: string } {
  const chave = `${args.condominioId}|${args.mes}`;
  if (jobs.get(chave)?.estado === 'rodando') {
    return { ok: false, erro: 'Já existe uma extração em andamento para este condomínio e mês. Aguarde terminar.' };
  }
  const job: JobValidacao = { estado: 'rodando', etapa: 'extrair', iniciadoEm: new Date().toISOString(), log: [] };
  jobs.set(chave, job);
  (async () => {
    try {
      const r1 = await rodarEtapaConciliacao({ condominioId: args.condominioId, mes: args.mes, etapa: 'extrair', arquivo: args.arquivoTmp });
      job.log.push(...r1.log);
      if (!r1.success) { job.estado = 'erro'; job.erro = r1.error ?? 'Falha na extração'; return; }
      job.etapa = 'interpretar';
      const r2 = await rodarEtapaConciliacao({ condominioId: args.condominioId, mes: args.mes, etapa: 'interpretar' });
      job.log.push(...r2.log);
      if (!r2.success) { job.estado = 'erro'; job.erro = r2.error ?? 'Falha ao gerar o esqueleto de revisão'; return; }
      job.estado = 'concluido';
    } catch (e: any) {
      job.estado = 'erro'; job.erro = e?.message ?? 'Erro interno';
    } finally {
      job.terminadoEm = new Date().toISOString();
      try { unlinkSync(args.arquivoTmp); } catch { /* ignore */ }
    }
  })();
  return { ok: true };
}
