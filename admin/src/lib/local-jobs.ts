import { randomUUID } from 'crypto';

export type JobStatus = 'running' | 'done' | 'error';

export interface LocalJob {
  id: string;
  status: JobStatus;
  result?: any;
  startedAt: number;
}

// Persiste na memória do processo PM2 — sobrevive a múltiplas requests
const jobs = new Map<string, LocalJob>();

export function createJob(): LocalJob {
  const job: LocalJob = { id: randomUUID(), status: 'running', startedAt: Date.now() };
  jobs.set(job.id, job);
  return job;
}

export function completeJob(id: string, result: any) {
  const job = jobs.get(id);
  if (job) { job.status = 'done'; job.result = result; }
}

export function failJob(id: string, error: string) {
  const job = jobs.get(id);
  if (job) { job.status = 'error'; job.result = { success: false, log: [], error }; }
}

export function getJob(id: string): LocalJob | undefined {
  return jobs.get(id);
}
