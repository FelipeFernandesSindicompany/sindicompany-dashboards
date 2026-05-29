import { NextRequest, NextResponse } from 'next/server';
import { getWorkflowRunStatus } from '@/lib/github';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const runId = request.nextUrl.searchParams.get('runId');
  if (!runId) {
    return NextResponse.json({ error: 'runId obrigatório' }, { status: 400 });
  }

  try {
    const result = await getWorkflowRunStatus(Number(runId));

    const done = result.status === 'completed';
    const success = result.conclusion === 'success';

    let resumo = null;
    if (done && result.outputs.resumo) {
      try { resumo = JSON.parse(result.outputs.resumo); } catch {}
    }

    return NextResponse.json({
      done,
      success: done && success,
      status: result.status,
      conclusion: result.conclusion,
      resumo,
      error: done && !success ? 'Erro no processamento — verifique o arquivo' : undefined,
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
