import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Images, LayoutGrid, List, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { fetchHistory, repairArtifact } from '../api/client';
import type { HistoryResponse } from '../api/contracts';

const layouts = [['grid', 'Grid', LayoutGrid], ['list', 'List', List]] as const;

export function HistoryPanel({ open }: { open: (id: string) => void }) {
  const [layout, setLayout] = useState<'grid' | 'list'>('grid');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => { setOffset(0); }, [query]);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchHistory(query, offset, abort.signal).then(result => { setData(result); setError(''); })
        .catch(error => { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : 'History is unavailable.'); })
        .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    }, 200);
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [query, offset, reload]);
  const repair = async (id: string) => { try { await repairArtifact(id); setReload(value => value + 1); } catch (error) { setError(error instanceof Error ? error.message : 'Repair failed.'); } };
  return <section className={`history-panel layout-${layout}`} aria-label="Saved drawing gallery">
    <div className="history-toolbar"><div><h1>Gallery</h1><p>Every saved revision on this computer, newest first. Opening one checks its artifact checksums.</p></div>
      <div className="history-controls"><label className="history-search"><Search size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search your drawings" aria-label="Search drawing history" /></label>
        <div className="pill-segmented" role="radiogroup" aria-label="Gallery layout">{layouts.map(([value, label, Icon]) =>
          <button key={value} type="button" role="radio" aria-checked={layout === value} aria-label={`${label} layout`} title={label} onClick={() => setLayout(value)}><Icon size={16} /></button>)}</div></div></div>
    {error && <div className="notice notice-error" role="alert"><p>{error}</p><button className="subtle-button" onClick={() => setReload(value => value + 1)}><RefreshCw size={14} />Retry</button></div>}
    {data?.recovery_notices?.map((notice, index) => <p key={index} className="history-recovery"><ShieldCheck size={14} />{notice}</p>)}
    {loading && !data ? <div className={`history-${layout} is-loading`} role="status" aria-label="Loading saved history">{Array.from({ length: layout === 'grid' ? 6 : 5 }, (_, index) => <div key={index} className="skeleton" />)}</div>
      : !data?.items.length ? <div className="history-message"><span className="empty-icon"><Images size={26} strokeWidth={1.5} /></span><h2>{query ? 'No matching drawings.' : 'Your first saved drawing starts here.'}</h2><p>Generated and imported revisions save automatically.</p></div>
      : layout === 'grid' ? <div className="history-grid" aria-busy={loading}>{data.items.map(item => <article key={item.revision_id} className="history-card">
        <button className="history-thumbnail" disabled={item.integrity !== 'ok'} onClick={() => open(item.revision_id)} aria-label={`Open ${item.title} revision ${item.revision}`}>
          {item.integrity === 'ok' ? <img src={`/api/drawings/${item.revision_id}/thumbnail`} alt={`${item.title} thumbnail`} loading="lazy" /> : <ShieldCheck size={28} />}
        </button><div className="history-card-copy"><strong>{item.title} <span>r{item.revision}</span></strong><p>{item.prompt}</p><small>{new Date(item.created_at).toLocaleString()}</small>
        {item.integrity === 'damaged' && <><p className="history-recovery">Artifact needs repair. Its recovery copy is preserved locally.</p><button className="outline-button" onClick={() => void repair(item.revision_id)}>Repair saved revision</button></>}</div>
      </article>)}</div>
      : <ol className="history-list" aria-busy={loading}>{data.items.map(item => <li key={item.revision_id} className="history-row">
        <button className="history-thumbnail" disabled={item.integrity !== 'ok'} onClick={() => open(item.revision_id)} aria-label={`Open ${item.title} revision ${item.revision}`}>
          {item.integrity === 'ok' ? <img src={`/api/drawings/${item.revision_id}/thumbnail`} alt="" loading="lazy" /> : <ShieldCheck size={20} />}
        </button>
        <div className="history-row-copy"><strong>{item.title} <span>Revision {item.revision} · {item.generator}</span></strong><p>{item.prompt}</p>
          {item.integrity === 'damaged' && <p className="history-recovery">Artifact needs repair. Its recovery copy is preserved locally.</p>}</div>
        <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
        {item.integrity === 'damaged' ? <button className="outline-button" onClick={() => void repair(item.revision_id)}>Repair</button>
          : <button className="subtle-button" disabled={item.integrity !== 'ok'} onClick={() => open(item.revision_id)} tabIndex={-1} aria-hidden="true">Open<ArrowRight size={14} /></button>}
      </li>)}</ol>}
    <div className="history-pagination"><span>{data ? `${data.total} saved revisions` : 'Saved locally'}</span><button className="subtle-button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset-12))}><ArrowLeft size={14} />Previous</button><button className="subtle-button" disabled={!data || offset+12 >= data.total || loading} onClick={() => setOffset(offset+12)}>Next<ArrowRight size={14} /></button></div>
  </section>;
}
