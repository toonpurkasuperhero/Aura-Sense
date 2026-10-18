// Records microphone audio and encodes it as 16 kHz mono 16-bit WAV in the browser,
// so the backend (and Gemma 4 native audio) always receives a format it can read.

export const canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.AudioContext);

export class WavRecorder {
  constructor(onLevel) { this.onLevel = onLevel; this.chunks = []; }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    this.ctx = new AudioContext();
    this.rate = this.ctx.sampleRate;
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
    this.proc.onaudioprocess = (e) => {
      const d = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(d));
      if (this.onLevel) {
        let s = 0; for (let i = 0; i < d.length; i += 16) s += d[i] * d[i];
        this.onLevel(Math.min(1, Math.sqrt(s / (d.length / 16)) * 4));
      }
    };
    src.connect(this.proc);
    this.proc.connect(this.ctx.destination);
    this.t0 = Date.now();
  }

  async stop() {
    this.proc.disconnect();
    this.stream.getTracks().forEach((t) => t.stop());
    await this.ctx.close();
    const len = this.chunks.reduce((a, c) => a + c.length, 0);
    const all = new Float32Array(len);
    let o = 0; for (const c of this.chunks) { all.set(c, o); o += c.length; }
    return encodeWav(downsample(all, this.rate, 16000), 16000);
  }

  elapsed() { return (Date.now() - this.t0) / 1000; }
}

function downsample(x, from, to) {
  if (from === to) return x;
  const ratio = from / to, n = Math.floor(x.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), b = Math.min(x.length, Math.floor((i + 1) * ratio));
    let s = 0; for (let j = a; j < b; j++) s += x[j];
    out[i] = s / Math.max(1, b - a);
  }
  return out;
}

function encodeWav(x, rate) {
  const buf = new ArrayBuffer(44 + x.length * 2), v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + x.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, x.length * 2, true);
  for (let i = 0; i < x.length; i++) { const s = Math.max(-1, Math.min(1, x[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
  return new Blob([buf], { type: "audio/wav" });
}
