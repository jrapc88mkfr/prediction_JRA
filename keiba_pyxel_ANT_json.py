# ============================================================
# keiba_pyxel_ANT_json.py  競馬予想ビューア  (Pyxel版 WEB対応版 v3)
#
# ★ ローカルデバッグ方法
#   1. IS_WEB_DEBUG = True にして python keiba_pyxel_ANT_json.py を実行
#      → urllib で BASE_URL/DATA/index.json を実際に取得しにいく
#      → コンソールに [FETCH OK] / [FETCH ERR] が出るので原因を確認
#   2. IS_WEB_DEBUG = False のまま動かす
#      → DATA/ フォルダの index.json または json ファイルをローカルから読む
#
# ★ WEB版が動かなかった原因 (前バージョンから修正)
#   - create_proxy を使った Promise チェーンは Pyxel の Emscripten ループと
#     相性が悪くコールバックが呼ばれないことがある
#   → pyodide.http.pyfetch + asyncio.ensure_future に変更
#   - asyncio イベントループを毎フレーム poll() で明示的に進める
# ============================================================

import sys, os, re, math, json, asyncio
import pyxel
import platform

# ============================================================
# WEB / ローカル判定
# IS_WEB_DEBUG = True → ローカルでも BASE_URL から fetch してデバッグ可能
# ============================================================
IS_WEB       = platform.system() == "Emscripten"
IS_WEB_DEBUG = False   # ← True にするとローカルで WEB 版コードパスを確認できる

_USE_WEB_FETCH = IS_WEB  # Pyodide pyfetch を使うか (ローカルは常に urllib)

# ============================================================
# パス設定
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if not IS_WEB else ""
BASE_URL = "https://jrapc88mkfr.github.io/prediction_JRA"

if IS_WEB:
    DATA_DIR = "DATA"
    FONT_DIR = ""          # bdf ファイルは index.html と同じルートに置く
else:
    DATA_DIR = os.path.join(BASE_DIR, "DATA")
    FONT_DIR = BASE_DIR

# ============================================================
# 設定
# ============================================================
W, H = 512, 320
FPS  = 30

# ============================================================
# カラーパレット
# ============================================================
COL_BG      = 1
COL_BG2     = 0
COL_BG3     = 1
COL_BORDER  = 5
COL_TITLE   = 10
COL_HEADER  = 6
COL_TEXT    = 7
COL_MUTED   = 13
COL_ODDS_LO = 8
COL_ODDS_MD = 9
COL_SC_HI   = 11
COL_SC_MD   = 10
COL_SC_LO   = 13
COL_BTN     = 5
COL_ST_E    = 8
COL_ST_S    = 9
COL_ST_D    = 12
COL_ST_O    = 14

GATE_COLS = [7,7,8,8,9,9,12,12,10,10,11,11,14,14,13,13]
STYLE_COL = {"逃":COL_ST_E,"先":COL_ST_S,"差":COL_ST_D,"追":COL_ST_O}

ROW_H       = 12
ITEM_H      = 16
FONT_S_SIZE = 10
FONT_M_SIZE = 12

_font_s_path = os.path.join(FONT_DIR, "umplus_j10r.bdf")
_font_m_path = os.path.join(FONT_DIR, "umplus_j12r.bdf")
FONT_S = pyxel.Font(_font_s_path)
FONT_M = pyxel.Font(_font_m_path)

SCENE_LOADING = "loading"
SCENE_FILE    = "file"
SCENE_LIST    = "list"
SCENE_DETAIL  = "detail"

SORT_KEYS   = ["no", "odds", "index"]
SORT_LABELS = ["馬番順", "オッズ順", "指数順"]

# ============================================================
# 描画ユーティリティ
# ============================================================
def draw_text(x, y, text, col=COL_TEXT, font=FONT_S):
    if not text: return
    pyxel.text(x, y, str(text), col, font)

def text_px(text, font=FONT_S):
    return len(str(text)) * 6

def truncate(text, max_px, size=FONT_S):
    if text_px(text, size) <= max_px: return text
    result = ""
    for ch in text:
        if text_px(result + ch, size) > max_px: break
        result += ch
    return result

def score_col(idx):
    if idx >= 90: return COL_SC_HI
    if idx >= 75: return COL_SC_MD
    return COL_SC_LO

def odds_col(odds):
    if odds is None: return COL_MUTED
    if odds <= 5:    return COL_ODDS_LO
    if odds <= 15:   return COL_ODDS_MD
    return COL_TEXT

def mark_col(mark):
    return {"◎":COL_TITLE,"○":COL_ODDS_MD,"▲":COL_ODDS_LO,
            "☆":COL_HEADER,"△":COL_SC_HI,"穴":14}.get(mark, COL_MUTED)

def clamp(v, lo, hi): return max(lo, min(hi, v))
def draw_rectb(x, y, w, h, col): pyxel.rectb(x, y, w, h, col)

def draw_btn(x, y, w, label, active=False, fsize=FONT_S):
    bg = COL_BG if active else COL_BTN
    tc = COL_TITLE if active else COL_TEXT
    pyxel.rect(x, y, w, FONT_S_SIZE + 4, bg)
    draw_rectb(x, y, w, FONT_S_SIZE + 4, 7 if active else COL_BORDER)
    tx = x + max(2, (w - text_px(label, fsize)) // 2)
    draw_text(tx, y + 2, label, tc, fsize)

# ============================================================
# ダミーデータ
# ============================================================
DUMMY_RACES = [{
    "race_name": "ヴィクトリアマイル 2026",
    "course"   : "東京 芝1600m  G1",
    "pace"     : "ミドル〜スロー",
    "horses"   : [
        dict(gate=1,no=1,  name="カピリナ",       odds=94.2, sex="牝5",jw=56,style="差",jockey="横山典", index=67,prev1="",prev2="",prev3="",prev_3F="33.8",train_1F="11.8",mark="",  summary={},raw={}),
        dict(gate=2,no=3,  name="マビュース",      odds=65.8, sex="牝4",jw=56,style="差",jockey="ゴンサル",index=88,prev1="",prev2="",prev3="",prev_3F="32.9",train_1F="11.3",mark="△",summary={},raw={}),
        dict(gate=4,no=7,  name="クイーンズウォー", odds=10.4, sex="牝5",jw=56,style="先",jockey="西村淳",index=86,prev1="",prev2="",prev3="",prev_3F="33.0",train_1F="11.2",mark="☆",summary={},raw={}),
        dict(gate=4,no=8,  name="カムニャック",    odds=5.3,  sex="牝4",jw=56,style="差",jockey="川田",  index=84,prev1="",prev2="",prev3="",prev_3F="32.7",train_1F="11.0",mark="",  summary={},raw={}),
        dict(gate=6,no=11, name="ポンドガール",    odds=30.7, sex="牝5",jw=56,style="差",jockey="丹内",  index=90,prev1="",prev2="",prev3="",prev_3F="32.8",train_1F="11.1",mark="▲",summary={},raw={}),
        dict(gate=6,no=12, name="エンブロイダリー", odds=2.8,  sex="牝4",jw=56,style="差",jockey="ルメール",index=96,prev1="",prev2="",prev3="",prev_3F="32.4",train_1F="10.8",mark="◎",summary={},raw={}),
        dict(gate=8,no=16, name="ニシノティアモ",  odds=9.8,  sex="牝5",jw=56,style="差",jockey="津村",  index=87,prev1="",prev2="",prev3="",prev_3F="32.9",train_1F="11.1",mark="☆",summary={},raw={}),
        dict(gate=8,no=18, name="チェルヴィニア",  odds=None, sex="牝5",jw=56,style="差",jockey="レーン", index=93,prev1="",prev2="",prev3="",prev_3F="32.5",train_1F="10.9",mark="○",summary={},raw={}),
    ],
}]

# ============================================================
# 非同期フェッチ
# ============================================================
class AsyncLoader:
    """
    _USE_WEB_FETCH=True  : pyodide.http.pyfetch を asyncio.ensure_future で投げる
    _USE_WEB_FETCH=False : urllib で同期取得（ローカル実行 / IS_WEB_DEBUG）
    poll() を毎フレーム呼ぶことで Pyodide の asyncio を進める
    """
    IDLE    = "idle"
    LOADING = "loading"
    DONE    = "done"
    ERROR   = "error"

    def __init__(self):
        self.state  = self.IDLE
        self.result = None
        self.error  = ""
        self._task  = None

    def fetch(self, url: str):
        # GitHub Pages は日本語ファイル名をそのまま受け付けるので
        # URLエンコードしない（エンコードすると逆に404になる）
        self.state  = self.LOADING
        self.result = None
        self.error  = ""
        print(f"[FETCH] {url}")
        if _USE_WEB_FETCH:
            self._task = asyncio.ensure_future(self._async_fetch(url))
        else:
            self._sync_fetch(url)

    def _sync_fetch(self, url: str):
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
            self.result = json.loads(raw)
            self.state  = self.DONE
            print(f"[FETCH OK] {url}")
        except Exception as e:
            self.error = str(e)
            self.state = self.ERROR
            print(f"[FETCH ERR] {url} -> {e}")

    async def _async_fetch(self, url: str):
        try:
            from pyodide.http import pyfetch
            resp = await pyfetch(url)
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status}: {url}")
            text = await resp.string()
            if not text or text.lstrip().startswith("<"):
                raise RuntimeError(f"HTMLが返ってきました(404ページ?): {text[:60]!r}")
            self.result = json.loads(text)
            self.state  = self.DONE
        except Exception as e:
            self.error = str(e)
            self.state = self.ERROR

    def poll(self):
        """毎フレーム呼ぶ。Pyodide の asyncio イベントループを進める。"""
        if _USE_WEB_FETCH and self.is_loading():
            try:
                loop = asyncio.get_event_loop()
                # 待機なしで 1 ステップ進める
                loop.run_until_complete(asyncio.sleep(0))
            except Exception:
                pass

    def is_loading(self): return self.state == self.LOADING
    def is_done(self):    return self.state == self.DONE
    def is_error(self):   return self.state == self.ERROR

# ============================================================
# JSON → レースデータ変換
# ============================================================
def parse_races_from_json(data: dict, label: str) -> list:
    pyxel_rows   = data.get("pyxel",   [])
    summary_rows = data.get("summary", [])
    raw_rows     = data.get("rawdata", [])
    if not pyxel_rows: return []

    summary_dict = {str(r.get("馬名","")).strip(): r for r in summary_rows if r.get("馬名")}
    raw_dict     = {str(r.get("馬名","")).strip(): r for r in raw_rows     if r.get("馬名")}

    def safe(v, default=""):
        if v is None: return default
        try:
            if math.isnan(float(v)): return default
        except (TypeError, ValueError): pass
        return v

    horses = []
    for row in pyxel_rows:
        try:
            no_val = row.get("馬番", "")
            if no_val in ("", None): continue
            no_val = int(no_val)
            gate   = math.ceil(no_val / 2)

            m    = re.search(r"(\d+\.\d+)", str(row.get("オッズ戦績", "")))
            odds = float(m.group(1)) if m else None

            horse_name = str(row.get("馬名", "")).strip()

            # 斤量: "53.0kg" → "53.0" に正規化
            jw_raw = str(row.get("斤量","")).replace("kg","").strip()

            # 性齢: "北5/鹿" → スラッシュ後半を使う、なければそのまま
            sex_raw = str(row.get("性齢",""))
            sex = sex_raw.split("/")[-1].strip() if "/" in sex_raw else sex_raw

            # オッズ: "24.9 (4.2.1.12)" → 先頭の数値を取得
            odds_str = str(row.get("オッズ戦績",""))
            odds_m = re.search(r"^(\d+\.?\d*)", odds_str) or re.search(r"(\d+\.\d+)", odds_str)
            odds = float(odds_m.group(1)) if odds_m else None

            horses.append(dict(
                gate=gate, no=no_val, name=horse_name,
                odds=odds,
                sex=sex,
                jw=jw_raw,
                style=str(row.get("脚質","差")).strip(),
                jockey=str(row.get("騎手","")),
                index=int(row.get("総合指数",0) or 0),
                prev1=safe(row.get("前走")),
                prev2=safe(row.get("前々")),
                prev3=safe(row.get("3走")),
                prev_3F=safe(row.get("前3F")),
                train_1F=safe(row.get("調1F")),
                mark=str(row.get("印","") or "").strip(),
                summary=summary_dict.get(horse_name,{}),
                raw=raw_dict.get(horse_name,{}),
            ))
        except Exception as ex:
            print(f"[WARN] skip row: {ex}")

    if not horses: return []

    pace = ""
    if summary_rows:
        biko = str(summary_rows[-1].get("備考","") or "")
        m = re.search(r"予想ペース[：:]\s*(\S+)", biko)
        if m: pace = m.group(1)

    return [{"race_name":label,
             "course":f'{data.get("course","")} {data.get("distance","")}',
             "pace":pace, "horses":horses}]

# ============================================================
# App
# ============================================================
class KeibaApp:

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

        self.file_list   = []
        self.file_cursor = 0
        self.file_scroll = 0

        self.current_race  = None
        self.horses_sorted = []
        self.list_cursor   = 0
        self.list_scroll   = 0
        self.sort_idx      = 0
        self.sort_asc      = True

        self.detail_horse  = None
        self.detail_scroll = 0

        self._index_loader = AsyncLoader()
        self._race_loader  = AsyncLoader()
        self._pending_file = None

        self.scene        = SCENE_LOADING
        self.err_msg      = ""
        self._loading_msg = "読み込み中..."
        self._dot_frame   = 0

        pyxel.init(W, H, title="競馬予想ビューア", fps=FPS)
        pyxel.mouse(True)
        self._start_index_fetch()
        pyxel.run(self.update, self.draw)

    # ----------------------------------------------------------
    # index.json フェッチ開始
    # ----------------------------------------------------------
    def _start_index_fetch(self):
        if IS_WEB or IS_WEB_DEBUG:
            url = f"{BASE_URL}/DATA/index.json"
            self._loading_msg = "index.json 取得中..."
            print(f"[INDEX FETCH] {url}")
            self._index_loader.fetch(url)
        else:
            idx_path = os.path.join(self.data_dir, "index.json")
            if os.path.isfile(idx_path):
                self._loading_msg = "index.json 読み込み中..."
                self._index_loader.fetch(idx_path)
            else:
                self._scan_local_dir()

    def _scan_local_dir(self):
        files = []
        if os.path.isdir(self.data_dir):
            for root, _, fs in os.walk(self.data_dir):
                for f in fs:
                    if f.lower().endswith(".json") and not f.startswith("~$") and f.lower() != "index.json":
                        full = os.path.join(root, f)
                        files.append({"path":full, "label":os.path.splitext(f)[0],
                                      "dir":os.path.relpath(root, self.data_dir)})
            files.sort(key=lambda x: os.path.getmtime(x["path"]), reverse=True)
        if files:
            self.file_list = files
        else:
            self.err_msg   = "jsonが見つかりません（サンプル表示）"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
        self.scene = SCENE_FILE

    def _on_index_loaded(self, raw):
        """index.json の中身を受けてファイルリストを構築"""
        print(f"[INDEX LOADED] type={type(raw).__name__}  val={str(raw)[:120]}")
        names = raw
        if isinstance(names, dict):
            # {"files": [...]} 形式
            names = names.get("files", list(names.values())[0] if names else [])
        if not isinstance(names, list):
            names = []

        if IS_WEB or IS_WEB_DEBUG:
            self.file_list = [
                {"path":f"{BASE_URL}/DATA/{os.path.basename(n)}",
                 "label":os.path.splitext(os.path.basename(n))[0],
                 "dir":"DATA"}
                for n in names
            ]
        else:
            self.file_list = [
                {"path":os.path.join(self.data_dir, os.path.basename(n)),
                 "label":os.path.splitext(os.path.basename(n))[0],
                 "dir":"."}
                for n in names
            ]

        if not self.file_list:
            self.err_msg   = "ファイルリストが空（サンプル表示）"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
        self.scene = SCENE_FILE

    # ----------------------------------------------------------
    # ソート
    # ----------------------------------------------------------
    def _apply_sort(self):
        hs  = list(self.current_race["horses"])
        key = SORT_KEYS[self.sort_idx]
        if   key == "odds":  hs.sort(key=lambda h:(h["odds"] is None, h["odds"] or 9999), reverse=not self.sort_asc)
        elif key == "index": hs.sort(key=lambda h:h["index"], reverse=not self.sort_asc)
        else:                hs.sort(key=lambda h:h["no"])
        self.horses_sorted = hs

    def _vis_rows(self):  return (H - 42) // ROW_H
    def _vis_items(self): return (H - 56) // ITEM_H

    # ==========================================================
    # UPDATE
    # ==========================================================
    def update(self):
        mx, my = pyxel.mouse_x, pyxel.mouse_y
        wh     = pyxel.mouse_wheel
        if pyxel.btnp(pyxel.KEY_Q): pyxel.quit()

        # 毎フレーム asyncio を進める（Pyodide 非同期のため必須）
        self._index_loader.poll()
        self._race_loader.poll()
        self._dot_frame = (self._dot_frame + 1) % (FPS * 3)

        # ---- index.json 待ち ----
        if self.scene == SCENE_LOADING:
            if self._index_loader.is_done():
                try:
                    self._on_index_loaded(self._index_loader.result)
                except Exception as e:
                    self.err_msg   = f"index解析エラー: {e}"
                    print(f"[INDEX PARSE ERROR] {e}")
                    self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
                    self.scene     = SCENE_FILE
            elif self._index_loader.is_error():
                self.err_msg   = f"index取得失敗: {self._index_loader.error[:60]}"
                print(f"[INDEX ERROR] {self._index_loader.error}")
                self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
                self.scene     = SCENE_FILE
            return

        # ---- race.json 待ち ----
        if self._race_loader.is_loading():
            self._poll_race_loader()
            return

        if   self.scene == SCENE_FILE:   self._upd_file(mx, my, wh)
        elif self.scene == SCENE_LIST:   self._upd_list(mx, my, wh)
        elif self.scene == SCENE_DETAIL: self._upd_detail(mx, my, wh)

    def _poll_race_loader(self):
        if self._race_loader.is_done():
            fi = self._pending_file
            try:
                races = parse_races_from_json(self._race_loader.result, fi["label"])
                if races:
                    self.current_race = races[0]
                    self.list_cursor = self.list_scroll = 0
                    self.sort_idx = 0; self.sort_asc = True
                    self._apply_sort()
                    self.scene = SCENE_LIST
                else:
                    self.err_msg = f"データなし: {fi['label']}"
            except Exception as e:
                self.err_msg = f"解析エラー: {e}"
                print(f"[RACE PARSE ERROR] {e}")
            self._pending_file = None

        elif self._race_loader.is_error():
            err = self._race_loader.error
            # エラーの種類を判別して分かりやすく表示
            if "404" in err:
                self.err_msg = f"ファイルが見つかりません(404): {self._pending_file['label'][:30]}"
            elif "JSON" in err or "HTMLでない" in err or "HTML?" in err:
                self.err_msg = f"JSON読込失敗(HTML返答?): {err[:50]}"
            else:
                self.err_msg = f"読込失敗: {err[:60]}"
            print(f"[RACE ERROR] {err}")
            self._pending_file = None

    # ---- ファイル選択 ----------------------------------------
    def _upd_file(self, mx, my, wh):
        n, vis = len(self.file_list), self._vis_items()
        if pyxel.btnp(pyxel.KEY_UP):
            self.file_cursor = max(0, self.file_cursor - 1)
            if self.file_cursor < self.file_scroll: self.file_scroll = self.file_cursor
        if pyxel.btnp(pyxel.KEY_DOWN):
            self.file_cursor = min(n-1, self.file_cursor + 1)
            if self.file_cursor >= self.file_scroll + vis: self.file_scroll = self.file_cursor - vis + 1
        if wh: self.file_scroll = clamp(self.file_scroll - wh, 0, max(0, n - vis))
        if pyxel.btnp(pyxel.KEY_RETURN): self._open_file(self.file_cursor)
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            TOP = 46
            for rel in range(vis):
                ry = TOP + rel * ITEM_H
                if ry <= my < ry + ITEM_H:
                    idx = self.file_scroll + rel
                    if 0 <= idx < n:
                        if self.file_cursor == idx: self._open_file(idx)
                        else: self.file_cursor = idx
                    break

    def _open_file(self, idx):
        fi = self.file_list[idx]
        if fi["path"] == "__DUMMY__":
            self.current_race = {**DUMMY_RACES[0]}
            self.current_race["race_name"] = "サンプルデータ"
            self.list_cursor = self.list_scroll = 0
            self.sort_idx = 0; self.sort_asc = True
            self._apply_sort()
            self.scene = SCENE_LIST
            return
        self._pending_file = fi
        self._loading_msg  = f"読込中: {fi['label']}..."
        self._dot_frame    = 0
        self._race_loader  = AsyncLoader()
        self._race_loader.fetch(fi["path"])

    def _open_detail(self, idx):
        self.detail_horse  = self.horses_sorted[idx]
        self.detail_scroll = 0
        self.scene         = SCENE_DETAIL

    # ---- 出走表 ----------------------------------------------
    def _upd_list(self, mx, my, wh):
        n, vis = len(self.horses_sorted), self._vis_rows()
        if pyxel.btnp(pyxel.KEY_ESCAPE): self.scene = SCENE_FILE; return
        if pyxel.btnp(pyxel.KEY_UP):
            self.list_cursor = max(0, self.list_cursor - 1)
            if self.list_cursor < self.list_scroll: self.list_scroll = self.list_cursor
        if pyxel.btnp(pyxel.KEY_DOWN):
            self.list_cursor = min(n-1, self.list_cursor + 1)
            if self.list_cursor >= self.list_scroll + vis: self.list_scroll = self.list_cursor - vis + 1
        if wh:
            self.list_scroll = clamp(self.list_scroll - wh, 0, max(0, n - vis))
            self.list_cursor = clamp(self.list_cursor, self.list_scroll, self.list_scroll + vis - 1)
        if pyxel.btnp(pyxel.KEY_RETURN): self._open_detail(self.list_cursor)
        if pyxel.btnp(pyxel.KEY_TAB):
            self.sort_idx = (self.sort_idx + 1) % len(SORT_KEYS)
            self.sort_asc = (self.sort_idx == 0)
            self._apply_sort(); self.list_cursor = self.list_scroll = 0
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            if 2 <= mx <= 80 and 2 <= my <= 16: self.scene = SCENE_FILE; return
            if my >= 30:
                row_i = (my - 30) // ROW_H + self.list_scroll
                if 0 <= row_i < n:
                    if row_i == self.list_cursor: self._open_detail(row_i)
                    else: self.list_cursor = row_i

    # ---- 詳細 -----------------------------------------------
    def _upd_detail(self, mx, my, wh):
        if pyxel.btnp(pyxel.KEY_ESCAPE): self.scene = SCENE_LIST; return
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            if 2 <= mx <= 80 and 2 <= my <= 16: self.scene = SCENE_LIST; return
        if wh: self.detail_scroll = clamp(self.detail_scroll - wh, 0, 40)
        if pyxel.btnp(pyxel.KEY_UP):   self.detail_scroll = max(0,  self.detail_scroll - 1)
        if pyxel.btnp(pyxel.KEY_DOWN): self.detail_scroll = min(40, self.detail_scroll + 1)

    # ==========================================================
    # DRAW
    # ==========================================================
    def draw(self):
        pyxel.cls(COL_BG2)

        # ロード中オーバーレイ
        if self.scene == SCENE_LOADING or self._race_loader.is_loading():
            if self.scene == SCENE_FILE:   self._drw_file()
            elif self.scene == SCENE_LIST: self._drw_list()
            self._drw_loading_overlay()
            return

        if   self.scene == SCENE_FILE:   self._drw_file()
        elif self.scene == SCENE_LIST:   self._drw_list()
        elif self.scene == SCENE_DETAIL: self._drw_detail()

    def _drw_loading_overlay(self):
        dots = "." * ((self._dot_frame // 10) % 4)
        msg  = self._loading_msg + dots
        bw = text_px(msg) + 24
        bh = 26
        bx = (W - bw) // 2
        by = (H - bh) // 2
        pyxel.rect(bx, by, bw, bh, COL_BG)
        draw_rectb(bx, by, bw, bh, COL_HEADER)
        draw_text(bx + 12, by + 8, msg, COL_TITLE, FONT_S)

    # ---- 共通 ------------------------------------------------
    def _footer(self, msg):
        pyxel.rect(0, H - 12, W, 12, COL_BG)
        draw_rectb(0, H - 12, W, 12, COL_BORDER)
        draw_text(4, H - 10, msg, COL_MUTED, FONT_S)

    def _scrollbar(self, top_y, total, vis, scroll):
        if total <= vis: return
        area = H - top_y - 12
        bh   = max(6, area * vis // total)
        by   = top_y + area * scroll // total
        pyxel.rect(W - 4, top_y, 3, area, COL_BG)
        pyxel.rect(W - 4, by,    3, bh,   COL_BORDER)

    # ---- ファイル選択 ----------------------------------------
    def _drw_file(self):
        pyxel.rect(0, 0, W, 44, COL_BG)
        draw_rectb(0, 0, W, 44, COL_BORDER)
        draw_text(6,  3, "★ KEIBA ANALYZER ★", COL_TITLE, FONT_M)
        url_str = f"{BASE_URL}/DATA/" if (IS_WEB or IS_WEB_DEBUG) else self.data_dir
        draw_text(6, 20, truncate(url_str, W - 12), COL_HEADER, FONT_S)
        cnt  = sum(1 for f in self.file_list if f["path"] != "__DUMMY__")
        info = self.err_msg if self.err_msg else f"{cnt} ファイル"
        draw_text(6, 32, info, COL_ODDS_LO if self.err_msg else COL_MUTED, FONT_S)

        vis = self._vis_items()
        TOP = 46
        for rel in range(vis):
            idx = self.file_scroll + rel
            if idx >= len(self.file_list): break
            fi  = self.file_list[idx]
            ry  = TOP + rel * ITEM_H
            sel = (idx == self.file_cursor)
            pyxel.rect(0, ry, W - 5, ITEM_H, COL_BG if sel else (COL_BG2 if rel % 2 == 0 else COL_BG3))
            if sel: draw_rectb(0, ry, W - 5, ITEM_H, COL_HEADER)
            draw_text(4, ry + 3, truncate(fi["label"], W - 12), COL_TITLE if sel else COL_TEXT, FONT_S)

        self._scrollbar(TOP, len(self.file_list), vis, self.file_scroll)
        self._footer("↑↓:選択  Enter/クリック2回:決定  Q:終了")

    # ---- 色ヘルパー -----------------------------------------
    def rating_color(self, v):
        try: v = float(v)
        except: return COL_TEXT
        if v >= 100: return pyxel.COLOR_RED
        if v >= 90:  return pyxel.COLOR_YELLOW
        return COL_TEXT

    def last3f_color(self, v):
        try: v = float(v)
        except: return COL_TEXT
        if v < 33.5: return pyxel.COLOR_RED
        if v < 34.0: return pyxel.COLOR_YELLOW
        return COL_SC_HI

    def train1f_color(self, v):
        try: v = float(v)
        except: return COL_TEXT
        if v < 11.0:  return pyxel.COLOR_RED
        if v <= 11.5: return pyxel.COLOR_YELLOW
        return COL_SC_HI

    # ---- 出走表一覧 -----------------------------------------
    def _drw_list(self):
        race = self.current_race
        pyxel.rect(0, 0, W, 18, COL_BG)
        draw_rectb(0, 0, W, 18, COL_BORDER)
        draw_btn(2, 2, text_px("←レース選択") + 70, "←レース選択")
        ox = text_px("←レース選択") + 70
        draw_text(ox + 20, 3, truncate(race["race_name"], W - ox - 80), COL_TITLE, FONT_M)
        slbl = SORT_LABELS[self.sort_idx]
        draw_btn(W - text_px(slbl) - 40, 3, text_px(slbl) + 40, slbl, active=True)

        cx = self._cx()
        yh = 19
        pyxel.rect(0, yh, W, ROW_H + 1, COL_BG)
        draw_rectb(0, yh, W, ROW_H + 1, COL_BORDER)
        for k, lbl in [("no","番"),("name","馬名"),("odds","オッズ"),("sex","性齢"),
                       ("style","脚"),("jkey","騎手"),("idx","指数"),
                       ("prev1","前走"),("prev2","前々"),("prev3","3走"),
                       ("prev_3F","前3F"),("train_1F","調1F"),("mark","印")]:
            draw_text(cx[k], yh + 2, lbl, COL_HEADER, FONT_S)

        vis = self._vis_rows()
        for rel in range(vis):
            ai = self.list_scroll + rel
            if ai >= len(self.horses_sorted): break
            h   = self.horses_sorted[ai]
            ry  = 31 + rel * ROW_H
            sel = (ai == self.list_cursor)
            pyxel.rect(0, ry, W-5, ROW_H, COL_BG if sel else (COL_BG2 if rel%2==0 else COL_BG3))
            if sel: draw_rectb(0, ry, W-5, ROW_H, COL_HEADER)
            ty = ry + 1

            gcol = GATE_COLS[min((h["gate"]-1)*2, len(GATE_COLS)-1)]
            pyxel.rect(cx["gate"], ty+2, 6, 6, gcol)
            draw_text(cx["no"], ty, f"{h['no']:2d}", COL_TEXT, FONT_S)
            nw = cx["odds"] - cx["name"] - 2
            draw_text(cx["name"], ty, truncate(h["name"], nw), COL_TITLE if sel else COL_TEXT, FONT_S)

            odds = h["odds"]
            odds_text = (f"{odds:.0f}" if odds and odds >= 100 else f"{odds:.1f}") if odds else "---"
            draw_text(cx["odds"],    ty, odds_text,                          odds_col(odds), FONT_S)
            draw_text(cx["sex"],     ty, truncate(h["sex"],24),              COL_TEXT, FONT_S)
            draw_text(cx["style"],   ty, h["style"],                         STYLE_COL.get(h["style"],COL_TEXT), FONT_S)
            draw_text(cx["jkey"],    ty, truncate(h["jockey"],cx["idx"]-cx["jkey"]-2), COL_MUTED, FONT_S)

            bw = clamp(h["index"]*30//100, 1, 30)
            pyxel.rect(cx["idx"], ty+3, bw, 5, score_col(h["index"]))
            draw_text(cx["idx"]+32, ty, f"{h['index']:3d}", score_col(h["index"]), FONT_S)

            draw_text(cx["prev1"],   ty, str(h.get("prev1","")),    self.rating_color(h.get("prev1",0)),    FONT_S)
            draw_text(cx["prev2"],   ty, str(h.get("prev2","")),    self.rating_color(h.get("prev2",0)),    FONT_S)
            draw_text(cx["prev3"],   ty, str(h.get("prev3","")),    self.rating_color(h.get("prev3",0)),    FONT_S)
            draw_text(cx["prev_3F"], ty, str(h.get("prev_3F","")), self.last3f_color(h.get("prev_3F","")), FONT_S)
            draw_text(cx["train_1F"],ty, str(h.get("train_1F","")),self.train1f_color(h.get("train_1F","")),FONT_S)
            draw_text(cx["mark"],    ty, h.get("mark",""),          mark_col(h.get("mark","")),             FONT_S)

        self._scrollbar(31, len(self.horses_sorted), vis, self.list_scroll)
        self._footer("Enter:詳細  Tab:ソート切替  ESC:戻る  Q:終了")

    def _cx(self):
        return dict(gate=2,no=10,name=22,odds=130,sex=170,style=200,jkey=220,
                    idx=252,prev1=310,prev2=340,prev3=370,prev_3F=400,train_1F=435,mark=470)

    # ---- 詳細 -----------------------------------------------
    def _drw_detail(self):
        h  = self.detail_horse
        sc = self.detail_scroll
        r  = h.get("raw", {})

        pyxel.rect(0, 0, W, 18, COL_BG)
        draw_rectb(0, 0, W, 18, COL_BORDER)
        draw_btn(2, 2, text_px("◀ 一覧") + 10, "◀ 一覧")
        ox   = text_px("◀ 一覧") + 16
        gcol = GATE_COLS[min((h["gate"]-1)*2, len(GATE_COLS)-1)]
        pyxel.rect(ox, 5, 8, 8, gcol)
        draw_text(ox+12, 3, truncate(f"{h['no']}番  {h['name']}", W-ox-16), COL_TITLE, FONT_M)

        LH = FONT_S_SIZE + 5
        SH = FONT_S_SIZE + 8

        def oy(dy): return 22 + dy - sc * LH

        def line(dy, label, val, vc=COL_TEXT):
            y = oy(dy)
            if not (18 < y < H - 13): return
            draw_text(4, y, label, COL_HEADER, FONT_S)
            draw_text(64, y, str(val), vc, FONT_S)

        def section(dy, title_s):
            y = oy(dy)
            if not (18 < y < H - 13): return
            pyxel.rect(2, y, W-8, FONT_S_SIZE+4, COL_BG)
            draw_rectb(2, y, W-8, FONT_S_SIZE+4, COL_BORDER)
            draw_text(6, y+2, title_s, COL_HEADER, FONT_S)

        odds_str = f"{h['odds']:.1f}倍" if h["odds"] else "---"
        section(0, "基本情報")
        line(SH, "", f'【{h["mark"]}】 {odds_str}  {h["sex"]}  {h["jw"]}kg  {h["jockey"]}  脚質:{h["style"]}')

        base2 = SH + LH
        section(base2, "総合指数")
        line(base2+SH, "指数    ", str(h["index"]), score_col(h["index"]))
        by = oy(base2+SH+LH+2)
        if 18 < by < H-13:
            bw = clamp(h["index"]*(W-24)//100, 1, W-24)
            pyxel.rect(4, by, W-8, 7, COL_BG)
            pyxel.rect(4, by, bw,  7, score_col(h["index"]))
            draw_rectb(4, by, W-8, 7, COL_BORDER)

        base3 = base2 + SH + LH*2
        section(base3, "調教")
        line(base3+SH,   "調教場所", r.get("調教場所・馬場",""))
        line(base3+SH*2, "調教時計", r.get("時計",""))

        base4 = base3 + SH + LH*2
        section(base4, "近走成績")
        for i, key in enumerate(["前走","前々走","3走前","4走前"]):
            txt = str(r.get(key,""))
            pos = txt.find("kg ")
            lines = [txt[:pos+3], txt[pos+3:]] if pos >= 0 else [txt]
            y = base4 + SH + i*(LH*2)
            line(y,    key, lines[0])
            if len(lines) > 1: line(y+LH, "", lines[1], COL_TITLE)

        self._footer("↑↓/ホイール:スクロール  ESC:戻る  Q:終了")

# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    KeibaApp(data_dir)
