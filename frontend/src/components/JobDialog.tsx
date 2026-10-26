import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, FileDown, FlaskConical, RefreshCw, ShieldCheck, Usb, X } from 'lucide-react';
import { armAutoSync, createTestTarget, exportJob, fetchJobs, fetchTargets, fetchTransfers, prepareJob, selectTarget, stageJob, startUsbRun } from '../api/client';
import { HomeControl } from './MachinePanel';
import { UsbRunCard, runActive, useMachine } from './UsbRunCard';
import type { CalibrationProfile, DrawingDraft, ExportRequest, PreparedJob, TargetsResponse, TransferRecord } from '../api/contracts';

function UsbStep({ job, profile }: { job: PreparedJob | null; profile?: CalibrationProfile }) {
  const [machine, refresh] = useMachine(true);
  const [clear, setClear] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const status = machine?.status; const hello = machine?.hello;
  const start = job?.expected_start_mm ?? [0, 0];
  const checks: [string, boolean][] = [
    ['Connected to Picasso firmware (Machine tab)', machine?.connection === 'connected'],
    ['Verified profile records canonical firmware with the machine\'s configuration ID', !!hello && profile?.firmware === 'picasso-canonical' && profile.firmware_config_id === hello.config_id],
    ['Origin set on the machine\'s keypad', !!status && status.origin !== 'UNSET'],
    [`Machine idle at the job start (${start[0].toFixed(1)}, ${start[1].toFixed(1)})`, !!status && status.state === 'IDLE' && status.position_mm[0] === start[0] && status.position_mm[1] === start[1]],
  ];
  const ready = !!job && checks.every(([, ok]) => ok) && clear && !runActive(machine?.run);
  const begin = async () => {
    if (!job || !status || !hello) return;
    setBusy(true); setMessage('');
    try { await startUsbRun(job.id, { expected_boot_id: status.boot_id, expected_origin_revision: status.origin_revision, expected_config_id: hello.config_id, area_clear_confirmed: true }); setClear(false); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'The run could not start.'); }
    finally { setBusy(false); }
  };
  return <div className="workflow-step"><h3>4. Or draw over USB</h3>
    <p>Streams this frozen job one acknowledged command at a time. Nothing moves until you start, and the keypad's ESC always stops the machine.</p>
    <ul className="usb-checks">{checks.map(([label, ok]) => <li key={label} className={ok ? 'ok' : ''}>{ok ? <Check size={13} /> : <X size={13} />}{label}</li>)}</ul>
    {machine && <HomeControl machine={machine} refresh={refresh} />}
    <label className="checkbox-control"><input type="checkbox" checked={clear} onChange={event => setClear(event.target.checked)} />The drawing area is clear and I am watching the machine.</label>
    <button className="primary-button dialog-done" disabled={!ready || busy} onClick={() => void begin()}><Usb size={16} />{busy ? 'Binding the job…' : 'Start USB drawing'}</button>
    {message && <p className="form-error" role="alert">{message}</p>}
    {machine?.run && machine.run.job_id === job?.id && <UsbRunCard run={machine.run} refresh={refresh} />}
  </div>;
}

export function JobDialog({ draft, mode, profile, close, updated }: {
  draft: DrawingDraft; mode: 'physical' | 'simulation'; profile?: CalibrationProfile; close: () => void; updated: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [job, setJob] = useState<PreparedJob | null>(null);
  const [previous, setPrevious] = useState<PreparedJob[]>([]);
  const [targets, setTargets] = useState<TargetsResponse | null>(null);
  const [record, setRecord] = useState<TransferRecord | null>(null);
  const [logs, setLogs] = useState<TransferRecord[]>([]);
  const [replace, setReplace] = useState(false); const [owns, setOwns] = useState(false); const [origin, setOrigin] = useState(false);
  const [mirror, setMirror] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const [pendingAutoSync, setPendingAutoSync] = useState<boolean | null>(null);
  const reviewedHash = useRef('');
  const refresh = useCallback(async () => {
    const result = await fetchTargets();
    const selected = result.targets.find(item => item.id === result.selected_target_id);
    const signature = `${selected?.id}:${selected?.current_main_sha256}:${result.local_mirror_sha256}`;
    if (reviewedHash.current !== signature) { setReplace(false); reviewedHash.current = signature; }
    setTargets(result); setLogs(await fetchTransfers());
  }, []);
  useEffect(() => { ref.current?.showModal(); void refresh().catch(error => setMessage(error.message));
    const abort = new AbortController(); fetchJobs(draft.revision_id, abort.signal).then(jobs => setPrevious(jobs.filter(item => item.mode === mode))).catch(() => {});
    return () => abort.abort();
  }, [draft.revision_id, mode, refresh]);
  useEffect(() => { if (!targets?.auto_sync.enabled) return; const timer = window.setInterval(() => void refresh().catch(error => setMessage(error.message)), 2000); return () => window.clearInterval(timer); }, [targets?.auto_sync.enabled, refresh]);
  const target = targets?.targets.find(item => item.id === targets.selected_target_id);
  const eligibleTargets = targets?.targets.filter(item => mode === 'simulation' ? item.kind === 'test_directory' : item.kind === 'physical_card') ?? [];
  const currentTarget = eligibleTargets.find(item => item.id === target?.id);
  const run = async (operation: () => Promise<void>) => { setBusy(true); setMessage(''); try { await operation(); updated(); } catch (error) { setMessage(error instanceof Error ? error.message : 'Operation failed.'); } finally { setBusy(false); } };
  const request = (): ExportRequest => {
    if (!job || !currentTarget) throw new Error('Prepare a job and select its target first.');
    return { target_id: currentTarget.id, expected_job_sha256: job.gcode_sha256, expected_existing_sha256: currentTarget.current_main_sha256,
      expected_local_mirror_sha256: targets?.local_mirror_sha256, acknowledge_replace: replace, computer_owns_card: owns,
      manual_start_understood: origin, stage_local_mirror: mirror };
  };
  return <dialog ref={ref} onCancel={close} className="studio-dialog wide-dialog export-dialog" aria-labelledby="job-title"><div className="dialog-top"><span className="eyebrow">{mode === 'simulation' ? 'ISOLATED TEST EXPORT' : 'PREPARE & EXPORT'}</span><button className="icon-button" onClick={close} aria-label="Close export"><X size={18} /></button></div><h2 id="job-title">{mode === 'simulation' ? 'Try a verified test copy' : 'Prepare for the SD workflow'}</h2>
    <p>{mode === 'simulation' ? 'This copies a simulation job only into the app-owned data/test-card folder. It cannot update a physical card or SdCard/main.nc.' : 'Freeze this revision against your operator-recorded profile, verify a copy, then start it manually from the machine.'}</p>
    <div className="notice"><ShieldCheck size={18} /><p>{mode === 'physical' ? `Profile: ${profile?.label ?? 'None'} · ${profile?.verified ? 'operator-recorded verification' : 'unverified'}. Every path and rope constraint, including initial travel, is checked.` : 'Computational validation only. This workflow is not a physical-card test or a machine calibration.'}</p></div>
    <div className="workflow-step"><h3>1. Freeze the drawing revision</h3><p>{draft.title} · revision {draft.revision} · G-code {draft.gcode_sha256.slice(0, 12)}</p><button className="outline-button" disabled={busy || (mode === 'physical' && !profile?.verified)} onClick={() => void run(async () => { setJob(await prepareJob(draft.revision_id, mode, profile)); setRecord(null); setMessage('Prepared locally. No file was copied and no machine was started.'); })}><FileDown size={15} />{job ? 'Prepare a fresh job' : mode === 'simulation' ? 'Prepare simulation job' : 'Prepare physical job'}</button>
      {!job && previous.length > 0 && <button className="subtle-button" disabled={busy} onClick={() => { setJob(previous[0]); setMessage('Restored an immutable prepared job. Export will recheck the current profile.'); }}>Restore last preparation</button>}
      {job && <p className="job-ready"><Check size={14} />Prepared job {job.id.slice(0, 8)} · manual origin required before each SD drawing</p>}
      {job?.gcode_crc32 && <p className="muted-copy machine-check">Machine check: canonical firmware shows <code>CRC {job.gcode_crc32}</code> after validating main.nc. Start only if it matches.</p>}
    </div>
    <div className="workflow-step"><h3>2. Choose the destination</h3><div className="target-actions"><button className="subtle-button" disabled={busy} onClick={() => void run(refresh)}><RefreshCw size={14} />Refresh targets</button>{mode === 'simulation' && <button className="subtle-button" disabled={busy} onClick={() => void run(async () => { await createTestTarget(); await refresh(); })}><FlaskConical size={14} />Create test directory</button>}</div>
      <label className="form-field">Selected target<select aria-label="Export target" value={currentTarget?.id ?? ''} disabled={busy} onChange={event => void run(async () => { await selectTarget(event.target.value); await refresh(); })}><option value="">Select a destination</option>{eligibleTargets.map(item => <option key={item.id} value={item.id} disabled={!item.available || !item.writable}>{item.label} · {item.available ? item.filesystem : 'unmounted'}</option>)}</select></label>
      {currentTarget ? <div className="target-summary"><strong>{currentTarget.kind === 'test_directory' ? 'Test directory — no physical card' : 'Mounted physical card'}</strong><code>{currentTarget.path}</code><p>{currentTarget.reason}</p><p>Current main.nc: {currentTarget.current_main_sha256?.slice(0, 16) ?? 'not present'}</p></div> : <p className="muted-copy">{mode === 'simulation' ? 'Create/select the isolated directory to test file verification.' : 'No physical card is selected. Mount a FAT16/FAT32 removable card in the computer and refresh. Arduino USB does not expose its SPI card.'}</p>}
      {targets?.discovery_error && <p className="muted-copy">{targets.discovery_error}</p>}
    </div>
    <div className="workflow-step"><h3>3. Review and copy</h3><label className="checkbox-control"><input type="checkbox" checked={replace} onChange={event => setReplace(event.target.checked)} />Back up and replace the reviewed main.nc with this frozen job.</label>
      {mode === 'physical' && <><label className="checkbox-control"><input type="checkbox" checked={owns} onChange={event => setOwns(event.target.checked)} />The computer exclusively owns the card while copying.</label><label className="checkbox-control"><input type="checkbox" checked={origin} onChange={event => setOrigin(event.target.checked)} />I understand the manual origin procedure before every SD-menu start.</label><label className="checkbox-control"><input type="checkbox" checked={mirror} onChange={event => setMirror(event.target.checked)} />Also back up and update the local SdCard/main.nc mirror.</label></>}
      <button className="primary-button dialog-done" disabled={busy || !job || !currentTarget?.available || !currentTarget.writable || !replace || (mode === 'physical' && (!owns || !origin))} onClick={() => void run(async () => { const result = await exportJob(job!.id, request()); setRecord(result); setMessage(result.message); await refresh(); })}>{busy ? 'Working…' : mode === 'simulation' ? 'Export to test directory' : 'Export selected job to card'}</button>
      {mode === 'physical' && <button className="outline-button local-stage" disabled={busy || !job || !replace} onClick={() => void run(async () => { const result = await stageJob(job!.id, { expected_existing_sha256: targets?.local_mirror_sha256, acknowledge_replace: replace }); setRecord(result); setMessage(result.message); await refresh(); })}>Stage local SD mirror only</button>}
      <label className="checkbox-control auto-sync-control"><input type="checkbox" aria-label="Automatically sync this frozen job" checked={pendingAutoSync ?? targets?.auto_sync.enabled ?? false} disabled={busy || (!targets?.auto_sync.enabled && (!job || !currentTarget || !replace || (mode === 'physical' && (!owns || !origin))))} onChange={event => { const enabled = event.target.checked; setPendingAutoSync(enabled); void run(async () => { try { const state = await armAutoSync(enabled ? { enabled, job_id: job!.id, export: request() } : { enabled }); setMessage(state.message ?? 'Automatic export settings updated.'); await refresh(); } finally { setPendingAutoSync(null); } }); }} />Automatically copy this exact job when this target is accessible (including now).</label>
      {targets?.auto_sync.enabled && <p className="job-ready">Auto-sync: {targets.auto_sync.status}. {targets.auto_sync.message}</p>}
    </div>
    {mode === 'physical' && <UsbStep job={job} profile={profile} />}
    {message && <p className="export-message" role="status">{message}</p>}{record?.status === 'verified' && <div className="verified-transfer"><Check size={18} /><div><strong>{record.target_kind === 'test_directory' ? 'Test copy verified' : 'File copy verified'}</strong><p>{record.bytes_verified} bytes · SHA-256 {record.gcode_sha256.slice(0, 16)}</p>{record.backup && <p>Previous main.nc preserved in {record.backup}.</p>}</div></div>}
    {logs.length > 0 && <details className="transfer-log"><summary>Recent transfer records</summary>{logs.slice(0, 6).map(log => <p key={log.id}>{log.target_kind} · {log.status} · {log.message}</p>)}</details>}
    <p className="insight-caption">File readback does not guarantee power-loss atomicity or hardware execution. Close file handles and use the operating system's safe eject before moving a physical card.</p>
  </dialog>;
}
