'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import { Upload, FileCheck2, Loader2, Download, Eye, Save, PlayCircle } from 'lucide-react';

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

interface EscopoResp {
  registros: number | null;
  comprovantes: number | null;
  regras: { chave: string; nome: string; aplicada: boolean; motivo: string | null }[];
  avisos: string[];
}

interface StatusResp {
  existe: boolean;
  escopo?: EscopoResp | null;
  versao: string | null;
  achadosBrutos: AchadoBruto[] | null;
  achadosRevisados: AchadoRevisado[] | null;
  relatorioExiste: boolean;
  pendentes: number;
  extracaoConcluida?: boolean;
  job?: { estado: 'rodando' | 'concluido' | 'erro'; etapa: 'extrair' | 'interpretar'; iniciadoEm: string; terminadoEm?: string; log: string[]; erro?: string } | null;
}

function mesAtualPadrao(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const MESES_LABEL = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

/** Últimos `qtd` meses (o atual + qtd-1 anteriores), mais recente primeiro. */
function opcoesDeMes(qtd = 15): { valor: string; label: string }[] {
  const hoje = new Date();
  const opcoes: { valor: string; label: string }[] = [];
  for (let i = 0; i < qtd; i++) {
    const d = new Date(hoje.getFullYear(), hoje.getMonth() - i, 1);
    const valor = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    opcoes.push({ valor, label: `${MESES_LABEL[d.getMonth()]}/${d.getFullYear()}` });
  }
  return opcoes;
}

const SEVERIDADES = ['critico', 'alto', 'atencao', 'informativo'];

interface CondominioInfo { id: string; nome: string; suportado: boolean; }

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
  const [condoInfo, setCondoInfo] = useState<CondominioInfo | null>(null);
  const [carregandoCondo, setCarregandoCondo] = useState(true);
  const [mostrarVerificados, setMostrarVerificados] = useState(false);

  useEffect(() => {
    fetch('/api/validacao/condominios')
      .then(r => r.json())
      .then(d => setCondoInfo((d.condominios ?? []).find((c: CondominioInfo) => c.id === condominioId) ?? null))
      .finally(() => setCarregandoCondo(false));
  }, [condominioId]);

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

  const emAndamento = status?.job?.estado === 'rodando';
  // Enquanto a extração roda no servidor, atualiza o andamento sozinho (a tela pode ser fechada e reaberta sem perder nada).
  useEffect(() => {
    if (!emAndamento) return;
    const t = setInterval(() => { carregarStatus(); }, 4000);
    return () => clearInterval(t);
  }, [emAndamento, carregarStatus]);

  // Rede de segurança: extração concluída mas sem a revisão preparada (ex.: versão antiga) — prepara sozinha, uma vez por versão.
  const interpretadaRef = useRef<string>('');
  useEffect(() => {
    if (!status?.versao || emAndamento || busy) return;
    if (status.extracaoConcluida && (status.achadosBrutos?.length ?? 0) > 0 && !status.achadosRevisados) {
      const chave = `${condominioId}|${mes}|${status.versao}`;
      if (interpretadaRef.current === chave) return;
      interpretadaRef.current = chave;
      rodarInterpretar();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, emAndamento, busy]);

  async function rodarExtrair() {
    if (!arquivo) { setErro('Selecione o PDF da pasta de prestação de contas.'); return; }
    setBusy('extrair'); setErro(null); setLog([]);
    try {
      const fd = new FormData();
      fd.append('condominioId', condominioId);
      fd.append('mes', mes);
      fd.append('arquivo', arquivo);
      const r = await fetch('/api/validacao/extrair', { method: 'POST', body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setErro(d.error ?? 'Falha ao iniciar a extração'); return; }
      // A extração e a preparação da revisão rodam juntas no servidor; a tela só acompanha o andamento.
      await carregarStatus();
    } catch {
      setErro('Não foi possível enviar o arquivo (conexão interrompida). Tente novamente.');
    } finally {
      setBusy(null);
    }
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

  const severidadeDe = (a: AchadoBruto) => revisados[a.id]?.severidade_final ?? a.severidade_sugerida;
  const verificados = status?.achadosBrutos?.filter(a => severidadeDe(a) === 'informativo') ?? [];
  const aConferir = status?.achadosBrutos?.filter(a => severidadeDe(a) !== 'informativo') ?? [];
  const interrompida = !!status?.versao && !status.extracaoConcluida && !emAndamento;
  const pronta = !!status?.versao && !!status.extracaoConcluida && !emAndamento;
  const pendentes = status?.achadosBrutos?.filter(a => !revisados[a.id] || revisados[a.id].revisado_por === 'pendente') ?? [];

  if (carregandoCondo) {
    return <div className="p-4 sm:p-8"><div className="skeleton h-24 rounded-xl max-w-4xl" /></div>;
  }

  if (!condoInfo || !condoInfo.suportado) {
    return (
      <div className="p-4 sm:p-8 page-enter max-w-4xl">
        <h1 className="text-xl sm:text-2xl font-bold text-text-primary mb-2">Validação de Balancetes</h1>
        <div className="card p-6 text-center">
          <p className="text-text-secondary font-medium">
            {condoInfo ? `${condoInfo.nome} ainda não tem conciliador implementado.` : 'Condomínio não encontrado.'}
          </p>
          <p className="text-text-muted text-[12px] mt-1">
            O motor de conciliação hoje só suporta a administradora Addomus — outras entram conforme forem implementadas.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-8 page-enter max-w-4xl">
      <div className="mb-5 sm:mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Validação de Balancetes</h1>
        <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">{condoInfo.nome}</p>
      </div>

      {/* Seleção de mês + upload */}
      <div className="card p-4 mb-4 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-[12px] text-text-muted">Competência a validar</label>
          <select value={mes} onChange={e => setMes(e.target.value)} className="input w-auto">
            {opcoesDeMes().map(o => <option key={o.valor} value={o.valor}>{o.label}</option>)}
          </select>
          <span className="text-[11px] text-text-muted">
            A validação compara automaticamente com o mês anterior encontrado na pasta do projeto do condomínio.
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="btn-ghost text-[12px] cursor-pointer flex items-center gap-1.5">
            <Upload size={13} />
            {arquivo ? arquivo.name : 'Selecionar prestação de contas (PDF ou Excel)'}
            <input type="file" accept=".pdf,.xlsx,.xls" className="hidden"
              onChange={e => setArquivo(e.target.files?.[0] ?? null)} />
          </label>
          <button className="btn-primary text-[12px] flex items-center gap-1.5" disabled={!!busy || emAndamento}
            onClick={rodarExtrair}>
            {busy === 'extrair' || busy === 'interpretar' || emAndamento
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

      {emAndamento && status?.job && (
        <div className="card p-4 mb-4">
          <p className="text-[13px] font-semibold text-text-primary flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Extração em andamento
          </p>
          <p className="text-[12px] text-text-secondary mt-1">
            Etapa: {status.job.etapa === 'extrair' ? 'lendo o arquivo e conferindo os comprovantes' : 'preparando a revisão'} — iniciada às{' '}
            {new Date(status.job.iniciadoEm).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}.
            Arquivos grandes levam vários minutos; esta tela atualiza sozinha e você pode sair e voltar. Nenhum resultado é mostrado até a extração terminar.
          </p>
        </div>
      )}

      {status?.job?.estado === 'erro' && !emAndamento && (
        <div className="card p-4 mb-4 border border-danger/40">
          <p className="text-[13px] font-semibold text-danger">A extração falhou</p>
          <p className="text-[12px] text-text-secondary mt-1">{status.job.erro}</p>
          {status.job.log.length > 0 && (
            <div className="font-mono text-[11px] space-y-0.5 max-h-32 overflow-y-auto bg-bg-base rounded-lg p-2 mt-2">
              {status.job.log.map((l, i) => <p key={i} className="text-text-secondary break-all">{l}</p>)}
            </div>
          )}
        </div>
      )}

      {interrompida && status?.job?.estado !== 'erro' && (
        <div className="card p-4 mb-4 border border-warning/40">
          <p className="text-[13px] font-semibold text-warning">A última extração não foi concluída</p>
          <p className="text-[12px] text-text-secondary mt-1">
            Ela foi interrompida (por exemplo, por reinício do sistema) e nenhum resultado foi gerado — isto NÃO significa que não há divergências.
            Selecione o arquivo e clique em &quot;Extrair e preparar revisão&quot; novamente.
          </p>
        </div>
      )}

      {/* O que foi — e o que NÃO foi — verificado nesta extração. "Nenhum achado" nunca deve ser lido como "tudo certo". */}
      {pronta && status && (
        <div className="card p-4 mb-4">
          <p className="text-[13px] font-semibold text-text-primary">
            {status.achadosBrutos && status.achadosBrutos.length === 0
              ? 'Nenhuma divergência nas verificações realizadas'
              : 'Verificações desta extração'}
          </p>
          {status.escopo && (() => {
            const e = status.escopo!;
            const semComprovantes = (e.registros ?? 0) === 0 || (e.comprovantes ?? 0) === 0;
            const naoAplicadas = e.regras.filter(r => !r.aplicada);
            return (
              <div className="mt-2 space-y-2 text-[12px]">
                {semComprovantes && (
                  <p className="text-warning">
                    ⚠ Comprovantes NÃO foram conferidos: {(e.registros ?? 0) === 0
                      ? 'nenhum lançamento/comprovante foi lido deste arquivo (ele só traz o Demonstrativo ou o layout não foi reconhecido pelo conferidor de comprovantes).'
                      : 'o arquivo não traz comprovantes anexados.'}
                  </p>
                )}
                {!semComprovantes && (
                  <p className="text-text-secondary">
                    ✓ Comprovantes: {e.registros} lançamentos lidos e {e.comprovantes} comprovantes localizados.
                  </p>
                )}
                <ul className="space-y-0.5">
                  {e.regras.map(r => (
                    <li key={r.chave} className={r.aplicada ? 'text-text-secondary' : 'text-warning'}>
                      {r.aplicada ? '✓' : '✗'} {r.nome}{r.aplicada ? '' : ` — NÃO verificada: ${r.motivo ?? 'sem motivo informado'}`}
                    </li>
                  ))}
                </ul>
                {naoAplicadas.length > 0 && (
                  <p className="text-text-muted">
                    Regras marcadas com ✗ não foram conferidas neste arquivo: a ausência de divergência nelas não significa que está correto.
                  </p>
                )}
              </div>
            );
          })()}
          {status.achadosBrutos && status.achadosBrutos.length === 0 && (
            <p className="text-[12px] text-text-muted mt-2">
              Isto NÃO significa que o balancete está 100% correto: só vale para o que está marcado com ✓ acima. O relatório final
              pode ser gerado e baixado abaixo.
            </p>
          )}
        </div>
      )}

      {/* Revisão dos achados */}
      {pronta && status?.achadosBrutos && status.achadosBrutos.length > 0 && (
        <div className="card p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-[14px] font-semibold text-text-primary">
                {aConferir.length} item(ns) a conferir{pendentes.length > 0 ? ` — ${pendentes.length} pendente(s) de revisão` : ''}
              </h2>
              <p className="text-[11px] text-text-muted mt-0.5">
                {verificados.length} lançamento(s) foram verificados sem problema e não entram no relatório.{' '}
                <button type="button" className="underline" onClick={() => setMostrarVerificados(v => !v)}>
                  {mostrarVerificados ? 'Ocultar os verificados' : 'Ver os verificados'}
                </button>
              </p>
            </div>
            <button className="btn-ghost text-[12px] flex items-center gap-1.5" disabled={!!busy} onClick={salvarRevisao}>
              {busy === 'revisar' ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
              Salvar revisão
            </button>
          </div>
          <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
            {(mostrarVerificados ? status.achadosBrutos : aConferir).map(a => {
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

      {/* Geração do relatório final — aparece sempre que a extração já rodou
          (status.versao existe), mesmo com 0 achados: um mês sem nenhuma
          divergência ainda precisa de um relatório pra baixar/entregar. */}
      {pronta && (
        <div className="card p-4 flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="text-[13px] font-semibold text-text-primary">Relatório final</p>
            <p className="text-[11px] text-text-muted">
              {status.relatorioExiste
                ? 'Relatório gerado — pode ser regenerado após novas edições.'
                : status.achadosBrutos && status.achadosBrutos.length > 0
                  ? 'Ainda não gerado.'
                  : 'Nenhuma divergência encontrada nesta extração — pode gerar o relatório diretamente.'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-primary text-[12px] flex items-center gap-1.5" disabled={!!busy} onClick={gerarRelatorio}>
              {busy === 'render' ? <Loader2 size={13} className="animate-spin" /> : <FileCheck2 size={13} />}
              Gerar relatório final
            </button>
            {status.relatorioExiste && (
              <>
                <a className="btn-ghost text-[12px] flex items-center gap-1.5"
                  href={`/api/validacao/pdf?condominioId=${condominioId}&mes=${mes}`} target="_blank" rel="noreferrer">
                  <Eye size={13} /> Ver PDF
                </a>
                <a className="btn-ghost text-[12px] flex items-center gap-1.5"
                  href={`/api/validacao/pdf?condominioId=${condominioId}&mes=${mes}&baixar=1`}>
                  <Download size={13} /> Baixar PDF
                </a>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
