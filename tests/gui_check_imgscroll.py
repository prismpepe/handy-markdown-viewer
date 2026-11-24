"""画像の多い文書で、再読み込み（自動更新・戻る/進む）をしても、読んでいた位置が保たれることを、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_imgscroll.py

画像は、読み込むまで大きさが分からない。再読み込みの直後は高さが縮み、位置を戻しても切り詰められる。
画像が読み込まれて高さが戻っても、位置は戻らず、読んでいた場所から大きくずれる。
画像は、わざと遅れて返す小さなサーバー（毎回読み込み直す設定）から読み込む（ネットの画像と同じ状況にする）。
設定の置き場所は一時フォルダーへ向ける（利用者の設定を書き換えない）。
"""
import http.server
import json
import os
import struct
import sys
import tempfile
import threading
import time
import zlib

sys.path.insert(0, '.')
sys.path.insert(0, 'tests')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='md_appdata_')
import webview
import mdviewer
import gui_nodialog  # noqa: F401  OS のダイアログを出さない（キー入力を奪うため）

tmp = tempfile.mkdtemp()
DELAY = 0.5


def png(w, h, rgb):
    raw = b''.join(bytes([0]) + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return bytes([137]) + b'PNG' + bytes([13, 10, 26, 10]) + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 1)) + chunk(b'IEND', b'')


IMG = png(900, 500, (60, 120, 200))


class Slow(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(DELAY)
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(IMG)))
        self.send_header('Cache-Control', 'no-store')            # 毎回、読み込み直す
        self.end_headers()
        try:
            self.wfile.write(IMG)
        except OSError:
            pass

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

DOC = os.path.join(tmp, 'img.md')
parts = ["# 画像の多い文書", ""]
for n in range(30):
    parts += [f"## 項目 {n}", "", f"説明の文章です。{n} 番目の項目です。", "", f"![図{n}](http://127.0.0.1:{PORT}/p{n}.png?n={n})", ""]
open(DOC, 'w', encoding='utf-8').write('\n'.join(parts))

api = mdviewer.Api(None)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1400, height=900, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def wait(code, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if js(code):
                return True
        except Exception:
            pass
        time.sleep(.2)
    return False


ALL_LOADED = "[...document.querySelectorAll('#content img')].length === 30 && [...document.querySelectorAll('#content img')].every(i => i.complete && i.naturalWidth > 0)"


def top_heading():
    """いま画面の上端にいちばん近い見出しの文字（読んでいる場所の目印）。"""
    return js("""(() => { const s = document.getElementById('scroll'), t = s.getBoundingClientRect().top;
      const h = [...document.querySelectorAll('#content h2')].filter(e => e.getBoundingClientRect().bottom > t + 1)[0];
      return h ? h.textContent : null; })()""")


def drive():
    time.sleep(6)
    js("openFile(%s)" % json.dumps(DOC))
    check("文書が開いて、遅れて届く画像が、すべて読み込まれる", wait(ALL_LOADED, 60), True)
    time.sleep(.8)
    js("document.getElementById('scroll').scrollTop = 6000; null"); time.sleep(.5)
    before = top_heading()
    print('    読んでいた場所', before, flush=True)

    # 自動更新と同じ: 位置を保って、開き直す
    js("openFile(%s, true)" % json.dumps(DOC))
    wait(ALL_LOADED, 60); time.sleep(2.0)
    check("位置を保って開き直し、画像が読み込まれたあとも、同じ場所を読んでいる", top_heading(), before)
    print('    開き直したあと', top_heading(), flush=True)

    # 戻る・進むと同じ: 前に読んでいた位置を指定して、開く
    js("openFile(%s, false, {top: 6000, left: 0})" % json.dumps(DOC))
    wait(ALL_LOADED, 60); time.sleep(2.0)
    check("前に読んでいた位置を指定して開き、画像が読み込まれたあとも、同じ場所を読んでいる", top_heading(), before)
    print('    開いたあと', top_heading(), flush=True)

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


def watchdog():
    """試験が止まっても、テスト用の画面を残さない。"""
    time.sleep(240)
    print('NG 時間切れ（試験が止まったため、終了した）', flush=True)
    os._exit(1)


threading.Thread(target=drive, daemon=True).start()
threading.Thread(target=watchdog, daemon=True).start()
webview.start()
