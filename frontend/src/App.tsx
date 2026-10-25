import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUp, BookOpen, Check, ChevronDown, CircleHelp, Cpu, FileCode2, History,
  Layers, Mic, Monitor, Plus, Settings2, ShieldCheck, Sparkles, SquarePen, Usb, X } from 'lucide-react';
import { downloadDraft, loadStudio, reviseDraft, submitCommand, type Studio } from './api/client';
import type { DrawingDraft } from './api/contracts';
import { Brand } from './components/Brand';
import { DrawingPreview } from './components/DrawingPreview';
import { DrawingInspector, emptyEdits, fieldsFor, revisionPayload, type Edits } from './components/DrawingInspector';

const examples = ['Draw a circle', 'Draw a butterfly', 'Create a beautiful mandala'];

function Dialog({ kind, studio, close }: { kind: 'guide' | 'settings'; studio: Studio | null; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.showModal(); return () => previous?.focus(); }, []);
  return <dialog ref={ref} onCancel={close} aria-labelledby="dialog-title" className="studio-dialog">
    <div className="dialog-top"><span className="eyebrow">PROJECT PICASSO</span><button className="icon-button" onClick={close} aria-label="Close dialog"><X size={18} /></button></div>
    <h2 id="dialog-title">{kind === 'guide' ? 'From an idea to a line.' : 'Your local studio.'}</h2>
    {kind === 'guide' ? <><p>Generate a drawing offline, refine its paths, and keep an unverified draft.</p>
      <ol className="guide-steps"><li><span>01</span><div><strong>Describe one drawing</strong><p>Try a circle, ellipse, rectangle, spiral, butterfly, mandala or geometric pattern. Add “120 mm wide”, “12 petals”, “seed 7”, or “intricate”.</p></div></li>
        <li><span>02</span><div><strong>Make it your own</strong><p>Adjust size, rotation, center, detail and seed. Controls update the path automatically. Playback is a visual simulation, not machine timing.</p></div></li>
        <li><span>03</span><div><strong>Keep a draft</strong><p>Download JSON, SVG or restricted G-code. Session revisions disappear on restart. Durable history and verified SD export follow in Phase 4.</p></div></li></ol>
      <div className="notice"><ShieldCheck size={18} /><p>Machine calibration is unverified. Draft downloads cannot authorize physical drawing. No hardware command is sent.</p></div>
    </> : <><p>Drawings are generated on your computer. No account, API key or network service is required.</p><dl className="settings-list">
      <div><dt>Application</dt><dd>{studio?.health.version ?? 'Service offline'}</dd></div><div><dt>Python</dt><dd>{studio?.health.python_version ?? 'Unavailable'}</dd></div>
      <div><dt>Current milestone</dt><dd>Phase 3 · Offline drawing</dd></div><div><dt>Local SD mirror</dt><dd>SdCard/ · unchanged</dd></div><div><dt>Machine profile</dt><dd>Not selected or verified</dd></div></dl>
      <div className="notice"><Cpu size={18} /><p>At most 16 revisions / 32 MB are kept by the service. This window shows its last eight revisions. Download drafts before closing or restarting.</p></div></>}
    <button className="primary-button dialog-done" onClick={close}>Back to the studio <ArrowRight size={16} /></button>
  </dialog>;
}

export default function App() {
  const [studio, setStudio] = useState<Studio | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState<'studio' | 'history'>('studio');
  const [inspector, setInspector] = useState<'drawing' | 'machine'>('drawing');
  const [referenceId, setReferenceId] = useState('reference-350');
  const [prompt, setPrompt] = useState('');
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [grid, setGrid] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [dialog, setDialog] = useState<'guide' | 'settings' | null>(null);
  const [draft, setDraft] = useState<DrawingDraft | null>(null);
  const [session, setSession] = useState<DrawingDraft[]>([]);
  const [fields, setFields] = useState<Edits>(emptyEdits);
  const [aspectLocked, setAspectLocked] = useState(true);
  const [seedLocked, setSeedLocked] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const controller = useRef<AbortController | null>(null);
  const ticket = useRef(0);
  const lastAttempt = useRef('');

  useEffect(() => {
    const abort = new AbortController();
    const refresh = async () => { try { setStudio(await loadStudio(abort.signal)); } catch { if (!abort.signal.aborted) setStudio(null); } finally { if (!abort.signal.aborted) setLoading(false); } };
    void refresh(); const timer = window.setInterval(refresh, 15000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [retry]);
  useEffect(() => () => { ticket.current++; controller.current?.abort(); }, []);

  const cancel = useCallback(() => { ticket.current++; controller.current?.abort(); setBusy(false); }, []);
  const accept = useCallback((result: DrawingDraft) => {
    setDraft(result); setFields(fieldsFor(result));
    setSession(current => [result, ...current.filter(item => item.revision_id !== result.revision_id)].slice(0, 8));
  }, []);
  const perform = useCallback(async (operation: (signal: AbortSignal) => Promise<DrawingDraft>, message: string) => {
    controller.current?.abort(); const version = ++ticket.current; const abort = new AbortController(); controller.current = abort;
    setBusy(true); setFeedback('');
    try { const result = await operation(abort.signal); if (ticket.current === version) { accept(result); setFeedback(`${result.title} · revision ${result.revision}. ${message}`); } }
    catch (error) { if (!abort.signal.aborted && ticket.current === version) setFeedback(error instanceof Error ? error.message : 'The drawing could not be updated.'); }
    finally { if (ticket.current === version) setBusy(false); }
  }, [accept]);

  const adjustment = useMemo(() => {
    if (!draft) return { dirty: false, key: '', error: '', payload: null };
    try { const payload = revisionPayload(draft, fields); const key = JSON.stringify(payload); return { payload, key: `${draft.revision_id}:${key}`, error: '', dirty: key !== JSON.stringify(revisionPayload(draft, fieldsFor(draft))) }; }
    catch (error) { return { dirty: true, key: '', payload: null, error: error instanceof Error ? error.message : 'Check drawing controls.' }; }
  }, [draft, fields]);
  useEffect(() => {
    if (!draft || !studio || busy || !adjustment.dirty) return;
    if (adjustment.error) { setFeedback(adjustment.error); return; }
    if (!adjustment.payload || lastAttempt.current === adjustment.key) return;
    const timer = window.setTimeout(() => {
      lastAttempt.current = adjustment.key;
      void perform(signal => reviseDraft(draft.revision_id, adjustment.payload!, signal), 'Preview and G-code updated. Simulation only.');
    }, 450);
    return () => window.clearTimeout(timer);
  }, [draft, studio, busy, adjustment, perform]);

  const change = (key: keyof Edits, value: string) => {
    cancel();
    setFields(current => {
      const next = { ...current, [key]: value };
      const numeric = Number(value);
      if (aspectLocked && draft && value.trim() && numeric > 0 && Number.isFinite(numeric)) {
        if (key === 'width') next.height = String(Number((numeric * draft.spec.dimensions.height_mm / draft.spec.dimensions.width_mm).toFixed(3)));
        if (key === 'height') next.width = String(Number((numeric * draft.spec.dimensions.width_mm / draft.spec.dimensions.height_mm).toFixed(3)));
      }
      return next;
    });
  };
  const command = () => { if (!prompt.trim() || busy || !studio) return; setView('studio'); setZoom(100); void perform(signal => submitCommand(prompt.trim(), signal), 'Simulation only; machine profile unverified.'); };
  const onSubmit = (event: FormEvent) => { event.preventDefault(); command(); };
  const draftCommand = (text: string) => { setView('studio'); setPrompt(text); setFeedback(''); input.current?.focus(); };
  const newDrawing = () => { cancel(); setDraft(null); setFields(emptyEdits); draftCommand(''); };
  const regenerate = () => { if (draft && !busy && studio) void perform(signal => reviseDraft(draft.revision_id, { regenerate: true, seed_locked: seedLocked }, signal), seedLocked ? 'Seed retained.' : 'New deterministic seed.'); };
  const download = async (format: 'json' | 'svg' | 'gcode') => {
    if (!draft || busy || adjustment.dirty || !studio) return;
    const version = ++ticket.current; const abort = new AbortController(); controller.current = abort; setBusy(true);
    try { const file = await downloadDraft(draft.revision_id, format, abort.signal); if (ticket.current !== version) return;
      const url = URL.createObjectURL(file.blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setFeedback(`Downloaded ${format === 'gcode' ? 'unverified G-code' : format.toUpperCase()} draft. No hardware operation was performed.`);
    } catch (error) { if (!abort.signal.aborted && ticket.current === version) setFeedback(error instanceof Error ? error.message : 'Download failed.'); }
    finally { if (ticket.current === version) setBusy(false); }
  };
  const selectedReference = studio?.profiles.profiles.find(profile => profile.id === referenceId);

  return <div className="app-shell"><a className="skip-link" href="#workspace">Skip to workspace</a>
    <aside className="sidebar" aria-label="Main navigation"><Brand /><button className="new-drawing" onClick={newDrawing}><Plus size={17} /> New drawing <span>+</span></button><p className="nav-label">YOUR SPACE</p><nav>
      <button className={view === 'studio' ? 'nav-item active' : 'nav-item'} aria-current={view === 'studio' ? 'page' : undefined} onClick={() => setView('studio')}><SquarePen size={18} /> Drawing studio</button>
      <button className={view === 'history' ? 'nav-item active' : 'nav-item'} aria-current={view === 'history' ? 'page' : undefined} onClick={() => setView('history')}><History size={18} /> Session drafts <span className="nav-phase">{session.length}</span></button></nav>
      {session.length ? <div className="session-list"><p className="nav-label">THIS WINDOW · NOT SAVED</p>{session.slice(0, 5).map(item => <button key={item.revision_id} onClick={() => { cancel(); accept(item); setView('studio'); setFeedback('Viewing a session revision. Durable history arrives in Phase 4.'); }} className={item.revision_id === draft?.revision_id ? 'selected' : ''}><Layers size={14} /><span>{item.title}<small>Revision {item.revision} · seed {item.spec.seed ?? 0}</small></span></button>)}</div> : <div className="sidebar-note"><Layers size={21} /><strong>A space for your next idea.</strong><p>Generate offline. Download your draft to keep a copy.</p></div>}
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => setDialog('guide')}><BookOpen size={18} /> Getting started <ArrowRight size={15} /></button><button className="nav-item" onClick={() => setDialog('settings')}><Settings2 size={18} /> Studio information</button><div className="local-badge"><span className={`status-dot ${studio ? 'online' : ''}`} /><div><strong>{loading ? 'Connecting to your studio' : studio ? 'Running locally' : 'Service offline'}</strong><span>{studio ? `Version ${studio.health.version} · on your computer` : 'No cloud connection required'}</span></div></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><span>Workspace</span><span className="breadcrumb-slash">/</span><strong>{view === 'studio' ? 'Drawing studio' : 'Session drafts'}</strong></div><div className="topbar-actions"><span className="phase-tag">PHASE 03</span><button className="icon-button" aria-label="Open getting started guide" onClick={() => setDialog('guide')}><CircleHelp size={19} /></button></div></header>
      <main id="workspace" className="main-content"><div className="page-heading"><div><p className="eyebrow">IDEAS IN. ART OUT.</p><h1>{view === 'studio' ? 'Your imagination, one line at a time.' : 'Ideas worth another look.'}</h1><p>{view === 'studio' ? 'Create offline, refine the paths, and keep a drawing draft.' : 'The last eight revisions in this window. Download a copy before restarting.'}</p></div><button className="subtle-button guide-button" onClick={() => setDialog('guide')}><BookOpen size={16} /> Quick guide <ArrowRight size={15} /></button></div>
        {!loading && !studio && <div className="connection-error" role="alert"><Monitor size={20} /><div><strong>The local service is offline</strong><p>Keep the Picasso launcher running, then reconnect. Your command stays in the composer.</p></div><button className="subtle-button" onClick={() => { setLoading(true); setRetry(value => value + 1); }}>Reconnect</button></div>}
        {view === 'history' ? <section className="history-empty panel"><div className="empty-icon"><History size={27} /></div><p className="eyebrow">SESSION DRAFTS</p><h2>{session.length ? 'Revisit a drawing revision.' : 'Your first drawing starts here.'}</h2><p>These drafts are not durable history. Saved history arrives in Phase 4.</p><div className="session-cards">{session.map(item => <button key={item.revision_id} className="outline-button" onClick={() => { cancel(); accept(item); setView('studio'); }}><Layers size={16} />{item.title} · revision {item.revision} · {item.preview.bounds.width_mm.toFixed(1)} × {item.preview.bounds.height_mm.toFixed(1)} mm</button>)}</div><button className="primary-button" onClick={() => setView('studio')}>Back to the studio <ArrowRight size={16} /></button></section> : <>
          <div className="workspace-columns"><DrawingPreview draft={draft} busy={busy} grid={grid} setGrid={setGrid} zoom={zoom} setZoom={setZoom} />
            <aside className="inspector panel" aria-label="Drawing and machine inspector"><div className="inspector-tabs"><button className={inspector === 'drawing' ? 'active' : ''} aria-pressed={inspector === 'drawing'} onClick={() => setInspector('drawing')}><Settings2 size={15} /> Drawing</button><button className={inspector === 'machine' ? 'active' : ''} aria-pressed={inspector === 'machine'} onClick={() => setInspector('machine')}><Cpu size={15} /> Machine</button></div>
              {inspector === 'drawing' ? <DrawingInspector draft={draft} fields={fields} change={change} busy={busy} available={!!studio} dirty={adjustment.dirty} aspectLocked={aspectLocked} setAspectLocked={setAspectLocked} seedLocked={seedLocked} setSeedLocked={setSeedLocked} regenerate={regenerate} download={format => void download(format)} /> : <div className="inspector-body"><div className="section-heading"><h3>Reference profiles</h3><span className="small-tag">READ ONLY</span></div><p className="muted-copy">Neither profile is selected for physical operation.</p><label className="reference-label">Source reference<div className="select-wrap"><select value={referenceId} onChange={event => setReferenceId(event.target.value)} disabled={!studio} aria-label="Inspect reference profile"><option value="reference-350">Drawbot · 350 mm</option><option value="reference-400">SD copy · 400 mm</option></select><ChevronDown size={15} /></div></label><div className="profile-badge"><ShieldCheck size={14} /> Unverified reference</div><dl className="path-insights profile-details"><div><dt>Motor spacing</dt><dd>{selectedReference ? `${selectedReference.separation_mm} mm` : '—'}</dd></div><div><dt>Spool diameter</dt><dd>{selectedReference ? `${selectedReference.spool_diameter_mm} mm` : '—'}</dd></div><div><dt>Steps / turn</dt><dd>{selectedReference?.steps_per_turn ?? '—'}</dd></div><div><dt>Board</dt><dd>Unconfirmed</dd></div><div><dt>Allowed workspace</dt><dd>Not established</dd></div></dl><div className="notice profile-notice"><Cpu size={18} /><p>{selectedReference?.notes ?? 'Connect to inspect source references.'}</p></div><p className="insight-caption">Viewing a reference does not activate it or change firmware.</p></div>}
            </aside></div>
          <section className="composer-section" aria-labelledby="composer-title"><div className="composer-heading"><h2 id="composer-title"><Sparkles size={17} /> What would you like to draw?</h2><span>OFFLINE DRAWING COMMAND</span></div><form onSubmit={onSubmit} className="composer"><label className="sr-only" htmlFor="drawing-command">Drawing command</label><textarea ref={input} id="drawing-command" value={prompt} maxLength={2000} rows={2} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); command(); } }} placeholder="Describe a circle, butterfly, mandala, or geometric pattern…" aria-describedby="command-hint" /><div className="composer-bottom"><span id="command-hint"><span className="composer-dot" />{busy ? 'Building the exported path…' : studio ? 'Offline engine · no API key needed' : loading ? 'Connecting to local service…' : 'Local service offline'}</span><div className="composer-actions">{busy && <button type="button" className="cancel-generation" onClick={() => { cancel(); setFeedback('Cancelled. The previous draft is retained.'); }}>Cancel</button>}<span title="Voice input arrives in Phase 8"><button type="button" disabled className="microphone-button" aria-label="Voice input unavailable until Phase 8"><Mic size={19} /></button></span><span className="action-divider" /><button className="submit-command" type="submit" aria-label="Submit drawing command" disabled={!prompt.trim() || !studio || busy}>{busy ? <span className="spinner" /> : <ArrowUp size={19} />}</button></div></div></form><div className="command-feedback" role="status" aria-live="polite">{feedback && <><CircleHelp size={16} /><span>{feedback}</span></>}</div><div className="example-commands"><span>A LITTLE INSPIRATION</span>{examples.map(text => <button key={text} onClick={() => draftCommand(text)}>{text}<ArrowRight size={12} /></button>)}</div></section>
        </>}
        <footer className="workspace-footer"><div className="footer-statuses"><span title={studio?.status.machine.reason ?? 'Machine control unavailable'}><Usb size={14} /><span className="status-dot" />Machine control unavailable</span><span title={studio?.status.storage.reason ?? 'SD export unavailable'}><FileCode2 size={14} /><span className="status-dot" />SD not configured</span></div><span><Check size={13} />Local first. Made for your machine.</span></footer>
      </main></div>{dialog && <Dialog kind={dialog} studio={studio} close={() => setDialog(null)} />}
  </div>;
}
