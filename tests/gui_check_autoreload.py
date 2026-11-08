"""自動更新（他のアプリで保存されたら、表示を作り直す）を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_autoreload.py

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
doc = os.path.join(tmp, 'a.md')
body = "# 題名\n\n" + "".join(f"段落{i}です。\n\n" for i in range(120))
open(doc, 'w', encoding='utf-8').write(body)

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
    wait("typeof watchTick === 'function' && prefs !== undefined")
    check("ツールバーに「自動更新」がある（更新の隣）", js("document.getElementById('btnReload').nextElementSibling.id"), 'btnAuto')
    check("初めは入（押された表示）", js("document.getElementById('btnAuto').classList.contains('active')"), True)
    check("ツールバーは、狭くしても崩れない（ボタンが画面内）", js("[...document.querySelectorAll('#toolbar button')].every(b => b.getBoundingClientRect().right <= innerWidth + 1)"), True)

    js("loadFolder(%s, true).then(() => openFile(%s))" % (json.dumps(tmp), json.dumps(doc)))
    check("文書が開く", wait("document.querySelector('#content h1') !== null"), True)
    check("見出し", h1(), '題名')

    # 読んでいる位置を下げておく
    js("document.getElementById('scroll').scrollTop = 600; null")
    time.sleep(.3)
    top0 = js("document.getElementById('scroll').scrollTop")
    check("スクロールできている", top0 > 300, True)

    # 他のアプリで保存されたことにする
    time.sleep(0.05)
    open(doc, 'w', encoding='utf-8').write(body.replace('# 題名', '# 書き換えた題名'))
    check("書き換えると、自動で表示が更新される（数秒以内）", wait("document.querySelector('#content h1').textContent === '書き換えた題名'", 8), True)
    top1 = js("document.getElementById('scroll').scrollTop")
    check("読んでいる位置は、そのまま保たれる", abs(top1 - top0) <= 2, True)
    check("「更新しました」と知らせる", wait("document.getElementById('msg').textContent.startsWith('更新しました')", 3), True)
    check("知らせは、赤い（エラーの）表示ではない", js("document.getElementById('msg').style.color"), 'var(--muted)')

    # 切ると、更新しない
    js("document.getElementById('btnAuto').click()")
    time.sleep(.4)
    check("切ると、ボタンの押された表示が消える", js("document.getElementById('btnAuto').classList.contains('active')"), False)
    check("切った設定が保存される", api.get_prefs().get('auto_reload'), False)
    open(doc, 'w', encoding='utf-8').write(body.replace('# 題名', '# 切っている間の題名'))
    time.sleep(3.5)
    check("切っている間は、更新しない", h1(), '書き換えた題名')
    js("document.getElementById('btnAuto').click()")
    check("入れ直すと、すぐ追いつく", wait("document.querySelector('#content h1').textContent === '切っている間の題名'", 8), True)

    # 書き込みの途中を読まない: 続けて書き換えている間は読まない（落ち着いてから1回だけ）
    reloads = []
    js("window._n = 0; const o = openFile; openFile = async function(p, k) { window._n++; return o(p, k); }; null")
    for i in range(5):
        open(doc, 'w', encoding='utf-8').write(body.replace('# 題名', f'# 連続{i}') + 'x' * (i + 1))
        time.sleep(0.4)
    check("連続して書き換えている間は、読み込まない", js("window._n"), 0)
    check("落ち着いたら、最後の内容で1回だけ読む", wait("document.querySelector('#content h1').textContent === '連続4'", 8), True)
    time.sleep(2.5)
    check("読み込みは、1回だけ", js("window._n"), 1)

    # 削除・復活
    os.remove(doc)
    check("ファイルが無くなると、知らせる", wait("document.getElementById('msg').textContent.includes('見つかりません')", 5), True)
    check("表示は、そのまま残る", h1(), '連続4')
    open(doc, 'w', encoding='utf-8').write(body.replace('# 題名', '# 復活'))
    check("ファイルが戻ると、また更新される", wait("document.querySelector('#content h1').textContent === '復活'", 8), True)

    # 印刷のダイアログを開いている間は、動かさない
    js("window._printOpen = MdPrint.isOpen; MdPrint.isOpen = () => true; null")
    open(doc, 'w', encoding='utf-8').write(body.replace('# 題名', '# ダイアログ中'))
    time.sleep(3.5)
    check("ダイアログを開いている間は、更新しない", h1(), '復活')
    js("MdPrint.isOpen = window._printOpen; null")
    check("閉じたあと、追いつく", wait("document.querySelector('#content h1').textContent === 'ダイアログ中'", 8), True)

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
