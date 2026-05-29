import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { PROJECT_ROOT, SCRIPTS_DIR } from './paths';

const execAsync = promisify(exec);

export interface ProcessResult {
  success: boolean;
  log: string[];
  error?: string;
}

export async function injectarMes(
  condominioId: string,
  mes: string,
  arquivoPath: string
): Promise<ProcessResult> {
  const script = path.join(SCRIPTS_DIR, 'injetar_mes.py');
  const cmd = [
    'python',
    `"${script}"`,
    `--condominio "${condominioId}"`,
    `--mes "${mes}"`,
    `--arquivo "${arquivoPath}"`,
  ].join(' ');

  try {
    const { stdout, stderr } = await execAsync(cmd, {
      cwd: PROJECT_ROOT,
      encoding: 'utf-8',
      timeout: 180_000,
      windowsHide: true,
    });

    const combined = (stdout + '\n' + stderr).trim();
    const lines = combined.split('\n').map(l => l.trim()).filter(Boolean);
    const success = lines.some(l => l.includes('[OK]'));
    const hasError = lines.some(l => l.includes('[ERRO]'));

    return { success: success && !hasError, log: lines };
  } catch (err: any) {
    const stdout = err.stdout ?? '';
    const stderr = err.stderr ?? '';
    const combined = (stdout + '\n' + stderr).trim();
    const lines = combined.split('\n').map((l: string) => l.trim()).filter(Boolean);

    return {
      success: false,
      log: lines,
      error: err.message ?? 'Erro desconhecido',
    };
  }
}
