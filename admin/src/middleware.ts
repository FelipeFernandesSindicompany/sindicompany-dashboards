import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const AUTH_COOKIE = 'sc_admin_auth';
const LOGIN_PATH  = '/login';

export function middleware(request: NextRequest) {
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

  if (cookie?.value === secret) {
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
