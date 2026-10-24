import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowDownToLine, ArrowRight, ArrowUp, BookOpen, Check, ChevronDown, CircleHelp,
  Cpu, FileCode2, Grid2X2, History, Layers, Maximize2, Mic, Minus, Monitor,
  PenLine, Plus, RotateCcw, Settings2, ShieldCheck, Sparkles, SquarePen, Usb, X } from 'lucide-react';
import { loadStudio, submitCommand, type Studio } from './api/client';
import { Brand } from './components/Brand';

const examples = ['Draw a circle', 'Draw a butterfly', 'Create a beautiful mandala'];

function Dialog({ kind, studio, close }: { kind: 'guide' | 'settings'; studio: Studio | null; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => previous?.focus();
  }, []);
  return <dialog ref={ref} onCancel={close} aria-labelledby="dialog-title" className="studio-dialog">
    <div className="dialog-top"><span className="eyebrow">PROJECT PICASSO</span><button className="icon-button" onClick={close} aria-label="Close dialog"><X size={18} /></button></div>
    <h2 id="dialog-title">{kind === 'guide' ? 'From an idea to a line.' : 'Your local studio.'}</h2>
    {kind === 'guide' ? <>
      <p>The foundation is ready. Here is how the drawing workflow will take shape.</p>
      <ol className="guide-steps">
        <li><span>01</span><div><strong>Describe your drawing</strong><p>Draft a command in the composer. Offline shapes and mandalas arrive in Phase 3.</p></div></li>
        <li><span>02</span><div><strong>Make it your own</strong><p>Preview, resize and regenerate paths before preparing a drawing.</p></div></li>
        <li><span>03</span><div><strong>Bring it to paper</strong><p>Verified SD export follows in Phase 4; USB control follows firmware hardening in Phases 5–6.</p></div></li>
      </ol>
      <div className="notice"><ShieldCheck size={18} /><p>Generation and hardware actions are unavailable in this phase. Your original files remain untouched.</p></div>
    </> : <>
      <p>The app runs on your computer. No account or AI key is required for this foundation.</p>
      <dl className="settings-list">
        <div><dt>Application</dt><dd>{studio?.health.version ?? 'Service offline'}</dd></div>
        <div><dt>Python</dt><dd>{studio?.health.python_version ?? 'Unavailable'}</dd></div>
        <div><dt>Current milestone</dt><dd>Phase 2 · Studio foundation</dd></div>
        <div><dt>Local SD mirror</dt><dd>{studio?.status.storage.local_mirror ?? 'SdCard'}/</dd></div>
        <div><dt>Physical machine profile</dt><dd>Not selected or verified</dd></div>
      </dl>
      <div className="notice"><Cpu size={18} /><p>Reference profiles describe bundled source code. Calibration editing and physical verification arrive in later phases.</p></div>
    </>}
    <button className="primary-button dialog-done" onClick={close}>Back to the studio <ArrowRight size={16} /></button>
  </dialog>;
}

function DisabledTool({ children, reason }: { children: ReactNode; reason: string }) {
  return <span className="disabled-tool" title={reason}><button disabled aria-label={reason}>{children}</button></span>;
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
  const [submitting, setSubmitting] = useState(false);
  const [grid, setGrid] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [dialog, setDialog] = useState<'guide' | 'settings' | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const commandController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      try { setStudio(await loadStudio(controller.signal)); }
      catch { if (!controller.signal.aborted) setStudio(null); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [retry]);
  useEffect(() => () => commandController.current?.abort(), []);

  const command = useCallback(async () => {
    if (!prompt.trim() || submitting) return;
    if (!studio) { setFeedback('The local service is offline. Reconnect before submitting a command.'); return; }
    setSubmitting(true);
    setFeedback('');
    const controller = new AbortController();
    commandController.current = controller;
    try { setFeedback((await submitCommand(prompt.trim(), controller.signal)).message); }
    catch { if (!controller.signal.aborted) setFeedback('The local service could not process this command. Please try again.'); }
    finally { if (!controller.signal.aborted) setSubmitting(false); }
  }, [prompt, submitting, studio]);

  const draft = (text: string) => { setView('studio'); setPrompt(text); setFeedback(''); input.current?.focus(); };
  const onSubmit = (event: FormEvent) => { event.preventDefault(); void command(); };
  const selectedReference = studio?.profiles.profiles.find(profile => profile.id === referenceId);
  const generationReason = studio?.capabilities.generation.reason ?? 'Connect to the local service to check drawing availability.';

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <aside className="sidebar" aria-label="Main navigation">
      <Brand />
      <button className="new-drawing" onClick={() => draft('')}><Plus size={17} /> New drawing <span>+</span></button>
      <p className="nav-label">YOUR SPACE</p>
      <nav>
        <button className={view === 'studio' ? 'nav-item active' : 'nav-item'} aria-current={view === 'studio' ? 'page' : undefined} onClick={() => setView('studio')}><SquarePen size={18} /> Drawing studio</button>
        <button className={view === 'history' ? 'nav-item active' : 'nav-item'} aria-current={view === 'history' ? 'page' : undefined} onClick={() => setView('history')}><History size={18} /> Drawing history <span className="nav-phase">04</span></button>
      </nav>
      <div className="sidebar-note"><Layers size={21} /><strong>A space for your next idea.</strong><p>Your drawings and their revisions will live here in Phase 4.</p></div>
      <div className="sidebar-bottom">
        <button className="nav-item" onClick={() => setDialog('guide')}><BookOpen size={18} /> Getting started <ArrowRight size={15} /></button>
        <button className="nav-item" onClick={() => setDialog('settings')}><Settings2 size={18} /> Studio information</button>
        <div className="local-badge"><span className={`status-dot ${studio ? 'online' : ''}`} /><div><strong>{loading ? 'Connecting to your studio' : studio ? 'Running locally' : 'Service offline'}</strong><span>{studio ? `Version ${studio.health.version} · on your computer` : 'No cloud connection required'}</span></div></div>
      </div>
    </aside>

    <div className="main-shell">
      <header className="topbar">
        <div className="breadcrumb"><span className="mobile-brand"><Brand compact /></span><span>Workspace</span><span className="breadcrumb-slash">/</span><strong>{view === 'studio' ? 'Drawing studio' : 'History'}</strong></div>
        <div className="topbar-actions"><span className="phase-tag">PHASE 02</span><button className="icon-button" aria-label="Open getting started guide" onClick={() => setDialog('guide')}><CircleHelp size={19} /></button></div>
      </header>

      <main id="workspace" className="main-content">
        <div className="page-heading"><div><p className="eyebrow">IDEAS IN. ART OUT.</p><h1>{view === 'studio' ? 'Your imagination, one line at a time.' : 'Every drawing has a story.'}</h1><p>{view === 'studio' ? 'A thoughtful space to create, refine, and bring your drawings to life.' : 'Your saved ideas and drawing revisions will find a home here.'}</p></div><button className="subtle-button guide-button" onClick={() => setDialog('guide')}><BookOpen size={16} /> Quick guide <ArrowRight size={15} /></button></div>

        {!loading && !studio && <div className="connection-error" role="alert"><Monitor size={20} /><div><strong>The local service is offline</strong><p>Keep the Picasso launcher running, then reconnect. Your command stays in the composer.</p></div><button className="subtle-button" onClick={() => { setLoading(true); setRetry(value => value + 1); }}>Reconnect</button></div>}

        {view === 'history' ? <section className="history-empty panel" aria-labelledby="history-title"><div className="empty-icon"><History size={27} /></div><p className="eyebrow">YOUR COLLECTION</p><h2 id="history-title">Good ideas deserve a place to stay.</h2><p>Drawing history and saved revisions arrive in Phase 4.<br />No drawings have been saved in this app yet.</p><button className="primary-button" onClick={() => setView('studio')}>Back to the studio <ArrowRight size={16} /></button></section> : <>
          <div className="workspace-columns">
            <section className="preview-panel panel" aria-label="Drawing preview">
              <div className="panel-toolbar"><div className="panel-title"><span className="status-dot" /><h2>Drawing preview</h2><span className="small-tag">EMPTY CANVAS</span></div><div className="preview-actions"><button className={`icon-button ${grid ? 'selected' : ''}`} aria-label="Toggle preview grid" aria-pressed={grid} title="Toggle grid" onClick={() => setGrid(value => !value)}><Grid2X2 size={17} /></button><button className="icon-button" aria-label="Reset preview zoom" title="Fit blank page" onClick={() => setZoom(100)}><Maximize2 size={17} /></button></div></div>
              <div className={`preview-stage ${grid ? 'show-grid' : ''}`}>
                <div className="canvas-meta"><span><span className="tiny-dot" /> PREVIEW WORKSPACE</span><span>mm</span></div>
                <div className="paper" style={{ transform: `scale(${zoom / 100})` }}>
                  <span className="paper-corner top-left" /><span className="paper-corner bottom-right" />
                  <div className="paper-empty"><div className="pen-emblem"><PenLine size={30} strokeWidth={1.25} /></div><h3>The page is yours.</h3><p>Start with a simple idea.<br />Your drawing will appear here.</p><span className="canvas-phase"><span /> DRAWING ENGINE · PHASE 3</span></div>
                  <span className="origin-mark" title="Illustrative page center, not a machine reference">+</span>
                </div>
                <div className="canvas-footer"><span>Blank A4 page <span className="separator">·</span> 210 × 297 mm</span><div className="zoom-controls"><button aria-label="Zoom out" disabled={zoom <= 75} onClick={() => setZoom(value => Math.max(75, value - 25))}><Minus size={14} /></button><output aria-label="Preview zoom">{zoom}%</output><button aria-label="Zoom in" disabled={zoom >= 150} onClick={() => setZoom(value => Math.min(150, value + 25))}><Plus size={14} /></button></div></div>
              </div>
              <div className="preview-bottom"><span><ShieldCheck size={14} /> Preview only · no machine motion</span><DisabledTool reason="Path playback arrives with the drawing engine in Phase 3"><RotateCcw size={14} /> Playback</DisabledTool></div>
            </section>

            <aside className="inspector panel" aria-label="Drawing and machine inspector">
              <div className="inspector-tabs"><button className={inspector === 'drawing' ? 'active' : ''} aria-pressed={inspector === 'drawing'} onClick={() => setInspector('drawing')}><Settings2 size={15} /> Drawing</button><button className={inspector === 'machine' ? 'active' : ''} aria-pressed={inspector === 'machine'} onClick={() => setInspector('machine')}><Cpu size={15} /> Machine</button></div>
              {inspector === 'drawing' ? <div className="inspector-body">
                <div className="section-heading"><h3>Make it your own</h3><span className="small-tag">PHASE 3</span></div><p className="muted-copy">Drawing controls become available when the drawing engine is ready.</p>
                <fieldset disabled><legend>Dimensions <span>mm</span></legend><div className="dimension-fields"><label>Width<input placeholder="—" aria-label="Drawing width in millimetres" /></label><span>×</span><label>Height<input placeholder="—" aria-label="Drawing height in millimetres" /></label></div>
                  <label className="control-label">Detail level <span>Standard</span><input type="range" min="1" max="3" value="2" readOnly aria-label="Drawing detail level" /><span className="range-labels"><span>Simple</span><span>Intricate</span></span></label>
                  <label className="control-label seed-field">Variation seed<input placeholder="Generated with your drawing" aria-label="Drawing variation seed" /></label>
                </fieldset>
                <div className="inspector-rule" /><h3>Path insights</h3><dl className="path-insights"><div><dt>Drawing distance</dt><dd>—</dd></div><div><dt>Travel distance</dt><dd>—</dd></div><div><dt>Pen lifts</dt><dd>—</dd></div></dl><p className="insight-caption">Calculated from your drawing's exported path.</p>
                <div className="inspector-rule" /><button className="outline-button" disabled title={generationReason}><RotateCcw size={15} /> Regenerate drawing</button>
                <button className="outline-button" disabled title="Saving drawings arrives in Phase 4"><ArrowDownToLine size={15} /> Save drawing</button>
                <button className="prepare-button" disabled title="Preparing a job requires a verified profile and the drawing engine">Prepare for drawing <ArrowRight size={15} /></button>
                <p className="inspector-footnote"><ShieldCheck size={13} /> Nothing is sent until you are ready.</p>
              </div> : <div className="inspector-body">
                <div className="section-heading"><h3>Reference profiles</h3><span className="small-tag">READ ONLY</span></div><p className="muted-copy">Inspect source settings. Neither profile is selected for physical operation.</p>
                <label className="reference-label">Source reference<div className="select-wrap"><select value={referenceId} onChange={event => setReferenceId(event.target.value)} disabled={!studio} aria-label="Inspect reference profile"><option value="reference-350">Drawbot · 350 mm</option><option value="reference-400">SD copy · 400 mm</option></select><ChevronDown size={15} /></div></label>
                <div className="profile-badge"><ShieldCheck size={14} /> Unverified reference</div>
                <dl className="path-insights profile-details"><div><dt>Motor spacing</dt><dd>{selectedReference ? `${selectedReference.separation_mm} mm` : '—'}</dd></div><div><dt>Spool diameter</dt><dd>{selectedReference ? `${selectedReference.spool_diameter_mm} mm` : '—'}</dd></div><div><dt>Steps / turn</dt><dd>{selectedReference?.steps_per_turn ?? '—'}</dd></div><div><dt>Board</dt><dd>Unconfirmed</dd></div><div><dt>Allowed workspace</dt><dd>Not established</dd></div></dl>
                <div className="notice profile-notice"><Cpu size={18} /><p>{selectedReference?.notes ?? 'Connect to the local service to inspect the bundled source references.'}</p></div>
                <p className="insight-caption">Viewing a reference does not activate it or change any firmware.</p>
              </div>}
            </aside>
          </div>

          <section className="composer-section" aria-labelledby="composer-title"><div className="composer-heading"><h2 id="composer-title"><Sparkles size={17} /> What would you like to draw?</h2><span>DRAWING COMMAND</span></div>
            <form onSubmit={onSubmit} className="composer"><label className="sr-only" htmlFor="drawing-command">Drawing command</label><textarea ref={input} id="drawing-command" value={prompt} maxLength={2000} rows={2} onChange={event => { setPrompt(event.target.value); setFeedback(''); }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void command(); } }} placeholder="Describe a drawing. A circle, a butterfly, a beautiful mandala…" aria-describedby="command-hint" />
              <div className="composer-bottom"><span id="command-hint"><span className="composer-dot" /> {studio ? 'Drawing engine arrives in Phase 3' : loading ? 'Connecting to local service…' : 'Local service offline'}</span><div className="composer-actions"><span title="Voice input arrives in Phase 8"><button type="button" disabled className="microphone-button" aria-label="Voice input unavailable until Phase 8"><Mic size={19} /></button></span><span className="action-divider" /><button className="submit-command" type="submit" aria-label="Submit drawing command" disabled={!prompt.trim() || !studio || submitting}>{submitting ? <span className="spinner" /> : <ArrowUp size={19} />}</button></div></div>
            </form>
            <div className="command-feedback" role="status" aria-live="polite">{feedback && <><CircleHelp size={16} /><span>{feedback}</span></>}</div>
            <div className="example-commands"><span>A LITTLE INSPIRATION</span>{examples.map(text => <button key={text} onClick={() => draft(text)}>{text}<ArrowRight size={12} /></button>)}</div>
          </section>
        </>}

        <footer className="workspace-footer"><div className="footer-statuses"><span title={studio?.status.machine.reason ?? 'Machine control unavailable'}><Usb size={14} /><span className="status-dot" />Machine control unavailable</span><span title={studio?.status.storage.reason ?? 'SD export unavailable'}><FileCode2 size={14} /><span className="status-dot" />SD not configured</span></div><span><Check size={13} /> Local first. Made for your machine.</span></footer>
      </main>
    </div>
    {dialog && <Dialog kind={dialog} studio={studio} close={() => setDialog(null)} />}
  </div>;
}
