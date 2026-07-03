import { execFile } from 'child_process';
import { promisify } from 'util';
import * as fs from 'fs';
import * as os from 'os';
import path from 'path';
import { PROJECT_ROOT, SCRIPTS_DIR } from './paths';

const execFileAsync = promisify(execFile);

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

  try {
    let result: ProcessResult;
    try {
      const { stdout, stderr } = await execFileAsync('python', args, {
        cwd: PROJECT_ROOT,
        encoding: 'utf-8',
        timeout: 600_000, // 10 min — PDFs grandes (300+ páginas) podem demorar
        windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1' },
      });

      const combined = (stdout + '\n' + stderr).trim();
      const lines = combined.split('\n').map(l => l.trim()).filter(Boolean);
      const success    = lines.some(l => l.includes('[OK]'));
      const hasError   = lines.some(l => l.includes('[ERRO]'));
      const mesExiste  = lines.some(l => l.includes('[JA_EXISTE]'));

      result = { success: success && !hasError, monthExists: mesExiste, log: lines };
    } catch (err: any) {
      const stdout = err.stdout ?? '';
      const stderr = err.stderr ?? '';
      const combined = (stdout + '\n' + stderr).trim();
      const lines = combined.split('\n').map((l: string) => l.trim()).filter(Boolean);
      result = { success: false, log: lines, error: err.message ?? 'Erro desconhecido' };
    }
    return result;
  } finally {
    try { fs.unlinkSync(tmpPath); } catch { /* ignore cleanup errors */ }
  }
}
