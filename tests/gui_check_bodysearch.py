"""フォルダー全体の検索（本文を探す）を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_bodysearch.py

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
os.makedirs(os.path.join(tmp, 'sub'))
open(os.path.join(tmp, 'a.md'), 'w', encoding='utf-8').write("# 議事録\n\n漏水の件を報告した。\n\n別の段落\n\n漏水が再発した。 LEAK と leak\n")
open(os.path.join(tmp, 'sub', 'b.md'), 'w', encoding='utf-8').write("# 設計\n漏水調査の計画\n")
open(os.path.join(tmp, 'c.md'), 'w', encoding='utf-8').write("何もない\n")

api = mdviewer.Api(None)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1200, height=800, x=20, y=20)
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


def set_query(q):
    js("(() => { const f = document.getElementById('filter'); f.value = %s; f.dispatchEvent(new Event('input')); })()" % json.dumps(q))


def count_text():
    return js("document.getElementById('count').textContent")


def heads():
    return js("[...document.querySelectorAll('#list .shead')].map(h => h.firstChild.textContent + ':' + h.querySelector('.scnt').textContent)")


def drive():
    time.sleep(8)
    wait("typeof bodyOn === 'function'")
    js("loadFolder(%s, true)" % json.dumps(tmp))
    wait("document.querySelectorAll('#list .item').length === 2")
    check("初めは「本文を探す」は切れている（ファイル名の絞り込み）", js("[document.getElementById('bodySearch').checked, document.getElementById('bodyOpts').hidden, document.getElementById('filter').placeholder]"), [False, True, '🔍 ファイル名で絞り込み'])

    js("document.getElementById('bodySearch').click()")
    check("入れると、オプション（Aa・.*）が出て、入力欄の案内が変わる", js("[document.getElementById('bodyOpts').hidden, document.getElementById('filter').placeholder]"), [False, '🔍 本文を探す語'])
    check("語が空のときは、案内を出す", wait("document.getElementById('count').textContent.includes('探す語を入力')"), True)

    set_query('漏水')
    check("本文を探す: ファイルごとの結果が出る", wait("document.querySelectorAll('#list .shead').length === 2"), True)
    check("ファイル名と、一致した行の数", heads(), ['b.md:1 行', 'a.md:2 行'])
    check("本文検索の結果も、フォルダーごとにまとめる（サブフォルダーが先）", js("[...document.querySelectorAll('#list > div')].map(r => r.classList.contains('dirrow') ? 'D:' + r.querySelector('.dname').textContent.replace('📁 ', '') + '(' + r.querySelector('.dcnt').textContent + ')' : r.classList.contains('shead') ? 'F:' + r.firstChild.textContent : null).filter(x => x)"), ['D:sub(1)', 'F:b.md', 'F:a.md'])
    check("本文検索でも、「すべて開く・閉じる」が使える", js("document.getElementById('treeBtns').hidden"), False)
    js("document.getElementById('treeClose').click()")
    check("「すべて閉じる」で、フォルダーが畳まれる（探した結果は、そのまま）", js("[document.querySelectorAll('#list .dirrow[aria-expanded=false]').length, document.querySelectorAll('#list .shead').length, document.getElementById('count').textContent.includes('2 ファイル')]"), [1, 1, True])
    js("document.getElementById('treeOpen').click()")
    check("「すべて開く」で、また開く", js("document.querySelectorAll('#list .shead').length"), 2)
    check("全体の件数", count_text(), '2 ファイル / 3 行が一致')
    check("一致した行が、行番号と、一致をハイライトして出る", js("[...document.querySelectorAll('#list .shit')].map(r => r.querySelector('.sln').textContent + '|' + r.querySelector('mark').textContent)"), ['2|漏水', '3|漏水', '7|漏水'])
    check("一致しなかったファイル（c.md）は、出ない", js("[...document.querySelectorAll('#list .shead')].some(h => h.textContent.startsWith('c.md'))"), False)

    # --- 大文字小文字
    set_query('leak')
    check("既定は、大文字小文字を区別しない", wait("document.querySelectorAll('#list .shit').length === 1"), True)
    js("document.getElementById('bsCase').click()")
    time.sleep(.8)
    check("区別すると、小文字の leak だけ（大文字の LEAK は、別の語）", js("document.querySelectorAll('#list .shit mark').length") == 1 and js("document.querySelector('#list .shit mark').textContent"), 'leak')
    js("document.getElementById('bsCase').click()")

    # --- 正規表現
    js("document.getElementById('bsRe').click()")
    set_query('漏水(が|調査)')
    check("正規表現で探せる", wait("document.querySelectorAll('#list .shit').length === 2"), True)
    set_query('(')
    check("正規表現が正しくないときは、理由を出す", wait("document.getElementById('count').textContent.includes('正規表現が正しくありません')"), True)
    js("document.getElementById('bsRe').click()")
    set_query('(')
    check("正規表現を切ると、括弧も、そのまま探せる（一致なし）", wait("document.getElementById('count').textContent.includes('見つかりませんでした')"), True)

    # --- 行へ移る（ビューア: 本文の中を同じ語で探し、その行の最初の一致へ）
    set_query('漏水')
    wait("document.querySelectorAll('#list .shit').length === 3")
    js("document.querySelectorAll('#list .shit')[2].click()")
    check("2つ目の一致（7行目）を押すと、a.md を開く", wait("(document.querySelector('#content h1') || {}).textContent === '議事録'"), True)
    check("本文の中の検索バーが開き、同じ語で探している", wait("!document.getElementById('sBar').hidden && document.getElementById('sq').value === '漏水'"), True)
    check("その行の段落（7行目＝data-line 6）の一致が、現在の一致になる",
          wait("(() => { const c = document.querySelector('#content mark.find-hit.cur'); const b = c && c.closest('[data-line]'); return !!b && b.dataset.line === '6'; })()"), True)
    js("document.querySelectorAll('#list .shit')[1].click()")
    check("1つ目の一致（3行目）を押すと、その段落（data-line 2）に移る",
          wait("(() => { const c = document.querySelector('#content mark.find-hit.cur'); const b = c && c.closest('[data-line]'); return !!b && b.dataset.line === '2'; })()"), True)
    check("同じファイルは、開き直さない（読んでいる文書は a.md のまま）", js("current.endsWith('a.md')"), True)

    # --- ファイル名の行を押すと、開くだけ
    js("document.querySelectorAll('#list .shead')[0].click()")
    check("ファイル名を押すと、そのファイルを開く", wait("(document.querySelector('#content h1') || {}).textContent === '設計'"), True)

    # --- 切ると、ファイル一覧に戻る
    check("切る前は、本文にハイライトが付いている", js("document.querySelectorAll('#content mark.find-hit').length > 0"), True)
    js("document.getElementById('bodySearch').click()")
    check("「本文を探す」を切ると、検索バーが閉じ、ハイライトも消える",
          wait("document.getElementById('sBar').hidden && document.querySelectorAll('#content mark.find-hit').length === 0"), True)
    set_query('')
    check("「本文を探す」を切ると、ファイルの一覧に戻る（開いた文書のフォルダは開いている）", wait("document.querySelectorAll('#list .item').length === 3 && document.getElementById('bodyOpts').hidden"), True)
    check("件数の表示も、ファイルの件数に戻る", count_text(), '3 / 3 件')

    # --- 古い検索の結果が、新しい検索を上書きしない
    js("document.getElementById('bodySearch').click()")
    set_query('漏水'); set_query('設計')
    time.sleep(1.6)
    check("続けて語を変えても、最後の語の結果だけが出る", heads(), ['b.md:1 行'])

    # --- フォルダーを変えると、絞り込み欄は空になる（従来どおり）が、「本文を探す」は入ったまま。新しいフォルダーを探す
    other = tempfile.mkdtemp()
    open(os.path.join(other, 'z.md'), 'w', encoding='utf-8').write("設計の別フォルダー\n")
    js("switchFolder(%s)" % json.dumps(other))
    check("フォルダーを変えると、探す語は空になり、案内が出る（「本文を探す」は、入ったまま）",
          wait("document.getElementById('bodySearch').checked && document.getElementById('count').textContent.includes('探す語を入力')", 15), True)
    set_query('設計')
    check("そのフォルダーの本文を探す（前のフォルダーの結果は、出ない）", wait("[...document.querySelectorAll('#list .shead')].map(h => h.firstChild.textContent).join() === 'z.md'", 15), True)

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
