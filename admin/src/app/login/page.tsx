'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Zap, Lock, Eye, EyeOff, Loader2 } from 'lucide-react';

export default function LoginPage() {
  const router = useRouter();

  const [password, setPassword] = useState('');
  const [show,     setShow]     = useState(false);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password) return;

    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });

      if (res.ok) {
        // Pega o parâmetro 'next' da URL (evita useSearchParams que quebra SSR)
        const next = typeof window !== 'undefined'
          ? new URLSearchParams(window.location.search).get('next') ?? '/'
          : '/';
        router.push(next);
        router.refresh();
      } else {
        setError('Senha incorreta. Tente novamente.');
        setPassword('');
      }
    } catch {
      setError('Erro de conexão. Verifique sua rede.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4"
      style={{ background: 'linear-gradient(135deg, #09090B 0%, #0E0E12 50%, #09090B 100%)' }}>

      {/* Card */}
      <div className="w-full max-w-sm">

        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4 shadow-lg"
            style={{ background: 'linear-gradient(135deg, #6366F1 0%, #818CF8 100%)' }}>
            <Zap size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold text-text-primary">Sindicompany</h1>
          <p className="text-text-muted text-[13px] mt-0.5">Admin Platform</p>
        </div>

        {/* Form */}
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-5">
            <div className="p-1.5 rounded-lg bg-accent-muted border border-accent-border">
              <Lock size={14} className="text-accent" />
            </div>
            <p className="text-[14px] font-semibold text-text-primary">Acesso restrito</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-[12px] text-text-muted mb-1.5">Senha de acesso</label>
              <div className="relative">
                <input
                  type={show ? 'text' : 'password'}
                  value={password}
                  onChange={e => { setPassword(e.target.value); setError(''); }}
                  placeholder="Digite a senha..."
                  autoFocus
                  className={`input pr-10 ${error ? 'border-danger/50 bg-danger/5' : ''}`}
                />
                <button
                  type="button"
                  onClick={() => setShow(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted
                    hover:text-text-secondary transition-colors p-0.5"
                  tabIndex={-1}
                >
                  {show ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              {error && (
                <p className="text-[11px] text-danger mt-1.5 flex items-center gap-1">
                  {error}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || !password}
              className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading
                ? <><Loader2 size={15} className="animate-spin" /> Entrando...</>
                : 'Entrar'
              }
            </button>
          </form>
        </div>

        <p className="text-center text-[11px] text-text-muted mt-5">
          Plataforma interna · Sindicompany © {new Date().getFullYear()}
        </p>
      </div>
    </div>
  );
}
