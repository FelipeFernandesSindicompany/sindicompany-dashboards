import { randomUUID } from 'crypto';
import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import os from 'os';

// Diretório persistente — sobrevive ao restart do PM2
const JOBS_DIR = join(os.tmpdir(), 'sindicompany-jobs');

function ensureDir() {
  try { mkdirSync(JOBS_DIR, { recursive: true }); } catch {}
}

function jobPath(id: string) {
  return join(JOBS_DIR, `${id}.json`);
}

export type JobStatus = 'running' | 'done' | 'error';

export interface LocalJob {
  id: string;
  status: JobStatus;
  result?: any;
  startedAt: number;
  heartbeatAt?: number;
  log?: string[];
}

export function createJob(): LocalJob {
  ensureDir();
  const job: LocalJob = { id: randomUUID(), status: 'running', startedAt: Date.now(), log: [] };
  writeFileSync(jobPath(job.id), JSON.stringify(job), 'utf-8');
  return job;
}

export function updateJobProgress(id: string, line: string) {
  ensureDir();
  const existing = getJob(id);
  if (existing && existing.status === 'running') {
    const log = [...(existing.log ?? []), line].slice(-100);
    writeFileSync(jobPath(id), JSON.stringify({ ...existing, heartbeatAt: Date.now(), log }), 'utf-8');
  }
}

export function completeJob(id: string, result: any) {
  ensureDir();
  const existing = getJob(id);
  if (existing) {
    writeFileSync(jobPath(id), JSON.stringify({ ...existing, status: 'done', result }), 'utf-8');
  }
}

export function failJob(id: string, error: string) {
  ensureDir();
  const existing = getJob(id);
  if (existing) {
    writeFileSync(jobPath(id), JSON.stringify({
      ...existing, status: 'error', result: { success: false, log: [], error },
    }), 'utf-8');
  }
}

export function getJob(id: string): LocalJob | undefined {
  try {
    const p = jobPath(id);
    if (!existsSync(p)) return undefined;
    return JSON.parse(readFileSync(p, 'utf-8'));
  } catch {
    return undefined;
  }
}
