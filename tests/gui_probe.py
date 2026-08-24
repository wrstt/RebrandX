#!/usr/bin/python3
"""Drives the real GTK window and reports what is actually painted.

    python3 tests/gui_probe.py [FOLDER]

Checks computed styles and geometry, not just DOM attributes -- an element
with the `hidden` attribute can still be visible if CSS overrides it.
"""
import sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from rebrandx.app import RebrandXWindow

TMP = Path(tempfile.mkdtemp(prefix="rbx-gui-"))
def fixture():
    r = TMP / "taskly"
    (r / "src").mkdir(parents=True); (r / ".github").mkdir()
    (r / "README.md").write_text("# Taskly\nSource: github.com/alexdev/taskly\ntaskly\n")
    (r / "src/taskly-core.js").write_text("class TasklyCore {}\n")
    (r / "LICENSE").write_text("MIT\n"); (r / "CHANGELOG.md").write_text("# Log\n")
    (r / ".github/build.yml").write_text("name: build\n")
    return str(r)

FX = sys.argv[1] if len(sys.argv) > 1 else fixture()
out = []

SCRIPT = """(()=>{
  const painted = id => { const e=document.getElementById(id); if(!e) return '?';
    const r=e.getBoundingClientRect();
    return (getComputedStyle(e).display!=='none' && r.width>0 && r.height>0)?'SHOWN':'hidden'; };
  const down = el => el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true}));
  const o=[];
  o.push('boot: source='+(S.source||'(none)')+' pill="'+document.getElementById('folderPath').textContent+'"');
  o.push('popovers at rest : picker='+painted('picker')+' settings='+painted('settings'));
  document.getElementById('folderPill').click();
  o.push('picker opens     : '+painted('picker'));
  down(document.getElementById('hdr'));
  o.push('header dismisses : '+painted('picker'));
  document.getElementById('gearBtn').click();
  o.push('settings opens   : '+painted('settings')+' rows='+document.querySelectorAll('#settingsRows .trow').length);
  window.dispatchEvent(new Event('blur'));
  o.push('blur dismisses   : '+painted('settings'));
  o.push('toolbar          : dryPill='+painted('dryPill')+' appliedWrap='+painted('appliedWrap'));
  return o.join('\\n')})()"""

SCRIPT2 = """(()=>{const o=[];
  o.push('totals      : '+JSON.stringify(S.totals));
  o.push('chips       : '+JSON.stringify(S.chips));
  o.push('file rows   : '+document.querySelectorAll('.frow').length);
  o.push('gh button   : '+document.getElementById('ghBtn').className);
  o.push('drop rows   : '+document.querySelectorAll('.frow.drop').length);
  o.push('selected    : '+(S.selected||'(none)'));
  o.push('diff pairs  : '+document.querySelectorAll('.pair').length);
  return o.join('\\n')})()"""

def js(w, code, then=None):
    def cb(wv, r, _):
        try:
            v = wv.evaluate_javascript_finish(r); out.append(v.to_string() if v else "None")
        except Exception as e: out.append("ERR %s" % e)
        if then: then()
    w.web.evaluate_javascript(code, -1, None, None, None, cb, None)

class P(RebrandXWindow):
    def __init__(s, a):
        super().__init__(a, None)                 # launch with NO folder
        s.web.connect("load-changed", s.after)
    def after(s, wv, ev):
        if ev == WebKit2.LoadEvent.FINISHED: GLib.timeout_add(2500, s.p1)
    def p1(s):
        js(s, "window.__e=[];window.onerror=m=>window.__e.push(m);'ok'")
        js(s, SCRIPT)
        js(s, "(()=>{__rbx_event('open-folder',{path:%r,label:%r});return 'opened'})()" % (FX, FX))
        GLib.timeout_add(2500, s.p2); return False
    def p2(s):
        js(s, """(()=>{S.find='taskly';S.replace='flowdesk';S.stripMeta=true;
            document.getElementById('findInput').value='taskly';
            document.getElementById('replInput').value='flowdesk';
            document.getElementById('ghBtn').click();return 'set'})()""")
        GLib.timeout_add(2800, s.p3); return False
    def p3(s):
        js(s, SCRIPT2); GLib.timeout_add(1200, s.fin); return False
    def fin(s):
        js(s, "JSON.stringify(window.__e)", then=s.done); return False
    def done(s):
        for chunk in out:
            if chunk in ("'ok'", "ok", "opened", "set", "None"): continue
            for line in str(chunk).split("\n"): print("   ", line)
        Gtk.main_quit()

class A(Gtk.Application):
    def do_activate(s): s.w = P(s)

a = A(); a.register(); a.activate()
GLib.timeout_add(40000, lambda: (print("    TIMEOUT"), Gtk.main_quit()))
try:
    Gtk.main()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
