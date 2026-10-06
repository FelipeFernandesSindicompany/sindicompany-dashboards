import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

// Usuários adicionais, além da senha mestra (ADMIN_SECRET/middleware) —
// cada um com senha própria, hash com salt (scrypt, nativo do Node, sem
// dependência nova). Arquivo fora do repo git (mesmo padrão de data/ usado
// pelo resto do projeto pra dados que não são código).
const USERS_PATH = path.join(process.cwd(), '..', 'data', 'admin_users.json');

interface AdminUser {
  usuario: string;
  nome: string;
  salt: string;
  senha_hash: string;
}

function lerUsuarios(): AdminUser[] {
  try {
    return JSON.parse(fs.readFileSync(USERS_PATH, 'utf8'));
  } catch {
    return [];
  }
}

export function hashSenha(senha: string, salt: string): string {
  return crypto.scryptSync(senha, salt, 64).toString('hex');
}

export function novoUsuario(usuario: string, nome: string, senha: string): AdminUser {
  const salt = crypto.randomBytes(16).toString('hex');
  return { usuario, nome, salt, senha_hash: hashSenha(senha, salt) };
}

export function salvarUsuarios(usuarios: AdminUser[]): void {
  fs.mkdirSync(path.dirname(USERS_PATH), { recursive: true });
  fs.writeFileSync(USERS_PATH, JSON.stringify(usuarios, null, 2), 'utf8');
}

/** Confere usuário + senha (usuário sem diferenciar maiúsculas). Calcula o
 * hash mesmo quando o usuário não existe, pra o tempo de resposta não
 * revelar quais usuários estão cadastrados. Comparação em tempo constante. */
export function verificarLogin(usuario: string, senha: string): AdminUser | null {
  const alvo = lerUsuarios().find(
    u => u.usuario.toLowerCase() === usuario.trim().toLowerCase()
  );
  const tentativa = Buffer.from(hashSenha(senha, alvo?.salt ?? '0'.repeat(32)), 'hex');
  if (!alvo) return null;
  const esperado = Buffer.from(alvo.senha_hash, 'hex');
  return tentativa.length === esperado.length && crypto.timingSafeEqual(tentativa, esperado)
    ? alvo
    : null;
}

// Bloqueio por tentativas erradas — as senhas são curtas de propósito (fáceis
// de lembrar) e o Admin fica exposto na internet via ngrok, então o limite de
// tentativas é o que protege contra adivinhação. Por usuário (não por IP):
// trocar de IP não zera o contador. Em memória: reiniciar o pm2 libera todos.
const MAX_FALHAS = 5;
const BLOQUEIO_MS = 15 * 60 * 1000;
const falhas = new Map<string, { n: number; ate: number }>();

const chaveFalha = (usuario: string) => usuario.trim().toLowerCase().slice(0, 40);

/** Minutos restantes de bloqueio (0 = liberado). */
export function minutosBloqueado(usuario: string): number {
  const f = falhas.get(chaveFalha(usuario));
  return f && f.ate > Date.now() ? Math.ceil((f.ate - Date.now()) / 60000) : 0;
}

export function registrarFalha(usuario: string): void {
  if (falhas.size > 1000) falhas.clear();
  const k = chaveFalha(usuario);
  const atual = falhas.get(k);
  const n = (atual && atual.ate !== 0 && atual.ate < Date.now() ? 0 : atual?.n ?? 0) + 1;
  falhas.set(k, n >= MAX_FALHAS ? { n: 0, ate: Date.now() + BLOQUEIO_MS } : { n, ate: 0 });
}

export function limparFalhas(usuario: string): void {
  falhas.delete(chaveFalha(usuario));
}

const SESSION_SECRET = process.env.ADMIN_SESSION_SECRET
  ?? process.env.ADMIN_SECRET
  ?? 'sindicompany2026';

/** Token de sessão assinado (HMAC) — não é só o texto da senha, então não
 * pode ser forjado sem conhecer SESSION_SECRET. Formato: usuario.expira.assinatura */
export function criarTokenSessao(usuario: string): string {
  const expira = Date.now() + 1000 * 60 * 60 * 24 * 30; // 30 dias, igual ao cookie mestre
  const payload = `${usuario}.${expira}`;
  const assinatura = crypto.createHmac('sha256', SESSION_SECRET).update(payload).digest('hex');
  return `${payload}.${assinatura}`;
}

export function validarTokenSessao(token: string): { usuario: string } | null {
  const partes = token.split('.');
  if (partes.length !== 3) return null;
  const [usuario, expiraStr, assinatura] = partes;
  const payload = `${usuario}.${expiraStr}`;
  const esperada = crypto.createHmac('sha256', SESSION_SECRET).update(payload).digest('hex');
  const a = Buffer.from(assinatura, 'hex');
  const b = Buffer.from(esperada, 'hex');
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  if (Date.now() > Number(expiraStr)) return null;
  return { usuario };
}
