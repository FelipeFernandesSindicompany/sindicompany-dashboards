import path from 'path';

// When running from admin/ folder, cwd is admin/, so .. is project root
export const PROJECT_ROOT = process.env.SINDICOMPANY_ROOT
  ? path.resolve(process.env.SINDICOMPANY_ROOT)
  : path.resolve(process.cwd(), '..');

export const DOCS_DIR = path.join(PROJECT_ROOT, 'docs');
export const CONFIG_PATH = path.join(PROJECT_ROOT, 'config', 'condominios.json');
export const DATA_DIR = path.join(PROJECT_ROOT, 'data');
export const SCRIPTS_DIR = path.join(PROJECT_ROOT, 'scripts');
export const UPLOADS_DIR = path.join(DATA_DIR, 'uploads');
export const HISTORY_PATH = path.join(DATA_DIR, 'import_history.json');
