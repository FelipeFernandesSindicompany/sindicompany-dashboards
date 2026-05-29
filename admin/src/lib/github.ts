// GitHub API helper for cloud operations
const OWNER = process.env.GITHUB_OWNER ?? 'FelipeFernandesSindicompany';
const REPO  = process.env.GITHUB_REPO  ?? 'sindicompany-dashboards';
const TOKEN = process.env.GITHUB_TOKEN ?? '';
const BASE  = 'https://api.github.com';

function headers() {
  return {
    'Authorization': `Bearer ${TOKEN}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };
}

export async function uploadFileToGitHub(
  content: Buffer,
  path: string,
  message: string
): Promise<void> {
  const b64 = content.toString('base64');

  // Check if file exists (need SHA to update)
  let sha: string | undefined;
  try {
    const existing = await fetch(`${BASE}/repos/${OWNER}/${REPO}/contents/${path}`, { headers: headers() });
    if (existing.ok) {
      const data = await existing.json();
      sha = data.sha;
    }
  } catch {}

  const body: any = { message, content: b64, branch: 'main' };
  if (sha) body.sha = sha;

  const res = await fetch(`${BASE}/repos/${OWNER}/${REPO}/contents/${path}`, {
    method: 'PUT',
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`GitHub upload failed: ${res.status} ${JSON.stringify(err)}`);
  }
}

export async function triggerWorkflow(inputs: Record<string, string>): Promise<void> {
  const res = await fetch(
    `${BASE}/repos/${OWNER}/${REPO}/actions/workflows/inject.yml/dispatches`,
    {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ ref: 'main', inputs }),
    }
  );
  if (!res.ok) {
    throw new Error(`Failed to trigger workflow: ${res.status}`);
  }
}

export async function getLatestWorkflowRun(afterDate: string): Promise<any | null> {
  // Wait a moment for the run to appear
  const res = await fetch(
    `${BASE}/repos/${OWNER}/${REPO}/actions/workflows/inject.yml/runs?per_page=5&created=>=${afterDate}`,
    { headers: headers() }
  );
  if (!res.ok) return null;
  const data = await res.json();
  return data.workflow_runs?.[0] ?? null;
}

export async function getWorkflowRunStatus(runId: number): Promise<{
  status: string;
  conclusion: string | null;
  outputs: Record<string, string>;
}> {
  // Get run status
  const runRes = await fetch(`${BASE}/repos/${OWNER}/${REPO}/actions/runs/${runId}`, { headers: headers() });
  const run = await runRes.json();

  // Get job outputs if completed
  let outputs: Record<string, string> = {};
  if (run.status === 'completed') {
    const jobsRes = await fetch(`${BASE}/repos/${OWNER}/${REPO}/actions/runs/${runId}/jobs`, { headers: headers() });
    const jobs = await jobsRes.json();
    const job = jobs.jobs?.[0];
    if (job) {
      // Parse outputs from steps
      for (const step of job.steps ?? []) {
        if (step.name === 'Run injection' && step.conclusion === 'success') {
          // Outputs are in the run itself via job outputs
        }
      }
    }
    // Get outputs via jobs API
    const outputRes = await fetch(`${BASE}/repos/${OWNER}/${REPO}/actions/runs/${runId}/jobs?filter=latest`, { headers: headers() });
    const outputData = await outputRes.json();
    const mainJob = outputData.jobs?.find((j: any) => j.name === 'inject');
    // Note: job outputs not directly accessible via REST API for non-reusable workflows
    // We'll read the log to get RESUMO
    if (run.status === 'completed' && run.conclusion === 'success') {
      const logRes = await fetch(`${BASE}/repos/${OWNER}/${REPO}/actions/runs/${runId}/logs`, {
        headers: { ...headers(), 'Accept': 'application/vnd.github+json' },
        redirect: 'follow',
      });
      if (logRes.ok) {
        const logText = await logRes.text();
        const resumoMatch = logText.match(/\[RESUMO\]\s*(\{[^\n]+\})/);
        if (resumoMatch) outputs.resumo = resumoMatch[1];
      }
    }
  }

  return { status: run.status, conclusion: run.conclusion, outputs };
}

export async function readFileFromGitHub(path: string): Promise<string> {
  const res = await fetch(`${BASE}/repos/${OWNER}/${REPO}/contents/${path}?ref=main`, { headers: headers() });
  if (!res.ok) return '';
  const data = await res.json();
  return Buffer.from(data.content, 'base64').toString('utf-8');
}
