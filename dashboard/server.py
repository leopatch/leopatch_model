#!/usr/bin/env python3
"""LeoPatch test bench: flash any exported model onto the nRF54LM20 DK and test it live.

Runs a small local web server (http://localhost:8054) that
  * lists the Axon model packages in the repo (deploy/out_*/firmware_generated, ...),
  * builds the on-chip firmware (firmware/leopatch_onchip) with the chosen model and flashes it,
  * reads the board's serial port: NPU self-test, live ECG, on-chip results,
  * triggers recordings and the Bluetooth upload from the browser, and checks that the
    Bluetooth copy matches what the board printed on the serial port.

usage: ~/.venvs/leopatch-axon/bin/python dashboard/server.py [--port 8054] [--no-browser]
Needs pyserial and bleak (both in the leopatch-axon venv) and the nRF Connect SDK toolchain
(nrfutil sdk-manager, NCS v3.4.1). Recordings are saved in dashboard/recordings/ (git-ignored:
they are health data).
"""
import argparse
import asyncio
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import serial

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FIRMWARE = REPO / "firmware/leopatch_onchip"
BUILD_ROOT = HERE / ".build"
RECORDINGS = HERE / "recordings"
EXTRA_MODELS = HERE / "extra_models.json"  # extra package folders added from the page

NCS_VERSION = os.environ.get("LEOPATCH_NCS_VERSION", "v3.4.1")
ZEPHYR_BASE = os.environ.get("ZEPHYR_BASE", f"/opt/nordic/ncs/{NCS_VERSION}/zephyr")
BOARD = "nrf54lm20dk/nrf54lm20b/cpuapp"
FS = 500

# Where model packages are looked for (folders holding nrf_axon_model_<name>_.h,
# frontend_params.h and test_beats.h).
MODEL_GLOBS = ["firmware/leopatch_onchip/src/generated", "deploy/out_*/firmware_generated"]
# Packages that are in the repo but are not real models yet; they are not listed.
HIDDEN_MODELS = {"ecg_chd_half"}
# What we know about packages that have no training .json next to their checkpoint.
KNOWN_MODELS = {
    "ecg_sex_beat": {"task": "sex", "lead": "V3", "width": 1.0, "val_auc": 0.84,
                     "note": "Full-width V3 median-beat model (models/2026.10.28)"},
}
ELECTRODES = {
    "V3": "V3 chest position (between V2 and V4) against the right-arm reference",
    "I": "Lead I: red on the right wrist, yellow on the left wrist",
}


# ---------------------------------------------------------------------------- event bus

class Bus:
    """Fan-out of JSON events to every open browser tab (server-sent events)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = []

    def subscribe(self):
        q = queue.Queue(maxsize=5000)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def emit(self, kind, **data):
        msg = json.dumps({"type": kind, **data})
        with self.lock:
            for q in self.clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


bus = Bus()


# ---------------------------------------------------------------------------- models

def _define(text, name):
    m = re.search(rf"#define\s+{name}\s+([-\d.]+)f?", text)
    return float(m.group(1)) if m else None


def _training_meta(name):
    """Find the train_halfwidth.py .json that belongs to an exported package, by task and width."""
    if name in KNOWN_MODELS:
        return dict(KNOWN_MODELS[name])
    width = 0.5 if "half" in name else 1.0
    hits = []
    for p in (REPO / "models").glob("*/*.json"):
        try:
            meta = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        task = str(meta.get("task", ""))
        if task and task in name and float(meta.get("width", 1.0)) == width:
            meta["json"] = str(p.relative_to(REPO))
            hits.append(meta)
    return max(hits, key=lambda m: m["json"]) if hits else {}


def model_package(folder):
    folder = Path(folder)
    headers = list(folder.glob("nrf_axon_model_*_.h"))
    if len(headers) != 1 or not (folder / "frontend_params.h").exists() or not (folder / "test_beats.h").exists():
        return None
    name = re.match(r"nrf_axon_model_(.*)_\.h$", headers[0].name).group(1)
    tb = (folder / "test_beats.h").read_text()
    with open(folder / "frontend_params.h") as f:
        fp = f.read(400)
    meta = _training_meta(name)
    task = meta.get("task") or ("sex" if "sex" in name else "")
    report = folder.parent / "int8_report.json"
    try:
        int8 = json.loads(report.read_text()) if report.exists() else {}
    except ValueError:
        int8 = {}
    lead = meta.get("lead", "")
    try:
        rel = str(folder.relative_to(REPO))
    except ValueError:
        rel = str(folder)
    return {
        "id": rel,
        "name": name,
        "dir": str(folder),
        "task": task,
        "lead": lead,
        "electrodes": ELECTRODES.get(lead, ""),
        "width": meta.get("width"),
        "val_auc": meta.get("val_auc"),
        "test_auc": meta.get("test_auc"),
        "auc_int8": int8.get("auc_int8"),
        "same_decision": int8.get("same_decision"),
        "tflite_kb": int8.get("tflite_kb"),
        "threshold": _define(tb, "MODEL_THRESHOLD"),
        "stem_channels": int(_define(fp, "FRONTEND_STEM_CHANNELS") or 0),
        "header_mb": headers[0].stat().st_size / 1e6,
        "modified": time.strftime("%Y-%m-%d", time.localtime(headers[0].stat().st_mtime)),
        "note": meta.get("note", meta.get("json", "")),
        "pos_label": "MALE" if task == "sex" else "POSITIVE",
        "neg_label": "FEMALE" if task == "sex" else "NEGATIVE",
        "flash_kb": last_flash_size.get(name),
    }


last_flash_size = {}  # model name -> KB of flash used by the last build


def extra_dirs():
    try:
        return json.loads(EXTRA_MODELS.read_text())
    except (OSError, ValueError):
        return []


def list_models():
    seen, out = set(), []
    dirs = [d for g in MODEL_GLOBS for d in sorted(REPO.glob(g))] + [Path(d) for d in extra_dirs()]
    for d in dirs:
        pkg = model_package(d) if d.is_dir() else None
        if pkg and pkg["name"] not in HIDDEN_MODELS and pkg["dir"] not in seen:
            seen.add(pkg["dir"])
            out.append(pkg)
    return out


# ---------------------------------------------------------------------------- boards

def list_boards():
    """Nordic boards seen by nrfutil, with their serial ports (the console is vcom 1 on the DK)."""
    try:
        out = subprocess.run(["nrfutil", "device", "list", "--json"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    boards = []
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") != "info":
            continue
        for d in msg["data"].get("devices", []):
            ports = sorted(d.get("serialPorts", []), key=lambda p: p.get("vcom", 0))
            boards.append({
                "serial": d.get("serialNumber", "").lstrip("0"),
                "kind": (d.get("devkit") or {}).get("boardVersion", "J-Link"),
                "ports": [p["path"] for p in ports],
                "console": ports[-1]["path"] if ports else None,
            })
    return boards


# ---------------------------------------------------------------------------- serial

RESULT_RE = re.compile(r"^# result-data: (\w[\w ]*?),(.*)$")
SELFTEST_RE = re.compile(r"^# self-test beat (\d+): logit ([-\d.]+), Python int8 ([-\d.]+), float ([-\d.]+), "
                         r"(\d+) ms (OK|MISMATCH)")
SELFTEST_SUM_RE = re.compile(r"^# self-test: (\d+)/(\d+)")


def parse_kv(text):
    out = {}
    for part in text.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k.strip()] = float(v) if re.fullmatch(r"-?[\d.]+", v.strip()) else v.strip()
            except ValueError:
                out[k.strip()] = v.strip()
    return out


class Board:
    """Owns the serial port: parses the firmware's lines into events and keeps the latest state."""

    def __init__(self):
        self.lock = threading.Lock()
        self.ser = None
        self.port = None
        self.serial_number = None
        self.thread = None
        self.info = {}          # last "# model:" line
        self.selftest = []      # rows of the last self-test
        self.selftest_summary = None
        self.state = "disconnected"  # disconnected / booting / ready / recording / busy / error
        self.rec = None         # samples of the recording in progress
        self.last_recording = None
        self.pending_result = None
        self.history = load_history()

    # -- connection
    def connect(self, port, serial_number=None):
        self.disconnect()
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        self.port, self.serial_number = port, serial_number
        self.state = "connected"
        self.thread = threading.Thread(target=self._reader, args=(self.ser,), daemon=True)
        self.thread.start()
        bus.emit("serial", port=port, connected=True)
        self.send("i")  # ask the firmware which model it runs

    def disconnect(self):
        ser, self.ser = self.ser, None
        if ser:
            try:
                ser.close()
            except OSError:
                pass
        self.state = "disconnected"
        bus.emit("serial", port=self.port, connected=False)

    def send(self, cmd):
        if not self.ser:
            raise RuntimeError("no board connected")
        self.ser.write(cmd.encode())

    def snapshot(self):
        return {"port": self.port, "connected": self.ser is not None, "serial_number": self.serial_number,
                "info": self.info, "selftest": self.selftest, "selftest_summary": self.selftest_summary,
                "state": self.state, "history": self.history[-200:],
                "last_recording": self.last_recording}

    # -- reader thread
    def _reader(self, ser):
        batch, batch_t = [], time.time()
        while self.ser is ser:
            try:
                raw = ser.readline()
            except (OSError, serial.SerialException) as e:
                bus.emit("log", line=f"[dashboard] serial port lost: {e}")
                self.ser = None
                self.state = "disconnected"
                bus.emit("serial", port=self.port, connected=False)
                return
            line = raw.decode(errors="ignore").strip()
            if line:
                if line.startswith("#"):
                    if batch:
                        bus.emit("samples", rows=batch)
                        batch = []
                    self._status_line(line)
                elif self.rec is not None:
                    parts = line.split(",")
                    if len(parts) == 3:
                        try:
                            row = [int(p) for p in parts]
                        except ValueError:
                            row = None
                        if row:
                            self.rec.append(row)
                            batch.append(row)
            if batch and (time.time() - batch_t > 0.08 or len(batch) >= 200):
                bus.emit("samples", rows=batch)
                batch, batch_t = [], time.time()

    def _set_state(self, s):
        self.state = s
        bus.emit("state", state=s)

    def _status_line(self, line):
        bus.emit("log", line=line)
        if line.startswith("# model:"):
            self.info = parse_kv(line[len("# model:"):])
            bus.emit("info", info=self.info)
            if self.state in ("connected", "disconnected"):
                self._set_state("ready")
        elif m := SELFTEST_RE.match(line):
            i = int(m.group(1))
            if i == 0:
                self.selftest = []
                self._set_state("busy")
            self.selftest.append({"beat": i, "chip": float(m.group(2)), "python_int8": float(m.group(3)),
                                  "float": float(m.group(4)), "ms": int(m.group(5)), "ok": m.group(6) == "OK"})
            bus.emit("selftest", rows=self.selftest, summary=None)
        elif m := SELFTEST_SUM_RE.match(line):
            self.selftest_summary = {"passed": int(m.group(1)), "total": int(m.group(2)),
                                     "time": time.strftime("%H:%M:%S")}
            bus.emit("selftest", rows=self.selftest, summary=self.selftest_summary)
        elif line.startswith("# start"):
            self.rec, self.pending_result = [], None
            self._set_state("recording")
            bus.emit("rec_start", seconds=self.info.get("record_s"), fs=self.info.get("fs", FS))
        elif line.startswith("# result-data:"):
            m = RESULT_RE.match(line)
            if m:
                self.pending_result = {"label": m.group(1), **parse_kv(m.group(2))}
        elif line.startswith("# result:"):
            text = line[len("# result:"):].strip()
            if text.startswith("error"):
                self.pending_result = {"label": "ERROR", "error": text[len("error"):].strip(" ,")}
            elif self.state == "recording":
                self._set_state("thinking")
        elif line.startswith("# done"):
            self._finish_recording()
        elif line.startswith("# ready"):
            if self.state not in ("ready",):
                self._set_state("ready")
        elif line.startswith("# error"):
            self._set_state("error")
        elif line.startswith("# bluetooth:"):
            bus.emit("ble", status="board", text=line[len("# bluetooth:"):].strip())

    def _finish_recording(self):
        rows, self.rec = self.rec or [], None
        res = self.pending_result or {"label": "?"}
        stamp = time.strftime("%Y%m%d_%H%M%S")
        RECORDINGS.mkdir(exist_ok=True)
        name = f"ecg_{stamp}.csv"
        lead_off = sum(1 for r in rows if r[2]) / max(len(rows), 1)
        entry = {"file": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": self.info.get("name", "?"),
                 "pos": self.info.get("pos"), "threshold": self.info.get("threshold"),
                 "n": len(rows), "lead_off": round(lead_off, 3), "ble": None, **res}
        with open(RECORDINGS / name, "w") as f:
            f.write(f"# board: {json.dumps(entry)}\n")
            f.write("raw_mv,filtered_mv,lead_off\n")
            f.writelines(f"{a},{b},{c}\n" for a, b, c in rows)
        self.history.append(entry)
        self.last_recording = {"file": name, "filtered": [r[1] for r in rows]}
        self._set_state("error" if res.get("label") == "ERROR" else "ready")
        bus.emit("result", entry=entry)


def load_history():
    out = []
    for p in sorted(RECORDINGS.glob("ecg_*.csv")) if RECORDINGS.exists() else []:
        try:
            with open(p) as f:
                first = f.readline()
            if first.startswith("# board: "):
                out.append(json.loads(first[len("# board: "):]))
        except (OSError, ValueError):
            pass
    return out


board = Board()


# ---------------------------------------------------------------------------- build + flash

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.stage = None
        self.log = []
        self.result = None

    def snapshot(self):
        return {"running": self.running, "stage": self.stage, "log": self.log[-400:], "result": self.result}


job = Job()


def ncs(*cmd):
    """Command line that runs inside the nRF Connect SDK toolchain."""
    return ["nrfutil", "sdk-manager", "toolchain", "launch", "--ncs-version", NCS_VERSION, "--", *cmd]


def _run(cmd, cwd):
    env = dict(os.environ, ZEPHYR_BASE=ZEPHYR_BASE)
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         bufsize=1)
    for line in p.stdout:
        line = line.rstrip()
        job.log.append(line)
        bus.emit("job_log", line=line)
        m = re.match(r"\s*FLASH:\s+(\d+) B\s+(\d+) KB\s+([\d.]+)%", line)
        if m:
            job.result = dict(job.result or {}, flash_kb=int(m.group(1)) // 1024, flash_pct=float(m.group(3)))
        m = re.match(r"\s*RAM:\s+(\d+) B\s+(\d+) KB\s+([\d.]+)%", line)
        if m:
            job.result = dict(job.result or {}, ram_kb=int(m.group(1)) // 1024, ram_pct=float(m.group(3)))
    return p.wait()


def _stage(name):
    job.stage = name
    bus.emit("job", **job.snapshot())


def flash_job(pkg, opts, serial_number):
    build = BUILD_ROOT / pkg["name"]
    BUILD_ROOT.mkdir(exist_ok=True)
    args = [f"-DMODEL_DIR={pkg['dir']}", f"-DMODEL_POS_LABEL={opts['pos_label']}",
            f"-DMODEL_NEG_LABEL={opts['neg_label']}", f"-DRUN_MODEL={1 if opts['run_model'] else 0}",
            f"-DRECORD_SECONDS={int(opts['record_seconds'])}"]
    try:
        _stage("build")
        rc = _run(ncs("west", "build", "-b", BOARD, "-d", str(build), "--pristine", str(FIRMWARE), "--", *args),
                  FIRMWARE)
        if rc:
            raise RuntimeError(f"build failed (exit {rc}), see the log")
        if job.result and "flash_kb" in job.result:
            last_flash_size[pkg["name"]] = job.result["flash_kb"]
        _stage("flash")
        cmd = ["west", "flash", "-d", str(build)]
        if serial_number:
            cmd += ["--dev-id", serial_number]
        rc = _run(ncs(*cmd), FIRMWARE)
        if rc:
            raise RuntimeError(f"flash failed (exit {rc}): is the DK on and its USB cable in the debugger port?")
        _stage("boot")
        board.selftest, board.selftest_summary = [], None
        # The board resets after flashing and prints its model line and self-test.
        t0 = time.time()
        while time.time() - t0 < 15 and board.selftest_summary is None:
            time.sleep(0.2)
        if board.ser and board.selftest_summary is None:
            board.send("t")
            t0 = time.time()
            while time.time() - t0 < 5 and board.selftest_summary is None:
                time.sleep(0.2)
        if board.ser:
            board.send("i")
        job.result = dict(job.result or {}, ok=True, model=pkg["name"],
                          selftest=board.selftest_summary)
        _stage("done")
    except Exception as e:  # report every failure on the page
        job.result = dict(job.result or {}, ok=False, error=str(e))
        _stage("failed")
    finally:
        job.running = False
        bus.emit("job", **job.snapshot())


def reset_board(serial_number):
    cmd = ["nrfutil", "device", "reset"]
    if serial_number:
        cmd += ["--serial-number", serial_number]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ---------------------------------------------------------------------------- bluetooth

NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # board -> receiver notifications
ble_state = {"running": False}


def ble_job(trigger):
    """Wait for the board's Bluetooth upload and compare it with the serial copy."""
    from bleak import BleakClient, BleakScanner

    async def receive():
        bus.emit("ble", status="scanning", text="Looking for LeoPatch ...")
        if trigger and board.ser:
            board.send("u")
        dev = await BleakScanner.find_device_by_name("LeoPatch", timeout=60)
        if dev is None:
            raise RuntimeError("LeoPatch not found within 60 s (did LED2 blink?)")
        chunks, done = [], asyncio.Event()

        def on_data(_, data):
            chunks.append(data.decode(errors="ignore"))
            if "# end" in chunks[-1]:
                done.set()

        async with BleakClient(dev) as client:
            bus.emit("ble", status="receiving", text="Connected, receiving ...")
            t0 = time.time()
            await client.start_notify(NUS_TX, on_data)
            await asyncio.wait_for(done.wait(), timeout=30)
            secs = time.time() - t0
        return "".join(chunks), secs

    try:
        text, secs = asyncio.run(receive())
        lines = text.splitlines()
        result = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("# result:")), "?")
        mv = [float(l) for l in lines if l and not l.startswith("#")]
        info = {"result": result, "n": len(mv), "seconds": round(secs, 2)}
        last = board.last_recording
        if last and board.history and board.history[-1]["file"] == last["file"]:
            ser = last["filtered"]
            same = sum(1 for a, b in zip(ser, mv) if abs(a - b) <= 1)
            info.update(compared_with=last["file"], matching=same, serial_n=len(ser),
                        match=len(ser) == len(mv) and same == len(mv))
            board.history[-1]["ble"] = info
            _update_csv_header(board.history[-1])
        stamp = time.strftime("%Y%m%d_%H%M%S")
        with open(RECORDINGS / f"ble_{stamp}.csv", "w") as f:
            f.write(f"# result: {result}\nfiltered_mv\n")
            f.writelines(f"{v:g}\n" for v in mv)
        bus.emit("ble", status="done", text=f"Received {len(mv)} samples in {secs:.1f} s", info=info,
                 history=board.history[-200:])
    except Exception as e:
        msg = str(e) or type(e).__name__
        if "not authorized" in msg.lower() or "permission" in msg.lower():
            msg += " (allow Bluetooth for your terminal app in System Settings > Privacy & Security)"
        bus.emit("ble", status="failed", text=msg)
    finally:
        ble_state["running"] = False


def _update_csv_header(entry):
    p = RECORDINGS / entry["file"]
    try:
        lines = p.read_text().splitlines(keepends=True)
        lines[0] = f"# board: {json.dumps(entry)}\n"
        p.write_text("".join(lines))
    except OSError:
        pass


# ---------------------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            self._json({"board": board.snapshot(), "models": list_models(), "job": job.snapshot(),
                        "ble": ble_state, "build_board": BOARD})
        elif url.path == "/api/boards":
            self._json(list_boards())
        elif url.path == "/api/recording":
            name = Path(parse_qs(url.query).get("file", [""])[0]).name
            p = RECORDINGS / name
            if not re.fullmatch(r"(ecg|ble)_\d{8}_\d{6}\.csv", name) or not p.exists():
                return self._json({"error": "not found"}, 404)
            body = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = bus.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {msg}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                bus.unsubscribe(q)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            b = self._body()
            if path == "/api/connect":
                board.connect(b["port"], b.get("serial"))
                self._json({"ok": True})
            elif path == "/api/disconnect":
                board.disconnect()
                self._json({"ok": True})
            elif path == "/api/command":
                cmd = b.get("cmd")
                if cmd not in ("r", "u", "t", "i"):
                    return self._json({"error": "unknown command"}, 400)
                board.send(cmd)
                self._json({"ok": True})
            elif path == "/api/reset":
                r = reset_board(board.serial_number)
                self._json({"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-500:]})
            elif path == "/api/flash":
                with job.lock:
                    if job.running:
                        return self._json({"error": "a build is already running"}, 409)
                    pkg = next((m for m in list_models() if m["id"] == b["model"]), None)
                    if not pkg:
                        return self._json({"error": "model not found"}, 404)
                    job.running, job.log, job.result, job.stage = True, [], None, "build"
                threading.Thread(target=flash_job, args=(pkg, b, board.serial_number), daemon=True).start()
                bus.emit("job", **job.snapshot())
                self._json({"ok": True})
            elif path == "/api/ble":
                if ble_state["running"]:
                    return self._json({"error": "already waiting for Bluetooth"}, 409)
                ble_state["running"] = True
                threading.Thread(target=ble_job, args=(bool(b.get("trigger", True)),), daemon=True).start()
                self._json({"ok": True})
            elif path == "/api/add_model":
                d = Path(b["dir"]).expanduser().resolve()
                if not model_package(d):
                    return self._json({"error": "that folder needs nrf_axon_model_<name>_.h, frontend_params.h "
                                                "and test_beats.h (the firmware_generated folder of an export)"},
                                      400)
                dirs = extra_dirs()
                if str(d) not in dirs:
                    EXTRA_MODELS.write_text(json.dumps(dirs + [str(d)], indent=2))
                self._json({"ok": True, "models": list_models()})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8054)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    boards = list_boards()
    if boards and boards[0]["console"]:
        try:
            board.connect(boards[0]["console"], boards[0]["serial"])
            print(f"Connected to {boards[0]['kind']} {boards[0]['serial']} on {boards[0]['console']}")
        except (OSError, serial.SerialException) as e:
            print(f"Could not open {boards[0]['console']}: {e}")
    else:
        print("No board found yet; plug in the DK and pick it on the page.")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    url = f"http://localhost:{args.port}"
    print(f"LeoPatch test bench on {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
