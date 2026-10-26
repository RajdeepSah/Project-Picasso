import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUp, ChevronDown, CircleAlert, CircleCheck, CircleHelp, Cpu, HardDrive, Mic, PenLine, Printer, Settings, ShieldCheck, Upload, WifiOff, X } from 'lucide-react';
import { controlMachine, downloadDraft, fetchDraft, fetchJob, loadStudio, reviseDraft, selectCalibration, submitCommand, type Studio } from './api/client';
import type { DrawingDraft } from './api/contracts';
import { Brand } from './components/Brand';
import { HistoryPanel } from './components/HistoryPanel';
import { ImportDialog } from './components/ImportDialog';
import { CalibrationDialog } from './components/CalibrationDialog';
import { JobDialog } from './components/JobDialog';
import { MachinePanel } from './components/MachinePanel';
import { ExecuteDialog } from './components/ExecuteDialog';
import { DocumentMenu } from './components/DocumentMenu';
import { ExportMenu, type DownloadFormat } from './components/ExportMenu';
import { runActive, useMachine } from './components/UsbRunCard';
import { DrawingPreview, executedFraction, isPaper, paperOptions, type Execution, type PaperId } from './components/DrawingPreview';
import { DrawingInspector, emptyEdits, fieldsFor, revisionPayload, type Edits } from './components/DrawingInspector';

const examples = [['Mandala', 'Create a beautiful mandala'], ['Geometric', 'Draw a geometric pattern'], ['Butterfly', 'Draw a butterfly'], ['Circle', 'Draw a circle']];
const views = [['studio', 'Studio'], ['gallery', 'Gallery'], ['history', 'History']] as const;
const machineLabels: Record<string, string> = { connected: 'Machine connected', connecting: 'Machine connecting', lost: 'Machine connection lost', incompatible: 'Incompatible firmware' };

function storedPaper(): PaperId {
  try { const value = window.localStorage.getItem('picasso.paper'); return isPaper(value) ? value : 'A4-portrait'; } catch { return 'A4-portrait'; }
}

function Dialog({ kind, studio, close }: { kind: 'guide' | 'settings'; studio: Studio | null; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.showModal(); return () => previous?.focus(); }, []);
  return <dialog ref={ref} onCancel={close} aria-labelledby="dialog-title" className="studio-dialog">
    <div className="dialog-top"><span className="eyebrow">PROJECT PICASSO</span><button className="icon-button" onClick={close} aria-label="Close dialog"><X size={18} /></button></div>
    <h2 id="dialog-title">{kind === 'guide' ? 'From an idea to a line.' : 'Your local studio.'}</h2>
    {kind === 'guide' ? <><p>Generate or import a drawing, refine its paths, and reopen it from saved history.</p>
      <ol className="guide-steps"><li><span>01</span><div><strong>Describe one drawing</strong><p>Try a circle, ellipse, rectangle, spiral, butterfly, mandala or geometric pattern. Add “120 mm wide”, “12 petals”, “seed 7”, or “intricate”.</p></div></li>
        <li><span>02</span><div><strong>Make it your own</strong><p>Adjust size, detail and paper, or open Advanced for rotation, center and seed. Controls update the path automatically. Playback is a visual simulation, not machine timing.</p></div></li>
        <li><span>03</span><div><strong>Draw it or keep it</strong><p>Execute streams the drawing to the machine over USB once it is connected, a verified profile is selected and the origin is set on the keypad. Or export G-code, JSON or SVG; revisions save automatically.</p></div></li></ol>
      <div className="notice"><ShieldCheck size={18} /><p>Nothing is sent to the machine until you connect explicitly and start a run. Draft downloads cannot authorize physical drawing.</p></div>
    </> : <><p>Drawings are generated on your computer. No account, API key or network service is required.</p><dl className="settings-list">
      <div><dt>Application</dt><dd>{studio?.health.version ?? 'Service offline'}</dd></div><div><dt>Python</dt><dd>{studio?.health.python_version ?? 'Unavailable'}</dd></div>
      <div><dt>Current milestone</dt><dd>Phase 6 · Acknowledged USB control</dd></div><div><dt>Local SD mirror</dt><dd>SdCard/ · unchanged</dd></div><div><dt>Machine profile</dt><dd>Not selected or verified</dd></div></dl>
      <div className="notice"><Cpu size={18} /><p>Revisions are stored in local history. Back up the data folder with the app stopped to retain the database, artifacts, profiles and recovery copies together.</p></div></>}
    <button className="primary-button dialog-done" onClick={close}>Back to the studio <ArrowRight size={16} /></button>
  </dialog>;
}

export default function App() {
  const [studio, setStudio] = useState<Studio | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState<'studio' | 'gallery' | 'history'>('studio');
  const [inspector, setInspector] = useState<'drawing' | 'machine'>('drawing');
  const [referenceId, setReferenceId] = useState('reference-350');
  const [prompt, setPrompt] = useState('');
  const [feedback, setFeedback] = useState('');
  const [tone, setTone] = useState<'info' | 'error'>('info');
  const [busy, setBusy] = useState(false);
  const [grid, setGrid] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [paper, setPaperState] = useState<PaperId>(storedPaper);
  const [dialog, setDialog] = useState<'guide' | 'settings' | null>(null);
  const [extra, setExtra] = useState<'import' | 'calibration' | 'test-export' | 'physical-export' | null>(null);
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
  const setPaper = (value: PaperId) => { setPaperState(value); try { window.localStorage.setItem('picasso.paper', value); } catch { /* preference only */ } };
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
  const perform = useCallback(async (operation: (signal: AbortSignal) => Promise<DrawingDraft>, message: string) => {
    controller.current?.abort(); const version = ++ticket.current; const abort = new AbortController(); controller.current = abort;
    setBusy(true); setFeedback('');
    try { const result = await operation(abort.signal); if (ticket.current === version) { accept(result); say(`${result.title} · revision ${result.revision}. ${message}`); } }
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
  const command = () => { if (!prompt.trim() || busy || !studio) return; setView('studio'); setZoom(100); void perform(signal => submitCommand(prompt.trim(), signal), 'Simulation only; machine profile unverified.'); };
  const onSubmit = (event: FormEvent) => { event.preventDefault(); command(); };
  const draftCommand = (text: string) => { setView('studio'); setPrompt(text); setFeedback(''); input.current?.focus(); };
  const newDrawing = () => { cancel(); setDraft(null); setFields(emptyEdits); draftCommand(''); };
  const regenerate = () => { if (draft && !busy && studio) void perform(signal => reviseDraft(draft.revision_id, { regenerate: true, seed_locked: seedLocked }, signal), seedLocked ? 'Seed retained.' : 'New deterministic seed.'); };
  const download = async (format: DownloadFormat) => {
    if (!draft || busy || adjustment.dirty || !studio) return;
    const version = ++ticket.current; const abort = new AbortController(); controller.current = abort; setBusy(true);
    try { const file = await downloadDraft(draft.revision_id, format, abort.signal); if (ticket.current !== version) return;
      const url = URL.createObjectURL(file.blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      say(`Downloaded ${format === 'gcode' ? 'unverified G-code' : format.toUpperCase()} draft. No hardware operation was performed.`);
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
  const hint = busy ? 'Building the exported path…' : studio ? 'Offline engine · no API key needed' : loading ? 'Connecting to local service…' : 'Local service offline';
  const help = (className: string) => <button className={`help-button ${className}`} aria-label="Open getting started guide" onClick={() => setDialog('guide')}><CircleHelp size={className === 'floating-help' ? 32 : 22} strokeWidth={1.5} /></button>;

  return <div className={`app-shell view-${view}`}><a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar">
      <div className="topbar-start"><Brand />
        <button className="service-status" onClick={() => setDialog('settings')} title={studio ? `Version ${studio.health.version} · on your computer` : 'No cloud connection required'}>
          <span className={`status-dot ${service}`} /><span className="status-label">{studio ? 'Running locally' : loading ? 'Connecting…' : 'Service offline'}</span><span className="sr-only">, studio information</span></button></div>
      <nav className="view-switch" aria-label="Main navigation">{views.map(([id, label]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}>{label}</button>)}</nav>
      <div className="topbar-actions">{help('topbar-help')}
        <button className="import-button" disabled={!studio || busy} onClick={() => setExtra('import')}><Upload size={19} /><span className="button-label">Import</span><span className="sr-only"> drawing</span></button>
        <ExportMenu blocked={executeBlocked} download={format => void download(format)} physicalReady={!!selectedMeasured?.verified} testExport={() => setExtra('test-export')} prepare={() => setExtra('physical-export')} /></div>
    </header>

    <main id="workspace" className={`workspace ${grid ? 'show-grid' : ''}`}>
      {view !== 'studio' ? <div className="library"><HistoryPanel key={view} layout={view} open={openSaved} /></div> : <>
        <section className="canvas-column" aria-label="Drawing canvas">
          <div className="document-bar">
            <div className="document-start"><DocumentMenu draft={draft} session={session} open={openSaved} newDrawing={newDrawing} browse={() => setView('history')} info={() => setDialog('settings')} />
              <span className="document-divider" aria-hidden="true" /><span className={`save-status ${save[0]}`} title={draft ? `Revision ${draft.revision} · stored in local history` : undefined}><span className={`status-dot ${save[0]}`} />{save[1]}</span></div>
            <label className="paper-pill"><span className="sr-only">Paper size</span><select value={paper} onChange={event => setPaper(event.target.value as PaperId)}>{paperOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select><ChevronDown size={16} /></label>
          </div>
          {!loading && !studio && <div className="connection-error" role="alert"><WifiOff size={19} /><div><strong>The local service is offline</strong><p>Keep the Picasso launcher running, then reconnect. Your command stays in the composer.</p></div><button className="subtle-button" onClick={reconnect}>Reconnect</button></div>}
          <DrawingPreview draft={draft} busy={busy} paper={paper} grid={grid} setGrid={setGrid} zoom={zoom} setZoom={setZoom} execute={() => setExecuteOpen(true)} executeBlocked={executeBlocked} execution={execution} />
          <section className="composer" aria-labelledby="composer-title">
            <div className="composer-head"><h2 id="composer-title">What would you like to draw?</h2><span id="command-hint" className={feedback ? 'sr-only' : `composer-hint ${service}`}>{hint}</span>
              <div className={`command-feedback ${tone}`} role="status" aria-live="polite">{feedback && <>{tone === 'error' ? <CircleAlert size={15} /> : <CircleCheck size={15} />}<span>{feedback}</span><button className="feedback-dismiss" aria-label="Dismiss message" onClick={() => setFeedback('')}><X size={13} /></button></>}</div></div>
            <form onSubmit={onSubmit} className="composer-form">
              <div className="composer-field"><label className="sr-only" htmlFor="drawing-command">Drawing command</label>
                <textarea ref={input} id="drawing-command" value={prompt} maxLength={2000} rows={1} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); command(); } }} placeholder="Describe a circle, butterfly, mandala, or geometric pattern…" aria-describedby="command-hint" />
                <span title="Voice input arrives in Phase 8"><button type="button" disabled className="microphone-button" aria-label="Voice input unavailable until Phase 8"><Mic size={20} /></button></span></div>
              {busy && <button type="button" className="cancel-generation" onClick={() => { cancel(); say('Cancelled. The previous draft is retained.'); }}>Cancel</button>}
              <button className="submit-command" type="submit" aria-label="Submit drawing command" disabled={!prompt.trim() || !studio || busy}>{busy ? <span className="spinner" /> : <ArrowUp size={22} />}</button>
            </form>
            <div className="example-commands" role="group" aria-label="Example drawings">{examples.map(([label, text]) => <button key={label} title={text} onClick={() => draftCommand(text)}>{label}</button>)}</div>
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
    {extra === 'import' && <ImportDialog close={() => setExtra(null)} imported={result => { cancel(); accept(result); setView('studio'); say('Imported and saved a new revision. Review its origin, fit and normalized paths.'); setExtra(null); }} />}
    {extra === 'calibration' && studio && <CalibrationDialog profiles={studio.profiles} close={() => setExtra(null)} saved={() => { setExtra(null); refreshStudio(); say('Measured profile saved and selected for software preparation. No firmware changed.'); }} />}
    {executeOpen && draft && <ExecuteDialog draft={draft} profile={selectedMeasured} machine={machine} refresh={refreshMachine} executingJobId={executing?.jobId} close={() => setExecuteOpen(false)}
      calibrate={() => { setExecuteOpen(false); setInspector('machine'); setExtra('calibration'); }} started={job => setExecuting({ jobId: job.id, revisionId: job.revision_id })} />}
    {(extra === 'test-export' || extra === 'physical-export') && draft && <JobDialog draft={draft} mode={extra === 'test-export' ? 'simulation' : 'physical'} profile={selectedMeasured} close={() => setExtra(null)} updated={refreshStudio} />}
  </div>;
}
