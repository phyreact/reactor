#!/usr/bin/env python3
"""Live microphone scope for the XIAO ReSpeaker Audio card, served as a web page.

Runs ON the ZERO, stdlib only.  Captures 16 kHz / stereo / S16_LE from ALSA via
`arecord`, keeps the last few seconds in RAM, and streams downsampled waveform
columns + levels to the browser over Server-Sent Events.  The page draws two
oscilloscope traces (L = ASR beam, R = comms beam), dBFS meters with peak hold,
a 1024-point spectrum of L, and polls the XIAO's CDC status.

    python3 micscope.py [--port 8778] [--device hw:1,0]
    then open http://127.0.0.1:8778/

Camera: the IMX219 behind the rkisp ISP is shown as information plus an
on-demand snapshot (one-shot GStreamer pipeline, hardware JPEG); no continuous
stream, and the disabled radxa-camera-preview.service is left alone.

Endpoints: /  /stream (SSE)  /status (XIAO CDC status JSON)  /wav?sec=5 (last N s as WAV)
           /camera (camera info JSON)  /snapshot.jpg (fresh frame, ~1.5 s)
"""
import argparse, collections, glob, io, json, math, os, shutil, struct, subprocess, sys, tempfile, termios, threading, time, tty, wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RATE, CH = 16000, 2
CHUNK_FRAMES = 160                    # 10 ms per read
HISTORY_SEC = 12
TICK_MS = 50                          # SSE frame period
COLS_PER_TICK = 20                    # waveform columns per tick (2.5 ms each)


class Capture(threading.Thread):
    def __init__(self, device, capture_cmd=None):
        super().__init__(daemon=True)
        self.device = device
        # Any command that writes raw S16LE stereo 16 kHz to stdout works here
        # (e.g. sim/twin/sim_arecord.py against the software twin).
        self.capture_cmd = capture_cmd
        self.lock = threading.Lock()
        self.hist = collections.deque(maxlen=RATE * HISTORY_SEC)   # (l, r) tuples
        self.total = 0
        self.state = "starting"
        self.restarts = 0

    def run(self):
        while True:
            cmd = self.capture_cmd or ["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", str(CH), "-t", "raw", "-"]
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as e:
                self.state = "arecord missing: %s" % e; time.sleep(2); continue
            self.state = "running"
            fmt = "<%dh" % (CHUNK_FRAMES * CH)
            n = CHUNK_FRAMES * CH * 2
            while True:
                buf = p.stdout.read(n)
                if len(buf) < n:
                    break
                s = struct.unpack(fmt, buf)
                with self.lock:
                    self.hist.extend(zip(s[0::2], s[1::2]))
                    self.total += CHUNK_FRAMES
            err = p.stderr.read().decode(errors="replace").strip()
            p.wait()
            self.restarts += 1
            self.state = "restarting (%s)" % (err.splitlines()[-1] if err else "arecord exited %d" % p.returncode)
            time.sleep(1)

    def recent(self, frames):
        with self.lock:
            if len(self.hist) < frames:
                return list(self.hist), self.total
            return list(self.hist)[-frames:], self.total


def dbfs(x):
    return 20 * math.log10(max(x, 1e-6) / 32768.0)


def columns(vals, ncols):
    """(min, max) per column over equal slices of vals."""
    out = []
    step = max(1, len(vals) // ncols)
    for i in range(0, step * ncols, step):
        seg = vals[i:i + step]
        if not seg:
            break
        out.append((min(seg), max(seg)))
    return out


def tick_frame(cap, last_total):
    """One SSE payload covering the frames captured since last_total."""
    want = RATE * TICK_MS // 1000
    data, total = cap.recent(want)
    if not data:
        return None, last_total
    L = [d[0] for d in data]; R = [d[1] for d in data]
    rmsL = math.sqrt(sum(v * v for v in L) / len(L)); rmsR = math.sqrt(sum(v * v for v in R) / len(R))
    payload = {
        "t": time.time(), "total": total, "state": cap.state, "restarts": cap.restarts,
        "l": columns(L, COLS_PER_TICK), "r": columns(R, COLS_PER_TICK),
        "rmsL": round(dbfs(rmsL), 1), "rmsR": round(dbfs(rmsR), 1),
        "peakL": round(dbfs(max(abs(v) for v in L)), 1), "peakR": round(dbfs(max(abs(v) for v in R)), 1),
        "specL": L[-1024:] if len(L) >= 1024 else None,
    }
    return payload, total


cdc_lock = threading.Lock()


def cdc_status():
    # Prefer the bridge daemon's socket (it owns the serial port); fall back to the raw port.
    sock_path = os.path.join(os.environ.get("XIAO_TOOLS_DIR", os.path.expanduser("~/xiao-tools")), "cdc.sock")
    if os.path.exists(sock_path):
        import socket
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0); s.connect(sock_path); s.sendall(b"status\n")
                buf = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk: break
                    buf += chunk
            return json.loads(buf.decode(errors="replace").strip().splitlines()[-1])
        except Exception as e:  # noqa: BLE001
            return {"error": "bridge socket: %s" % e}
    ports = glob.glob(os.environ.get("XIAO_PORT_GLOB", "/dev/serial/by-id/usb-*_XIAO_ReSpeaker_Audio_*-if03"))
    if not ports:
        return {"error": "no XIAO CDC port"}
    with cdc_lock:
        try:
            fd = os.open(ports[0], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK); tty.setraw(fd)
            a = termios.tcgetattr(fd); a[2] &= ~termios.HUPCL; termios.tcsetattr(fd, termios.TCSANOW, a)
            os.write(fd, b"status\n"); buf = b""; t = time.time() + 0.6
            while time.time() < t:
                try: buf += os.read(fd, 4096)
                except BlockingIOError: time.sleep(0.02)
                if buf.endswith(b"}\n"): break
            os.close(fd)
            return json.loads(buf.decode(errors="replace").strip().splitlines()[-1])
        except Exception as e:  # noqa: BLE001 - reported to the page
            return {"error": str(e)}


CAM_DEV = "/dev/video0"          # rkisp_mainpath
PREVIEW_PORT = 8080              # user's realtime MJPEG preview: /stream.mjpg
cam_lock = threading.Lock()
cam_last = {"jpeg": None, "time": 0.0, "bytes": 0, "took": 0.0, "count": 0, "error": None}


def sh(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return "(%s)" % e


def camera_info():
    """Static + live facts about the camera stack; nothing here opens the device."""
    sensor = ""
    for d in glob.glob("/sys/bus/i2c/devices/*/name"):
        n = open(d).read().strip()
        if n.startswith(("imx", "ov", "gc", "sc")):
            sensor = "%s @ %s" % (n, d.split("/")[-2])
    fmt = sh(["v4l2-ctl", "-d", CAM_DEV, "--get-fmt-video"])
    size = pix = ""
    for line in fmt.splitlines():
        if "Width/Height" in line: size = line.split(":", 1)[1].strip()
        if "Pixel Format" in line: pix = line.split(":", 1)[1].strip()
    busy = sh(["fuser", CAM_DEV])
    # The user's own realtime MJPEG preview (~/camera-preview/server.py) listens on 8080 when running.
    import socket
    try:
        with socket.create_connection(("127.0.0.1", PREVIEW_PORT), timeout=0.3):
            preview_up = True
    except OSError:
        preview_up = False
    return {
        "preview_server": "listening on %d" % PREVIEW_PORT if preview_up else "not running (port %d)" % PREVIEW_PORT,
        "preview_up": preview_up,
        "sensor": sensor or "not found",
        "device": CAM_DEV, "node_name": sh(["cat", "/sys/class/video4linux/video0/name"]),
        "format": "%s %s" % (size, pix),
        "rkaiq_3A": sh(["systemctl", "is-active", "rkaiq_3A.service"]),
        "preview_service": "%s/%s" % (sh(["systemctl", "is-enabled", "radxa-camera-preview.service"]),
                                      sh(["systemctl", "is-active", "radxa-camera-preview.service"])),
        "busy": bool(busy),
        "last_snapshot": {k: v for k, v in cam_last.items() if k != "jpeg"},
    }


def camera_snapshot():
    """One-shot capture: 8 frames so auto-exposure settles, keep the last, hardware JPEG."""
    with cam_lock:
        t0 = time.time()
        tmp = tempfile.mkdtemp(prefix="snap_")
        try:
            cmd = ["gst-launch-1.0", "-q", "v4l2src", "device=" + CAM_DEV, "io-mode=4", "num-buffers=8", "!",
                   "video/x-raw,format=NV12,width=3280,height=2464", "!", "mppjpegenc", "!",
                   "multifilesink", "location=%s/f_%%02d.jpg" % tmp]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            files = sorted(glob.glob(tmp + "/f_*.jpg"))
            if not files:
                raise RuntimeError("no frame: rc=%d %s" % (r.returncode, (r.stderr or r.stdout).strip()[-200:]))
            data = open(files[-1], "rb").read()
            if not (data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"):
                raise RuntimeError("frame is not a complete JPEG (%d bytes)" % len(data))
            cam_last.update(jpeg=data, time=time.time(), bytes=len(data), took=round(time.time() - t0, 2),
                            count=cam_last["count"] + 1, error=None)
            return data, None
        except Exception as e:  # noqa: BLE001 - reported to the page
            cam_last.update(error=str(e), took=round(time.time() - t0, 2))
            return None, str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>XIAO mic scope</title>
<style>
body{background:#111;color:#ddd;font:14px/1.4 -apple-system,Helvetica,Arial,sans-serif;margin:0;padding:12px}
h1{font-size:16px;margin:0 0 8px} canvas{display:block;background:#000;border:1px solid #333;width:100%}
.row{display:flex;gap:12px;align-items:center;margin:6px 0} .meter{flex:1;height:14px;background:#222;position:relative}
.meter i{position:absolute;left:0;top:0;bottom:0;background:#3a3} .meter b{position:absolute;top:0;bottom:0;width:2px;background:#fc3}
.lab{width:170px;font-family:menlo,monospace;font-size:12px} #st{font-family:menlo,monospace;font-size:11px;color:#9a9;white-space:pre-wrap}
select,button{background:#222;color:#ddd;border:1px solid #444;padding:2px 6px}
</style></head><body>
<h1>XIAO ReSpeaker Audio — live mic (16 kHz, L = ASR beam, R = comms beam)</h1>
<div class="row">zoom <select id="zoom"><option value="1">×1</option><option value="4">×4</option><option value="16" selected>×16</option><option value="64">×64</option><option value="256">×256</option></select>
<label><input type="checkbox" id="auto" checked> auto-scale</label>
<a href="/wav?sec=5" style="color:#8bf">download last 5 s .wav</a> <span id="cap"></span></div>
<div class="row"><span class="lab" id="lL">L</span><div class="meter"><i id="mL"></i><b id="pL"></b></div></div>
<canvas id="cL" height="160"></canvas>
<div class="row"><span class="lab" id="lR">R</span><div class="meter"><i id="mR"></i><b id="pR"></b></div></div>
<canvas id="cR" height="160"></canvas>
<div class="row"><span class="lab">spectrum L (0–8 kHz, dBFS)</span></div>
<canvas id="cS" height="140"></canvas>
<div id="st">status: …</div>
<h1 style="margin-top:14px">Camera — IMX219 via rkisp</h1>
<div id="caminfo" style="font-family:menlo,monospace;font-size:11px;color:#9a9;white-space:pre-wrap"></div>
<div class="row"><span id="livest" style="font-family:menlo,monospace;font-size:12px">realtime preview: checking…</span></div>
<img id="live" style="max-width:100%;border:1px solid #333;margin-top:6px;display:none">
<div class="row" id="snaprow"><button id="shot">Snapshot (fallback when the live stream is unavailable)</button>
<label><input type="checkbox" id="autoshot"> Auto capture every 5 seconds</label> <span id="camst" style="font-family:menlo,monospace;font-size:12px"></span></div>
<img id="snap" style="max-width:100%;border:1px solid #333;margin-top:6px;display:none">
<script>
// Realtime MJPEG from the user's own preview server (port 8080) when it is up; snapshot row only otherwise.
let liveUp=null;
function setLive(up){if(up===liveUp)return;liveUp=up;const img=document.getElementById('live');
 if(up){img.src='http://'+location.hostname+':8080/stream.mjpg?t='+Date.now();img.style.display='block';document.getElementById('snaprow').style.display='none';document.getElementById('snap').style.display='none';
  document.getElementById('livest').textContent='realtime preview: live from :8080/stream.mjpg';}
 else{img.removeAttribute('src');img.style.display='none';document.getElementById('snaprow').style.display='flex';
  document.getElementById('livest').textContent='realtime preview: not running on :8080 (start ~/camera-preview/server.py to see it here)';}}
document.getElementById('live').onerror=()=>setLive(false);
async function camInfo(){try{const r=await fetch('/camera');const j=await r.json();setLive(j.preview_up);document.getElementById('caminfo').textContent=
 'sensor '+j.sensor+' | '+j.device+' '+j.node_name+' '+j.format+' | rkaiq_3A '+j.rkaiq_3A+' | preview systemd service '+j.preview_service+' | preview server '+j.preview_server+' | device busy '+j.busy+
 (j.last_snapshot.count?(' | last snapshot '+new Date(j.last_snapshot.time*1000).toLocaleTimeString()+' '+j.last_snapshot.bytes+' B in '+j.last_snapshot.took+' s'):'')+(j.last_snapshot.error?(' | error: '+j.last_snapshot.error):'');}catch(e){}}
let shooting=false;
async function shoot(){if(shooting)return;shooting=true;const b=document.getElementById('shot');b.disabled=true;document.getElementById('camst').textContent='capturing…';
 try{const r=await fetch('/snapshot.jpg?t='+Date.now());if(!r.ok){document.getElementById('camst').textContent='error: '+await r.text();}
 else{const blob=await r.blob();const img=document.getElementById('snap');img.src=URL.createObjectURL(blob);img.style.display='block';document.getElementById('camst').textContent=new Date().toLocaleTimeString()+' '+Math.round(blob.size/1024)+' kB';}}
 catch(e){document.getElementById('camst').textContent='error: '+e;}finally{shooting=false;b.disabled=false;camInfo();}}
document.getElementById('shot').onclick=shoot;
setInterval(()=>{if(document.getElementById('autoshot').checked&&!liveUp)shoot();},5000);camInfo();setInterval(camInfo,5000);
</script>
<script>
const cL=document.getElementById('cL'),cR=document.getElementById('cR'),cS=document.getElementById('cS');
function fit(c){c.width=c.clientWidth*devicePixelRatio;} [cL,cR,cS].forEach(fit); addEventListener('resize',()=>[cL,cR,cS].forEach(fit));
const colsL=[],colsR=[]; let holdL=-120,holdR=-120,holdT=0, autoGain=1;
function push(arr,cols){for(const c of cols){arr.push(c);} while(arr.length>cL.width) arr.shift();}
function draw(c,arr,color){const g=c.getContext('2d'),W=c.width,H=c.height,z=zoomValue();g.fillStyle='#000';g.fillRect(0,0,W,H);
 g.strokeStyle='#233';g.beginPath();for(let k=1;k<4;k++){g.moveTo(0,H*k/4);g.lineTo(W,H*k/4);}g.stroke();
 g.strokeStyle=color;g.beginPath();const x0=W-arr.length;for(let i=0;i<arr.length;i++){const [mn,mx]=arr[i];const y1=H/2-mx*z*H/65536,y2=H/2-mn*z*H/65536;g.moveTo(x0+i+0.5,Math.max(0,Math.min(H,y1)));g.lineTo(x0+i+0.5,Math.max(0,Math.min(H,y2)));}g.stroke();
 g.fillStyle='#666';g.font='11px menlo';g.fillText('±'+Math.round(32768/z)+' (±'+(20*Math.log10(1/z)).toFixed(0)+' dBFS full scale), 2.5 ms/col',6,12);}
function zoomValue(){return document.getElementById('auto').checked?autoGain:+document.getElementById('zoom').value;}
function meter(id,pid,lid,rms,peak,hold,name){const w=Math.max(0,Math.min(100,(rms+100)));document.getElementById(id).style.width=w+'%';
 document.getElementById(pid).style.left=Math.max(0,Math.min(100,hold+100))+'%';document.getElementById(lid).textContent=name+' rms '+rms.toFixed(1)+' dBFS pk '+peak.toFixed(1);}
// radix-2 FFT, real input, Hann window
function fftMag(x){const N=x.length,re=new Float64Array(N),im=new Float64Array(N);for(let i=0;i<N;i++){re[i]=x[i]*(0.5-0.5*Math.cos(2*Math.PI*i/(N-1)))/32768;}
 for(let i=1,j=0;i<N;i++){let bit=N>>1;for(;j&bit;bit>>=1)j^=bit;j^=bit;if(i<j){[re[i],re[j]]=[re[j],re[i]];[im[i],im[j]]=[im[j],im[i]];}}
 for(let len=2;len<=N;len<<=1){const ang=-2*Math.PI/len,wr=Math.cos(ang),wi=Math.sin(ang);for(let i=0;i<N;i+=len){let cr=1,ci=0;for(let k=0;k<len/2;k++){const ur=re[i+k],ui=im[i+k],vr=re[i+k+len/2]*cr-im[i+k+len/2]*ci,vi=re[i+k+len/2]*ci+im[i+k+len/2]*cr;re[i+k]=ur+vr;im[i+k]=ui+vi;re[i+k+len/2]=ur-vr;im[i+k+len/2]=ui-vi;const t=cr*wr-ci*wi;ci=cr*wi+ci*wr;cr=t;}}}
 const m=new Float64Array(N/2);for(let k=0;k<N/2;k++){m[k]=20*Math.log10(Math.hypot(re[k],im[k])*2/N*2+1e-9);}return m;}
function drawSpec(mags){const g=cS.getContext('2d'),W=cS.width,H=cS.height;g.fillStyle='#000';g.fillRect(0,0,W,H);g.strokeStyle='#233';g.beginPath();
 for(let f=1000;f<8000;f+=1000){const x=W*f/8000;g.moveTo(x,0);g.lineTo(x,H);}g.stroke();g.fillStyle='#666';g.font='11px menlo';
 for(let f=1000;f<8000;f+=1000)g.fillText((f/1000)+'k',W*f/8000+2,H-3);g.strokeStyle='#5af';g.beginPath();
 for(let k=0;k<mags.length;k++){const x=W*k/mags.length,y=H*(-mags[k])/100;if(k===0)g.moveTo(x,y);else g.lineTo(x,y);}g.stroke();}
const es=new EventSource('/stream');
es.onmessage=e=>{const d=JSON.parse(e.data);push(colsL,d.l);push(colsR,d.r);const now=Date.now();
 if(d.peakL>holdL||now-holdT>1500){holdL=d.peakL;}if(d.peakR>holdR||now-holdT>1500){holdR=d.peakR;holdT=now;}
 if(document.getElementById('auto').checked){const pk=Math.max(d.peakL,d.peakR,-90);const want=Math.pow(2,Math.floor(Math.max(0,(-pk-6)/6)));autoGain=Math.min(256,Math.max(1,want));}
 draw(cL,colsL,'#3f6');draw(cR,colsR,'#f93');meter('mL','pL','lL',d.rmsL,d.peakL,holdL,'L');meter('mR','pR','lR',d.rmsR,d.peakR,holdR,'R');
 if(d.specL)drawSpec(fftMag(d.specL));document.getElementById('cap').textContent='capture: '+d.state+(d.restarts?(' restarts '+d.restarts):'')+' | frames '+d.total;};
es.onerror=()=>{document.getElementById('cap').textContent='capture: stream disconnected, retrying…';};
async function poll(){try{const r=await fetch('/status');const j=await r.json();document.getElementById('st').textContent='XIAO status: '+JSON.stringify(j);}catch(e){document.getElementById('st').textContent='XIAO status: '+e;}setTimeout(poll,3000);}poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    cap = None

    def log_message(self, *a):  # quiet
        pass

    def send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            self.send(200, "text/html; charset=utf-8", PAGE.encode())
        elif path == "/status":
            self.send(200, "application/json", json.dumps(cdc_status()).encode())
        elif path == "/camera":
            self.send(200, "application/json", json.dumps(camera_info()).encode())
        elif path == "/snapshot.jpg":
            data, err = camera_snapshot()
            if data: self.send(200, "image/jpeg", data)
            else: self.send(503, "text/plain; charset=utf-8", err.encode())
        elif path == "/wav":
            sec = 5
            for kv in query.split("&"):
                if kv.startswith("sec="):
                    try: sec = max(1, min(HISTORY_SEC, int(kv[4:])))
                    except ValueError: pass
            data, _ = self.cap.recent(RATE * sec)
            bio = io.BytesIO(); w = wave.open(bio, "wb"); w.setnchannels(CH); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<hh", l, r) for l, r in data)); w.close()
            self.send_response(200); self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Disposition", 'attachment; filename="xiao-mic-%s.wav"' % time.strftime("%Y%m%d-%H%M%S"))
            self.send_header("Content-Length", str(bio.tell())); self.end_headers(); self.wfile.write(bio.getvalue())
        elif path == "/stream":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "keep-alive"); self.end_headers()
            last = 0
            try:
                while True:
                    payload, last = tick_frame(self.cap, last)
                    if payload:
                        self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n"); self.wfile.flush()
                    time.sleep(TICK_MS / 1000.0)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.send(404, "text/plain", b"not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8778)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--device", default=None, help="ALSA capture device from arecord -L")
    ap.add_argument("--capture-cmd", default=None,
                    help="command producing raw S16LE stereo 16 kHz on stdout instead of arecord "
                         "(e.g. 'python3 sim/twin/sim_arecord.py' for the software twin)")
    a = ap.parse_args()
    if not a.device and not a.capture_cmd:
        ap.error("choose --device from arecord -L, or supply --capture-cmd")
    import shlex
    cap = Capture(a.device, shlex.split(a.capture_cmd) if a.capture_cmd else None); cap.start()
    Handler.cap = cap
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print("micscope on http://%s:%d/ capturing %s" % (a.bind, a.port, a.device), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
