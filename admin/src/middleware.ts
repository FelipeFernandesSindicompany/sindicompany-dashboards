import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const AUTH_COOKIE = 'sc_admin_auth';
const LOGIN_PATH  = '/login';

// Middleware roda no Edge runtime (Next 14 não suporta runtime "nodejs" pra
// middleware) — sem o módulo `crypto` do Node, então a verificação do token
// de sessão de usuário individual (ver src/lib/auth.ts::criarTokenSessao,
// que assina com Node crypto.createHmac) usa a Web Crypto API nativa do
// Edge, que produz o MESMO HMAC-SHA256 em hex pra mesma chave+mensagem.
async function tokenValido(token: string, secret: string): Promise<boolean> {
  const partes = token.split('.');
  if (partes.length !== 3) return false;
  const [usuario, expiraStr, assinatura] = partes;
  if (Date.now() > Number(expiraStr)) return false;

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(`${usuario}.${expiraStr}`));
  const esperada = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
  return esperada === assinatura;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Rotas sempre liberadas (login + auth + dashboards públicos)
  if (
    pathname === LOGIN_PATH ||
    pathname.startsWith('/api/auth') ||
    pathname.startsWith('/api/dashboard/')
  ) {
    return NextResponse.next();
  }

  // Verifica cookie de sessão
  const cookie = request.cookies.get(AUTH_COOKIE);
  const secret = process.env.ADMIN_SECRET ?? 'sindicompany2026';
  const sessionSecret = process.env.ADMIN_SESSION_SECRET ?? secret;

  if (cookie?.value === secret) {
    return NextResponse.next();
  }
  if (cookie?.value && (await tokenValido(cookie.value, sessionSecret))) {
    return NextResponse.next();
  }

  // Páginas HTML → redireciona para login
  if (!pathname.startsWith('/api/')) {
    const loginUrl = new URL(LOGIN_PATH, request.url);
    loginUrl.searchParams.set('next', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // API routes → retorna 401
  return NextResponse.json({ error: 'Não autorizado' }, { status: 401 });
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
