import { useCallback, useEffect, useState } from 'react';
import { Pause, Play, Square } from 'lucide-react';
import { controlMachine, fetchMachine } from '../api/client';
import type { CalibrationProfile, MachineState, UsbRun } from '../api/contracts';

const active = new Set(['starting', 'streaming', 'pausing', 'paused', 'resuming', 'stopping']);
export const runActive = (run?: UsbRun | null) => !!run && active.has(run.state);

/** The controller's start preconditions, shown before the operator starts a run (it rechecks them). */
export function usbChecks(machine: MachineState | null, profile: CalibrationProfile | undefined, start: [number, number], connectHint = ''): [string, boolean][] {
  const status = machine?.status; const hello = machine?.hello;
  return [
    [`Connected to Picasso firmware${connectHint}`, machine?.connection === 'connected'],
    ['Verified profile records canonical firmware with the machine\'s configuration ID', !!hello && profile?.firmware === 'picasso-canonical' && profile.firmware_config_id === hello.config_id],
    ['Origin set on the machine\'s keypad', !!status && status.origin !== 'UNSET'],
    [`Machine idle at the job start (${start[0].toFixed(1)}, ${start[1].toFixed(1)})`, !!status && status.state === 'IDLE' && status.position_mm[0] === start[0] && status.position_mm[1] === start[1]],
  ];
}

/** Polls the local machine state; the service answers without waiting for the device. */
export function useMachine(enabled = true): [MachineState | null, () => Promise<void>] {
  const [machine, setMachine] = useState<MachineState | null>(null);
  const refresh = useCallback(async () => { try { setMachine(await fetchMachine()); } catch { setMachine(null); } }, []);
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    const poll = async () => { try { const state = await fetchMachine(abort.signal); if (!abort.signal.aborted) setMachine(state); } catch { if (!abort.signal.aborted) setMachine(null); } };
    void poll(); const timer = window.setInterval(poll, 1000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [enabled]);
  return [machine, refresh];
}

export function UsbRunCard({ run, refresh }: { run: UsbRun; refresh: () => Promise<void> }) {
  const [message, setMessage] = useState('');
  const act = (action: 'pause' | 'resume' | 'stop') => void controlMachine(action).then(refresh).then(() => setMessage('')).catch(error => setMessage(error.message));
  const acknowledged = run.acknowledged_seq ?? 0;
  const percent = run.total_commands ? Math.round(acknowledged / run.total_commands * 100) : 0;
  return <div className={`usb-run ${run.state}`} aria-label="USB run">
    <div className="usb-run-top"><strong>{run.title}</strong><span className="small-tag">{run.state.toUpperCase()}</span></div>
    <div className="usb-progress" role="progressbar" aria-label="Acknowledged commands" aria-valuemin={0} aria-valuemax={run.total_commands} aria-valuenow={acknowledged}><span style={{ width: `${percent}%` }} /></div>
    <p>{acknowledged} of {run.total_commands} commands acknowledged after motion · commanded position {run.position_mm ? `(${run.position_mm[0].toFixed(3)}, ${run.position_mm[1].toFixed(3)}) mm` : 'unknown'}</p>
    {run.current_line && runActive(run) && <p>Executing <code>{run.current_line}</code></p>}
    <p>{run.message}</p>
    {runActive(run) && <div className="usb-run-actions">
      {run.state === 'paused' ? <button className="subtle-button" onClick={() => act('resume')}><Play size={13} />Resume</button>
        : <button className="subtle-button" disabled={!['streaming', 'resuming'].includes(run.state)} onClick={() => act('pause')}><Pause size={13} />Pause</button>}
      <button className="subtle-button stop-button" disabled={run.state === 'stopping'} onClick={() => act('stop')}><Square size={13} />Stop</button></div>}
    {message && <p className="form-error" role="alert">{message}</p>}
    <p className="insight-caption">Progress counts acknowledgements from the firmware. There are no encoders: position is commanded, not measured.</p>
  </div>;
}
