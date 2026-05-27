import React, { useCallback, useEffect, useRef, useState } from "react";

interface SpeechRecognitionAlternative {
  transcript: string;
}
interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternative;
}
interface SpeechRecognitionResultList {
  readonly length: number;
  [index: number]: SpeechRecognitionResult;
}
interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}
interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message?: string;
}
interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((ev: SpeechRecognitionEvent) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function transcriptFromEvent(ev: SpeechRecognitionEvent): string {
  let text = "";
  for (let i = 0; i < ev.results.length; i++) {
    text += ev.results[i][0]?.transcript ?? "";
  }
  return text.trim();
}

async function ensureMicrophoneAccess(): Promise<string | null> {
  if (!navigator.mediaDevices?.getUserMedia) return null;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    return null;
  } catch {
    return "Microphone blocked. Click the lock icon in the address bar, allow Microphone, then try again.";
  }
}

export function SpeechInput(props: {
  label?: string;
  placeholder?: string;
  value: string;
  onChange: (text: string) => void;
  disabled?: boolean;
}) {
  const {
    label = "Speak your preference",
    placeholder = "Tap the mic and describe finishes or style…",
    value,
    onChange,
    disabled,
  } = props;

  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(true);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionInstance | null>(null);
  const baseTextRef = useRef("");
  const liveTranscriptRef = useRef("");

  useEffect(() => {
    const Ctor = getSpeechRecognition();
    const secure = typeof window !== "undefined" && window.isSecureContext;
    setSupported(Boolean(Ctor && secure));
    if (!secure && Ctor) {
      setSpeechError("Speech needs HTTPS or localhost. Open the app via http://localhost (not a file path).");
    }
    return () => {
      recRef.current?.abort();
      recRef.current = null;
    };
  }, []);

  const applyTranscript = useCallback(
    (spoken: string) => {
      const base = baseTextRef.current.trim();
      const next = base && spoken ? `${base} ${spoken}` : base || spoken;
      onChange(next);
    },
    [onChange],
  );

  const stopListening = useCallback(() => {
    try {
      recRef.current?.stop();
    } catch {
      /* ignore */
    }
    setListening(false);
  }, []);

  const startListening = useCallback(async () => {
    const Ctor = getSpeechRecognition();
    if (!Ctor || disabled) return;

    setSpeechError(null);
    const micErr = await ensureMicrophoneAccess();
    if (micErr) {
      setSpeechError(micErr);
      return;
    }

    baseTextRef.current = value;
    liveTranscriptRef.current = "";

    const rec = new Ctor();
    rec.lang = "en-IN";
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
    recRef.current = rec;

    rec.onstart = () => setListening(true);

    rec.onresult = (ev: SpeechRecognitionEvent) => {
      const session = transcriptFromEvent(ev);
      if (session) {
        liveTranscriptRef.current = session;
        applyTranscript(session);
      }
    };

    rec.onerror = (ev: SpeechRecognitionErrorEvent) => {
      const code = ev.error || "unknown";
      const messages: Record<string, string> = {
        "not-allowed": "Microphone permission denied. Allow mic access for this site.",
        aborted: "Speech input stopped.",
        "no-speech": "No speech detected. Try again, closer to the mic.",
        network: "Speech service network error. Check connection or type instead.",
        "service-not-allowed": "Speech recognition not allowed (try Chrome or Edge).",
      };
      setSpeechError(messages[code] ?? `Speech error: ${code}`);
      setListening(false);
    };

    rec.onend = () => {
      setListening(false);
      if (liveTranscriptRef.current) {
        applyTranscript(liveTranscriptRef.current);
      }
      recRef.current = null;
    };

    try {
      rec.start();
      setListening(true);
    } catch (e) {
      setSpeechError(e instanceof Error ? e.message : "Could not start speech recognition.");
      setListening(false);
    }
  }, [applyTranscript, disabled, value]);

  const toggleListen = useCallback(() => {
    if (listening) {
      stopListening();
    } else {
      void startListening();
    }
  }, [listening, startListening, stopListening]);

  return (
    <div className="speechBlock">
      {label ? <div className="smallTitle">{label}</div> : null}
      <div className="speechRow">
        <textarea
          className="input speechTextarea"
          rows={3}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        />
        <button
          type="button"
          className={`btn speechBtn ${listening ? "listening" : "secondary"}`}
          onClick={toggleListen}
          disabled={disabled || !supported}
          title={
            supported
              ? listening
                ? "Stop listening"
                : "Start speech input (uses microphone)"
              : "Speech not available"
          }
          aria-pressed={listening}
        >
          {listening ? "■ Stop" : "🎤 Speak"}
        </button>
      </div>
      {speechError ? (
        <p className="pill warn" style={{ marginTop: 8 }}>
          {speechError}
        </p>
      ) : null}
      {!supported && !speechError ? (
        <p className="muted" style={{ marginTop: 6 }}>
          Use Chrome or Edge on localhost/HTTPS. You can still type above.
        </p>
      ) : listening ? (
        <p className="muted" style={{ marginTop: 6 }}>
          Listening… speak clearly, then click Stop when finished.
        </p>
      ) : null}
    </div>
  );
}
