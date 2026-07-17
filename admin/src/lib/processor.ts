import { spawn } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import path from 'path';
import { PROJECT_ROOT, SCRIPTS_DIR } from './paths';

export interface ProcessResult {
  success: boolean;
  /** true quando o mês já existe no dashboard e force não foi usado */
  monthExists?: boolean;
  log: string[];
  error?: string;
}

export async function injectarMes(
  condominioId: string,
  mes: string,
  arquivoPath: string,
  force = false,
  onProgress?: (line: string) => void,
): Promise<ProcessResult> {
  // Copy file to a temp path without Unicode characters to avoid Windows
  // code-page corruption when Node.js passes the path to Python as a CLI arg.
  const ext = path.extname(arquivoPath) || '.xlsx';
  const tmpPath = path.join(os.tmpdir(), `sc_inj_${Date.now()}${ext}`);
  fs.copyFileSync(arquivoPath, tmpPath);

  const script = path.join(SCRIPTS_DIR, 'injetar_mes.py');
  const args = [
    script,
    '--condominio', condominioId,
    '--mes', mes,
    '--arquivo', tmpPath,
    ...(force ? ['--force'] : []),
  ];

  const allLines: string[] = [];

  const processChunk = (data: Buffer) => {
    data.toString('utf-8').split('\n').forEach(raw => {
      const line = raw.trim();
      if (!line) return;
      allLines.push(line);
      try { onProgress?.(line); } catch { /* ignore callback errors */ }
    });
  };

  return new Promise<ProcessResult>((resolve) => {
    let settled = false;

    const settle = (result: ProcessResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      resolve(result);
    };

    const child = spawn('python', args, {
      cwd: PROJECT_ROOT,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' },
    });

    child.stdout.on('data', processChunk);
    child.stderr.on('data', processChunk);

    // 10 min absolute timeout — mata o processo filho explicitamente
    const timeoutId = setTimeout(() => {
      child.kill('SIGTERM');
      setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* ignore */ } }, 2000);
      settle({ success: false, log: allLines, error: 'Timeout de 10 minutos excedido' });
    }, 600_000);

    child.on('close', (code) => {
      const success   = allLines.some(l => l.includes('[OK]'));
      const hasError  = allLines.some(l => l.includes('[ERRO]'));
      const mesExiste = allLines.some(l => l.includes('[JA_EXISTE]'));
      settle({
        success: success && !hasError,
        monthExists: mesExiste,
        log: allLines,
        ...(code !== 0 && !success ? { error: `Processo encerrado com código ${code}` } : {}),
      });
    });

    child.on('error', (err) => {
      settle({ success: false, log: allLines, error: err.message });
    });

  }).finally(() => {
    try { fs.unlinkSync(tmpPath); } catch { /* ignore cleanup errors */ }
  });
}
