import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, History, Images, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { fetchHistory, repairArtifact } from '../api/client';
import type { HistoryResponse } from '../api/contracts';

const copy = {
  gallery: { title: 'Gallery', lead: 'Every saved drawing on this computer. Opening one checks its artifact checksums.' },
  history: { title: 'History', lead: 'Each saved revision, newest first. Reopen any of them in the studio.' },
};

export function HistoryPanel({ open, layout = 'gallery' }: { open: (id: string) => void; layout?: 'gallery' | 'history' }) {
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
  const Empty = layout === 'gallery' ? Images : History;
  return <section className={`history-panel layout-${layout}`} aria-label={layout === 'gallery' ? 'Saved drawing gallery' : 'Saved drawing history'}>
    <div className="history-toolbar"><div><h1>{copy[layout].title}</h1><p>{copy[layout].lead}</p></div><label className="history-search"><Search size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search your drawings" aria-label="Search drawing history" /></label></div>
    {error && <div className="notice notice-error" role="alert"><p>{error}</p><button className="subtle-button" onClick={() => setReload(value => value + 1)}><RefreshCw size={14} />Retry</button></div>}
    {data?.recovery_notices?.map((notice, index) => <p key={index} className="history-recovery"><ShieldCheck size={14} />{notice}</p>)}
    {loading && !data ? <div className={`history-${layout === 'gallery' ? 'grid' : 'list'} is-loading`} role="status" aria-label="Loading saved history">{Array.from({ length: layout === 'gallery' ? 6 : 5 }, (_, index) => <div key={index} className="skeleton" />)}</div>
      : !data?.items.length ? <div className="history-message"><span className="empty-icon"><Empty size={26} strokeWidth={1.5} /></span><h2>{query ? 'No matching drawings.' : 'Your first saved drawing starts here.'}</h2><p>Generated and imported revisions save automatically.</p></div>
      : layout === 'gallery' ? <div className="history-grid" aria-busy={loading}>{data.items.map(item => <article key={item.revision_id} className="history-card">
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
