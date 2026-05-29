import { NextRequest, NextResponse } from 'next/server';
import { v4 as uuidv4 } from 'uuid';
import { getCondominio } from '@/lib/condominios';
import type { ProcessRequest } from '@/lib/types';
import { triggerWorkflow, getLatestWorkflowRun } from '@/lib/github';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

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

    const recordId = uuidv4();
    const triggeredAt = new Date().toISOString().slice(0, 19) + 'Z';

    // Trigger GitHub Actions workflow
    await triggerWorkflow({
      file_path: savedPath,
      condominio_id: condominioId,
      mes,
      record_id: recordId,
    });

    // Wait briefly then find the run ID
    await new Promise(r => setTimeout(r, 3000));
    const run = await getLatestWorkflowRun(triggeredAt.slice(0, 10));
    const runId = run?.id ?? null;

    return NextResponse.json({
      success: true,
      status: 'running',
      runId,
      recordId,
      condominioNome: condo.nome,
      log: [`Processamento iniciado via GitHub Actions`],
    });
  } catch (err: any) {
    console.error('[process] erro:', err?.message ?? err);
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  }
}
