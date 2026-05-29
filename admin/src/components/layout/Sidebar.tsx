'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState, useCallback } from 'react';
import {
  LayoutDashboard,
  Upload,
  Building2,
  History,
  Settings,
  Zap,
  LogOut,
  Globe,
  Copy,
  Check,
} from 'lucide-react';

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

function TunnelUrl() {
  const [url, setUrl]       = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const fetch_ = () =>
      fetch('/api/tunnel').then(r => r.json()).then(d => setUrl(d.url ?? null)).catch(() => {});
    fetch_();
    const id = setInterval(fetch_, 15_000);
    return () => clearInterval(id);
  }, []);

  const copy = useCallback(() => {
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [url]);

  if (!url) return null;

  const short = url.replace('https://', '').split('.')[0];

  return (
    <div className="px-3 py-2">
      <p className="text-[9px] text-text-muted uppercase tracking-wider font-semibold mb-1.5 flex items-center gap-1">
        <Globe size={9} className="text-success" /> URL Pública
      </p>
      <div className="flex items-center gap-1.5 bg-bg-surface border border-success/20 rounded-lg px-2 py-1.5">
        <span className="text-[10px] text-success font-mono truncate flex-1" title={url}>
          {short}...
        </span>
        <button onClick={copy}
          className="flex-shrink-0 text-text-muted hover:text-success transition-colors p-0.5"
          title="Copiar URL completa">
          {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
        </button>
      </div>
    </div>
  );
}

const navItems = [
  { href: '/',            icon: LayoutDashboard, label: 'Visão Geral', shortLabel: 'Geral'    },
  { href: '/importar',    icon: Upload,           label: 'Importar',    shortLabel: 'Importar' },
  { href: '/condominios', icon: Building2,        label: 'Condomínios', shortLabel: 'Condos'   },
  { href: '/historico',   icon: History,          label: 'Histórico',   shortLabel: 'Histórico'},
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <>
      {/* ══════════════════════════════════════════
          DESKTOP — sidebar lateral fixa (≥ 768 px)
          ══════════════════════════════════════════ */}
      <aside
        className="hidden md:flex fixed left-0 top-0 h-screen w-[220px] border-r border-border flex-col z-40"
        style={{ background: 'linear-gradient(180deg, #0E0E12 0%, #09090B 100%)' }}
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-border">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #6366F1 0%, #818CF8 100%)' }}
          >
            <Zap size={14} className="text-white" />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-text-primary leading-none">Sindicompany</p>
            <p className="text-[10px] text-text-muted mt-0.5 leading-none">Admin Platform</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          <p className="px-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
            Plataforma
          </p>
          {navItems.map(({ href, icon: Icon, label }) => {
            const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium
                  transition-all duration-150 group relative
                  ${active
                    ? 'text-white bg-accent/15 border border-accent/20'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover border border-transparent'
                  }`}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-accent rounded-r-full" />
                )}
                <Icon size={15} className={active ? 'text-accent' : 'text-text-muted group-hover:text-text-secondary'} />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Bottom */}
        <div className="px-3 pb-4 pt-2 border-t border-border space-y-0.5">
          <Link
            href="/settings"
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] text-text-muted
              hover:text-text-secondary hover:bg-bg-hover transition-colors duration-150"
          >
            <Settings size={15} />
            Configurações
          </Link>
          <div className="px-3 py-2">
            <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse-dot" />
              Sistema operacional
            </div>
          </div>
          <TunnelUrl />
          <button onClick={logout}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] text-text-muted
              hover:text-danger hover:bg-danger/5 transition-colors duration-150 w-full text-left">
            <LogOut size={15} />
            Sair
          </button>
        </div>
      </aside>

      {/* ══════════════════════════════════════════
          MOBILE — cabeçalho fixo no topo (< 768 px)
          ══════════════════════════════════════════ */}
      <header
        className="md:hidden fixed top-0 left-0 right-0 h-14 border-b border-border z-40 flex items-center px-4"
        style={{ background: 'linear-gradient(180deg, #0E0E12 0%, #09090B 100%)' }}
      >
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #6366F1 0%, #818CF8 100%)' }}
          >
            <Zap size={14} className="text-white" />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-text-primary leading-none">Sindicompany</p>
            <p className="text-[10px] text-text-muted leading-none">Admin Platform</p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-[10px] text-text-muted">
          <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse-dot" />
          Online
        </div>
      </header>

      {/* ══════════════════════════════════════════
          MOBILE — barra de navegação inferior (< 768 px)
          ══════════════════════════════════════════ */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 h-16 border-t border-border z-40 flex items-center"
        style={{ background: 'linear-gradient(0deg, #0E0E12 0%, #09090B 100%)' }}
      >
        {navItems.map(({ href, icon: Icon, shortLabel }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex-1 flex flex-col items-center justify-center gap-1 py-2
                transition-colors duration-150
                ${active ? 'text-accent' : 'text-text-muted'}`}
            >
              <Icon size={21} />
              <span className="text-[10px] font-medium leading-none">{shortLabel}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
