'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { ShieldCheck, ChevronRight, Clock } from 'lucide-react';

interface CondominioConciliacao {
  id: string;
  nome: string;
  cor: string;
  empresa_gestora: string;
  suportado: boolean;
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

  const suportados = condominios.filter(c => c.suportado).length;

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
          {!loading && ` ${suportados} de ${condominios.length} condomínios já suportados.`}
        </p>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)}
        </div>
      ) : condominios.length > 0 ? (
        <div className="space-y-2">
          {condominios.map(c => {
            const conteudo = (
              <>
                <div className="w-2 h-8 rounded-full flex-shrink-0" style={{ background: c.cor }} />
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-semibold text-text-primary truncate">{c.nome}</p>
                  <p className="text-[11px] text-text-muted">{c.empresa_gestora}</p>
                </div>
                {c.suportado ? (
                  <ChevronRight size={16} className="text-text-muted flex-shrink-0" />
                ) : (
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full flex items-center gap-1 flex-shrink-0
                    text-text-muted bg-bg-elevated border border-border">
                    <Clock size={10} /> Em breve
                  </span>
                )}
              </>
            );
            return c.suportado ? (
              <Link key={c.id} href={`/validacao/${c.id}`}
                className="card px-4 py-3 flex items-center gap-3 hover:border-border-focus transition-colors">
                {conteudo}
              </Link>
            ) : (
              <div key={c.id} className="card px-4 py-3 flex items-center gap-3 opacity-60 cursor-not-allowed">
                {conteudo}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="py-16 sm:py-20 text-center">
          <ShieldCheck size={36} className="text-text-disabled mx-auto mb-4" />
          <p className="text-text-secondary font-medium">Nenhum condomínio ativo cadastrado</p>
        </div>
      )}
    </div>
  );
}
