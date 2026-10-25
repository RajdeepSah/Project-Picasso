import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, History, Search, ShieldCheck } from 'lucide-react';
import { fetchHistory, repairArtifact } from '../api/client';
import type { HistoryResponse } from '../api/contracts';

export function HistoryPanel({ open }: { open: (id: string) => void }) {
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
  return <section className="history-panel panel" aria-label="Saved drawing history">
    <div className="history-toolbar"><div><h2>Saved drawings & revisions</h2><p>Stored on this computer. Reopening a revision checks its artifact checksums.</p></div><label className="history-search"><Search size={16} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search your drawings" aria-label="Search drawing history" /></label></div>
    {error && <div className="notice" role="alert"><p>{error}</p><button onClick={() => setReload(value => value + 1)}>Retry</button></div>}
    {data?.recovery_notices?.map((notice, index) => <p key={index} className="history-recovery"><ShieldCheck size={14} />{notice}</p>)}
    {loading ? <p className="history-message" role="status">Loading saved history…</p> : !data?.items.length ? <div className="history-message"><History size={27} /><h3>{query ? 'No matching drawings.' : 'Your first saved drawing starts here.'}</h3><p>Generated and imported revisions save automatically.</p></div> : <div className="history-grid">{data.items.map(item => <article key={item.revision_id} className="history-card">
      <button className="history-thumbnail" disabled={item.integrity !== 'ok'} onClick={() => open(item.revision_id)} aria-label={`Open ${item.title} revision ${item.revision}`}>
        {item.integrity === 'ok' ? <img src={`/api/drawings/${item.revision_id}/thumbnail`} alt={`${item.title} thumbnail`} loading="lazy" /> : <ShieldCheck size={28} />}
      </button><div className="history-card-copy"><strong>{item.title} <span>r{item.revision}</span></strong><p>{item.prompt}</p><small>{new Date(item.created_at).toLocaleString()}</small>
      {item.integrity === 'damaged' && <><p className="history-recovery">Artifact needs repair. Its recovery copy is preserved locally.</p><button className="outline-button" onClick={() => void repair(item.revision_id)}>Repair saved revision</button></>}</div>
    </article>)}</div>}
    <div className="history-pagination"><span>{data ? `${data.total} saved revisions` : 'Saved locally'}</span><button className="subtle-button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset-12))}><ArrowLeft size={14} />Previous</button><button className="subtle-button" disabled={!data || offset+12 >= data.total || loading} onClick={() => setOffset(offset+12)}>Next<ArrowRight size={14} /></button></div>
  </section>;
}
