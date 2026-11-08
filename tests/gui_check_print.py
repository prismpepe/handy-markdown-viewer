"""印刷・PDF 出力を、実際の画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_print.py

設定の置き場所は一時フォルダーへ向ける（利用者の設定を書き換えない）。PDF も一時フォルダーへ作る。
プリンターへは実際には送らない（存在しないプリンター名で、失敗の扱いだけ確かめる）。
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
import webview
import mdviewer
import gui_nodialog  # noqa: F401  OS のダイアログを出さない（キー入力を奪うため）
import printing

tmp = tempfile.mkdtemp()
long_md = os.path.join(tmp, 'long.md')
body = ["# 長い文書", ""]
for i in range(70):
    body += [f"## 見出し{i}", "", f"本文の段落 {i}。" + "文章が続きます。" * 12, ""]
open(long_md, 'w', encoding='utf-8', newline='\n').write("\n".join(body))

short_md = os.path.join(tmp, 'short.md')
open(short_md, 'w', encoding='utf-8').write("# 短い\n\n一行だけ。\n")

cols = 14
rows = ["| " + " | ".join(f"項目{c}の見出し" for c in range(cols)) + " |", "|" + "---|" * cols]
for r in range(10):
    rows.append("| " + " | ".join(f"ABCDEFGH{10000 + r * cols + c}" for c in range(cols)) + " |")
wide_md = os.path.join(tmp, 'wide.md')
open(wide_md, 'w', encoding='utf-8').write("# 幅広の表\n\n" + "\n".join(rows) + "\n")

api = mdviewer.Api(long_md)
w = webview.create_window('t', html=mdviewer.build_html(), js_api=api, width=1300, height=800, x=20, y=20)
api._window = w
results = []

PB = {
    'none': "# 一\n\n本文\n\n# 二\n\n本文\n",
    'class': "# 一\n\n本文\n\n<div class=\"page-break\"></div>\n\n# 二\n\n本文\n",
    'three': "# 一\n\n<div class=\"page-break\"></div>\n\n# 二\n\n<div style=\"page-break-after: always;\"></div>\n\n# 三\n\n<div class=\"pagebreak\"></div>\n\n# 四\n",
    'before': "# 一\n\n本文\n\n<p class=\"page-break-before\">ここから次のページ</p>\n\n本文\n",
    'after': "<p class=\"page-break-after\">一ページ目だけ</p>\n\n二ページ目\n",
    'inline': "# 一\n\n本文\n\n<div style=\"color:red; break-before: page\">二ページ目</div>\n",
    'trailing': "# 一\n\n本文\n\n<div class=\"page-break\"></div>\n",
}


def js(code):
    return w.evaluate_js(code)


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(('OK ' if ok else 'NG ') + name + ('' if ok else f'\n    実際: {got!r}\n    期待: {want!r}'), flush=True)


BASE = dict(paper='A4', landscape=False, margin='標準', scale=1.0, backgrounds=True, header_footer=True,
            title='long.md', uri=long_md, printer='', copies=1, mono=False)


def pages(**kw):
    r = api.print_count({**BASE, **kw})
    return r['pages'] if r['ok'] else r


def pdf(ranges, **kw):
    path = os.path.join(tmp, f"out_{len(os.listdir(tmp))}.pdf")
    r = api.print_save_pdf({**BASE, **kw}, ranges, path)
    if not r['ok']:
        return r
    data = open(path, 'rb').read()
    media = re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)', data)
    return {'pages': printing.count_pdf_pages(data), 'head': data[:5],
            'size': (float(media.group(1)), float(media.group(2))) if media else None}


def open_doc(path):
    js(f"openFile({json.dumps(path)})")
    time.sleep(2.5)


# ---- 図・グラフの日本語が、PDF で Type3 フォントにならないこと（Acrobat Reader の警告「T3Font_n を抽出できません」の原因）
import zlib
VEGA_SPEC = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "title": "売上の推移",
             "data": {"values": [{"月": "一月", "売上": 3}, {"月": "二月", "売上": 5}]}, "mark": "bar",
             "encoding": {"x": {"field": "月", "type": "nominal"}, "y": {"field": "売上", "type": "quantitative"}}}
FONT_DOCS = {
    'mermaid': "# 図\n\n```mermaid\nflowchart LR\n  A[開始] --> B{判断}\n  B -->|はい| C[処理]\n  B -->|いいえ| D[終了]\n```\n",
    'symbols': "# 記号\n\nボタン 📁 📄 🔍 💾 🔗 と ▦ ① → ✓ ⚠ ★ の記号\n",
    'mermaid_emoji': "```mermaid\nflowchart LR\n  A[🙂 開始] --> B[📄 文書]\n```\n",
    'vega': "# グラフ\n\n```vega-lite\n" + json.dumps(VEGA_SPEC, ensure_ascii=False) + "\n```\n",
    # 色分けしたコード（日本語のコメント・記号つき）。色は付くが、字体は変えないので、Type3 にならない
    # 数式（KaTeX のフォント）。フォントは静的な woff2 なので、Type3 にならない。PDF にフォント名が出る
    'math': ("# 数式\n\n文中の数式 $E=mc^2$ と $\\alpha+\\beta$、日本語 $\\text{確率}$。\n\n"
             "$$\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n$$\n\n"
             "```math\n\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}\\ \\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\\ \\mathbb{R}\\ \\mathcal{L}\\ \\mathfrak{g}\n```\n"),
    'code': ("# コード\n\n```bat\n@echo off\nREM バッチのコメント\nset NAME=世界\nif exist \"%~dp0a.txt\" (echo 「%NAME%」) else goto :end\n:end\n```\n\n"
             "```powershell\n# 日本語コメント → 矢印 ✓\nfunction Get-Foo($a) { Write-Host \"値: $a\" }\n```\n\n"
             "```bash\n#!/bin/bash\n# コメント ★\nNAME=\"あ\"; if [ -f \"$NAME\" ]; then echo \"${NAME}\"; fi\n```\n\n"
             "```python\ndef f(x: int) -> str:\n    \"\"\"説明\"\"\"\n    return f\"{x}\"  # 末尾コメント\n```\n"),
}


def type3_count(data):
    blobs = [data]
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', data, re.S):
        try:
            blobs.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    return len(re.findall(rb'/Subtype\s*/Type3', b'\n'.join(blobs)))


def drive():
    time.sleep(8)
    n = pages()
    check("長い文書は複数ページになる", isinstance(n, int) and n >= 5, True)
    print("    A4 縦の全ページ数:", n, flush=True)
    check("A3 のほうがページ数は少ない", pages(paper='A3') < n, True)
    check("横向きのほうがページ数は多い", pages(landscape=True) > n, True)
    check("倍率を下げるとページ数が減る", pages(scale=0.5) < n, True)

    full = pdf('')
    check("全ページの PDF（先頭が %PDF）", (full['head'], full['pages']), (b'%PDF-', n))
    check("A4 縦の用紙サイズ", tuple(round(v) for v in full['size']), (595, 842))
    check("ページ指定 2 → 1ページ", pdf('2')['pages'], 1)
    check("ページ指定 1-3 → 3ページ", pdf('1-3')['pages'], 3)
    check("ページ指定 1-2,4 → 3ページ", pdf('1-2,4')['pages'], 3)
    land = pdf('1', landscape=True)
    check("横向きの用紙サイズ（幅 > 高さ）", land['size'][0] > land['size'][1], True)
    check("A3 の用紙サイズ", tuple(round(v) for v in pdf('1', paper='A3')['size']), (842, 1191))

    # 画面の部品（ツールバー・一覧）は紙に出ない: 短い文書は1ページ
    open_doc(short_md)
    check("短い文書は1ページ（画面の部品は紙に出ない）", pages(), 1)

    # 改ページ（class / style）: 実際の PDF のページ数で確かめる
    def pb(name):
        p = os.path.join(tmp, f'pb_{name}.md')
        open(p, 'w', encoding='utf-8', newline='\n').write(PB[name])
        open_doc(p)
        return pages(uri=p)
    check("改ページが無ければ1ページ", pb('none'), 1)
    check("class=page-break で2ページ", pb('class'), 2)
    check("class と style と pagebreak の混在で4ページ", pb('three'), 4)
    check("class=page-break-before で次のページへ", pb('before'), 2)
    check("class=page-break-after の後ろが次のページ", pb('after'), 2)
    check("style の改ページは通り、他の style（color）は無視される", pb('inline'), 2)
    print("    末尾の改ページ（空白ページが増えるか）:", pb('trailing'), flush=True)
    pb('class')
    check("画面には何も表示しない（高さ0・線なし・文字なし）", js("""(() => { const e = document.querySelector('#content .page-break');
        const c = getComputedStyle(e), a = getComputedStyle(e, '::after');
        return [e.getBoundingClientRect().height, c.borderTopStyle, c.borderBottomStyle, a.content]; })()"""), [0, 'none', 'none', 'none'])

    # 印刷ダイアログ
    open_doc(wide_md)
    js("openPrint()")
    time.sleep(3)
    check("印刷ダイアログが開く", js("document.getElementById('pveil').classList.contains('show')"), True)
    js("var f=document.getElementById('pFit'); f.checked=false; f.dispatchEvent(new Event('change'))")
    off = js("MdPrint.currentOptions().scale")
    js("var f=document.getElementById('pFit'); f.checked=true; f.dispatchEvent(new Event('change'))")
    on = js("MdPrint.currentOptions().scale")
    print("    幅広の表: 縮小なしの倍率 =", off, " 縮小ありの倍率 =", on, flush=True)
    check("縮小しない設定では、倍率は指定どおり（100%）", off, 1.0)
    check("幅の広い表は、縮小する設定にすると倍率が下がる", 0.2 <= on < 1.0, True)
    js("var s=document.getElementById('pPaper'); s.value='A3'; s.dispatchEvent(new Event('change'))")
    check("用紙が大きいほど、縮小は小さくて済む", js("MdPrint.currentOptions().scale") >= on, True)
    js("var s=document.getElementById('pPaper'); s.value='A4'; s.dispatchEvent(new Event('change'))")
    js("document.querySelector('input[name=pOri][value=l]').click()")
    check("横向きは幅が広いので、縮小は小さくて済む", js("MdPrint.currentOptions().scale") >= on, True)
    js("document.querySelector('input[name=pOri][value=p]').click()")
    check("ヘッダーに文書名が入る設定", js("MdPrint.currentOptions().title"), 'wide.md')

    js("document.querySelector('input[name=pRange][value=some]').click()")
    js("var e=document.getElementById('pRanges'); e.value='5-1'; e.dispatchEvent(new Event('input'))")
    time.sleep(1)
    check("逆順の指定は誤りと表示される", js("document.getElementById('pRanges').classList.contains('bad')"), True)
    js("var e=document.getElementById('pRanges'); e.value='1'; e.dispatchEvent(new Event('input'))")
    time.sleep(1.5)
    check("正しい指定は受け付けられる", (js("document.getElementById('pRanges').classList.contains('bad')"),
                                      js("document.getElementById('pRangeInfo').textContent")), (False, '1 ページを出力します'))
    js("var e=document.getElementById('pRanges'); e.value='9'; e.dispatchEvent(new Event('input'))")
    time.sleep(1)
    check("全ページ数を超える指定は誤りと表示される", js("document.getElementById('pRanges').classList.contains('bad')"), True)
    js("document.querySelector('input[name=pRange][value=all]').click()")
    check("「すべて」に戻すと指定欄は無効になる", js("document.getElementById('pRanges').disabled"), True)
    js("document.querySelector('input[name=pMode][value=pdf]').click()")
    check("PDF 保存を選ぶとプリンター欄が隠れ、ボタンが変わる",
          (js("document.getElementById('pPrintOnly').style.display"), js("document.getElementById('pRun').textContent")), ('none', 'PDF を保存…'))
    js("document.querySelector('input[name=pMode][value=print]').click()")
    js("document.getElementById('pClose').click()")
    time.sleep(.5)
    check("閉じられる", js("document.getElementById('pveil').classList.contains('show')"), False)
    check("設定が保存される（次回の初期値になる）", mdviewer.load_settings().get('print', {}).get('paper'), 'A4')

    # 文書が開いていないとき
    js("current = null")
    js("openPrint()")
    time.sleep(.5)
    check("文書がなければダイアログは開かず、案内を出す",
          (js("document.getElementById('pveil').classList.contains('show')"), js("document.getElementById('msg').hidden")), (False, False))

    bad = api.print_send({**BASE, 'printer': '存在しないプリンター'}, '')
    check("存在しないプリンターは失敗として返る（落ちない）", bad['ok'], False)

    saved = mdviewer.load_settings().get("print", {})
    check("ページ範囲は保存されない（次回は「すべて」から始まる）", ("ranges" in saved, "rangeAll" in saved), (False, False))

    # 図・グラフの日本語、絵文字・記号は、Type3 フォントにならない（Reader の警告の原因）。図のフォントが日本語を持たない場合（Segoe UI）も同じ
    for kind in ('mermaid', 'vega', 'symbols', 'mermaid_emoji', 'code', 'math'):
        for fam in ('', 'Segoe UI'):
            js("prefs.fonts = Object.assign({}, prefs.fonts, {diagram: {family: %s}}); applyFonts();" % json.dumps(fam))
            fp = os.path.join(tmp, f"fontdoc_{kind}.md")
            open(fp, 'w', encoding='utf-8', newline='\n').write(FONT_DOCS[kind])
            open_doc(fp)
            time.sleep(4)
            out = os.path.join(tmp, f"fonts_{kind}_{len(os.listdir(tmp))}.pdf")
            r = api.print_save_pdf({**BASE, 'uri': fp}, '', out)
            check("%s の日本語は Type3 フォントにならない（図のフォント: %s）" % (kind, fam or '既定'),
                  type3_count(open(out, 'rb').read()) if r['ok'] else r, 0)
    js("prefs.fonts = Object.assign({}, prefs.fonts, {diagram: {family: ''}}); applyFonts();")

    # 色分けしたコードは、PDF にも色つきの文字で出る（明るい配色。ダークモードでも、印刷は明るい背景用）
    fp = os.path.join(tmp, "fontdoc_code.md")
    open_doc(fp)
    time.sleep(3)
    out = os.path.join(tmp, "code_colors.pdf")
    r = api.print_save_pdf({**BASE, 'uri': fp}, '', out)
    data = open(out, 'rb').read()
    streams = [data]
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', data, re.S):
        try:
            streams.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    fills = set(re.findall(rb'([\d.]+ [\d.]+ [\d.]+) rg', b'\n'.join(streams)))
    check("色分けしたコードは、PDF に色つきの文字で出る（文字色が3種類以上）", (r['ok'], len(fills) >= 3), (True, True))
    print("    PDF の文字色の種類:", len(fills), flush=True)


    # 数式の PDF: KaTeX のフォントで出る（数式が、画像や空白にならない）。Type3 でないことは、上のループで確かめた
    fp = os.path.join(tmp, "fontdoc_math.md")
    open_doc(fp)
    time.sleep(3)
    out = os.path.join(tmp, "math.pdf")
    r = api.print_save_pdf({**BASE, 'uri': fp}, '', out)
    data = open(out, 'rb').read()
    check("数式の PDF に、KaTeX のフォントが埋め込まれる（数式が文字として出る）", (r['ok'], b'KaTeX_Main' in data, b'KaTeX_Math' in data), (True, True, True))

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
