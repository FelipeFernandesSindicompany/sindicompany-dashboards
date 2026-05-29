import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const { password } = await request.json();
  const secret = process.env.ADMIN_SECRET ?? 'sindicompany2026';

  if (password !== secret) {
    return NextResponse.json({ error: 'Senha incorreta' }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set('sc_admin_auth', secret, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 30, // 30 dias
  });
  return res;
}
