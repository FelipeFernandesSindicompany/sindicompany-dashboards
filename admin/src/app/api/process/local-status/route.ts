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

  // Se ficou "running" por mais de 11 min, o processo Python provavelmente morreu
  const STALE_MS = 11 * 60 * 1000;
  if (job.status === 'running' && Date.now() - job.startedAt > STALE_MS) {
    return NextResponse.json({
      done: true, success: false, status: 'error',
      error: 'Processamento excedido (>11 min). Clique em Injetar novamente.',
    });
  }

  const done = job.status !== 'running';
  const success = job.status === 'done' && job.result?.success === true;

  return NextResponse.json({
    done,
    success,
    status: job.status,
    ...(done ? job.result : {}),
  });
}
