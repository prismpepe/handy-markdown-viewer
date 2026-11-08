"""戻る・進む（開いたファイルの履歴）を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_nav.py

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
filler = "".join(f"段落{i}です。\n\n" for i in range(150))
files = {
    'a.md': "# A\n\n[Bへ](b.md)\n\n" + filler,
    'b.md': "# B\n\n[Cへ](c.md)\n\n[Aへ戻るリンク](a.md)\n\n" + filler,
    'c.md': "# C\n\n" + filler,
    'd.md': "# D\n",
}
for n, t in files.items():
    open(os.path.join(tmp, n), 'w', encoding='utf-8').write(t)
P = {n: os.path.join(tmp, n) for n in files}

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


def waith(t):
    return wait("(document.querySelector('#content h1') || {}).textContent === %s" % json.dumps(t))


def state():
    return js("[nav.list.map(e => e.path.split('\\\\').pop()).join(','), nav.idx, document.getElementById('btnBack').disabled, document.getElementById('btnFwd').disabled]")


def drive():
    time.sleep(8)
    wait("typeof nav !== 'undefined'")
    check("タイトル行に、戻る・進むのボタンがある", js("[!!document.getElementById('btnBack'), !!document.getElementById('btnFwd')]"), [True, True])
    check("最初は、どちらも押せない", js("[document.getElementById('btnBack').disabled, document.getElementById('btnFwd').disabled]"), [True, True])

    js("loadFolder(%s, true).then(() => openFile(%s))" % (json.dumps(tmp), json.dumps(P['a.md'])))
    check("a を開く", waith('A'), True)
    check("履歴は a だけ。戻れない・進めない", state(), ['a.md', 0, True, True])

    # リンクをたどる（a → b → c）。a では、下へ読み進めておく
    js("document.getElementById('scroll').scrollTop = 500; null")
    time.sleep(.3)
    top_a = js("document.getElementById('scroll').scrollTop")
    js("[...document.querySelectorAll('#content a')].find(a => a.textContent === 'Bへ').click()")
    check("リンクで b に移る", waith('B'), True)
    check("履歴: a, b。戻れる", state(), ['a.md,b.md', 1, False, True])
    js("document.getElementById('scroll').scrollTop = 300; null")
    time.sleep(.3)
    top_b = js("document.getElementById('scroll').scrollTop")
    js("[...document.querySelectorAll('#content a')].find(a => a.textContent === 'Cへ').click()")
    check("リンクで c に移る", waith('C'), True)
    check("履歴: a, b, c", state(), ['a.md,b.md,c.md', 2, False, True])
    check("戻るボタンの説明に、戻り先が出る", js("document.getElementById('btnBack').title.startsWith('戻る: b.md')"), True)

    # 戻る
    js("document.getElementById('btnBack').click()")
    check("戻る → b", waith('B'), True)
    check("b の読んでいた位置に戻る", abs(js("document.getElementById('scroll').scrollTop") - top_b) <= 2, True)
    check("履歴の位置は b。進める", state(), ['a.md,b.md,c.md', 1, False, False])
    js("document.getElementById('btnBack').click()")
    check("戻る → a", waith('A'), True)
    check("a の読んでいた位置に戻る", abs(js("document.getElementById('scroll').scrollTop") - top_a) <= 2, True)
    check("先頭では、戻れない", state()[2:], [True, False])
    js("document.getElementById('btnBack').click()")
    time.sleep(.4)
    check("戻れないときに押しても、何も起きない", [h1(), state()[1]], ['A', 0])

    # 進む
    js("document.getElementById('btnFwd').click()")
    check("進む → b", waith('B'), True)

    # Alt+←・Alt+→
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft', altKey: true, bubbles: true, cancelable: true}))")
    check("Alt+← で戻る（a）", waith('A'), True)
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', altKey: true, bubbles: true, cancelable: true}))")
    check("Alt+→ で進む（b）", waith('B'), True)

    # 戻ってから別のファイルを開くと、進む側は捨てる
    js("document.getElementById('btnBack').click()")
    waith('A')
    js("document.querySelector('.item[data-rel=\"d.md\"]').click()")
    check("一覧から d を開く", waith('D'), True)
    check("途中で別のファイルを開くと、「進む」側は捨てる（a, d）", state(), ['a.md,d.md', 1, False, True])

    # 同じファイルの開き直し・読み直し・自動更新では、履歴は増えない
    js("document.getElementById('btnReload').click()")
    time.sleep(1.0)
    check("読み直しでは、履歴が増えない", state()[0], 'a.md,d.md')
    time.sleep(0.05)
    open(P['d.md'], 'w', encoding='utf-8').write("# D2\n")
    check("自動更新される", waith('D2'), True)
    check("自動更新でも、履歴は増えない", state()[0], 'a.md,d.md')
    js("document.querySelector('.item[data-rel=\"d.md\"]').click()")
    time.sleep(.8)
    check("同じファイルをもう一度開いても、増えない", state()[0], 'a.md,d.md')

    # 消えたファイルは、履歴から外す
    js("document.getElementById('btnBack').click()")
    waith('A')
    js("document.querySelector('.item[data-rel=\"b.md\"]').click()")
    waith('B')
    js("document.getElementById('btnBack').click()")
    waith('A')
    os.remove(P['b.md'])
    js("document.getElementById('btnFwd').click()")
    check("消えたファイルへは進めず、メッセージが出る", wait("document.getElementById('msg').textContent.length > 0 && document.getElementById('msg').style.color !== 'var(--muted)'"), True)
    check("消えたファイルは、履歴から外れる", state()[0], 'a.md')
    check("表示は、そのまま（a）", h1(), 'A')

    # フォルダーを変えると、履歴は空になる
    other = tempfile.mkdtemp()
    open(os.path.join(other, 'z.md'), 'w', encoding='utf-8').write("# Z\n")
    js("switchFolder(%s)" % json.dumps(other))
    time.sleep(1.2)
    check("フォルダーを変えると、履歴は空になる", state(), ['', -1, True, True])

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
