"""HTML への書き出しを、実際の画面で確かめる（ビューア用）。書き出したファイルを読み、別のフレームに描いて、見た目も確かめる。

    .venv\\Scripts\\python tests\\gui_check_htmlexport.py

設定の置き場所は一時フォルダーへ向ける（利用者の設定を書き換えない）。ブラウザーは、実際には開かない。
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

sys.path.insert(0, '.')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='md_appdata_')
os.startfile = lambda p: None                      # 「ブラウザーで開く」を、実際には開かない
import webview
import mdviewer
import gui_nodialog  # noqa: F401  OS のダイアログを出さない（キー入力を奪うため）

tmp = tempfile.mkdtemp()
OUT = os.path.join(tmp, '書き出し.html')
DOC = os.path.join(tmp, 'doc.md')
BAD = os.path.join(tmp, 'bad.md')
open(DOC, 'w', encoding='utf-8').write("""# 議事録のテスト

本文です。**太字**と `code` と [外部リンク](https://example.com) と [見出しへ](#表)。

## 表

| 名前 | 数 |
|---|--:|
| りんご | 3 |

```python
def f(x):
    return x + 1
```

数式: $E = mc^2$ と

$$
\\frac{a}{b}
$$

```mermaid
graph TD
  A[開始] --> B[終了]
```

```vega-lite
{"data": {"values": [{"k": "a", "v": 1}, {"k": "b", "v": 3}]}, "mark": "bar",
 "encoding": {"x": {"field": "k", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
```

![赤い点](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==)
""".replace('\\\\', '\\'))
open(BAD, 'w', encoding='utf-8').write("# 失敗\n\n```mermaid\ngraph TD\n  A --> \n  B[[[\n```\n")

api = mdviewer.Api(None)
api.pick_html_path = lambda *a, **k: OUT
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1300, height=900, x=20, y=20)
api._window = w
results = []


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


def wait(code, timeout=25):
    t = time.time()
    while time.time() - t < timeout:
        if js(code):
            return True
        time.sleep(.25)
    return bool(js(code))


def drive():
    time.sleep(8)
    wait("typeof exportHtml === 'function'")

    # --- 文書が無いときは、書き出さない
    js("exportHtml()")
    check("文書が無いと、書き出さない（知らせる）", wait("document.getElementById('msg').textContent.includes('書き出す文書がありません')"), True)
    check("ファイルも作らない", os.path.exists(OUT), False)

    js("window._asked = []; window._ask = ask; ask = async (t, x, b) => { window._asked.push(t + '||' + x); return 1; }; null")      # 「閉じる」
    js("loadFolder(%s, true).then(() => openFile(%s))" % (json.dumps(tmp), json.dumps(DOC)))
    check("文書が開き、図・グラフ・数式が描かれる", wait("document.querySelector('#content .diagram svg') && document.querySelector('#content .diagram.vega svg') && document.querySelector('#content .katex')"), True)
    # 文書内検索で、ハイライトを付けておく（書き出しに、入らないこと）
    js("document.getElementById('sq').value = 'def'; finder.open(); null")
    check("検索のハイライトが付いている", wait("document.querySelectorAll('#content mark.find-hit').length > 0"), True)

    js("exportHtml()")
    check("書き出しが終わる（完了の画面が出る）", wait("window._asked.length === 1"), True)
    asked = js("window._asked[0]")
    check("完了の画面に、保存先が出る。警告は出ない", [OUT in asked, '※' in asked], [True, False])
    html = open(OUT, encoding='utf-8').read()

    check("先頭は doctype・文字コード・言語の指定", html.startswith('<!doctype html>\n<html lang="ja">') and '<meta charset="utf-8">' in html, True)
    check("題名は、最初の見出し", '<title>議事録のテスト</title>' in html, True)
    check("生成したアプリと版が入る", re.search(r'name="generator" content="Handy Markdown Viewer v\d+\.\d+\.\d+"', html) is not None, True)
    check("スクリプトは入れない", '<script' in html.lower(), False)
    check("外部のファイルを読み込まない", [('<link' in html), ('@import' in html), bool(re.search(r'src="https?:', html))], [False, False, False])
    check("行番号（data-line）・検索のハイライトは入らない", ['data-line' in html, 'find-hit' in html, 'data-src' in html], [False, False, False])
    check("Mermaid と Vega-Lite は、SVG のまま入る（2つ以上）", html.count('<svg') >= 2, True)
    check("数式は、KaTeX の HTML と、そのスタイル（フォントの埋め込み）が入る", [('class="katex"' in html), ('@font-face' in html and 'data:font' in html)], [True, True])
    check("画像は、埋め込み済み", 'src="data:image/png;base64,' in html, True)
    check("外部リンクは、新しいタブで開き、安全な指定を付ける", 'href="https://example.com" target="_blank" rel="noopener noreferrer"' in html, True)
    check("本文用のスタイルが、.md-body として入る（#content ではない）", ('.md-body h1' in html or '.md-body h2' in html) and '#content' not in html, True)
    check("暗い配色（@media prefers-color-scheme）は入らない", 'prefers-color-scheme' in html, False)

    js("""(() => { const f = document.createElement('iframe'); f.id = 'chk'; f.style.cssText = 'position:fixed;left:0;top:0;width:900px;height:700px;opacity:0;pointer-events:none';
        window._loaded = false; f.onload = () => { window._loaded = true; }; f.srcdoc = %s; document.body.appendChild(f); })()""" % json.dumps(html))
    check("書き出した HTML が、そのまま読み込める", wait("window._loaded === true"), True)
    time.sleep(1.0)
    st = json.loads(js("""(() => { const d = document.getElementById('chk').contentDocument, cs = e => d.defaultView.getComputedStyle(e);
        return JSON.stringify({ bg: cs(d.body).backgroundColor, h1: parseFloat(cs(d.querySelector('h1')).fontSize), svgs: d.querySelectorAll('svg').length,
          katexFont: cs(d.querySelector('.katex .mord')).fontFamily.includes('KaTeX'), tableBorder: parseFloat(cs(d.querySelector('th')).borderTopWidth) > 0,
          width: Math.round(d.querySelector('.md-body').getBoundingClientRect().width), anchor: !!d.getElementById('表'),
          img: (() => { const i = d.querySelector('img'); return !!i && i.complete && i.naturalWidth === 1; })() }); })()"""))
    check("背景は白（明るい配色）", st['bg'], 'rgb(255, 255, 255)')
    check("見出しが、本文より大きい", st['h1'] > 20, True)
    check("図・グラフの SVG が、フレームの中でも描かれている", st['svgs'] >= 2, True)
    check("数式が、KaTeX のフォントで組まれている", st['katexFont'], True)
    check("表に、罫線がある（アプリのスタイルが効いている）", st['tableBorder'], True)
    check("本文の幅に、上限がある", st['width'] <= 960, True)
    check("画像が読み込めて、見出しへのリンク先（id）がある", [st['img'], st['anchor']], [True, True])

    check("書き出しても、画面の状態は変わらない（図が残り、検索のハイライトも残る）",
          js("[document.querySelectorAll('#content .diagram svg').length >= 2, document.querySelectorAll('#content mark.find-hit').length > 0]"), [True, True])

    # --- 描けなかった図があると、警告を添える
    js("window._asked = []; openFile(%s)" % json.dumps(BAD))
    wait("document.querySelector('#content .diagram-error')")
    js("exportHtml()")
    check("描けなかった図があると、完了の画面に警告を添える", wait("window._asked.length === 1 && window._asked[0].includes('描けなかった図')"), True)

    # --- 保存先を選ばなければ、何も書かない
    os.remove(OUT)
    api.pick_html_path = lambda *a, **k: None
    js("window._asked = []; null")
    js("exportHtml()")
    time.sleep(3)
    check("保存先を選ばない（キャンセル）と、ファイルは作らず、完了の画面も出ない", [os.path.exists(OUT), js("window._asked.length")], [False, 0])

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
