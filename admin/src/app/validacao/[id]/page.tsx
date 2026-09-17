'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Upload, FileCheck2, Loader2, Download, Save, PlayCircle } from 'lucide-react';

interface AchadoBruto {
  id: string;
  tipo: string;
  severidade_sugerida: string;
  regra_aplicada: string;
  valor_esperado: number | null;
  valor_encontrado: number | null;
  linha_demonstrativo: string | null;
}

interface AchadoRevisado {
  achado_id: string;
  titulo: string;
  paragrafo: string;
  severidade_final: string;
  o_que_verificar: string;
  confianca_ia: number;
  revisado_por: string;
  revisado_em: string;
  motivo_divergencia_da_sugestao: string | null;
}

interface StatusResp {
  existe: boolean;
  versao: string | null;
  achadosBrutos: AchadoBruto[] | null;
  achadosRevisados: AchadoRevisado[] | null;
  relatorioExiste: boolean;
  pendentes: number;
}

function mesAtualPadrao(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const SEVERIDADES = ['critico', 'alto', 'atencao', 'informativo'];

export default function ValidacaoCondominioPage() {
  const params = useParams();
  const condominioId = String(params.id);

  const [mes, setMes] = useState(mesAtualPadrao());
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [status, setStatus] = useState<StatusResp | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // etapa em execução, para spinner
  const [log, setLog] = useState<string[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [revisados, setRevisados] = useState<Record<string, AchadoRevisado>>({});

  const carregarStatus = useCallback(async () => {
    const r = await fetch(`/api/validacao/status?condominioId=${condominioId}&mes=${mes}`);
    const d: StatusResp = await r.json();
    setStatus(d);
    if (d.achadosRevisados) {
      const mapa: Record<string, AchadoRevisado> = {};
      d.achadosRevisados.forEach(rv => { mapa[rv.achado_id] = rv; });
      setRevisados(mapa);
    } else {
      setRevisados({});
    }
  }, [condominioId, mes]);

  useEffect(() => { carregarStatus(); }, [carregarStatus]);

  async function rodarExtrair() {
    if (!arquivo) { setErro('Selecione o PDF da pasta de prestação de contas.'); return; }
    setBusy('extrair'); setErro(null); setLog([]);
    const fd = new FormData();
    fd.append('condominioId', condominioId);
    fd.append('mes', mes);
    fd.append('arquivo', arquivo);
    const r = await fetch('/api/validacao/extrair', { method: 'POST', body: fd });
    const d = await r.json();
    setLog(d.log ?? []);
    if (!r.ok) { setErro(d.error ?? 'Falha na extração'); setBusy(null); return; }
    // Encadeia automaticamente a geração do esqueleto de revisão.
    await rodarInterpretar();
  }

  async function rodarInterpretar() {
    setBusy('interpretar'); setErro(null);
    const r = await fetch('/api/validacao/interpretar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ condominioId, mes }),
    });
    const d = await r.json();
    setLog(l => [...l, ...(d.log ?? [])]);
    if (!r.ok) { setErro(d.error ?? 'Falha ao gerar esqueleto de revisão'); setBusy(null); return; }
    await carregarStatus();
    setBusy(null);
  }

  function atualizarCampo(achadoId: string, campo: keyof AchadoRevisado, valor: string) {
    setRevisados(prev => ({
      ...prev,
      [achadoId]: { ...prev[achadoId], [campo]: valor, revisado_por: 'humano:admin' },
    }));
  }

  async function salvarRevisao() {
    setBusy('revisar'); setErro(null);
    const r = await fetch('/api/validacao/revisar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ condominioId, mes, revisados: Object.values(revisados) }),
    });
    const d = await r.json();
    if (!r.ok) { setErro(d.error ?? 'Falha ao salvar revisão'); setBusy(null); return; }
    await carregarStatus();
    setBusy(null);
  }

  async function gerarRelatorio() {
    setBusy('render'); setErro(null); setLog([]);
    const r = await fetch('/api/validacao/render', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ condominioId, mes }),
    });
    const d = await r.json();
    setLog(d.log ?? []);
    if (!r.ok) { setErro(d.error ?? 'Falha ao gerar o relatório — confira se todos os achados foram revisados'); setBusy(null); return; }
    await carregarStatus();
    setBusy(null);
  }

  const pendentes = status?.achadosBrutos?.filter(a => !revisados[a.id] || revisados[a.id].revisado_por === 'pendente') ?? [];

  return (
    <div className="p-4 sm:p-8 page-enter max-w-4xl">
      <div className="mb-5 sm:mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Validação de Balancetes</h1>
        <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">{condominioId}</p>
      </div>

      {/* Seleção de mês + upload */}
      <div className="card p-4 mb-4 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-[12px] text-text-muted">Competência</label>
          <input type="month" value={mes} onChange={e => setMes(e.target.value)} className="input w-auto" />
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="btn-ghost text-[12px] cursor-pointer flex items-center gap-1.5">
            <Upload size={13} />
            {arquivo ? arquivo.name : 'Selecionar pasta de prestação de contas (PDF)'}
            <input type="file" accept=".pdf" className="hidden"
              onChange={e => setArquivo(e.target.files?.[0] ?? null)} />
          </label>
          <button className="btn-primary text-[12px] flex items-center gap-1.5" disabled={!!busy}
            onClick={rodarExtrair}>
            {busy === 'extrair' || busy === 'interpretar'
              ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />}
            Extrair e preparar revisão
          </button>
        </div>
        {erro && <p className="text-[12px] text-danger">{erro}</p>}
        {log.length > 0 && (
          <div className="font-mono text-[11px] space-y-0.5 max-h-32 overflow-y-auto bg-bg-base rounded-lg p-2">
            {log.map((l, i) => <p key={i} className="text-text-secondary break-all">{l}</p>)}
          </div>
        )}
      </div>

      {/* Revisão dos achados */}
      {status?.achadosBrutos && status.achadosBrutos.length > 0 && (
        <div className="card p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[14px] font-semibold text-text-primary">
              Revisão dos achados ({status.achadosBrutos.length} no total, {pendentes.length} pendentes)
            </h2>
            <button className="btn-ghost text-[12px] flex items-center gap-1.5" disabled={!!busy} onClick={salvarRevisao}>
              {busy === 'revisar' ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
              Salvar revisão
            </button>
          </div>
          <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
            {status.achadosBrutos.map(a => {
              const rev = revisados[a.id] ?? {
                achado_id: a.id, titulo: '', paragrafo: '', severidade_final: a.severidade_sugerida,
                o_que_verificar: '', confianca_ia: 0, revisado_por: 'pendente', revisado_em: '', motivo_divergencia_da_sugestao: null,
              };
              return (
                <div key={a.id} className="border border-border rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2 flex-wrap text-[11px] text-text-muted font-mono">
                    <span>{a.id}</span>
                    <span className="px-1.5 py-0.5 bg-bg-elevated rounded">{a.tipo}</span>
                    {a.valor_esperado != null && <span>esperado: R$ {a.valor_esperado.toFixed(2)}</span>}
                    {a.valor_encontrado != null && <span>encontrado: R$ {a.valor_encontrado.toFixed(2)}</span>}
                    {rev.revisado_por === 'pendente' && <span className="text-warning">pendente</span>}
                  </div>
                  <input className="input text-[12px]" placeholder="Título"
                    value={rev.titulo} onChange={e => atualizarCampo(a.id, 'titulo', e.target.value)} />
                  <textarea className="input text-[12px] min-h-[60px]" placeholder="Parágrafo explicativo"
                    value={rev.paragrafo} onChange={e => atualizarCampo(a.id, 'paragrafo', e.target.value)} />
                  <div className="flex items-center gap-2">
                    <select className="input w-auto text-[12px]" value={rev.severidade_final}
                      onChange={e => atualizarCampo(a.id, 'severidade_final', e.target.value)}>
                      {SEVERIDADES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <span className="text-[11px] text-text-muted">sugerida: {a.severidade_sugerida}</span>
                  </div>
                  <textarea className="input text-[12px] min-h-[40px]" placeholder="O que verificar"
                    value={rev.o_que_verificar} onChange={e => atualizarCampo(a.id, 'o_que_verificar', e.target.value)} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Geração do relatório final */}
      {status?.achadosBrutos && status.achadosBrutos.length > 0 && (
        <div className="card p-4 flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="text-[13px] font-semibold text-text-primary">Relatório final</p>
            <p className="text-[11px] text-text-muted">
              {status.relatorioExiste ? 'Relatório gerado — pode ser regenerado após novas edições.' : 'Ainda não gerado.'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-primary text-[12px] flex items-center gap-1.5" disabled={!!busy} onClick={gerarRelatorio}>
              {busy === 'render' ? <Loader2 size={13} className="animate-spin" /> : <FileCheck2 size={13} />}
              Gerar relatório final
            </button>
            {status.relatorioExiste && (
              <a className="btn-ghost text-[12px] flex items-center gap-1.5"
                href={`/api/validacao/pdf?condominioId=${condominioId}&mes=${mes}`} target="_blank" rel="noreferrer">
                <Download size={13} /> Ver PDF
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
