import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { transcribeAudio, warmVoice } from '../api/client';

type Phase = 'idle' | 'listening' | 'transcribing';
type Props = { available: boolean; reason: string; transcript: (text: string) => void; say: (text: string, tone?: 'info' | 'error') => void };

const MAX_MS = 30000;      // matches the backend recording limit
const SILENCE_MS = 1300;   // a pause this long after speech ends the recording
const NO_SPEECH_MS = 8000;
const LOUD_RMS = 0.015;
const mimeTypes = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm'];

function microphoneError(error: unknown) {
  const name = error instanceof DOMException ? error.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Microphone access was blocked. Allow it in the browser’s site settings, or type the command.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found. Connect one, or type the command.';
  if (name === 'NotReadableError') return 'The microphone is in use by another application.';
  return 'The microphone could not be started. Type the command instead.';
}

/** Records one spoken command and hands the recognized words to the composer. It never submits them. */
export function VoiceButton({ available, reason, transcript, say }: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const button = useRef<HTMLButtonElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const discard = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const release = useRef<() => void>(() => {});
  const latest = useRef({ transcript, say });
  latest.current = { transcript, say };

  const stop = useCallback((keep: boolean) => {
    discard.current = !keep;
    if (recorder.current?.state === 'recording') recorder.current.stop();
  }, []);
  const cancel = useCallback(() => {
    if (phase === 'listening') { stop(false); latest.current.say('Voice input cancelled.'); }
    if (phase === 'transcribing') { abort.current?.abort(); setPhase('idle'); latest.current.say('Transcription cancelled.'); }
  }, [phase, stop]);

  useEffect(() => () => { stop(false); release.current(); abort.current?.abort(); }, [stop]);
  useEffect(() => {
    if (phase !== 'listening') return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); cancel(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase, cancel]);

  const send = async (audio: Blob) => {
    setPhase('transcribing'); latest.current.say('Transcribing on this computer…');
    const controller = new AbortController(); abort.current = controller;
    try {
      const result = await transcribeAudio(audio, controller.signal);
      if (controller.signal.aborted) return;
      latest.current.transcript(result.text);
      latest.current.say(`Heard “${result.text}”. Review or edit it, then press Enter to draw.`);
    } catch (error) {
      if (!controller.signal.aborted) latest.current.say(error instanceof Error ? error.message : 'Speech could not be transcribed.', 'error');
    } finally {
      if (abort.current === controller) { abort.current = null; setPhase('idle'); }
    }
  };

  const listen = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      say('This browser cannot record audio here. Type the command instead.', 'error'); return;
    }
    void warmVoice().catch(() => {});  // load the model while the operator speaks
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
    catch (error) { say(microphoneError(error), 'error'); return; }
    const mimeType = mimeTypes.find(type => MediaRecorder.isTypeSupported?.(type));
    const media = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    let heard = false;
    const timers: number[] = [];
    let context: AudioContext | null = null;
    release.current = () => { timers.forEach(id => window.clearTimeout(id)); stream.getTracks().forEach(track => track.stop()); void context?.close().catch(() => {}); button.current?.style.removeProperty('--level'); };
    media.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    media.onstop = () => {
      release.current(); recorder.current = null;
      if (discard.current) { setPhase('idle'); return; }
      // Even if the level meter heard nothing, Whisper's own voice detection decides.
      void send(new Blob(chunks, { type: media.mimeType || mimeType || 'audio/webm' }));
    };
    // End on a natural pause after speech (or after a long quiet start); without Web Audio, the second click or the time limit ends it.
    const started = Date.now();
    let lastLoud = started;
    if (typeof AudioContext !== 'undefined') {
      context = new AudioContext();
      const analyser = context.createAnalyser(); analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      timers.push(window.setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
        button.current?.style.setProperty('--level', Math.min(1, rms * 12).toFixed(2));
        const now = Date.now();
        if (rms > LOUD_RMS) { heard = true; lastLoud = now; }
        if ((heard && now - lastLoud > SILENCE_MS) || (!heard && now - started > NO_SPEECH_MS)) stop(true);
      }, 100));
    }
    timers.push(window.setTimeout(() => stop(true), MAX_MS));
    discard.current = false; recorder.current = media;
    media.start(250); setPhase('listening');
    say('Listening… say a command such as “Draw a butterfly”. Pausing ends the recording; Esc cancels.');
  };

  const click = () => { if (phase === 'idle') void listen(); else if (phase === 'listening') stop(true); else cancel(); };
  const label = !available ? `Voice input unavailable: ${reason}` : phase === 'listening' ? 'Stop recording and transcribe' : phase === 'transcribing' ? 'Cancel transcription' : 'Start voice input';
  return <span title={available ? undefined : reason}>
    <button ref={button} type="button" className={`microphone-button ${phase}`} disabled={!available} aria-label={label} title={available ? label : undefined} aria-pressed={phase === 'listening'} onClick={click}>
      {phase === 'transcribing' ? <span className="spinner" aria-hidden="true" /> : phase === 'listening' ? <Square size={14} fill="currentColor" /> : <Mic size={20} />}
    </button>
  </span>;
}
