'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { ShieldCheck, ChevronRight } from 'lucide-react';

interface CondominioConciliacao {
  id: string;
  nome: string;
  cor: string;
  empresa_gestora: string;
}

export default function ValidacaoPage() {
  const [condominios, setCondominios] = useState<CondominioConciliacao[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/validacao/condominios')
      .then(r => r.json())
      .then(d => { if (d.condominios) setCondominios(d.condominios); })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-4 sm:p-8 page-enter max-w-4xl">
      <div className="mb-5 sm:mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-text-primary flex items-center gap-2">
          <ShieldCheck size={22} className="text-accent" />
          Validação de Balancetes
        </h1>
        <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">
          Conciliação comprovante-a-comprovante da pasta de prestação de contas contra o demonstrativo —
          gera um anexo com só as divergências e pendências encontradas, além da análise financeira do mês.
        </p>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)}
        </div>
      ) : condominios.length > 0 ? (
        <div className="space-y-2">
          {condominios.map(c => (
            <Link key={c.id} href={`/validacao/${c.id}`}
              className="card px-4 py-3 flex items-center gap-3 hover:border-border-focus transition-colors">
              <div className="w-2 h-8 rounded-full flex-shrink-0" style={{ background: c.cor }} />
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-text-primary truncate">{c.nome}</p>
                <p className="text-[11px] text-text-muted">{c.empresa_gestora}</p>
              </div>
              <ChevronRight size={16} className="text-text-muted flex-shrink-0" />
            </Link>
          ))}
        </div>
      ) : (
        <div className="py-16 sm:py-20 text-center">
          <ShieldCheck size={36} className="text-text-disabled mx-auto mb-4" />
          <p className="text-text-secondary font-medium">Nenhum condomínio com conciliação disponível ainda</p>
          <p className="text-text-muted text-[12px] mt-1">
            O motor de conciliação hoje só suporta a administradora Addomus — outras entram conforme forem implementadas.
          </p>
        </div>
      )}
    </div>
  );
}
