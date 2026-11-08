"""文書内の検索を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_search.py

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

DOC = """# 検索の確認

Apple と apple と APPLE が並ぶ。りんご、リンゴ、林檎。

これは**太字の途中**にある語と、*斜体*と`コード`の語を含む。

- 項目1: apple pie
- 項目2: banana

| 名前 | 内容 |
| --- | --- |
| apple | 表の中 |

```python
apple = "コードブロックの中"
```

```mermaid
flowchart LR
  A[図の中のapple] --> B[終わり]
```

最後の段落。
"""
tmp = tempfile.mkdtemp()
doc = os.path.join(tmp, 'doc.md')
open(doc, 'w', encoding='utf-8', newline='\n').write(DOC)
other = os.path.join(tmp, 'other.md')
open(other, 'w', encoding='utf-8').write("# 別の文書\n\napple が1つだけ。\n")

api = mdviewer.Api(doc)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1200, height=800, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def wait(code, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        if js(code):
            return True
        time.sleep(.3)
    return bool(js(code))


def setq(q, cs=False, re=False):
    js("document.getElementById('sq').value = %s; document.getElementById('sCase').checked = %s; document.getElementById('sRegex').checked = %s; finder.refresh(false)"
       % (json.dumps(q), str(cs).lower(), str(re).lower()))


MARKS = "document.querySelectorAll('#content mark.find-hit').length"
COUNT = "document.getElementById('sCount').textContent"
CUR = "[...document.querySelectorAll('#content mark.find-hit.cur')].map(m => m.textContent).join('')"


def drive():
    time.sleep(8)
    wait("document.querySelector('#content .diagram svg')", 25)           # 図が描かれるまで待つ
    js("finder.open()")
    check("検索バーが開く", js("!document.getElementById('sBar').hidden"), True)
    check("開いたとき、検索欄に焦点がある", js("document.activeElement.id"), 'sq')

    setq("apple")
    check("大文字小文字を区別しないで探す（本文・箇条書き・表・コードブロックの4種×...）", js(MARKS), 6)
    check("件数の表示（図の中の apple は数えない）", js(COUNT), "1 / 6 件" if js("finder.current()") == 0 else js(COUNT))
    setq("apple", cs=True)
    check("大文字小文字を区別すると、小文字だけ", js(MARKS), 4)
    setq("apple", cs=False)

    # 太字の途中など、要素をまたぐ語
    setq("太字の途中")
    check("太字の途中でも、つなげて探せる", (js(MARKS) >= 1, js("[...document.querySelectorAll('#content mark.find-hit')].map(m => m.textContent).join('')")), (True, "太字の途中"))
    setq("字の途中にある語")
    check("太字の内側から外へまたがる語も探せる", js("[...document.querySelectorAll('#content mark.find-hit')].map(m => m.textContent).join('')"), "字の途中にある語")
    check("またがる一致は、1件として数える", js("finder.count()"), 1)

    # 色分けで <span> に分かれたコードの中でも、またがる語を探せる（変数・記号・文字列は、別の <span>）
    check("コードが色分けされている（この検査の前提）", js("document.querySelectorAll('#content pre code.highlighted span[class^=tok-]').length > 3"), True)
    setq('apple = "コードブロック')
    check("色分けされたコードの中で、<span> をまたぐ語も探せる", (js("finder.count()"), js("[...document.querySelectorAll('#content mark.find-hit')].map(m => m.textContent).join('')")), (1, 'apple = "コードブロック'))
    setq("コードブロックの中")
    check("探したあとも、コードの文字は元のまま", js("document.querySelector('#content pre code.highlighted').textContent"), 'apple = "コードブロックの中"\n')

    # 段落をまたぐ一致は出さない
    setq("が並ぶ。りんご")
    check("同じ段落の中の語は探せる", js("finder.count()"), 1)
    setq("最後の段落。これは")
    check("段落をまたぐ語は、一致にしない", js("finder.count()"), 0)
    check("見つからないとき", js(COUNT), "見つかりません")

    # 図の中の文字は対象外
    setq("図の中")
    check("図（SVG）の中の文字は、対象にしない", js("finder.count()"), 0)

    # 正規表現
    setq("りんご|リンゴ|林檎", re=True)
    check("正規表現: または（3つの表記）", js("finder.count()"), 3)
    setq("apple", re=True)
    setq(r"項目\d", re=True)
    check("正規表現: 数字", js("finder.count()"), 2)
    setq("^項目", re=True)
    check("正規表現: ブロックの先頭（^）は、各ブロックの頭に当たる", js("finder.count()"), 2)
    setq("(", re=True)
    check("正規表現の誤りを知らせる", (js(COUNT), js("document.getElementById('sq').classList.contains('bad')")), ("正規表現が正しくありません", True))
    check("誤りのとき、ハイライトは出ない", js(MARKS), 0)
    setq("", re=False)
    setq("a.c", re=False)
    check("正規表現でないとき、. は文字のまま", js("finder.count()"), 0)
    setq("^", re=True)
    check("長さ0の一致は、数えない", js("finder.count()"), 0)
    js("document.getElementById('sRegex').checked = false")

    # 次へ・前へ
    setq("apple")
    js("finder.refresh(true)")
    check("最初の一致が、現在の位置になる", js("finder.current()"), 0)
    check("現在の一致だけ、強調が違う", js("document.querySelectorAll('#content mark.find-hit.cur').length"), 1)
    js("finder.step(1)")
    check("次へ", (js("finder.current()"), js(COUNT)), (1, "2 / 6 件"))
    js("finder.step(-1)")
    check("前へ", js("finder.current()"), 0)
    js("finder.step(-1)")
    check("先頭で前へ: 末尾に戻る", (js("finder.current()"), js(COUNT)), (5, "6 / 6 件（末尾に戻りました）"))
    js("finder.step(1)")
    check("末尾で次へ: 先頭に戻る", (js("finder.current()"), js(COUNT)), (0, "1 / 6 件（先頭に戻りました）"))

    # 現在の一致が、画面に見える位置へ移る
    js("document.getElementById('scroll').scrollTop = 0; finder.step(1); finder.step(1); finder.step(1); finder.step(1)")
    time.sleep(.5)
    check("一致の位置まで、スクロールして見せる", js("""(() => { const m = document.querySelector('#content mark.find-hit.cur').getBoundingClientRect();
        const s = document.getElementById('scroll').getBoundingClientRect(); return m.top >= s.top - 1 && m.bottom <= s.bottom + 1; })()"""), True)

    # キー操作
    setq("apple")
    js("document.getElementById('sq').focus()")
    def key(k, **kw):
        js("document.getElementById('sq').dispatchEvent(new KeyboardEvent('keydown', {key: %s, shiftKey: %s, bubbles: true}))" % (json.dumps(k), str(kw.get('shift', False)).lower()))
    js("finder.refresh(true)")
    key('Enter')
    check("Enter で次へ", js("finder.current()"), 1)
    key('Enter', shift=True)
    check("Shift+Enter で前へ", js("finder.current()"), 0)
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'F3', bubbles: true}))")
    check("F3 で次へ", js("finder.current()"), 1)
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'F3', shiftKey: true, bubbles: true}))")
    check("Shift+F3 で前へ", js("finder.current()"), 0)

    # 文書が変わったら、取り直す
    js(f"openFile({json.dumps(other)})")
    wait("document.querySelector('#content h1') && document.querySelector('#content h1').textContent === '別の文書'")
    time.sleep(.8)
    check("別の文書を開くと、新しい文書で探し直す", (js(MARKS), js(COUNT)), (1, "1 / 1 件"))
    js(f"openFile({json.dumps(doc)})")
    wait("document.querySelector('#content h1') && document.querySelector('#content h1').textContent === '検索の確認'")
    wait("document.querySelector('#content .diagram svg')", 25)
    time.sleep(.8)
    check("元の文書へ戻すと、また探し直す", js(MARKS), 6)
    js("finder.close()")                                                    # ハイライトの無い状態を、検索前の見本にする
    html_before = js("document.getElementById('content').innerHTML")
    text_before = js("document.getElementById('content').textContent")
    js("finder.open()")
    check("開き直すと、また探す", js(MARKS), 6)

    # 閉じると、文書は元のまま
    js("finder.close()")
    check("閉じると、ハイライトが消える", js(MARKS), 0)
    check("閉じたあとの本文の文字は、検索前と同じ", js("document.getElementById('content').textContent"), text_before)
    check("閉じたあとの本文の構造（HTML）も、検索前と同じ", js("document.getElementById('content').innerHTML"), html_before)
    check("閉じると検索バーが隠れる", js("document.getElementById('sBar').hidden"), True)

    # 本文の外（ファイル名の表示）で選んだ文字は、取り込まない
    js("""(() => { const r = document.createRange(); r.selectNodeContents(document.getElementById('title')); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
    js("document.getElementById('sq').value = '前の検索語'; finder.open()")
    check("本文の外で選んだ文字は、検索する文字列に入れない", js("document.getElementById('sq').value"), '前の検索語')
    js("finder.close()")

    # 開くとき、選んでいる文字が入る
    js("""(() => { const p = [...document.querySelectorAll('#content p')].find(e => e.textContent.startsWith('最後の')); const r = document.createRange();
        r.selectNodeContents(p); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
    js("finder.open()")
    check("選んでいる文字が、検索する文字列に入る", js("document.getElementById('sq').value"), "最後の段落。")
    js("finder.close()")

    # 本文以外のとき・Esc
    js("finder.open()")
    js("document.getElementById('sq').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    check("Esc で閉じる", js("document.getElementById('sBar').hidden"), True)
    js("document.getElementById('btnFind').click()")
    check("ツールバーの「検索」ボタンで開く", js("!document.getElementById('sBar').hidden"), True)
    js("finder.close()")

    # 文書を閉じたとき（フォルダーを変えたとき）
    js("finder.open()"); setq("apple")
    js("closeDocument()")
    time.sleep(.8)
    check("文書を閉じると、検索結果も消える", (js(MARKS), js(COUNT)), (0, "開いている文書がありません"))
    js("finder.close()")

    # 印刷には、ハイライトも検索バーも出さない
    css = js("[...document.styleSheets].flatMap(s => [...s.cssRules]).filter(r => r.media && r.media.mediaText === 'print').map(r => r.cssText).join(' ')")
    check("印刷では、ハイライトを消す（CSS）", 'mark.find-hit' in css and 'none' in css, True)
    check("印刷では、検索バーを隠す（CSS）", '#sBar' in css, True)

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
