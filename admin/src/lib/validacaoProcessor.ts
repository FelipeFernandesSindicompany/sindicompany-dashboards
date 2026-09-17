import { spawn } from 'child_process';
import { PROJECT_ROOT } from './paths';
import path from 'path';

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

    // Extração de pastas de 300+ páginas pode demorar — 15 min de teto.
    const timeoutId = setTimeout(() => {
      child.kill('SIGTERM');
      setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* ignore */ } }, 2000);
      settle({ success: false, log: allLines, error: 'Timeout de 15 minutos excedido' });
    }, 900_000);

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
export const EMPRESAS_COM_CONCILIACAO = ['addomus_pdf'];

export function condoDirConciliacao(pastaDados: string, mes: string): string {
  return path.join(PROJECT_ROOT, pastaDados, 'conciliacao', mes);
}
