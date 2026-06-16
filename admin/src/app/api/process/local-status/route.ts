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
    return NextResponse.json({ error: 'Job não encontrado' }, { status: 404 });
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
