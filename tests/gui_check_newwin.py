"""新しいウィンドウで開く入口（一覧の Ctrl+クリック・中クリック・右クリック、リンクの Ctrl+クリック、Ctrl+Shift+N）を、
実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_newwin.py

新しいウィンドウの起動は、実際には行わず、呼ばれた内容を記録する。設定の置き場所は一時フォルダーへ向ける。
"""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, '.')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='md_appdata_')
import webview
import mdviewer
import gui_nodialog  # noqa: F401  OS のダイアログを出さない（キー入力を奪うため）
import multiwin

launched = []
multiwin.launch_self = lambda args: launched.append(list(args)) or True

tmp = tempfile.mkdtemp()
A, B = os.path.join(tmp, 'a.md'), os.path.join(tmp, 'b.md')
open(A, 'w', encoding='utf-8').write('# A\n\n[Bへ](b.md)\n')
open(B, 'w', encoding='utf-8').write('# B\n')

api = mdviewer.Api(None)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1100, height=700, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def wait(code, timeout=12):
    t = time.time()
    while time.time() - t < timeout:
        if js(code):
            return True
        time.sleep(.2)
    return bool(js(code))


def h1():
    return js("(document.querySelector('#content h1') || {}).textContent")


def drive():
    time.sleep(8)
    wait("typeof openInNewWindow === 'function'")
    js("loadFolder(%s, true).then(() => openFile(%s))" % (json.dumps(tmp), json.dumps(A)))
    check("a を開く", wait("(document.querySelector('#content h1') || {}).textContent === 'A'"), True)

    # --- 一覧
    js("document.querySelector('.item[data-rel=\"b.md\"]').dispatchEvent(new MouseEvent('click', {ctrlKey: true, bubbles: true, cancelable: true}))")
    time.sleep(.5)
    check("一覧の Ctrl+クリックで、新しいウィンドウを起動する", launched[-1:], [[B]])
    check("このウィンドウの文書は、そのまま", h1(), 'A')
    check("起動したことを、画面に出す", js("document.getElementById('msg').textContent.includes('新しいウィンドウで開きました')"), True)
    js("document.querySelector('.item[data-rel=\"b.md\"]').dispatchEvent(new MouseEvent('auxclick', {button: 1, bubbles: true, cancelable: true}))")
    time.sleep(.5)
    check("中クリックでも、新しいウィンドウ", launched[-1], [B])
    js("document.querySelector('.item[data-rel=\"b.md\"]').dispatchEvent(new MouseEvent('contextmenu', {clientX: 60, clientY: 160, bubbles: true, cancelable: true}))")
    check("右クリックで、メニューが出る", wait("!document.getElementById('ctx').hidden"), True)
    check("メニューの内容", js("[...document.querySelectorAll('#ctx .citem')].map(b => b.firstChild.textContent)"), ['開く', '新しいウィンドウで開く'])
    check("メニューが、画面に収まる", js("(() => { const r = document.getElementById('ctx').getBoundingClientRect(); return r.right <= innerWidth && r.bottom <= innerHeight && r.left >= 0 })()"), True)
    js("[...document.querySelectorAll('#ctx .citem')].find(b => b.firstChild.textContent === '新しいウィンドウで開く').click()")
    time.sleep(.5)
    check("「新しいウィンドウで開く」で起動する", launched[-1], [B])
    check("選んだら、メニューは閉じる", js("document.getElementById('ctx').hidden"), True)
    js("document.querySelector('.item[data-rel=\"b.md\"]').dispatchEvent(new MouseEvent('contextmenu', {clientX: 60, clientY: 160, bubbles: true, cancelable: true}))")
    wait("!document.getElementById('ctx').hidden")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}))")
    check("Esc で、メニューが閉じる", js("document.getElementById('ctx').hidden"), True)
    js("document.querySelector('.item[data-rel=\"b.md\"]').dispatchEvent(new MouseEvent('contextmenu', {clientX: 60, clientY: 160, bubbles: true, cancelable: true}))")
    wait("!document.getElementById('ctx').hidden")
    js("document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    check("ほかの場所を押すと、メニューが閉じる", js("document.getElementById('ctx').hidden"), True)
    n = len(launched)
    js("document.querySelector('.item[data-rel=\"b.md\"]').click()")
    check("普通のクリックは、これまでどおり、このウィンドウで開く", [wait("(document.querySelector('#content h1') || {}).textContent === 'B'"), len(launched)], [True, n])

    # --- リンク
    js("openFile(%s)" % json.dumps(A))
    wait("(document.querySelector('#content h1') || {}).textContent === 'A'")
    js("[...document.querySelectorAll('#content a')].find(a => a.textContent === 'Bへ').dispatchEvent(new MouseEvent('click', {ctrlKey: true, bubbles: true, cancelable: true}))")
    time.sleep(.8)
    check("リンクの Ctrl+クリックで、新しいウィンドウ", [len(launched), launched[-1]], [n + 1, [B]])
    check("このウィンドウの文書は、そのまま", h1(), 'A')
    js("[...document.querySelectorAll('#content a')].find(a => a.textContent === 'Bへ').click()")
    check("普通のクリックは、このウィンドウで開く", wait("(document.querySelector('#content h1') || {}).textContent === 'B'"), True)

    # --- Ctrl+Shift+N: いまの文書を引き継ぐ
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'N', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true}))")
    time.sleep(.5)
    check("Ctrl+Shift+N で、いま開いている文書を、新しいウィンドウで開く", launched[-1], [B])
    js("closeDocument()")
    time.sleep(.5)
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'N', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true}))")
    time.sleep(.5)
    check("文書が無いときは、いまのフォルダーを引き継ぐ", launched[-1], [tmp])

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
