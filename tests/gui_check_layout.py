"""ツールバーの折り返しと、フォルダーを変えたときの文書の扱いを、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_layout.py

設定の置き場所は一時フォルダーへ向ける（利用者の設定を書き換えない）。
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

tmp = tempfile.mkdtemp()
folder_a = os.path.join(tmp, 'A')
folder_b = os.path.join(tmp, 'B')
for d in (folder_a, folder_b):
    os.makedirs(d)
doc_a = os.path.join(folder_a, 'a.md')
open(doc_a, 'w', encoding='utf-8').write("# Aの文書\n\n本文です。\n")
open(os.path.join(folder_b, 'b.md'), 'w', encoding='utf-8').write("# Bの文書\n")

api = mdviewer.Api(None)
html = mdviewer.build_html()
w = webview.create_window('t', html=html, js_api=api, width=1100, height=700, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def wait(code, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        if js(code):
            return True
        time.sleep(.3)
    return bool(js(code))


def drive():
    time.sleep(7)
    # ---- フォルダーを変えたときの文書の扱い
    js(f"loadFolder({json.dumps(folder_a)}, false).then(() => openFile({json.dumps(doc_a)}))")
    wait("document.querySelector('#content h1') && document.querySelector('#content h1').textContent === 'Aの文書'")
    check("文書が開いている", js("document.querySelector('#content h1') && document.querySelector('#content h1').textContent"), 'Aの文書')
    js(f"switchFolder({json.dumps(folder_a)})")           # 同じフォルダーへ
    time.sleep(1)
    check("同じフォルダーを選び直しても、文書は開いたまま",
          (js("current") is not None, js("document.querySelector('#content h1') ? document.querySelector('#content h1').textContent : ''")), (True, 'Aの文書'))
    js(f"switchFolder({json.dumps(folder_a.upper())})")   # 大文字小文字だけ違う同じフォルダー
    time.sleep(1)
    check("大文字小文字が違うだけの同じフォルダーも、同じ扱い", js("current") is not None, True)

    js(f"switchFolder({json.dumps(folder_b)})")           # 別のフォルダーへ
    wait("current === null")
    time.sleep(1)
    check("別のフォルダーを選ぶと、開いていた文書が閉じる", js("current"), None)
    check("本文は空白の表示（案内が出る）", (js("document.querySelectorAll('#content h1').length"), js("document.getElementById('empty') !== null")), (0, True))
    check("ファイル名の表示も消える", js("document.getElementById('title').textContent"), '')
    check("一覧は新しいフォルダーのものになる", js("files.join(',')"), 'b.md')
    check("新しいフォルダーの案内が出る", '一覧から' in (js("document.getElementById('empty').textContent") or ''), True)
    check("一覧に選択中の行はない", js("document.querySelectorAll('#list .item.sel').length"), 0)
    check("記憶している前回のファイルも消える", 'last_file' in mdviewer.load_settings(), False)
    check("前回のフォルダーは新しいほう", mdviewer.load_settings().get('last_folder'), folder_b)
    js(f"openFile({json.dumps(os.path.join(folder_b, 'b.md'))})")
    check("閉じたあとも、別の文書を開ける", wait("document.querySelector('#content h1') && document.querySelector('#content h1').textContent === 'Bの文書'"), True)

    # ---- 一覧が、時間か件数の上限で途中までのときの表示
    js("listTruncated = true; renderList()")
    check("一覧が途中までのとき、件数の行で知らせる", '途中までです' in js("document.getElementById('count').textContent"), True)
    check("途中までの知らせは、色でも目立たせる", js("document.getElementById('count').style.color") != '', True)
    js("listTruncated = false; renderList()")
    check("途中でなければ、知らせは出ない", '途中' in js("document.getElementById('count').textContent"), False)

    # ---- ツールバーの折り返し
    def toolbar():
        return js("""(() => {
          const t = document.getElementById('toolbar');
          const btns = [...t.querySelectorAll('button')];
          const tops = [...new Set(btns.map(b => Math.round(b.getBoundingClientRect().top)))];
          return JSON.stringify({ maxBtnH: Math.max(...btns.map(b => b.getBoundingClientRect().height)),
                                  rows: tops.length, h: t.getBoundingClientRect().height,
                                  overflowX: t.scrollWidth > t.clientWidth + 1 });
        })()""")
    w.resize(1500, 700)
    time.sleep(1)
    check("広い窓（1500px）では、ツールバーは1行", json.loads(toolbar())['rows'], 1)
    for width in (700, 520, 380):
        w.resize(width, 700)
        time.sleep(1)
        r = json.loads(toolbar())
        check(f"幅{width}px: ボタンが縦長にならない（高さ {r['maxBtnH']:.0f}px）", r['maxBtnH'] < 45, True)
        check(f"幅{width}px: ツールバーは折り返して複数行になる（{r['rows']}行）", r['rows'] >= 2, True)
        check(f"幅{width}px: ツールバーが横にはみ出さない", r['overflowX'], False)
    w.resize(1500, 700)
    time.sleep(1)
    check("窓を広げ直すと、また1行に戻る", json.loads(toolbar())['rows'], 1)

    # hidden 属性の要素は、実際に隠れている（display を指定した CSS が、hidden を打ち消していないか）
    shown = js("[...document.querySelectorAll('[hidden]')].filter(e => getComputedStyle(e).display !== 'none').map(e => e.id || e.className || e.tagName)")
    check("hidden 属性の要素が、すべて隠れている", shown, [])

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
