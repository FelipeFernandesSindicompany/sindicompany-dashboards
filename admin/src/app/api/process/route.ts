import { NextRequest, NextResponse } from 'next/server';
import { v4 as uuidv4 } from 'uuid';
import { injectarMes } from '@/lib/processor';
import { appendHistory } from '@/lib/history';
import { getCondominio } from '@/lib/condominios';
import type { ProcessRequest } from '@/lib/types';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

// Modo: 'cloud' quando GITHUB_TOKEN está definido (Vercel), 'local' caso contrário
const IS_CLOUD = !!process.env.GITHUB_TOKEN;

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as ProcessRequest;
    const { condominioId, mes, savedPath } = body;

    if (!condominioId || !mes || !savedPath) {
      return NextResponse.json({ error: 'Parâmetros inválidos' }, { status: 400 });
    }

    const condo = getCondominio(condominioId);
    if (!condo) {
      return NextResponse.json({ error: `Condomínio '${condominioId}' não encontrado` }, { status: 404 });
    }

    if (!/^\d{4}-\d{2}$/.test(mes)) {
      return NextResponse.json({ error: 'Formato de mês inválido. Use YYYY-MM' }, { status: 400 });
    }

    if (IS_CLOUD) {
      // ── Modo Vercel: dispara GitHub Actions e retorna runId para polling ──
      const { triggerWorkflow, getLatestWorkflowRun } = await import('@/lib/github');
      const recordId = uuidv4();
      const triggeredAt = new Date().toISOString().slice(0, 19) + 'Z';

      await triggerWorkflow({
        file_path: savedPath,
        condominio_id: condominioId,
        mes,
        record_id: recordId,
      });

      await new Promise(r => setTimeout(r, 3000));
      const run = await getLatestWorkflowRun(triggeredAt.slice(0, 10));
      const runId = run?.id ?? null;

      return NextResponse.json({
        success: true,
        status: 'running',
        runId,
        recordId,
        condominioNome: condo.nome,
        log: ['Processamento iniciado via GitHub Actions'],
      });

    } else {
      // ── Modo Local (ngrok / PM2): roda Python direto no servidor ──────────
      const result = await injectarMes(condominioId, mes, savedPath);

      const record = {
        id: uuidv4(),
        timestamp: new Date().toISOString(),
        condominioId,
        condominioNome: condo.nome,
        mes,
        arquivo: savedPath.split(/[/\\]/).pop() ?? savedPath,
        status: result.success ? 'success' as const : 'error' as const,
        operador: 'admin',
        log: result.log,
        error: result.error,
      };

      appendHistory(record);

      // Extrai o resumo do log
      const resumoLine = result.log.find(l => l.includes('[RESUMO]'));
      const resumo = resumoLine
        ? (() => { try { return JSON.parse(resumoLine.split('[RESUMO]')[1].trim()); } catch { return null; } })()
        : null;

      return NextResponse.json({ success: result.success, log: result.log, record, resumo });
    }

  } catch (err: any) {
    console.error('[process] erro:', err?.message ?? err);
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  }
}
