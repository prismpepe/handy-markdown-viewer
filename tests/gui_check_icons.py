"""Mermaid の Architecture Diagram で、追加アイコン（logos）が描かれることを画面で確かめる（ビューア用）。

    .venv\\Scripts\\python tests\\gui_check_icons.py

設定の置き場所は一時フォルダーへ向ける（利用者の設定を書き換えない）。
"""
import gzip
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

pack = json.loads(gzip.open(os.path.join('vendor', 'icons', 'logos.json.gz'), 'rt', encoding='utf-8').read())


def marker(name):
    """図形の座標データの一部（ID を含まないので、描画時に書き換わらない）。"""
    m = re.search(r'd="([^"]{40,})"', pack['icons'][name]['body'])
    return m.group(1)[:40]


DIAGRAM = """architecture-beta
    group storage(logos:aws)[Storage]
    service slack(logos:slack-icon)[Slack]
    service lambda(logos:aws-lambda)[Lambda] in storage
    service bucket(logos:aws-s3)[Bucket] in storage
    service db(database)[DB]
    slack:R -- L:lambda
    lambda:R -- L:bucket
    bucket:B -- T:db
"""
UNKNOWN = """architecture-beta
    service a(nosuchpack:foo)[A]
    service b(server)[B]
    a:R -- L:b
"""

tmp = tempfile.mkdtemp()
with_icons = os.path.join(tmp, 'icons.md')
open(with_icons, 'w', encoding='utf-8').write("# 構成図\n\n```mermaid\n" + DIAGRAM + "```\n")
unknown = os.path.join(tmp, 'unknown.md')
open(unknown, 'w', encoding='utf-8').write("# 未登録\n\n```mermaid\n" + UNKNOWN + "```\n")

api = mdviewer.Api(with_icons)
html = mdviewer.build_html()
w = webview.create_window('t', html=html, js_api=api, width=1200, height=800, x=20, y=20)
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
        time.sleep(.4)
    return bool(js(code))


def drive():
    time.sleep(8)
    wait("document.querySelectorAll('#content .diagram svg').length >= 1")
    time.sleep(1.5)
    svg = js("document.querySelector('#content .diagram') ? document.querySelector('#content .diagram').innerHTML : ''") or ''
    check("図が描かれる（エラー表示ではない）", (bool(svg), js("document.querySelectorAll('#content .diagram-error').length")), (True, 0))
    for name in ('slack-icon', 'aws-lambda', 'aws-s3'):
        check(f"追加アイコン logos:{name} が描かれる", marker(name) in svg, True)

    js(f"openFile({json.dumps(unknown)})")
    wait("document.querySelectorAll('#content .diagram svg, #content .diagram-error').length >= 1")
    time.sleep(1.5)
    check("未登録のアイコン集でも図は描かれる（落ちない）",
          (js("document.querySelectorAll('#content .diagram svg').length >= 1"), js("document.querySelectorAll('#content .diagram-error').length")), (True, 0))

    print("RESULT", sum(results), "/", len(results), flush=True)
    os._exit(0)


threading.Thread(target=drive, daemon=True).start()
webview.start()
