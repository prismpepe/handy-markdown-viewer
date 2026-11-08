"""ウィンドウへのドロップ（Markdown ファイル1つ／フォルダー1つ）を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_drop.py

エクスプローラーからの本物のドロップは再現できないので、pywebview がネイティブ側で拾うパスの記録
（_dnd_state）を直接書き込み、画面にはドロップのイベントを送る。確かめるのは「イベント → 実パスの
取得 → 対象の判定 → 画面の処理」の経路。設定の置き場所は一時フォルダーへ向ける。
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
from webview.dom import _dnd_state

tmp = tempfile.mkdtemp()
dir_a = os.path.join(tmp, '資料 A')
dir_b = os.path.join(tmp, 'B')
os.makedirs(dir_a)
os.makedirs(dir_b)
doc_a = os.path.join(dir_a, '最初.md')
doc_b = os.path.join(dir_b, '別.md')
txt_b = os.path.join(dir_b, 'メモ.txt')
open(doc_a, 'w', encoding='utf-8').write('# 最初の文書\n')
open(doc_b, 'w', encoding='utf-8').write('# 別のフォルダーの文書\n')
open(txt_b, 'w', encoding='utf-8').write('text')

api = mdviewer.Api(doc_a)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1200, height=800, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def drop(*paths):
    """ネイティブ側が拾うパスの記録を用意し、ドロップのイベントを送る。返り値: 既定の動作を止めたか"""
    for p in paths:
        _dnd_state['paths'].append((os.path.basename(p), p))
    names = json.dumps([os.path.basename(p) for p in paths])
    prevented = js("""(() => {
        const dt = new DataTransfer();
        for (const n of %s) dt.items.add(new File(['x'], n));
        const e = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true });
        document.body.dispatchEvent(e);
        return e.defaultPrevented; })()""" % names)
    time.sleep(2.5)
    return prevented


def title():
    return js("document.getElementById('title').textContent")


def folder():
    return js("document.getElementById('folder').textContent")


def drive():
    time.sleep(8)
    mdviewer._install_drop(w)
    time.sleep(2)
    # 疑似のファイルは、実ファイルを渡すネイティブ呼び出しに通せないので、この呼び出しだけ空にする（本物のドロップでは使われる）
    js("chrome.webview.postMessageWithAdditionalObjects = () => {}")
    check("最初のファイルが開いている", title(), doc_a)

    over = js("""(() => { const e = new DragEvent('dragover', { bubbles: true, cancelable: true });
        document.body.dispatchEvent(e); return e.defaultPrevented; })()""")
    check("ドラッグ中、既定の動作（ブラウザーで開く）を止める", over, True)

    check("Markdown ファイルのドロップ: 既定の動作を止める", drop(doc_b), True)
    check("Markdown ファイルをドロップすると、それが開く", title(), doc_b)
    check("そのファイルのフォルダーの一覧になる", folder(), dir_b)

    check("Markdown 以外のファイルは、既定の動作を止めたうえで無視する", drop(txt_b), True)
    check("Markdown 以外は開かない（表示はそのまま）", title(), doc_b)

    check("複数ファイルのドロップは無視する", drop(doc_a, doc_b) and title(), doc_b)

    drop(dir_a)
    check("フォルダーをドロップすると、そのフォルダーの一覧になる", folder(), dir_a)
    check("フォルダーを変えたので、開いていた文書は閉じる", title(), '')

    drop(doc_b)
    check("続けてファイルをドロップしても開ける", title(), doc_b)

    # 実際のドラッグ中は、dragover が絶え間なく届く。Python へ送ると画面が固まり、ドロップが遅れていた
    t0 = time.time()
    js("for (let i = 0; i < 300; i++) document.body.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true }))")
    check("dragover を300回送っても、画面は固まらない（2秒以内に戻る）", time.time() - t0 < 2, True)
    _dnd_state['paths'].append((os.path.basename(doc_a), doc_a))
    js("""(() => { const dt = new DataTransfer(); dt.items.add(new File(['x'], %s));
        document.body.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); })()""" % json.dumps(os.path.basename(doc_a)))
    t1 = time.time()
    while time.time() - t1 < 10 and title() != doc_a:
        time.sleep(0.1)
    took = time.time() - t1
    print("    ドロップから開くまで: %.2f 秒" % took, flush=True)
    check("大量の dragover のあとでも、ドロップしてすぐ（2秒以内に）開く", took < 2, True)

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
