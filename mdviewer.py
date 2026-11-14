"""Handy Markdown Viewer（Windows）。

使い方:
    MarkdownViewer.exe [ファイル.md | フォルダー]
    MarkdownViewer.exe --register     エクスプローラーの「プログラムから開く」に登録
    MarkdownViewer.exe --unregister   登録を解除

描画は Edge の WebView2（Windows 11 に標準で入っている）。Markdown は
Python 側で HTML にして画面へ渡す。文書に埋め込まれた HTML は sanitize.py で
許可したタグだけ残す（表などは表示し、スクリプトは動かさない）。
"""
import base64
import gzip
import ctypes
import json
import mimetypes
import os
import re
import sys
import time
import webbrowser

import autolink
import cjk_emphasis
import dialogs
import deck
import filedrop
import highlight
import mdext
import foldersearch
import mathtex
import multiwin
import printing
import shellreg
import uiprefs
from sanitize import sanitize

MD_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")
APP_VERSION = "1.16.1"          # 画面上部（ウィンドウのタイトル）などに出すバージョン。ここだけ書き換える
APP_TITLE = f"Handy Markdown Viewer v{APP_VERSION}"
PROG_ID = "MarkdownViewer.File"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_FILES = 5000
SCAN_SECONDS = 10          # 一覧の読み込みに使う時間の上限（秒）
MAX_INLINE_IMAGE = 20 * 1024 * 1024
DATA_EXTENSIONS = (".csv", ".tsv", ".json")   # Vega-Lite の data.url で読めるローカルファイル
MAX_DATA_FILE = 20 * 1024 * 1024
# 文書内のリンクから、関連づけられたアプリで開いてよいローカルファイル。
# 実行ファイル・スクリプト・ショートカット・マクロ付き Office などは含めない
OPEN_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf",
    ".odt", ".ods", ".odp", ".txt", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
)


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


WINDOW_MARK = "Handy Markdown Viewer"            # 自分のウィンドウを見分けるための、タイトルの一部（複数のウィンドウを、ずらして開くため）


def settings_path():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "MarkdownViewer", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    multiwin.write_json_atomic(settings_path(), data)      # 複数のウィンドウが、同時に書いても、壊れない（一時ファイル→置き換え）


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def is_markdown(path):
    return path.lower().endswith(MD_EXTENSIONS)


def scan_markdown(folder, max_seconds=SCAN_SECONDS):
    """フォルダー以下の Markdown を相対パスで返す（サブフォルダーも含む）。(一覧, 途中で打ち切ったか)

    ドライブ全体やホームのような巨大なフォルダーを開いても、長く待たされないよう、件数（MAX_FILES）か
    時間（max_seconds）の上限に達したら、そこまでの一覧を返す。
    """
    found = []
    deadline = time.monotonic() + max_seconds
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if is_markdown(name):
                rel = os.path.relpath(os.path.join(root, name), folder)
                found.append(rel.replace("\\", "/"))
                if len(found) >= MAX_FILES:
                    return found, True
        if time.monotonic() >= deadline:
            return found, True
    return found, False


def list_markdown(folder):
    """フォルダー以下の Markdown を相対パスで返す（上限の扱いは scan_markdown と同じ）。"""
    return scan_markdown(folder)[0]


from markdown_it.common.utils import escapeHtml


BAD_LINK = re.compile(r"^(vbscript|javascript|data):", re.I)
GOOD_DATA_IMAGE = re.compile(r"^data:image/(gif|png|jpeg|webp);", re.I)


def validate_link(url):
    """markdown-it の標準の判定から、file: だけを許す。実際に出してよい書き方かは、sanitize と Api.open_local が決める。"""
    url = url.strip()
    return not BAD_LINK.match(url) or bool(GOOD_DATA_IMAGE.match(url))


LINE_TOKENS = {"paragraph_open", "heading_open", "bullet_list_open", "ordered_list_open",
               "list_item_open", "blockquote_open", "table_open", "tr_open", "hr"}


def make_renderer():
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = MarkdownIt("commonmark", {"html": True})
    md.validateLink = validate_link   # 標準では file: を拒み、file:/// の画像が文字のまま出る
    cjk_emphasis.apply(md)       # 日本語の文で、記号に接した ** が強調になるようにする
    autolink.apply(md)           # 文中の URL（https://… や www.…）を、そのままリンクにする（GFM の拡張）
    md.enable(["table", "strikethrough"])
    mathtex.apply(md)            # 数式（```math、$$ ... $$、文中の $...$）。組版は画面側の KaTeX
    md.use(tasklists_plugin)
    mdext.apply(md)             # 脚注・Qiita の :::note・GitHub のアラート（[!NOTE]）
    md.use(anchors_plugin, min_level=1, max_level=6)

    def add_lines(state):
        # 本文のブロックに、元の文書の行番号（data-line）を付ける。フォルダー全体の検索で、結果の行へ移るために使う
        for tok in state.tokens:
            if tok.map and tok.type in LINE_TOKENS:
                tok.attrSet("data-line", str(tok.map[0]))

    md.core.ruler.push("source_lines", add_lines)

    def image(self, tokens, idx, options, env):
        tok = tokens[idx]
        tok.attrSet("src", inline_image(tok.attrGet("src") or "", env.get("base", "")))
        tok.attrSet("alt", self.renderInlineAsText(tok.children, options, env))
        return self.renderToken(tokens, idx, options, env)

    def fence(self, tokens, idx, options, env):
        tok = tokens[idx]
        if tok.info.strip().split(" ")[0].lower() == "mermaid":
            return ('<pre class="mermaid-src"><code>'
                    + escapeHtml(tok.content) + "</code></pre>")
        if highlight.language_of(tok.info) == mathtex.LANG:         # ```math は、数式として画面で組む
            return mathtex.block_html(tok.content)
        head = mdext.filename_html(tok.info)                        # ```ruby:app.rb は、ファイル名を上に出す
        colored = highlight.render_fence(tok.content, tok.info)     # 言語名つきのコードは、色分けする
        if colored is not None:
            return head + colored
        return head + default_fence(tokens, idx, options, env)

    default_fence = md.renderer.fence
    md.add_render_rule("image", image)
    md.add_render_rule("fence", fence)
    return md


def inline_image(src, base):
    """相対パスの画像は data URI にして埋め込む（読み込み元を持たない画面のため）。"""
    if not src or src.startswith(("http://", "https://", "data:")):
        return src
    from urllib.parse import unquote
    path = unquote(src.split("#")[0].split("?")[0])
    if path.lower().startswith("file:///"):
        path = path[8:]
    if os.name == "nt" and path[:1] in ("/", "\\") and path[:2] not in ("//", "\\\\"):
        path = os.path.splitdrive(base)[0] + path     # ドライブを省いた /Users/… は、文書と同じドライブとみなす
    elif not os.path.isabs(path):
        path = os.path.join(base, path)
    try:
        if os.path.getsize(path) > MAX_INLINE_IMAGE:
            return src
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return src
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{mime};base64,{data}"


def initial_dir(initial):
    """ダイアログの開始位置。開いているフォルダー → 前回 → 起動したフォルダー の順。"""
    if initial and os.path.isdir(initial):
        return initial
    last = load_settings().get("last_folder")
    if last and os.path.isdir(last):
        return last
    return os.getcwd()


class Api:
    def __init__(self, start_path):
        self._window = None
        self.md = make_renderer()
        self.start_path = start_path
        self._deck = deck.DeckHost(resource_path, lambda: os.path.dirname(settings_path()), lambda patch: self.set_prefs(patch))
        self._mermaid = None
        self._vendor = {}
        self._doc_dir = None      # いま開いている文書のフォルダー（Vega-Lite のデータ読み込みの基準）
        self._fonts = None
        # ファイル名を指定して起動したときは、その回の使用フォルダー・開いたファイルを記憶しない
        # （次回の起動で、そのフォルダーが「前回のフォルダー」として復元されないように）。
        # 「フォルダーを開く」「ファイルを開く」で利用者が選び直したら、記憶を再開する
        self._persist_location = not (start_path and os.path.isfile(start_path))

    # --- 画面から呼ばれる ---------------------------------------------------
    def get_initial(self):
        settings = load_settings()
        start = self.start_path
        result = {"folder": None, "file": None,
                  "last_folder": settings.get("last_folder"), "error": None}
        if start:
            if os.path.isdir(start):
                result["folder"] = start
            elif os.path.isfile(start):
                result["file"] = start
                result["folder"] = os.path.dirname(start)
            else:
                result["error"] = f"見つかりません: {start}"
        else:
            # 何も指定しない起動: 前回のフォルダー（と開いていたファイル）をそのまま復元する
            last = settings.get("last_folder")
            if last and os.path.isdir(last):
                result["folder"] = last
                last_file = settings.get("last_file")
                if (last_file and os.path.isfile(last_file)
                        and os.path.normcase(os.path.abspath(last_file)).startswith(
                            os.path.normcase(os.path.abspath(last)) + os.sep)):
                    result["file"] = last_file
        return result

    def pick_folder(self, initial=None):
        path = dialogs.pick_folder(initial_dir(initial))
        if path:
            self._persist_location = True
        return path

    def pick_file(self, initial=None):
        path = dialogs.pick_file(initial_dir(initial))
        if path:
            self._persist_location = True
        return path

    def open_in_new_window(self, path=None):
        """新しいウィンドウ（別のプロセス）で、Markdown ファイルかフォルダーを開く。path が無ければ、空のウィンドウ。
        開けるのは、Markdown ファイルかフォルダーだけ（画面から、任意の実行ファイルなどを起動させない）。"""
        args = []
        if path:
            if not isinstance(path, str) or not (os.path.isdir(path) or (os.path.isfile(path) and is_markdown(path))):
                return {"error": "新しいウィンドウでは開けません: %s" % path}
            args = [os.path.abspath(path)]
        if not multiwin.launch_self(args):
            return {"error": "新しいウィンドウを開けませんでした"}
        return {"error": None}

    def search_folder(self, folder, query, case=False, regex=False, overrides=None):
        """フォルダーの中の Markdown ファイルの本文を探し、一致した行を返す（foldersearch.py）。
        新しい検索が始まったら、前の検索は、そこで取りやめる。"""
        if not (isinstance(folder, str) and os.path.isdir(folder) and isinstance(query, str)):
            return {"results": [], "total": 0, "files": 0, "scanned": 0, "skipped": 0, "truncated": False, "reason": "",
                    "error": "フォルダーが見つかりません"}
        self._search_id = getattr(self, "_search_id", 0) + 1
        mine = self._search_id
        files, _ = scan_markdown(folder)
        return foldersearch.search(folder, files, query, bool(case), bool(regex), read=read_text,
                                   cancelled=lambda: self._search_id != mine)

    def list_files(self, folder):
        if not os.path.isdir(folder):
            return {"error": f"フォルダーが見つかりません: {folder}", "files": []}
        if self._persist_location:
            settings = load_settings()
            if settings.get("last_folder") != folder:
                settings["last_folder"] = folder
                save_settings(settings)
        files, truncated = scan_markdown(folder)
        return {"error": None, "files": files, "truncated": truncated}

    @staticmethod
    def file_stamp(path):
        """ファイルの更新の目印（更新日時・大きさ）。変わったかを見るためだけに使う。無ければ None。"""
        try:
            st = os.stat(path)
        except (OSError, TypeError, ValueError):
            return None
        return [st.st_mtime_ns, st.st_size]

    def open_file(self, path):
        stamp = self.file_stamp(path)
        try:
            text = read_text(path)
        except OSError as e:
            return {"error": f"開けません: {e}"}
        base = os.path.dirname(path)
        self._doc_dir = base
        if self._persist_location:
            settings = load_settings()
            if settings.get("last_file") != path:
                settings["last_file"] = path
                save_settings(settings)
        try:
            html = sanitize(self.md.render(text, {"base": base}),
                            lambda src: inline_image(src, base))
        except Exception as e:             # 変換器の不具合で例外が出ても、文書が開けなくならないように、エラーを表示する
            html = mdext.error_html(e)
        try:
            self._window.set_title(f"{os.path.basename(path)} - {APP_TITLE}")
        except Exception:
            pass
        return {"error": None, "html": html, "path": path,
                "name": os.path.basename(path), "stamp": stamp}

    def close_document(self):
        """文書を閉じた（フォルダーを変えた）。記憶している前回のファイルも忘れ、タイトルを元に戻す。"""
        self._doc_dir = None
        if self._persist_location:
            settings = load_settings()
            if "last_file" in settings:
                del settings["last_file"]
                save_settings(settings)
        try:
            self._window.set_title(APP_TITLE)
        except Exception:
            pass

    def read_data(self, uri):
        """Vega-Lite の data.url に書かれた相対パスのデータ（CSV/TSV/JSON）を読む。
        文書のあるフォルダーとその下だけ。絶対パス・../ での外出・他の拡張子は拒否する。"""
        from urllib.parse import unquote
        base = self._doc_dir
        if not base:
            return {"error": "文書が開かれていません"}
        rel = unquote(str(uri).split("#")[0].split("?")[0]).strip()
        if (not rel or os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel)
                or rel.startswith(("\\\\", "/")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", rel)):
            return {"error": "相対パスだけ使えます: " + str(uri)}
        if not rel.lower().endswith(DATA_EXTENSIONS):
            return {"error": "読めるファイルは .csv / .tsv / .json だけです: " + str(uri)}
        root = os.path.realpath(base)
        path = os.path.realpath(os.path.join(root, rel))
        try:
            inside = os.path.commonpath([root, path]) == root
        except ValueError:          # 別ドライブなど
            inside = False
        if not inside:
            return {"error": "文書のフォルダーの外は読めません: " + str(uri)}
        try:
            if os.path.getsize(path) > MAX_DATA_FILE:
                return {"error": "ファイルが大きすぎます（20MBまで）: " + str(uri)}
            return {"error": None, "text": read_text(path)}
        except OSError as e:
            return {"error": f"開けません: {e}"}

    def resolve_link(self, current, href):
        """文書内の相対リンクを開く先に解決する。Markdown 以外は開かない。"""
        from urllib.parse import unquote
        target = unquote(href.split("#")[0])
        if not target:
            return None
        path = os.path.normpath(os.path.join(os.path.dirname(current), target))
        if os.path.isfile(path) and is_markdown(path):
            return path
        return None

    def open_local(self, current, href):
        """文書内のローカルファイル（PDF・Word など）へのリンクを、関連づけられたアプリで開く。
        許す書き方: 相対パス（../ も可。文書のあるフォルダー基準）、file:///C:/…、C:/…。
        ネットワーク共有（UNC）・存在しないファイル・OPEN_EXTENSIONS 以外は開かない。"""
        from urllib.parse import unquote, urlsplit
        from urllib.request import url2pathname
        raw = str(href).strip()
        if re.match(r"(?i)^file:", raw):
            parts = urlsplit(raw)
            if parts.netloc not in ("", "localhost"):
                return {"error": "ネットワーク上のファイルへのリンクは開けません: " + raw}
            path = url2pathname(unquote(parts.path))
            if os.name == "nt" and re.match(r"^[\\/][A-Za-z]:", path):
                path = path[1:]
            if not re.match(r"^[A-Za-z]:[\\/]", path):
                return {"error": "ドライブ名から始まるパスだけ開けます: " + raw}
        else:
            rel = unquote(raw.split("#")[0].split("?")[0]).strip()
            if not rel:
                return {"error": "開き先がありません"}
            if rel.startswith(("\\\\", "//")):
                return {"error": "ネットワーク上のファイルへのリンクは開けません: " + raw}
            if re.match(r"^[A-Za-z]:[\\/]", rel):
                path = rel
            elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", rel) or os.path.isabs(rel):
                return {"error": "このリンクは開けません: " + raw}
            else:
                if not current:
                    return {"error": "文書が開かれていません"}
                path = os.path.join(os.path.dirname(current), rel)
        path = os.path.normpath(path)
        if not path.lower().endswith(OPEN_EXTENSIONS):
            return {"error": "この種類のファイルは開けません（%s）" % os.path.basename(path)}
        if not os.path.isfile(path):
            return {"error": "ファイルが見つかりません: " + path}
        real = os.path.realpath(path)
        if not real.lower().endswith(OPEN_EXTENSIONS):      # リンク先の実体も同じ条件で確かめる
            return {"error": "この種類のファイルは開けません（%s）" % os.path.basename(real)}
        try:
            os.startfile(path)
        except OSError as e:
            return {"error": f"開けませんでした: {e}"}
        return {"error": None}

    # --- Mermaid の追加アイコン（Architecture Diagram の `logos:slack-icon` など）---------
    def list_icon_packs(self):
        folder = resource_path(os.path.join("vendor", "icons"))
        try:
            return sorted(n[:-8] for n in os.listdir(folder) if n.endswith(".json.gz"))
        except OSError:
            return []

    def get_icon_pack(self, name):
        """アイコン集（iconify の JSON）を返す。図でそのアイコンが要るときだけ画面が取りに来る。"""
        if not re.fullmatch(r"[a-z0-9-]+", name or ""):
            return None
        path = os.path.join(resource_path(os.path.join("vendor", "icons")), name + ".json.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def get_mermaid(self):
        """Mermaid 本体。図があるときだけ画面が取りに来る（3.5MB あるため）。"""
        if self._mermaid is None:
            with open(resource_path("vendor/mermaid.min.js"), encoding="utf-8") as f:
                self._mermaid = f.read()
        return self._mermaid

    # Vega-Lite 用のライブラリ。vendor/ に置いた3ファイルだけを、図があるときに画面が取りに来る
    _VENDOR_FILES = {
        "vega": "vega.min.js",
        "vega-lite": "vega-lite.min.js",
        "vega-embed": "vega-embed.min.js",
    }

    def get_vendor(self, name):
        fname = self._VENDOR_FILES.get(name)
        if fname is None:
            raise ValueError("unknown vendor library: %s" % name)
        if name not in self._vendor:
            with open(resource_path("vendor/" + fname), encoding="utf-8") as f:
                self._vendor[name] = f.read()
        return self._vendor[name]

    def get_katex(self):
        """KaTeX（数式の組版）。数式があるときだけ画面が取りに来る。描画部品と、フォントを埋め込んだ CSS を返す。"""
        if "katex" not in self._vendor:
            self._vendor["katex"] = mathtex.katex_assets(resource_path("vendor/katex"))
        return self._vendor["katex"]

    # --- 画面の設定（フォント・表示倍率・一覧の表示）-------------------------
    # --- 発表（スライドショー。deck.py）-------------------------------------
    def deck_prepare(self, doc_path=None):
        return self._deck.prepare(doc_path if isinstance(doc_path, str) else None)

    def deck_theme_css(self, theme_id, doc_path=None):
        return self._deck.theme_css(theme_id, doc_path if isinstance(doc_path, str) else None)

    def deck_make_theme(self, doc_path=None):
        return self._deck.make_sample_theme(doc_path if isinstance(doc_path, str) else None)

    def deck_open(self, html, opts):
        return self._deck.open(html, opts)

    def deck_export_pdf(self, html, mode, path):
        return self._deck.export_pdf(html, mode, path)

    def deck_running(self):
        return self._deck.running()

    def deck_close(self):
        self._deck.close()

    def get_prefs(self):
        return uiprefs.clean_prefs(load_settings())

    def set_prefs(self, patch):
        clean = uiprefs.clean_prefs(patch)
        if clean:
            settings = load_settings()
            if "deck" in clean:              # 発表の設定は、項目ごとに足す（別の項目を消さない）
                old = settings.get("deck") if isinstance(settings.get("deck"), dict) else {}
                clean = {**clean, "deck": {**uiprefs.clean_deck(old), **clean["deck"]}}
            settings.update(clean)
            save_settings(settings)
        return clean

    def list_fonts(self):
        if self._fonts is None:
            self._fonts = uiprefs.list_system_fonts()
        return self._fonts

    # --- 印刷・PDF ----------------------------------------------------------
    def get_print_prefs(self):
        return load_settings().get("print", {})

    def set_print_prefs(self, prefs):
        settings = load_settings()
        settings["print"] = prefs
        save_settings(settings)

    def print_printers(self):
        try:
            return printing.list_printers()
        except Exception:
            return {"printers": [], "default": ""}

    def print_check_ranges(self, text, total):
        try:
            return {"ok": True, "ranges": printing.parse_ranges(text, total or None)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def _print_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except printing.PrintError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                      # 画面へは文言で返す（原因が分かるように）
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def print_count(self, opts):
        return self._print_call(lambda: {"pages": printing.count_pages(self._window, opts)})

    def print_preview(self, opts, ranges):
        return self._print_call(lambda: printing.preview_pdf(
            self._window, opts, printing.parse_ranges(ranges)) and None)

    def print_save_pdf(self, opts, ranges, path):
        return self._print_call(lambda: printing.save_pdf(
            self._window, opts, printing.parse_ranges(ranges), path) and None)

    def print_send(self, opts, ranges):
        return self._print_call(lambda: printing.send_to_printer(
            self._window, opts, printing.parse_ranges(ranges)) and None)

    def pick_html_path(self, name, initial_dir_=None):
        return dialogs.pick_save(initial_dir(initial_dir_), name, "html")

    MAX_HTML = 200 * 1024 * 1024         # 書き出す HTML の大きさの上限

    def save_html(self, path, html):
        """書き出した HTML を、ファイルに書く。拡張子は .html か .htm のどちらか（無ければ .html を足す）。"""
        if not (isinstance(path, str) and path and isinstance(html, str)):
            return {"error": "保存先か内容が正しくありません"}
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
        if len(html) > self.MAX_HTML:
            return {"error": "大きすぎて書き出せません（200MB まで）"}
        if not multiwin.write_text_atomic(path, html):
            return {"error": "書き込めませんでした: " + path}
        self._exported_html = os.path.normcase(os.path.abspath(path))
        return {"error": None, "path": path, "bytes": len(html.encode("utf-8"))}

    def open_exported_html(self, path):
        """いま書き出した HTML を、ふだん使っているブラウザーで開く（書き出したファイルだけ）。"""
        if not (isinstance(path, str) and os.path.normcase(os.path.abspath(path)) == getattr(self, "_exported_html", None)):
            return {"error": "開けません"}
        try:
            os.startfile(path)
        except OSError as e:
            return {"error": "開けません: " + str(e)}
        return {"error": None}

    def pick_pdf_path(self, name, initial_dir_=None):
        return dialogs.pick_save(initial_dir(initial_dir_), name, "pdf")

    def open_external(self, url):
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)


# --- エクスプローラー連携 ----------------------------------------------------
def message(text, title="Handy Markdown Viewer"):
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)


VERB = "MarkdownViewer"                    # フォルダーの右クリックのメニューのキー名（ほかのアプリと別にする）
MENU_TEXT = "Handy Markdown Viewer で開く"


def register_association():
    if not getattr(sys, "frozen", False):
        message("exe 版から実行してください。")
        return
    shellreg.register(sys.executable, PROG_ID, MENU_TEXT, VERB)
    shellreg.notify_shell()
    message("登録しました。\n\n"
            "■ Markdown ファイル\n"
            "右クリック →「プログラムから開く」→「別のプログラムを選択」で「Handy Markdown Viewer で開く」を選び、"
            "「常に使う」を押すと、ダブルクリックで開けます。\n\n"
            "■ フォルダー\n"
            "フォルダーを右クリックすると、「Handy Markdown Viewer で開く」が出ます。フォルダーを開いて、"
            "何もない場所を右クリックしても出ます。\n"
            "Windows 11 では、右クリックしてすぐ出るメニューではなく、「その他のオプションを表示」を押した先に出ます"
            "（Shift キーを押しながら右クリックしても出ます）。")


def unregister_association():
    shellreg.unregister(PROG_ID, VERB)
    shellreg.notify_shell()
    message("登録を解除しました。")


class WindowKeeper:
    """ウィンドウの位置・大きさ・最大化を、閉じるときに保存する（次の起動で戻す）。

    高 DPI の画面では、作るときに渡す大きさと、あとから読み取る大きさの単位が
    違うことがあるので、表示できた時点で両者の比を測り、保存する値をそろえる
    （そろえないと、起動のたびにウィンドウが少しずつ大きくなる）。
    どこかで失敗しても、保存・復元をやめるだけで、アプリの動作には影響しない。
    """

    def __init__(self, window, width, height, maximize, offset=(0, 0), placed=None):
        self.window = window
        self.width, self.height = width, height
        self.maximize = maximize
        self.offset = offset            # 他のウィンドウと重ならないよう、保存した位置からずらした分
        self.placed = placed            # ずらしたあとの、開いた位置 (x, y)
        self.ratio_w = self.ratio_h = 1.0
        self.measured = False

    def _bounds(self):
        """(左, 上, 幅, 高さ, 最大化か)。最小化中などで取れなければ None。"""
        native = getattr(self.window, "native", None)
        if native is None:
            w = self.window
            return (w.x, w.y, w.width, w.height, False)
        try:
            state = int(native.WindowState)              # 0 通常, 1 最小化, 2 最大化
        except Exception:
            state = {"Normal": 0, "Minimized": 1, "Maximized": 2}.get(str(native.WindowState), 0)
        if state == 1:
            return None
        if state == 2:                                   # 最大化の前の、元の位置と大きさを残す
            r = native.RestoreBounds
            return (r.X, r.Y, r.Width, r.Height, True)
        return (native.Left, native.Top, native.Width, native.Height, False)

    def on_loaded(self):
        if self.measured:
            return
        self.measured = True
        try:
            b = self._bounds()
            if b and not b[4]:
                rw, rh = b[2] / self.width, b[3] / self.height
                if 0.95 <= rw <= 3 and 0.95 <= rh <= 3:  # 画面に収まるよう削られた場合は使わない
                    self.ratio_w, self.ratio_h = rw, rh
        except Exception:
            pass
        if self.maximize:
            try:
                self.window.maximize()
            except Exception:
                pass

    def on_closing(self):
        try:
            b = self._bounds()
            if not b:
                return
            x, y, w, h, maximized = b
            # 開いたときの位置から動かしていなければ、ずらす前の位置を保存する（開くたびに、右下へ流れていかないように）
            if self.placed and abs(x - self.placed[0]) <= 2 and abs(y - self.placed[1]) <= 2:
                x, y = x - self.offset[0], y - self.offset[1]
            settings = load_settings()
            settings["window"] = {
                "x": int(x), "y": int(y),
                "width": int(round(w / self.ratio_w)), "height": int(round(h / self.ratio_h)),
                "maximized": bool(maximized)}
            save_settings(settings)
        except Exception:
            pass



def _install_drop(window):
    """ウィンドウへのドロップ（Markdown ファイル1つ／フォルダー1つ）を受ける。読み込みの完了後に1度だけ。"""
    if getattr(window, "_drop_installed", False):
        return
    window._drop_installed = True
    try:
        filedrop.install(window, is_markdown, filedrop.open_in_window(window))
    except Exception:
        pass            # ドロップが使えなくても、ほかの機能は使えるようにする


def build_html():
    """画面を組み立てる。部品（印刷・検索）は文字列として埋め込む（読み込み元を持たない画面のため）。"""
    def read(name):
        with open(resource_path(name), encoding="utf-8") as f:
            return f.read()

    return (read("ui.html")
            .replace("/*PRINT_JS*/", read("print.js"))
            .replace("/*DECK_UI_JS*/", read("deck_ui.js"))
            .replace("/*FIND_JS*/", read("vfind.js"))
            .replace("__APP_VERSION__", APP_VERSION))


def main():
    args = sys.argv[1:]
    if args and args[0] == "--register":
        register_association()
        return
    if args and args[0] == "--unregister":
        unregister_association()
        return

    import webview
    start = os.path.abspath(shellreg.clean_path_arg(args[0])) if args else None
    api = Api(start)
    html = build_html()
    # 前回のウィンドウの位置・大きさを戻す（画面の外に出てしまう位置は使わない）
    geo = uiprefs.clean_window(load_settings().get("window"))
    width, height = geo.get("width", 1200), geo.get("height", 800)
    place = {}
    if uiprefs.place_visible(geo, uiprefs.virtual_screen()):
        place = {"x": geo["x"], "y": geo["y"]}
    # すでに同じアプリのウィンドウがあれば、真上に重ならないよう、右下へずらして開く
    offset = (0, 0)
    if place and not geo.get("maximized"):
        x, y = multiwin.cascade(place["x"], place["y"], multiwin.other_windows(WINDOW_MARK))
        if (x, y) != (place["x"], place["y"]) and uiprefs.place_visible(dict(geo, x=x, y=y), uiprefs.virtual_screen()):
            offset = (x - place["x"], y - place["y"])
            place = {"x": x, "y": y}
    window = webview.create_window(
        APP_TITLE, html=html, js_api=api,
        width=width, height=height, min_size=(640, 400), **place)
    api._window = window
    keeper = WindowKeeper(window, width, height, bool(geo.get("maximized")), offset, (place["x"], place["y"]) if place else None)
    window.events.loaded += keeper.on_loaded
    window.events.loaded += lambda: _install_drop(window)
    window.events.closing += keeper.on_closing
    window.events.closed += lambda: api._deck.close()          # 本体を終えたとき、発表の画面だけが残らないように
    webview.start()


if __name__ == "__main__":
    main()
