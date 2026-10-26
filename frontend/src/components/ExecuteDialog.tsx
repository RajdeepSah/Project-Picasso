import { useEffect, useRef, useState } from 'react';
import { Check, Ruler, ShieldCheck, Usb, X } from 'lucide-react';
import { prepareJob, startUsbRun } from '../api/client';
import type { CalibrationProfile, DrawingDraft, MachineState, PreparedJob } from '../api/contracts';
import { HomeControl, PortPicker } from './MachinePanel';
import { UsbRunCard, runActive, usbChecks } from './UsbRunCard';

/** One place to draw the current revision over USB: connect, check, confirm, start, watch. */
export function ExecuteDialog({ draft, profile, machine, refresh, executingJobId, close, calibrate, started }: {
  draft: DrawingDraft; profile?: CalibrationProfile; machine: MachineState | null; refresh: () => Promise<void>;
  executingJobId?: string; close: () => void; calibrate: () => void; started: (job: PreparedJob) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [job, setJob] = useState<PreparedJob | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [clear, setClear] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  useEffect(() => { ref.current?.showModal(); }, []);
  const verified = !!profile?.verified;
  // The profile object is refreshed by polling; prepare again only when its identity changes.
  const profileKey = verified ? `${profile!.id}:${profile!.revision}` : '';
  useEffect(() => {
    if (!profileKey) return;
    let current = true;
    setJob(null); setPreparing(true); setMessage('');
    prepareJob(draft.revision_id, 'physical', profile).then(result => { if (current) setJob(result); })
      .catch(error => { if (current) setMessage(error instanceof Error ? error.message : 'The drawing could not be prepared for this machine.'); })
      .finally(() => { if (current) setPreparing(false); });
    return () => { current = false; };
  }, [draft.revision_id, profileKey]);
  const status = machine?.status; const hello = machine?.hello;
  const connected = machine?.connection === 'connected';
  const run = machine?.run;
  const ownRun = run && (run.job_id === job?.id || run.job_id === executingJobId) ? run : null;
  const active = runActive(run);
  const checks = usbChecks(machine, profile, job?.expected_start_mm ?? [0, 0]);
  const ready = !!job && verified && checks.every(([, ok]) => ok) && clear && !active;
  const begin = async () => {
    if (!job || !status || !hello) return;
    setBusy(true); setMessage('');
    try {
      await startUsbRun(job.id, { expected_boot_id: status.boot_id, expected_origin_revision: status.origin_revision, expected_config_id: hello.config_id, area_clear_confirmed: true });
      setClear(false); started(job); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'The run could not start.'); }
    finally { setBusy(false); }
  };
  return <dialog ref={ref} onCancel={close} className="studio-dialog wide-dialog execute-dialog" aria-labelledby="execute-title"><div className="dialog-top"><span className="eyebrow">EXECUTE OVER USB</span><button className="icon-button" onClick={close} aria-label="Close execute"><X size={18} /></button></div>
    <h2 id="execute-title">Draw it on the machine</h2>
    <p>Streams {draft.title} · revision {draft.revision} to the Arduino one acknowledged command at a time. The SD card stays in the machine; nothing is copied to it. Nothing moves until you start, and the keypad's ESC always stops.</p>
    {active && !ownRun && run ? <UsbRunCard run={run} refresh={refresh} /> : <>
      <div className="workflow-step"><h3>1. Connect the machine</h3>
        {connected ? <p className="job-ready"><Check size={14} />Picasso firmware {hello?.firmware_version} · configuration {hello?.config_id} · boot {status?.boot_id}{machine?.simulated && machine.port?.startsWith('sim://') ? ' · simulated' : ''}</p>
          : <PortPicker refresh={refresh} />}
      </div>
      <div className="workflow-step"><h3>2. Machine profile</h3>
        {verified ? <p className="job-ready"><Check size={14} />{profile!.label} · verified by operator · {profile!.firmware === 'picasso-canonical' ? `canonical firmware ${profile!.firmware_config_id}` : 'legacy sketch (cannot stream)'}</p>
          : <><p className="muted-copy">USB drawing needs a verified measured profile that records the canonical firmware's configuration ID. Record your measurements, upload the generated firmware, then verify the profile.</p>
            <button className="outline-button" onClick={calibrate}><Ruler size={15} />Record measurements</button></>}
      </div>
      <div className="workflow-step"><h3>3. Check the drawing</h3>
        {!verified ? <p className="muted-copy">Checked against the verified profile's workspace and rope limits once one is selected.</p>
          : preparing ? <p className="muted-copy">Checking every path and rope constraint…</p>
          : job ? <p className="job-ready"><Check size={14} />Prepared job {job.id.slice(0, 8)} · {job.preview.strokes} stroke{job.preview.strokes === 1 ? '' : 's'} · fits the recorded workspace</p>
          : <p className="form-error" role="alert">{message}</p>}
      </div>
      <div className="workflow-step"><h3>4. Start</h3>
        <ul className="usb-checks">{checks.map(([label, ok]) => <li key={label} className={ok ? 'ok' : ''}>{ok ? <Check size={13} /> : <X size={13} />}{label}</li>)}</ul>
        {connected && status?.origin === 'UNSET' && <p className="muted-copy">On the keypad choose Setup → Set origin with the pen at the origin. Opening the port resets the UNO, so this is needed after every connect.</p>}
        {machine && <HomeControl machine={machine} refresh={refresh} />}
        <label className="checkbox-control"><input type="checkbox" checked={clear} disabled={active} onChange={event => setClear(event.target.checked)} />The drawing area is clear and I am watching the machine.</label>
        <button className="primary-button dialog-done" disabled={!ready || busy} onClick={() => void begin()}><Usb size={16} />{busy ? 'Binding the job…' : 'Start drawing'}</button>
        {message && job && <p className="form-error" role="alert">{message}</p>}
      </div>
      {ownRun ? <UsbRunCard run={ownRun} refresh={refresh} />
        : <div className="notice"><ShieldCheck size={18} /><p>Progress will count acknowledgements from the firmware after each motion and pen change. There are no encoders: the position is commanded, not measured.</p></div>}
    </>}
  </dialog>;
}
