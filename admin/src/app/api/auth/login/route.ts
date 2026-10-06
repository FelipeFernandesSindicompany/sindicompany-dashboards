import { NextResponse } from 'next/server';
import { verificarLogin, criarTokenSessao, minutosBloqueado, registrarFalha, limparFalhas } from '@/lib/auth';

const COOKIE = 'sc_admin_auth';
const COOKIE_OPCOES = {
  httpOnly: true,
  sameSite: 'lax' as const,
  path: '/',
  maxAge: 60 * 60 * 24 * 30, // 30 dias
};

export async function POST(request: Request) {
  const corpo = await request.json().catch(() => ({}));
  const usuario = String(corpo.usuario ?? '').trim();
  const password = String(corpo.password ?? '');
  const secret = process.env.ADMIN_SECRET ?? 'sindicompany2026';

  if (!usuario || !password) {
    return NextResponse.json({ error: 'Informe usuário e senha.' }, { status: 400 });
  }

  const bloqueio = minutosBloqueado(usuario);
  if (bloqueio > 0) {
    return NextResponse.json(
      { error: `Muitas tentativas incorretas. Tente novamente em ${bloqueio} min.` },
      { status: 429 },
    );
  }

  // Acesso mestre (emergência): usuário "admin" + ADMIN_SECRET. O cookie
  // continua sendo o próprio segredo (compatível com o middleware).
  if (usuario.toLowerCase() === 'admin' && password === secret) {
    limparFalhas(usuario);
    const res = NextResponse.json({ ok: true });
    res.cookies.set(COOKIE, secret, COOKIE_OPCOES);
    return res;
  }

  // Usuário individual (felipe, luciane) — cookie é um token assinado, não a
  // senha, identificando quem entrou.
  const conta = verificarLogin(usuario, password);
  if (conta) {
    limparFalhas(usuario);
    const res = NextResponse.json({ ok: true });
    res.cookies.set(COOKIE, criarTokenSessao(conta.usuario), COOKIE_OPCOES);
    return res;
  }

  registrarFalha(usuario);
  return NextResponse.json({ error: 'Usuário ou senha incorretos.' }, { status: 401 });
}
