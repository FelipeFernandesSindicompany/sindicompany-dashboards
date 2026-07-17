import { NextRequest, NextResponse } from 'next/server';
import { getJob } from '@/lib/local-jobs';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const jobId = request.nextUrl.searchParams.get('jobId');
  if (!jobId) {
    return NextResponse.json({ error: 'jobId obrigatório' }, { status: 400 });
  }

  const job = getJob(jobId);
  if (!job) {
    // Job não existe — pode ter sido criado em outra instância antes do restart
    return NextResponse.json({
      done: true, success: false, status: 'error',
      error: 'Job perdido (servidor reiniciado). Clique em Injetar novamente.',
    });
  }

  if (job.status === 'running') {
    // 3 min sem nenhuma saída do Python → processo provavelmente travou
    const HEARTBEAT_STALE_MS = 3 * 60 * 1000;
    // 12 min absolutos como rede de segurança final
    const ABSOLUTE_STALE_MS  = 12 * 60 * 1000;

    const heartbeatStale = job.heartbeatAt != null && (Date.now() - job.heartbeatAt > HEARTBEAT_STALE_MS);
    const absoluteStale  = Date.now() - job.startedAt > ABSOLUTE_STALE_MS;
    // Sem nenhum heartbeat após 2 min = Python não iniciou ou morreu imediatamente
    const silentStale    = job.heartbeatAt == null && (Date.now() - job.startedAt > 2 * 60 * 1000);

    if (heartbeatStale || absoluteStale || silentStale) {
      return NextResponse.json({
        done: true, success: false, status: 'error',
        error: heartbeatStale
          ? 'Processo parou de responder (3 min sem saída). Verifique se os dados foram inseridos.'
          : absoluteStale
          ? 'Processamento excedido (>12 min). Verifique se os dados foram inseridos.'
          : 'Processo não iniciou. Clique em Tentar novamente.',
        log: job.log ?? [],
      });
    }
  }

  const done = job.status !== 'running';
  const success = job.status === 'done' && job.result?.success === true;

  return NextResponse.json({
    done,
    success,
    status: job.status,
    log: job.log ?? [],
    ...(done ? job.result : {}),
  });
}
