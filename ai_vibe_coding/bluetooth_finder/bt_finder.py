#!/usr/bin/env python3
"""
BT·FINDER — Three-source Bluetooth RSSI Tracker
Source priority (per device):
  1. GATT readRSSI   — active BLE connection, ~3x/sec, best quality
  2. BLE advertising — passive, works on everything, sparse on Apple devices
  3. Classic HCI     — paired Classic devices via hcitool rssi

Requirements:
  sudo apt install python3-dbus python3-gi bluez
  sudo systemctl start bluetooth
"""

import sys, os, signal, threading, time, collections, termios, tty, re
import subprocess, shutil
from datetime import datetime

try:
    import dbus, dbus.mainloop.glib
    from gi.repository import GLib
except ImportError:
    sys.exit("Missing: sudo apt install python3-dbus python3-gi")

# ── ANSI ──────────────────────────────────────────────────────────────────────
RST  = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
STRIP = re.compile(r'\033\[[0-9;]*m')

def fg(r,g,b): return f"\033[38;2;{r};{g};{b}m"
def vlen(s):   return len(STRIP.sub('', s))
def trunc(s,n): s=str(s); return s if len(s)<=n else s[:n-1]+'…'

TEAL   = fg(0,210,170);  BLUE  = fg(80,140,255)
WHITE  = fg(230,235,245); GRAY  = fg(100,110,125)
LGRAY  = fg(50,55,65);    GREEN = fg(50,220,120)
YELLOW = fg(255,195,50);  RED   = fg(255,80,90)
ORANGE = fg(255,140,60)

# Source labels + colours
SRC_GATT = (fg(50,220,120),  "GATT")   # green  — best
SRC_ADV  = (fg(80,140,255),  "ADV ")   # blue   — passive
SRC_HCI  = (fg(255,140,60),  "HCI ")   # orange — classic

def sig_col(pct):
    if pct >= 65: return GREEN
    if pct >= 35: return YELLOW
    return RED

def prox_str(pct):
    if pct >= 85: return "very close"
    if pct >= 65: return "close"
    if pct >= 45: return "nearby"
    if pct >= 25: return "far"
    return "very far"

def age_str(sec):
    if sec <  2:   return f"{GREEN}live{RST}"
    if sec < 10:   return f"{YELLOW}{int(sec)}s ago{RST}"
    if sec < 60:   return f"{RED}{int(sec)}s ago{RST}"
    if sec < 3600: return f"{GRAY}{int(sec//60)}m{int(sec%60):02d}s ago{RST}"
    return f"{GRAY}{int(sec//3600)}h{int((sec%3600)//60):02d}m ago{RST}"

def rssi_pct(rssi):
    return max(0, min(100, round(((max(-100, min(-35, rssi)) + 100) / 65) * 100)))

def sparkline(buf):
    if len(buf) < 2: return ""
    chars = "▁▂▃▄▅▆▇█"
    lo, hi = min(buf), max(buf)
    rng = hi - lo or 1
    return "".join(chars[min(7, round((v-lo)/rng*7))] for v in buf)

# ── Tuning ────────────────────────────────────────────────────────────────────
AVG_WIN       = 6
STALE_AFTER   = 5.0    # seconds before a device dims
RENDER_HZ     = 0.5    # render interval
GATT_INTERVAL = 0.35   # seconds between GATT readRSSI calls (~3/sec)
HCI_INTERVAL  = 2.0    # seconds between hcitool rssi polls
GATT_TIMEOUT  = 6.0    # give up on GATT connect after this many seconds

# ── Shared state ──────────────────────────────────────────────────────────────
# addr → {addr, name, rssi_raw, rssi_avg, pct, last_seen, source,
#          gatt_task, gatt_server, gatt_active}
devices   = {}
bufs      = {}          # addr → deque
lock      = threading.Lock()
pinned    = None
imap      = {}          # 1-9 → addr
HCITOOL   = shutil.which("hcitool")

# ── Core update (thread-safe) ─────────────────────────────────────────────────
def upsert(addr, name, rssi, source):
    """Record a new RSSI sample. source is one of SRC_GATT/SRC_ADV/SRC_HCI."""
    now = time.monotonic()
    with lock:
        if addr not in bufs:
            bufs[addr] = collections.deque(maxlen=AVG_WIN)
        bufs[addr].append(rssi)
        avg = round(sum(bufs[addr]) / len(bufs[addr]))
        if addr not in devices:
            devices[addr] = {"addr": addr, "name": name or addr,
                             "gatt_active": False, "gatt_task": None}
        if name and name != addr:
            devices[addr]["name"] = name
        devices[addr].update({
            "rssi_raw": rssi, "rssi_avg": avg,
            "pct": rssi_pct(avg), "last_seen": now,
            "source": source,
        })

# ── SOURCE 1: GATT readRSSI ───────────────────────────────────────────────────
# BlueZ exposes RSSI on a connected device via the Device1.RSSI property,
# which updates when you call GetProperties while connected.
# We connect, then repeatedly read the RSSI property in a tight loop.

def gatt_worker(addr, bus_name="org.bluez"):
    """
    Runs in its own daemon thread for each pinned device.
    Connects via GATT and polls RSSI ~3x/sec until cancelled.
    """
    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=False)
        bus = dbus.SystemBus()

        # Find the object path for this address
        mgr = dbus.Interface(bus.get_object("org.bluez", "/"),
                             "org.freedesktop.DBus.ObjectManager")
        dev_path = None
        for path, ifaces in mgr.GetManagedObjects().items():
            d = ifaces.get("org.bluez.Device1")
            if d and str(d.get("Address","")).upper() == addr.upper():
                dev_path = path
                break

        if not dev_path:
            return

        dev_iface = dbus.Interface(
            bus.get_object("org.bluez", dev_path),
            "org.bluez.Device1"
        )
        prop_iface = dbus.Interface(
            bus.get_object("org.bluez", dev_path),
            "org.freedesktop.DBus.Properties"
        )

        # Connect (with timeout)
        try:
            dev_iface.Connect(timeout=GATT_TIMEOUT)
        except dbus.DBusException as e:
            if "Already" not in str(e):
                with lock:
                    if addr in devices:
                        devices[addr]["gatt_active"] = False
                return

        with lock:
            if addr in devices:
                devices[addr]["gatt_active"] = True

        # Poll RSSI until thread is cancelled (device unpinned / removed)
        while True:
            with lock:
                still_running = (addr in devices and
                                 devices[addr].get("gatt_task") ==
                                 threading.current_thread())
            if not still_running:
                break

            try:
                all_props = prop_iface.GetAll("org.bluez.Device1")
                rssi = all_props.get("RSSI")
                name = str(all_props.get("Name") or all_props.get("Alias") or "")
                if rssi is not None:
                    upsert(addr, name, int(rssi), SRC_GATT)
            except Exception:
                break

            time.sleep(GATT_INTERVAL)

    except Exception:
        pass
    finally:
        # Try to disconnect cleanly
        try:
            dev_iface.Disconnect()
        except Exception:
            pass
        with lock:
            if addr in devices:
                devices[addr]["gatt_active"] = False
                if devices[addr].get("gatt_task") == threading.current_thread():
                    devices[addr]["gatt_task"] = None

def start_gatt(addr):
    """Spin up a GATT worker thread for addr."""
    with lock:
        if addr not in devices:
            return
        # Stop any existing worker first
        existing = devices[addr].get("gatt_task")
        if existing and existing.is_alive():
            devices[addr]["gatt_task"] = None   # signal it to stop
            # let it wind down in background
        t = threading.Thread(target=gatt_worker, args=(addr,), daemon=True)
        devices[addr]["gatt_task"] = t
    t.start()

def stop_gatt(addr):
    """Signal the GATT worker for addr to stop."""
    with lock:
        if addr in devices:
            devices[addr]["gatt_task"] = None

# ── SOURCE 3: Classic HCI RSSI via hcitool ───────────────────────────────────
# hcitool rssi <addr> reads RSSI from an active Classic BT link.
# Only works for paired+connected Classic devices (phones, headphones, etc.)

def hci_worker():
    """
    Background thread: every HCI_INTERVAL seconds, for every known device
    that is NOT already getting GATT updates, try hcitool rssi.
    """
    if not HCITOOL:
        return   # hcitool not installed

    while True:
        time.sleep(HCI_INTERVAL)
        with lock:
            candidates = [
                (addr, d["name"])
                for addr, d in devices.items()
                if not d.get("gatt_active", False)
            ]

        for addr, name in candidates:
            try:
                result = subprocess.run(
                    [HCITOOL, "rssi", addr],
                    capture_output=True, text=True, timeout=2.0
                )
                # Output: "RSSI return value: -54"
                m = re.search(r'(-?\d+)', result.stdout)
                if m:
                    rssi = int(m.group(1))
                    if -120 < rssi < 0:   # sanity check
                        upsert(addr, name, rssi, SRC_HCI)
            except Exception:
                pass

# ── SOURCE 2: BLE advertisements via D-Bus PropertiesChanged ─────────────────
def make_adv_handler(bus):
    def handler(iface, changed, _, path=None):
        if iface != "org.bluez.Device1" or "RSSI" not in changed:
            return
        rssi = int(changed["RSSI"])
        try:
            p = dbus.Interface(bus.get_object("org.bluez", path),
                               "org.freedesktop.DBus.Properties")
            all_p = p.GetAll("org.bluez.Device1")
            addr  = str(all_p.get("Address", "??"))
            name  = str(all_p.get("Name") or all_p.get("Alias") or "")
        except Exception:
            addr = str(path).split("/")[-1] if path else "??"; name = ""

        with lock:
            # Only use ADV if no GATT worker is active for this device
            gatt_on = devices.get(addr, {}).get("gatt_active", False)

        if not gatt_on:
            upsert(addr, name, rssi, SRC_ADV)

    return handler

# ── Terminal ──────────────────────────────────────────────────────────────────
_cols   = 80
_resize = threading.Event()

def _sz():
    global _cols
    try: _cols = os.get_terminal_size().columns
    except: pass

def _winch(s,f): _sz(); _resize.set()
signal.signal(signal.SIGWINCH, _winch)
_sz()

def goto(r,c=1):    sys.stdout.write(f"\033[{r};{c}H")
def clrline():      sys.stdout.write("\033[2K")
def clrdown():      sys.stdout.write("\033[J")
def hide_cursor():  sys.stdout.write("\033[?25l")
def show_cursor():  sys.stdout.write("\033[?25h")

# ── Snapshot + stable index ───────────────────────────────────────────────────
def build_snapshot(now):
    global imap
    with lock:
        snap = list(devices.items())

    active = sorted([(a,d) for a,d in snap
                     if now - d.get("last_seen",0) <= STALE_AFTER],
                    key=lambda x: x[1]["pct"], reverse=True)
    offline = sorted([(a,d) for a,d in snap
                      if now - d.get("last_seen",0) > STALE_AFTER],
                     key=lambda x: x[1].get("last_seen",0), reverse=True)

    if pinned:
        pe = next(((a,d) for a,d in active if a==pinned), None)
        if pe: active.remove(pe); active.insert(0, pe)

    old = dict(imap); new = {}; used = set()
    for idx, addr in old.items():
        if any(a==addr for a,_ in active+offline):
            new[idx]=addr; used.add(idx)
    n=1
    for addr,_ in active+offline:
        if addr in new.values(): continue
        while n in used or n>9: n+=1
        if n<=9: new[n]=addr; used.add(n); n+=1
    imap = new
    return active, offline, {v:k for k,v in new.items()}

# ── Render ────────────────────────────────────────────────────────────────────
_rlock = threading.Lock()

def render():
    now  = time.monotonic()
    cols = _cols
    # Fixed cols per row: idx(3) src(6) name(18) rssi(9) pct(5) prox(12) age(10) spacing(6)
    FIXED = 3+6+18+9+5+12+10+6
    bar_w = max(4, cols - FIXED)

    active, offline, a2i = build_snapshot(now)

    out = []   # (row, text)
    r = 1

    def W(text): out.append((r, text))

    # ── Title ─────────────────────────────────────────────────────────────────
    ts    = datetime.now().strftime("%H:%M:%S")
    left  = f"{TEAL}{BOLD} BT·FINDER{RST} {GRAY}│{RST} {WHITE}{ts}{RST}  {GRAY}{len(active)} active  {len(offline)} out of range{RST}"
    hint  = f"{GRAY}{'0·unpin' if pinned else '1-9·track'}  ^C·quit{RST}"
    pad   = max(1, cols - vlen(left) - vlen(hint))
    out.append((r, left + " "*pad + hint)); r+=1
    out.append((r, LGRAY+"─"*cols+RST));   r+=1

    # ── Pinned panel ──────────────────────────────────────────────────────────
    if pinned and pinned in devices:
        d        = devices[pinned]
        age      = now - d.get("last_seen", now)
        act      = age <= STALE_AFTER
        pct      = d.get("pct", 0)
        c        = sig_col(pct) if act else GRAY
        src_col, src_lbl = d.get("source", SRC_ADV)
        gatt_on  = d.get("gatt_active", False)
        src_indicator = (
            f"{GREEN}◉ GATT{RST}" if gatt_on else
            f"{ORANGE}◎ HCI{RST}"  if d.get("source")==SRC_HCI else
            f"{BLUE}○ ADV{RST}"
        )

        out.append((r, "")); r+=1
        out.append((r,
            f" {TEAL}▶{RST} {BOLD}{WHITE}{trunc(d['name'],30)}{RST}  "
            f"{GRAY}{d['addr']}{RST}  {src_indicator}"
        )); r+=1
        out.append((r, "")); r+=1

        big_w  = cols - 4
        filled = round(pct/100*big_w)
        out.append((r,
            f"  {c}{'█'*filled}{DIM}{'░'*(big_w-filled)}{RST}"
        )); r+=1
        out.append((r, "")); r+=1
        out.append((r,
            f"  {BOLD}{c}{pct:>3}%{RST}  "
            f"{c}{d.get('rssi_avg',0):>+4} dBm{RST}  "
            f"{WHITE}{prox_str(pct)}{RST}  "
            f"last seen {age_str(age)}"
        )); r+=1

        with lock:
            spark_buf = list(bufs.get(pinned,[]))
        if len(spark_buf)>1:
            out.append((r, f"  {GRAY}trend {RST}{c}{sparkline(spark_buf)}{RST}")); r+=1

        out.append((r, "")); r+=1
        out.append((r, LGRAY+"─"*cols+RST)); r+=1

    # ── Column header ──────────────────────────────────────────────────────────
    out.append((r,
        f" {GRAY}"
        f"{'#':<3}{'SRC':<6}{'DEVICE':<18}"
        f"{'RSSI':>9}  "
        f"{'BAR':<{bar_w}}  "
        f"{'PCT':>4}  "
        f"{'PROXIMITY':<12}"
        f"LAST SEEN{RST}"
    )); r+=1
    out.append((r, LGRAY+"─"*cols+RST)); r+=1

    # ── Row renderer ──────────────────────────────────────────────────────────
    def row(addr, d, is_active):
        age  = now - d.get("last_seen", now)
        pct  = d.get("pct", 0)
        c    = sig_col(pct) if is_active else GRAY
        fd   = WHITE if is_active else GRAY
        idx  = str(a2i.get(addr," "))
        pin  = f"{TEAL}▶{RST}" if addr==pinned else " "
        name = trunc(d["name"], 17)

        src_col, src_lbl = d.get("source", SRC_ADV)
        gatt_on = d.get("gatt_active", False)
        if gatt_on:
            src_str = f"{GREEN}{BOLD}GATT{RST} "
        elif d.get("source") == SRC_HCI:
            src_str = f"{ORANGE}HCI {RST} "
        else:
            src_str = f"{BLUE}ADV {RST} "

        filled = round(pct/100*bar_w)
        bar    = (c+"█"*filled+DIM+"░"*(bar_w-filled)+RST) if is_active else (DIM+"░"*bar_w+RST)

        return (
            f" {TEAL}{BOLD}{idx}{RST}{pin}"
            f"{src_str}"
            f"{fd}{name:<17}{RST} "
            f"{c}{d.get('rssi_avg',0):>+5} dBm{RST}  "
            f"{bar}  "
            f"{c}{BOLD}{pct:>3}%{RST}  "
            f"{fd}{prox_str(pct):<12}{RST}"
            f"{age_str(age)}"
        )

    for addr, d in active:
        out.append((r, row(addr, d, True))); r+=1

    if offline:
        out.append((r, f" {LGRAY}{'── out of range '+'╌'*max(0,cols-18)}{RST}")); r+=1
        for addr, d in offline:
            out.append((r, row(addr, d, False))); r+=1

    if not active and not offline:
        out.append((r, f"  {GRAY}Scanning… bring a device nearby.{RST}")); r+=1

    # ── Legend ─────────────────────────────────────────────────────────────────
    out.append((r, "")); r+=1
    out.append((r,
        f" {GRAY}source quality: "
        f"{GREEN}●GATT{RST}{GRAY} (best, active connection)  "
        f"{ORANGE}●HCI{RST}{GRAY} (classic link)  "
        f"{BLUE}●ADV{RST}{GRAY} (BLE advertisement){RST}"
    )); r+=1

    last_row = r

    with _rlock:
        hide_cursor()
        for row_n, text in out:
            goto(row_n); clrline()
            sys.stdout.write(text)
        goto(last_row); clrdown()
        sys.stdout.flush()

# ── Keyboard ──────────────────────────────────────────────────────────────────
def kb_loop():
    global pinned
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == '\x03': os.kill(os.getpid(), signal.SIGINT); break
            if ch.isdigit():
                n = int(ch)
                if n == 0:
                    if pinned: stop_gatt(pinned)
                    pinned = None
                else:
                    target = imap.get(n)
                    if target:
                        if pinned and pinned != target:
                            stop_gatt(pinned)
                        if target == pinned:
                            stop_gatt(pinned)
                            pinned = None
                        else:
                            pinned = target
                            start_gatt(target)   # ← kick off GATT source
                render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    mgr = dbus.Interface(bus.get_object("org.bluez","/"),
                         "org.freedesktop.DBus.ObjectManager")

    ap = None
    for path, ifaces in mgr.GetManagedObjects().items():
        if "org.bluez.Adapter1" in ifaces: ap=path; break
    if not ap:
        sys.exit(f"{RED}No Bluetooth adapter found.{RST}")

    adapter = dbus.Interface(bus.get_object("org.bluez",ap),"org.bluez.Adapter1")
    try:
        adapter.SetDiscoveryFilter({
            "Transport":     dbus.String("auto"),
            "DuplicateData": dbus.Boolean(True),   # Source 2: every ADV packet
        })
    except: pass
    try:
        adapter.StartDiscovery()
    except dbus.DBusException as e:
        if "Already" not in str(e):
            sys.exit(f"Discovery failed: {e}\nTry: sudo systemctl start bluetooth")

    # Source 2: BLE advertisement signal receiver
    bus.add_signal_receiver(
        make_adv_handler(bus),
        dbus_interface="org.freedesktop.DBus.Properties",
        signal_name="PropertiesChanged",
        path_keyword="path", arg0="org.bluez.Device1"
    )

    # Seed already-cached devices
    for path, ifaces in mgr.GetManagedObjects().items():
        d = ifaces.get("org.bluez.Device1")
        if d and d.get("RSSI") is not None and path.startswith(ap):
            upsert(str(d.get("Address","??")),
                   str(d.get("Name") or d.get("Alias") or ""),
                   int(d["RSSI"]), SRC_ADV)

    # Source 3: Classic HCI poller thread
    if HCITOOL:
        threading.Thread(target=hci_worker, daemon=True).start()
    else:
        pass  # hcitool not found — Source 3 silently disabled

    loop = GLib.MainLoop()

    def _exit(sig, frame):
        if pinned: stop_gatt(pinned)
        try: adapter.StopDiscovery()
        except: pass
        loop.quit()
        show_cursor()
        sys.stdout.write("\033[2J\033[H")
        src3 = "enabled" if HCITOOL else "not found (install bluez-tools)"
        print(f"{TEAL}BT·FINDER{RST} stopped.\n")
        sys.exit(0)

    signal.signal(signal.SIGINT, _exit)
    threading.Thread(target=loop.run, daemon=True).start()
    threading.Thread(target=kb_loop, daemon=True).start()

    sys.stdout.write("\033[2J")
    hide_cursor()

    # Print startup status
    goto(1)
    print(f"\n {TEAL}{BOLD}BT·FINDER{RST} starting up…\n")
    print(f"  {GREEN}●{RST} Source 1 (GATT)  — ready, activates when you pin a device")
    print(f"  {BLUE}●{RST} Source 2 (ADV)   — active, scanning all BLE advertisements")
    src3_status = f"{ORANGE}●{RST} ready" if HCITOOL else f"{GRAY}●{RST} disabled (hcitool not found)"
    print(f"  {src3_status}  Source 3 (HCI)   — polls Classic link RSSI")
    print(f"\n  {GRAY}Waiting for devices…{RST}\n")
    sys.stdout.flush()
    time.sleep(1.5)

    while True:
        if _resize.is_set():
            _resize.clear()
            sys.stdout.write("\033[2J")
            sys.stdout.flush()
        render()
        time.sleep(RENDER_HZ)

if __name__ == "__main__":
    main()
