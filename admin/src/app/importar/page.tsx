'use client';

import { useState, useEffect } from 'react';
import { Upload, Info, FileText, FileSpreadsheet, BookOpen, AlertTriangle } from 'lucide-react';
import { DropZone } from '@/components/upload/DropZone';
import type { Condominio } from '@/lib/types';

const ADAPTER_INFO = [
  { id: 'habitacional_xlsx', label: 'Habitacional', ext: '.xlsx', color: '#3B82F6', Icon: FileSpreadsheet, desc: 'Prestação de contas mensal · colunas E/G/I/K' },
  { id: 'lello_xls',         label: 'Lello',        ext: '.xls',  color: '#8B5CF6', Icon: FileSpreadsheet, desc: 'Relatório mensal · tabelas HTML' },
  { id: 'lirba_pdf',         label: 'Lirba',        ext: '.PDF',  color: '#10B981', Icon: FileText,        desc: 'Prestação de Contas MM.YYYY.PDF' },
  { id: 'datadigitus_pdf',   label: 'DataDigitus',  ext: '.pdf',  color: '#F59E0B', Icon: FileText,        desc: 'Relatório DataDigitus · TOTAL GERAL' },
  { id: 'iello_pdf',         label: 'Iello',        ext: '.pdf',  color: '#EC4899', Icon: FileText,        desc: 'Relatório Iello · SALDO FINAL' },
];

export default function ImportarPage() {
  const [condominios, setCondominios] = useState<Condominio[]>([]);
  const [loading, setLoading]         = useState(true);
  const [refreshKey, setRefreshKey]   = useState(0);
  const [isViaNgrok, setIsViaNgrok]   = useState(false);

  useEffect(() => {
    // Detecta se está acessando via ngrok (não localhost)
    const host = window.location.hostname;
    setIsViaNgrok(host !== 'localhost' && host !== '127.0.0.1' && !host.startsWith('192.168.'));
  }, []);

  useEffect(() => {
    fetch('/api/condominios')
      .then(r => r.json())
      .then(data => {
        if (data.statuses) {
          setCondominios(data.statuses.map((s: any) => s.condominio));
        }
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-4 sm:p-8 page-enter max-w-4xl">

      {/* Header */}
      <div className="mb-6 sm:mb-8">
        <div className="flex items-center gap-2 mb-2">
          <div className="p-2 rounded-lg bg-accent-muted border border-accent-border">
            <Upload size={18} className="text-accent" />
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Importar Dados</h1>
        </div>
        <p className="text-text-muted text-[12px] sm:text-[13px]">
          Envie os arquivos financeiros mensais · detecção automática de condomínio e período
        </p>
      </div>

      {/* Step indicator — oculto em telas muito pequenas */}
      <div className="hidden sm:flex items-center gap-3 mb-8">
        {[
          { n: 1, label: 'Enviar arquivo' },
          { n: 2, label: 'Confirmar dados' },
          { n: 3, label: 'Injetar no dashboard' },
        ].map(({ n, label }, i) => (
          <div key={n} className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold
                bg-accent text-white flex-shrink-0">
                {n}
              </div>
              <span className="text-[12px] text-text-secondary">{label}</span>
            </div>
            {i < 2 && <div className="w-8 h-px bg-border" />}
          </div>
        ))}
      </div>

      {/* Steps simplificados para mobile */}
      <div className="flex items-center gap-2 mb-6 sm:hidden">
        {[1, 2, 3].map((n, i) => (
          <div key={n} className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold
              bg-accent text-white flex-shrink-0">
              {n}
            </div>
            {i < 2 && <div className="w-6 h-px bg-border" />}
          </div>
        ))}
        <span className="text-[11px] text-text-muted ml-1">Enviar → Confirmar → Injetar</span>
      </div>

      {/* Aviso: acesso via ngrok pode causar lentidão no upload */}
      {isViaNgrok && (
        <div className="mb-6 p-4 rounded-xl border border-warning/30 bg-warning/5 flex items-start gap-3">
          <AlertTriangle size={16} className="text-warning flex-shrink-0 mt-0.5" />
          <div className="text-[12px] text-text-secondary space-y-1">
            <p className="font-semibold text-warning">Upload via ngrok pode ser lento ou falhar</p>
            <p>Você está acessando pelo link público. Para importar arquivos (especialmente PDFs grandes), abra o admin diretamente neste computador:</p>
            <a
              href="http://localhost:3500/importar"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-1 px-3 py-1.5 rounded-lg bg-accent text-white text-[11px] font-semibold hover:bg-accent/80 transition-colors"
            >
              Abrir em localhost:3500 →
            </a>
          </div>
        </div>
      )}

      {/* Drop zone */}
      {loading ? (
        <div className="card p-12 text-center">
          <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-text-muted text-[13px]">Carregando condomínios...</p>
        </div>
      ) : (
        <DropZone
          condominios={condominios}
          onImportDone={() => setRefreshKey(k => k + 1)}
        />
      )}

      {/* Adapters guide — 2 colunas mobile, 3 tablet, 5 desktop */}
      <div className="mt-6 sm:mt-8">
        <div className="flex items-center gap-2 mb-4">
          <BookOpen size={14} className="text-text-muted" />
          <h2 className="text-[13px] font-semibold text-text-secondary">Formatos suportados</h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {ADAPTER_INFO.map(({ id, label, ext, color, Icon, desc }) => (
            <div key={id} className="card p-3">
              <div className="flex items-center gap-2 mb-2">
                <Icon size={14} style={{ color }} />
                <span className="text-[12px] font-semibold text-text-primary">{label}</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                style={{ color, background: `${color}18` }}>
                {ext}
              </span>
              <p className="text-[10px] text-text-muted mt-1.5 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Tips */}
      <div className="mt-5 sm:mt-6 p-4 rounded-xl bg-accent-muted border border-accent-border flex gap-3">
        <Info size={16} className="text-accent flex-shrink-0 mt-0.5" />
        <div className="text-[12px] text-text-secondary space-y-1">
          <p><strong className="text-text-primary">Detecção automática:</strong> o sistema identifica o mês pelo nome do arquivo (ex: <code className="font-mono text-accent text-[11px]">05.2026</code>, <code className="font-mono text-accent text-[11px]">2026-05</code>).</p>
          <p><strong className="text-text-primary">Múltiplos arquivos:</strong> importe todos os condomínios de uma vez — cada arquivo é processado de forma independente.</p>
          <p><strong className="text-text-primary">Segurança:</strong> se o mês já existe, a injeção é bloqueada — sem risco de duplicação.</p>
        </div>
      </div>
    </div>
  );
}
