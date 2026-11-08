"""数式（KaTeX）の表示を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_math.py

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

DOC = r"""# 数式の確認

文中の数式 $E=mc^2$ と、金額の $100から$200 は別物です。コード `$a$` は、そのまま。

$$
\int_0^1 x^2\,dx = \frac{1}{3}
$$

```math
x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}
```

| 式 | 意味 |
| --- | --- |
| $a^2+b^2=c^2$ | 三平方の定理 |

誤りの数式（文中）: $\foo{x}$ です。

$$
\frac{1
$$

最後の段落。
"""
tmp = tempfile.mkdtemp()
doc = os.path.join(tmp, 'math.md')
open(doc, 'w', encoding='utf-8', newline='\n').write(DOC)

api = mdviewer.Api(doc)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1200, height=900, x=20, y=20)
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
        if js(code):
            return True
        time.sleep(.3)
    return bool(js(code))


def count(sel):
    return js("document.querySelectorAll(%s).length" % json.dumps(sel))


def drive():
    time.sleep(8)
    ok = wait("document.querySelectorAll('#content .math.typeset').length >= 6")
    check("数式が組まれる（6 個: 文中2・表1・ブロック3）", (ok, count('#content .math.typeset')), (True, 6))
    time.sleep(1)

    check("正しい数式は KaTeX で組まれる（4 個: 文中の 2 個と、ブロックの 2 個）", count('#content .math:not(.math-error) .katex'), 4)
    check("独立した行の数式は、中央に置く表示（$$ と ```math の 2 個）", count('#content .math.block .katex-display'), 2)
    check("表のセルの中の数式も組まれる", count('#content td .math .katex'), 1)
    check("```math は、コードブロックとして残らない", count('#content pre'), 0)

    check("金額の文は、数式にならず、そのまま残る", js("document.querySelector('#content p').textContent.includes('$100から$200')"), True)
    check("コードの中の $a$ は、数式にならない", js("(() => { const c = document.querySelector('#content p code'); return c && c.textContent === '$a$' && !c.querySelector('.katex'); })()"), True)

    # 誤りは、黙って消さず、その位置に原文と理由を見せる
    check("誤りの数式（文中）: 原文が残り、理由を title に持つ",
          js("(() => { const e = document.querySelector('#content span.math-error'); return e ? [e.textContent, /Undefined control sequence|foo/i.test(e.title), e.title.startsWith('数式を組めませんでした')] : null; })()"),
          ['$\\foo{x}$', True, True])
    check("誤りの数式（ブロック）: 原文と、理由が見える",
          js("(() => { const e = document.querySelector('#content div.math-error'); return e ? [e.querySelector('code').textContent.includes('\\\\frac{1'), (e.querySelector('.math-error-msg') || {}).textContent.startsWith('数式を組めませんでした')] : null; })()"),
          [True, True])
    check("誤りの数式の、枠は赤（ブロック）", js("(() => { const e = document.querySelector('#content div.math-error'); return getComputedStyle(e).borderTopColor !== getComputedStyle(e).backgroundColor && getComputedStyle(e).borderTopWidth === '1px'; })()"), True)

    # 見た目
    check("数式のフォント（KaTeX_Main）が読み込まれている", js("document.fonts.check('16px KaTeX_Main') && [...document.fonts].some(f => f.family.includes('KaTeX') && f.status === 'loaded')"), True)
    check("数式の文字色は、本文と同じ（ダークモードでも読める）", js("getComputedStyle(document.querySelector('#content .katex')).color === getComputedStyle(document.querySelector('#content p')).color"), True)
    check("独立した行の数式は、横にはみ出さない", js("(() => { const b = document.querySelector('#content .math.block'); return b.scrollWidth <= b.clientWidth + 1; })()"), True)
    check("独立した行の数式は、中央に寄る", js("(() => { const b = document.querySelector('#content .math.block'); const k = b.querySelector('.katex').getBoundingClientRect(), r = b.getBoundingClientRect(); return Math.abs((k.left + k.width / 2) - (r.left + r.width / 2)) < 4; })()"), True)

    # 検索: 数式の中は対象外（KaTeX の部品が、検索の印で壊れないように）
    js("finder.open()")
    js("document.getElementById('sq').value = '三平方'; finder.refresh(false)")
    check("検索は、数式の外の文字を探せる", count('#content mark.find-hit'), 1)
    js("document.getElementById('sq').value = 'c'; finder.refresh(false)")
    check("検索の印は、数式（.katex）の中に入らない", count('#content .katex mark.find-hit'), 0)
    js("finder.close()")

    # 別の文書へ移って戻っても、組み直される
    other = os.path.join(tmp, 'other.md')
    open(other, 'w', encoding='utf-8').write("# 数式なし\n\nふつうの文章です。\n")
    js("openFile(%s)" % json.dumps(other))
    time.sleep(2)
    check("数式のない文書では、数式の部品を使わない（数式 0）", count('#content .math'), 0)
    js("openFile(%s)" % json.dumps(doc))
    ok = wait("document.querySelectorAll('#content .math.typeset').length >= 6")
    check("数式のある文書へ戻ると、組み直される", (ok, count('#content .math:not(.math-error) .katex')), (True, 4))

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
