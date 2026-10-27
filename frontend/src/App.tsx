import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUp, ChevronDown, CircleAlert, CircleCheck, CircleHelp, Cpu, HardDrive, PenLine, Printer, Settings, ShieldCheck, Upload, WifiOff, X } from 'lucide-react';
import { controlMachine, downloadDraft, fetchDraft, fetchJob, loadStudio, reviseDraft, selectCalibration, submitCommand, type CommandOptions, type Studio } from './api/client';
import type { DrawingDraft } from './api/contracts';
import { Brand } from './components/Brand';
import { HistoryPanel } from './components/HistoryPanel';
import { ImportDialog } from './components/ImportDialog';
import { CalibrationDialog } from './components/CalibrationDialog';
import { MachinePanel } from './components/MachinePanel';
import { ExecuteDialog } from './components/ExecuteDialog';
import { DocumentMenu } from './components/DocumentMenu';
import { VoiceButton } from './components/VoiceButton';
import { ExportMenu, type DownloadFormat } from './components/ExportMenu';
import { runActive, useMachine } from './components/UsbRunCard';
import { DrawingPreview, executedFraction, isPaper, paperOptions, paperSize, type Execution, type PaperId } from './components/DrawingPreview';
import { DrawingInspector, emptyEdits, fieldsFor, revisionPayload, type Edits } from './components/DrawingInspector';

const examples = [['Mandala', 'Create a beautiful mandala'], ['Geometric', 'Draw a geometric pattern'], ['Butterfly', 'Draw a butterfly'], ['Circle', 'Draw a circle']];
const views = [['studio', 'Studio'], ['gallery', 'Gallery']] as const;
const machineLabels: Record<string, string> = { connected: 'Machine connected', connecting: 'Machine connecting', lost: 'Machine connection lost', incompatible: 'Incompatible firmware' };
type Route = NonNullable<CommandOptions['mode']>;
type Detail = NonNullable<CommandOptions['detail']>;
const routes: [Route, string, string][] = [
  ['auto', 'Auto', 'Shapes are drawn offline; anything else becomes AI line art'],
  ['offline', 'Offline only', 'Never uses the network or the API key'],
  ['ai', 'AI image', 'Always asks OpenAI for line art, then traces it locally'],
];
const commandDetails: [Detail, string][] = [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']];

function storedPaper(): PaperId {
  try { const value = window.localStorage.getItem('picasso.paper'); return isPaper(value) ? value : 'A4-portrait'; } catch { return 'A4-portrait'; }
}
function stored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try { const value = window.localStorage.getItem(key) as T | null; return value && allowed.includes(value) ? value : fallback; } catch { return fallback; }
}
function remember(key: string, value: string) { try { window.localStorage.setItem(key, value); } catch { /* preference only */ } }

function Dialog({ kind, studio, close }: { kind: 'guide' | 'settings'; studio: Studio | null; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.showModal(); return () => previous?.focus(); }, []);
  return <dialog ref={ref} onCancel={close} aria-labelledby="dialog-title" className="studio-dialog">
    <div className="dialog-top"><span className="eyebrow">PROJECT PICASSO</span><button className="icon-button" onClick={close} aria-label="Close dialog"><X size={18} /></button></div>
    <h2 id="dialog-title">{kind === 'guide' ? 'From an idea to a line.' : 'Your local studio.'}</h2>
    {kind === 'guide' ? <><p>Generate or import a drawing, refine its paths, and reopen it from saved history.</p>
      <ol className="guide-steps"><li><span>01</span><div><strong>Describe one drawing</strong><p>Type or say it. A circle, ellipse, rectangle, spiral, butterfly, mandala or geometric pattern is drawn offline; add “120 mm wide”, “12 petals” or “seed 7”. With an OpenAI key set up, anything else becomes AI line art traced on this computer. Low, Medium and High set the detail.</p></div></li>
        <li><span>02</span><div><strong>Make it your own</strong><p>Adjust size, detail and paper, or open Advanced for rotation, center and seed. Controls update the path automatically. Playback estimates machine time from the firmware's step timing; its speed control changes only the preview, never the machine.</p></div></li>
        <li><span>03</span><div><strong>Draw it or keep it</strong><p>Execute streams the drawing to the machine over USB once it is connected, a verified profile is selected and the origin is set on the keypad. Or export it as G-code, SVG or PNG; revisions save automatically.</p></div></li></ol>
      <div className="notice"><ShieldCheck size={18} /><p>Nothing is sent to the machine until you connect explicitly and start a run.</p></div>
    </> : <><p>Drawings are generated on your computer. No account, API key or network service is required; an optional OpenAI key adds AI line art for requests the offline shapes cannot draw.</p><dl className="settings-list">
      <div><dt>Application</dt><dd>{studio?.health.version ?? 'Service offline'}</dd></div><div><dt>Python</dt><dd>{studio?.health.python_version ?? 'Unavailable'}</dd></div>
      <div><dt>Current milestone</dt><dd>Phase 6 · Acknowledged USB control</dd></div><div><dt>Local SD mirror</dt><dd>SdCard/ · unchanged</dd></div><div><dt>Machine profile</dt><dd>Not selected or verified</dd></div><div><dt>Voice input</dt><dd>{studio?.capabilities.voice.available ? 'Offline · Faster-Whisper small' : 'Speech model not installed'}</dd></div><div><dt>AI drawing</dt><dd title={studio?.capabilities.ai.reason}>{studio?.capabilities.ai.available ? 'OpenAI · used only on request' : 'Not set up · offline only'}</dd></div></dl>
      <div className="notice"><Cpu size={18} /><p>Revisions are stored in local history. Back up the data folder with the app stopped to retain the database, artifacts, profiles and recovery copies together.</p></div></>}
    <button className="primary-button dialog-done" onClick={close}>Back to the studio <ArrowRight size={16} /></button>
  </dialog>;
}

export default function App() {
  const [studio, setStudio] = useState<Studio | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState<'studio' | 'gallery'>('studio');
  const [inspector, setInspector] = useState<'drawing' | 'machine'>('drawing');
  const [referenceId, setReferenceId] = useState('reference-350');
  const [prompt, setPrompt] = useState('');
  const [feedback, setFeedback] = useState('');
  const [tone, setTone] = useState<'info' | 'error'>('info');
  const [busy, setBusy] = useState(false);
  const [grid, setGrid] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [paper, setPaperState] = useState<PaperId>(storedPaper);
  const [route, setRouteState] = useState<Route>(() => stored('picasso.route', ['auto', 'offline', 'ai'], 'auto'));
  const [detail, setDetailState] = useState<Detail>(() => stored('picasso.detail', ['low', 'medium', 'high'], 'medium'));
  const [dialog, setDialog] = useState<'guide' | 'settings' | null>(null);
  const [extra, setExtra] = useState<'import' | 'calibration' | null>(null);
  const [draft, setDraft] = useState<DrawingDraft | null>(null);
  const [session, setSession] = useState<DrawingDraft[]>([]);
  const [fields, setFields] = useState<Edits>(emptyEdits);
  const [aspectLocked, setAspectLocked] = useState(true);
  const [seedLocked, setSeedLocked] = useState(false);
  const [executeOpen, setExecuteOpen] = useState(false);
  const [executing, setExecuting] = useState<{ jobId: string; revisionId: string } | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const controller = useRef<AbortController | null>(null);
  const ticket = useRef(0);
  const lastAttempt = useRef('');
  const say = useCallback((text: string, kind: 'info' | 'error' = 'info') => { setFeedback(text); setTone(kind); }, []);
  const setPaper = (value: PaperId) => { setPaperState(value); remember('picasso.paper', value); };
  const setRoute = (value: Route) => { setRouteState(value); remember('picasso.route', value); };
  const setDetail = (value: Detail) => { setDetailState(value); remember('picasso.detail', value); };
  const aiAvailable = !!studio?.capabilities.ai.available;
  const activeRoute: Route = route === 'ai' && !aiAvailable ? 'auto' : route;  // AI needs a configured key
  // A local snapshot without device I/O, so Execute, Stop and the machine status stay current.
  const [machine, refreshMachine] = useMachine(true);
  const run = machine?.run;
  useEffect(() => {  // after a reload, find which revision an active run belongs to
    if (!run || !runActive(run) || executing?.jobId === run.job_id) return;
    const abort = new AbortController();
    fetchJob(run.job_id, abort.signal).then(job => setExecuting({ jobId: job.id, revisionId: job.revision_id })).catch(() => {});
    return () => abort.abort();
  }, [run?.job_id, run?.state, executing?.jobId]);

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
  const perform = useCallback(async (operation: (signal: AbortSignal) => Promise<DrawingDraft>, message: string | ((result: DrawingDraft) => string)) => {
    controller.current?.abort(); const version = ++ticket.current; const abort = new AbortController(); controller.current = abort;
    setBusy(true); setFeedback('');
    try { const result = await operation(abort.signal); if (ticket.current === version) { accept(result); say(`${result.title} · revision ${result.revision}. ${typeof message === 'string' ? message : message(result)}`); } }
    catch (error) { if (!abort.signal.aborted && ticket.current === version) say(error instanceof Error ? error.message : 'The drawing could not be updated.', 'error'); }
    finally { if (ticket.current === version) setBusy(false); }
  }, [accept, say]);

  const adjustment = useMemo(() => {
    if (!draft) return { dirty: false, key: '', error: '', payload: null };
    try { const payload = revisionPayload(draft, fields); const key = JSON.stringify(payload); return { payload, key: `${draft.revision_id}:${key}`, error: '', dirty: key !== JSON.stringify(revisionPayload(draft, fieldsFor(draft))) }; }
    catch (error) { return { dirty: true, key: '', payload: null, error: error instanceof Error ? error.message : 'Check drawing controls.' }; }
  }, [draft, fields]);
  useEffect(() => {
    if (!draft || !studio || busy || !adjustment.dirty) return;
    if (adjustment.error) { say(adjustment.error, 'error'); return; }
    if (!adjustment.payload || lastAttempt.current === adjustment.key) return;
    const timer = window.setTimeout(() => {
      lastAttempt.current = adjustment.key;
      void perform(signal => reviseDraft(draft.revision_id, adjustment.payload!, signal), 'Preview and G-code updated. Simulation only.');
    }, 450);
    return () => window.clearTimeout(timer);
  }, [draft, studio, busy, adjustment, perform, say]);

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
  const command = () => {
    if (!prompt.trim() || busy || !studio) return;
    setView('studio'); setZoom(100);
    // AI line art is fitted to the page like an imported image; offline shapes keep their own size.
    const page = paperSize(paper);
    const options: CommandOptions = { mode: activeRoute, detail, fit_width_mm: page ? page[0] * .85 : null, fit_height_mm: page ? page[1] * .85 : null };
    void perform(signal => submitCommand(prompt.trim(), signal, options), result => result.import_source?.ai
      ? `AI line art from ${result.import_source.ai.model}, traced on this computer. Review the preview before executing.`
      : 'Simulation only; machine profile unverified.');
  };
  const onSubmit = (event: FormEvent) => { event.preventDefault(); command(); };
  const draftCommand = (text: string) => { setView('studio'); setPrompt(text); setFeedback(''); input.current?.focus(); };
  // Spoken words are inserted at the cursor (replacing any selection) for review; they are never submitted automatically.
  const dictate = (text: string) => {
    const field = input.current; const current = field?.value ?? prompt;
    const start = field?.selectionStart ?? current.length; const end = field?.selectionEnd ?? current.length;
    const before = current.slice(0, start).trimEnd(); const after = current.slice(end).trimStart();
    const head = before ? `${before} ${text}` : text; const next = (after ? `${head} ${after}` : head).slice(0, 2000);
    setView('studio'); setPrompt(next);
    window.requestAnimationFrame(() => { const caret = Math.min(head.length, next.length); input.current?.focus(); input.current?.setSelectionRange(caret, caret); });
  };
  const newDrawing = () => { cancel(); setDraft(null); setFields(emptyEdits); draftCommand(''); };
  const regenerate = () => { if (draft && !busy && studio) void perform(signal => reviseDraft(draft.revision_id, { regenerate: true, seed_locked: seedLocked }, signal), seedLocked ? 'Seed retained.' : 'New deterministic seed.'); };
  const download = async (format: DownloadFormat) => {
    if (!draft || busy || adjustment.dirty || !studio) return;
    const version = ++ticket.current; const abort = new AbortController(); controller.current = abort; setBusy(true);
    try { const file = await downloadDraft(draft.revision_id, format, abort.signal); if (ticket.current !== version) return;
      const url = URL.createObjectURL(file.blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      say(`Downloaded ${file.filename}.`);
    } catch (error) { if (!abort.signal.aborted && ticket.current === version) say(error instanceof Error ? error.message : 'Download failed.', 'error'); }
    finally { if (ticket.current === version) setBusy(false); }
  };
  const selectedReference = studio?.profiles.profiles.find(profile => profile.id === referenceId);
  const selectedMeasured = studio?.profiles.measured_profiles?.find(profile => profile.id === studio.profiles.active_profile_id);
  const execution = useMemo((): Execution | null => {
    if (!run || !runActive(run)) return null;
    const acknowledged = run.acknowledged_seq ?? 0;
    const shown = draft && executing?.jobId === run.job_id && executing.revisionId === draft.revision_id;
    return { fraction: shown ? executedFraction(draft, acknowledged) : null, position: run.position_mm ?? null,
      percent: run.total_commands ? Math.round(acknowledged / run.total_commands * 100) : 0, stopping: run.state === 'stopping',
      stop: () => void controlMachine('stop').then(refreshMachine).catch(error => say(error.message, 'error')) };
  }, [run, draft, executing, refreshMachine, say]);
  const machineState = machine?.connection ?? studio?.status.machine.state;
  const executeBlocked = !draft ? 'Generate or open a drawing first' : !studio ? 'The local service is offline'
    : busy ? 'Wait for the drawing to update' : adjustment.dirty ? 'Wait for your adjustments to save' : '';
  const openSaved = (id: string) => { setView('studio'); void perform(signal => fetchDraft(id, signal), 'Opened from saved history with artifact checksums verified.'); };
  const refreshStudio = () => setRetry(value => value + 1);
  const reconnect = () => { setLoading(true); setRetry(value => value + 1); };

  const service = studio ? 'online' : loading ? 'pending' : 'offline';
  const save = !draft ? (busy ? ['pending', 'Drawing…'] : ['idle', 'Nothing saved yet'])
    : adjustment.error ? ['error', 'Check drawing values'] : busy || adjustment.dirty ? ['pending', 'Saving…']
    : !studio ? ['offline', 'Service offline'] : ['online', 'Saved locally'];
  const machineLabel = runActive(run) ? 'Machine drawing' : machineLabels[machineState ?? ''] ?? 'Machine not connected';
  const storage = studio?.status.storage.state === 'test_directory' ? 'Test directory selected' : studio?.status.storage.state === 'ready' ? 'SD target mounted'
    : studio?.status.storage.state === 'unmounted' ? 'SD target unavailable' : 'SD not configured';
  const hint = busy ? (activeRoute === 'ai' ? 'Generating AI line art, then tracing it locally…' : activeRoute === 'auto' && aiAvailable ? 'Building the drawing… AI requests take up to a minute' : 'Building the exported path…')
    : !studio ? (loading ? 'Connecting to local service…' : 'Local service offline')
    : activeRoute === 'offline' || !aiAvailable ? 'Offline engine · no API key needed' : activeRoute === 'ai' ? 'AI line art · sent to OpenAI' : 'Shapes offline · other requests via OpenAI';
  const help = (className: string) => <button className={`help-button ${className}`} aria-label="Open getting started guide" onClick={() => setDialog('guide')}><CircleHelp size={className === 'floating-help' ? 32 : 22} strokeWidth={1.5} /></button>;

  return <div className={`app-shell view-${view}`}><a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar">
      <div className="topbar-start"><Brand />
        <button className="service-status" onClick={() => setDialog('settings')} title={studio ? `Version ${studio.health.version} · on your computer` : 'No cloud connection required'}>
          <span className={`status-dot ${service}`} /><span className="status-label">{studio ? 'Running locally' : loading ? 'Connecting…' : 'Service offline'}</span><span className="sr-only">, studio information</span></button></div>
      <nav className="view-switch" aria-label="Main navigation">{views.map(([id, label]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}>{label}</button>)}</nav>
      <div className="topbar-actions">{help('topbar-help')}
        <button className="import-button" disabled={!studio || busy} onClick={() => setExtra('import')}><Upload size={19} /><span className="button-label">Import</span><span className="sr-only"> drawing</span></button>
        <ExportMenu blocked={executeBlocked} download={format => void download(format)} /></div>
    </header>

    <main id="workspace" className={`workspace ${grid ? 'show-grid' : ''}`}>
      {view !== 'studio' ? <div className="library"><HistoryPanel open={openSaved} /></div> : <>
        <section className="canvas-column" aria-label="Drawing canvas">
          <div className="document-bar">
            <div className="document-start"><DocumentMenu draft={draft} session={session} open={openSaved} newDrawing={newDrawing} browse={() => setView('gallery')} info={() => setDialog('settings')} />
              <span className="document-divider" aria-hidden="true" /><span className={`save-status ${save[0]}`} title={draft ? `Revision ${draft.revision} · stored in local history` : undefined}><span className={`status-dot ${save[0]}`} />{save[1]}</span></div>
            <label className="paper-pill"><span className="sr-only">Paper size</span><select value={paper} onChange={event => setPaper(event.target.value as PaperId)}>{paperOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select><ChevronDown size={16} /></label>
          </div>
          {!loading && !studio && <div className="connection-error" role="alert"><WifiOff size={19} /><div><strong>The local service is offline</strong><p>Keep the Picasso launcher running, then reconnect. Your command stays in the composer.</p></div><button className="subtle-button" onClick={reconnect}>Reconnect</button></div>}
          <DrawingPreview draft={draft} busy={busy} paper={paper} grid={grid} setGrid={setGrid} zoom={zoom} setZoom={setZoom} execute={() => setExecuteOpen(true)} executeBlocked={executeBlocked} execution={execution} geometry={selectedMeasured ?? selectedReference ?? null} />
          <section className="composer" aria-labelledby="composer-title">
            <div className="composer-head"><h2 id="composer-title">What would you like to draw?</h2><span id="command-hint" className={feedback ? 'sr-only' : `composer-hint ${service}`}>{hint}</span>
              <div className={`command-feedback ${tone}`} role="status" aria-live="polite">{feedback && <>{tone === 'error' ? <CircleAlert size={15} /> : <CircleCheck size={15} />}<span>{feedback}</span><button className="feedback-dismiss" aria-label="Dismiss message" onClick={() => setFeedback('')}><X size={13} /></button></>}</div></div>
            <form onSubmit={onSubmit} className="composer-form">
              <div className="composer-field"><label className="sr-only" htmlFor="drawing-command">Drawing command</label>
                <textarea ref={input} id="drawing-command" value={prompt} maxLength={2000} rows={1} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); command(); } }} placeholder={aiAvailable && activeRoute !== 'offline' ? 'Describe a shape, or anything else for AI line art…' : 'Describe a circle, butterfly, mandala, or geometric pattern…'} aria-describedby="command-hint" />
                <VoiceButton available={!!studio?.capabilities.voice.available} reason={studio ? studio.capabilities.voice.reason : 'The local service is offline.'} transcript={dictate} say={say} /></div>
              {busy && <button type="button" className="cancel-generation" onClick={() => { cancel(); say('Cancelled. The previous draft is retained.'); }}>Cancel</button>}
              <button className="submit-command" type="submit" aria-label="Submit drawing command" disabled={!prompt.trim() || !studio || busy}>{busy ? <span className="spinner" /> : <ArrowUp size={22} />}</button>
            </form>
            <div className="composer-footer">
              <div className="example-commands" role="group" aria-label="Example drawings">{examples.map(([label, text]) => <button key={label} title={text} onClick={() => draftCommand(text)}>{label}</button>)}</div>
              <div className="command-options">
                <div className="pill-segmented" role="radiogroup" aria-label="Command detail">{commandDetails.map(([value, label]) =>
                  <button key={value} type="button" role="radio" aria-checked={detail === value} disabled={busy} onClick={() => setDetail(value)}>{label}</button>)}</div>
                <label className="route-pill" title={aiAvailable ? routes.find(([value]) => value === activeRoute)?.[2] : studio?.capabilities.ai.reason}><span className="sr-only">Drawing engine</span>
                  <select value={activeRoute} disabled={busy} onChange={event => setRoute(event.target.value as Route)}>{routes.map(([value, label]) =>
                    <option key={value} value={value} disabled={value === 'ai' && !aiAvailable}>{value === 'auto' && !aiAvailable ? 'Auto · offline' : label}</option>)}</select><ChevronDown size={14} /></label>
              </div>
            </div>
          </section>
        </section>

        <aside className="side-column" aria-label="Drawing and machine inspector">
          <div className="inspector">
            <div className="inspector-tabs"><button className={inspector === 'drawing' ? 'active' : ''} aria-pressed={inspector === 'drawing'} onClick={() => setInspector('drawing')}><PenLine size={20} /> Drawing</button><button className={inspector === 'machine' ? 'active' : ''} aria-pressed={inspector === 'machine'} onClick={() => setInspector('machine')}><Settings size={20} /> Machine</button></div>
            {inspector === 'drawing' ? <DrawingInspector draft={draft} fields={fields} change={change} busy={busy} available={!!studio} dirty={adjustment.dirty} aspectLocked={aspectLocked} setAspectLocked={setAspectLocked} seedLocked={seedLocked} setSeedLocked={setSeedLocked} regenerate={regenerate} paper={paper} setPaper={setPaper} />
              : <div className="inspector-body machine-body"><h2 className="inspector-title">Your machine</h2>
                <MachinePanel machine={machine} refresh={refreshMachine} profile={selectedMeasured} />
                <p className="storage-line" title={studio?.status.storage.reason ?? 'SD export unavailable'}><HardDrive size={15} />{storage}</p>
                <div className="inspector-rule" /><div className="section-heading"><h3>Reference profiles</h3><span className="small-tag">READ ONLY</span></div><p className="muted-copy">Inspect bundled source values or record your actual measurements.</p><button className="outline-button" disabled={!studio} onClick={() => setExtra('calibration')}>Record / edit measurements</button>
                {!!studio?.profiles.measured_profiles?.length && <label className="reference-label">Profile for preparation<div className="select-field"><select aria-label="Measured profile for preparation" value={studio.profiles.active_profile_id ?? ''} onChange={event => { const profile = studio.profiles.measured_profiles?.find(item => item.id === event.target.value); if (profile) void selectCalibration(profile).then(refreshStudio).catch(error => say(error.message, 'error')); }}><option value="" disabled>Select a measured profile</option>{studio.profiles.measured_profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label} · {profile.verified ? 'verified by operator' : 'unverified'}</option>)}</select><ChevronDown size={16} /></div></label>}
                <label className="reference-label">Source reference<div className="select-field"><select value={referenceId} onChange={event => setReferenceId(event.target.value)} disabled={!studio} aria-label="Inspect reference profile"><option value="reference-350">Drawbot · 350 mm</option><option value="reference-400">SD copy · 400 mm</option></select><ChevronDown size={16} /></div></label>
                <div className="profile-badge"><ShieldCheck size={14} /> Unverified reference</div>
                <dl className="path-insights profile-details"><div><dt>Motor spacing</dt><dd>{selectedReference ? `${selectedReference.separation_mm} mm` : '—'}</dd></div><div><dt>Spool diameter</dt><dd>{selectedReference ? `${selectedReference.spool_diameter_mm} mm` : '—'}</dd></div><div><dt>Steps / turn</dt><dd>{selectedReference?.steps_per_turn ?? '—'}</dd></div><div><dt>Board</dt><dd>Unconfirmed</dd></div><div><dt>Allowed workspace</dt><dd>Not established</dd></div><div><dt>Firmware config</dt><dd>{studio?.profiles.firmware?.config_ids?.[referenceId] ?? '—'} · jog-only</dd></div></dl>
                <div className="notice profile-notice"><Cpu size={18} /><p>{selectedReference?.notes ?? 'Connect to inspect source references.'}</p></div><p className="insight-caption">Viewing a reference does not activate it or change firmware.</p></div>}
            <div className={`machine-status ${runActive(run) ? 'running' : machineState === 'connected' ? 'connected' : machineState === 'lost' || machineState === 'incompatible' ? 'warning' : ''}`} title={machine?.message ?? studio?.status.machine.reason ?? 'Machine control unavailable'}>
              <Printer size={30} strokeWidth={1.5} /><p><span>{machineLabel}</span>{execution && <small>{execution.percent}% of commands acknowledged</small>}</p>
              {inspector === 'drawing' && <button className="link-button" onClick={() => setInspector('machine')}>{machineState === 'connected' ? 'Manage' : 'Set up'} <ArrowRight size={16} /></button>}
            </div>
          </div>
          <p className="local-footer"><span className={`status-dot ${service}`} />{studio ? 'Local studio · Everything saved on this device' : loading ? 'Connecting to the local studio…' : 'Local service offline · changes are not saved'}</p>
        </aside>
      </>}
    </main>
    {help('floating-help')}
    {dialog && <Dialog kind={dialog} studio={studio} close={() => setDialog(null)} />}
    {extra === 'import' && <ImportDialog paper={paper} close={() => setExtra(null)} imported={result => { cancel(); accept(result); setView('studio'); setZoom(100); say(`Imported ${result.import_source?.filename ?? 'drawing'} · ${result.preview.strokes} ${result.preview.strokes === 1 ? 'path' : 'paths'}. Saved locally.`); setExtra(null); }} />}
    {extra === 'calibration' && studio && <CalibrationDialog profiles={studio.profiles} close={() => setExtra(null)} saved={() => { setExtra(null); refreshStudio(); say('Measured profile saved and selected for software preparation. No firmware changed.'); }} />}
    {executeOpen && draft && <ExecuteDialog draft={draft} profile={selectedMeasured} machine={machine} refresh={refreshMachine} executingJobId={executing?.jobId} close={() => setExecuteOpen(false)}
      calibrate={() => { setExecuteOpen(false); setInspector('machine'); setExtra('calibration'); }} started={job => setExecuting({ jobId: job.id, revisionId: job.revision_id })} />}
  </div>;
}
