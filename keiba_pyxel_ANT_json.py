# ============================================================
# keiba_pyxel.py  競馬予想ビューア  (Pyxel版)
#
# 依存:
#   pip install pyxel pandas openpyxl pillow
#
# 日本語フォント:
#   Windows の場合は msgothic.ttc / meiryo.ttc が自動検索されます。
#   なければ同フォルダに "font.ttf" を置いてください。
#
# 起動:
#   python keiba_pyxel.py
#   python keiba_pyxel.py "C:\path\to\DATA"
#
# 画面遷移:
#   SCENE_FILE   … DATAフォルダの xlsx ファイル選択
#   SCENE_LIST   … 出走表一覧
#   SCENE_DETAIL … 馬詳細
#
# 操作:
#   ↑↓ / マウスホイール … スクロール
#   Enter / クリック    … 選択・決定
#   Esc                 … 前の画面へ戻る
#   Tab                 … 一覧ソート切替
#   Q                   … 終了
# ============================================================

import sys, os, re, math, glob, json
import pyxel

# ============================================================
# 設定
# ============================================================
DATA_DIR = r"C:\user\[00]競馬\3ハロンVI\DATA"
W, H     = 512, 320
FPS      = 30
# FONT_S   = 11   # 小フォントサイズ（行内テキスト）
# FONT_M   = 13   # 中フォントサイズ（見出し）

# ============================================================
# Pyxel カラーパレット (デフォルト16色インデックス)
# ============================================================
COL_BG      = 1   # 紺
COL_BG2     = 0   # 黒
COL_BG3     = 1   # 紺(奇数行)
COL_BORDER  = 5   # 灰
COL_TITLE   = 10  # 黄
COL_HEADER  = 6   # 水色
COL_TEXT    = 7   # 白
COL_MUTED   = 13  # 薄紫
COL_ODDS_LO = 8   # 赤  (〜5倍)
COL_ODDS_MD = 9   # 橙  (〜15倍)
COL_SC_HI   = 11  # 黄緑 (90+)
COL_SC_MD   = 10  # 黄   (75+)
COL_SC_LO   = 13  # 薄紫
COL_BTN     = 5
COL_BTN_A   = 6
COL_ST_E    = 8   # 逃
COL_ST_S    = 9   # 先
COL_ST_D    = 12  # 差
COL_ST_O    = 14  # 追

# pyxel パレットの RGB 値 (デフォルト)
PALETTE_RGB = [
    (0,0,0),(29,43,83),(126,37,83),(0,135,81),
    (171,82,54),(95,87,79),(194,195,199),(255,241,232),
    (255,0,77),(255,163,0),(255,236,39),(0,228,54),
    (41,173,255),(131,118,156),(255,119,168),(255,204,170),
]

GATE_COLS = [7,7,8,8,9,9,12,12,10,10,11,11,14,14,13,13]
STYLE_COL = {'逃':COL_ST_E,'先':COL_ST_S,'差':COL_ST_D,'追':COL_ST_O}

ROW_H  = 12   # 一覧行高さ
ITEM_H = 16   # ファイル/シート選択行高さ

FONT_S_SIZE = 10
FONT_M_SIZE = 12
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_S = pyxel.Font( os.path.join(BASE_DIR, "umplus_j10r.bdf") )
FONT_M = pyxel.Font( os.path.join(BASE_DIR, "umplus_j12r.bdf") )
# ============================================================
# シーン定数
# ============================================================
SCENE_FILE   = "file"
SCENE_LIST   = "list"
SCENE_DETAIL = "detail"

SORT_KEYS   = ["no","odds","index"]
SORT_LABELS = ["馬番順","オッズ順","指数順"]

# ============================================================
# PIL → Pyxel テキスト描画
# ============================================================
# Pyxelの色インデックス→RGB 逆引きキャッシュ
_COL2RGB = {i: PALETTE_RGB[i] for i in range(16)}

# 描画済みテキストの (text, size, col) → (w, h, pixel_list) キャッシュ
_TEXT_CACHE: dict = {}


def draw_text(x: int, y: int, text: str, col: int = COL_TEXT, font = FONT_S): 
    """日本語表示"""
    if not text:
        return
    pyxel.text( x, y, str(text), col, font)

def text_px(text, font=FONT_S):
    """テキストの描画幅(px)を返す"""
    return len(str(text)) * 6


def truncate(text: str, max_px: int, size: int = FONT_S) -> str:
    """max_px 幅に収まるよう末尾を切り詰める"""
    if text_px(text, size) <= max_px:
        return text
    result = ""
    for ch in text:
        if text_px(result + ch, size) > max_px:
            break
        result += ch
    return result


def wrap_text(text: str, max_px: int, size: int = FONT_S) -> list:
    """max_px 幅で折り返してリストを返す"""
    lines, buf = [], ""
    for ch in text:
        if text_px(buf + ch, size) > max_px:
            if buf:
                lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        lines.append(buf)
    return lines

# ============================================================
# その他ユーティリティ
# ============================================================
def score_col(idx: int) -> int:
    if idx >= 90: return COL_SC_HI
    if idx >= 75: return COL_SC_MD
    return COL_SC_LO

def odds_col(odds) -> int:
    if odds is None: return COL_MUTED
    if odds <= 5:    return COL_ODDS_LO
    if odds <= 15:   return COL_ODDS_MD
    return COL_TEXT

def mark_col(mark: str) -> int:
    return {"◎":COL_TITLE,"○":COL_ODDS_MD,"▲":COL_ODDS_LO,
            "☆":COL_HEADER,"△":COL_SC_HI,"穴":14}.get(mark, COL_MUTED)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def draw_rectb(x, y, w, h, col):
    pyxel.rectb(x, y, w, h, col)

def draw_btn(x, y, w, label, active=False, fsize=FONT_S):
    bg   = COL_BTN_A if active else COL_BTN
    tc   = COL_TITLE if active else COL_TEXT
    pyxel.rect(x, y, w, FONT_S_SIZE + 4, bg)
    draw_rectb(x, y, w, FONT_S_SIZE + 4, 7 if active else COL_BORDER)
    tx = x + max(2, (w - text_px(label, fsize)) // 2)
    draw_text(tx, y + 2, label, tc, fsize)

# ============================================================
# ダミーデータ
# ============================================================
DUMMY_RACES = [
    {
        "race_name": "ヴィクトリアマイル 2026",
        "course"   : "東京 芝1600m  G1",
        "pace"     : "ミドル〜スロー",
        "horses"   : [
            dict(gate=1,no=1, name="カピリナ",        odds=94.2, sex="牝5",jw=56,style="差",jockey="横山典", index=67, prev="3W東京1600良 3着9人 3F33.8", wk="11.8",mark="",  comment="切れ味勝負は疑問"),
            dict(gate=1,no=2, name="ワイドラトゥール",  odds=149.2,sex="牝5",jw=56,style="差",jockey="横山武", index=68, prev="4W阪神1600良 2着6人 3F33.5", wk="12.1",mark="",  comment="展開待ち強い"),
            dict(gate=2,no=3, name="マビュース",       odds=65.8, sex="牝4",jw=56,style="差",jockey="ゴンサル",index=88, prev="3W東京1600良 1着2人 3F32.9", wk="11.3",mark="△",comment="内差し展開なら向い"),
            dict(gate=2,no=4, name="エリカエクスプレ",  odds=20.9, sex="牝4",jw=56,style="逃",jockey="武豊",  index=79, prev="4W東京1600良 2着4人 3F34.2", wk="12.4",mark="",  comment="単騎逃げなら警戒"),
            dict(gate=3,no=5, name="ケリフレッドアス",  odds=76.1, sex="牝4",jw=56,style="差",jockey="ディー",index=66, prev="6W中山1600稍 5着8人 3F34.0", wk="11.9",mark="",  comment="展開向けば浮上"),
            dict(gate=3,no=6, name="ラヴァンダ",       odds=26.6, sex="牝5",jw=56,style="差",jockey="岩田望",index=77, prev="4W東京1600良 4着5人 3F33.1", wk="11.5",mark="",  comment="東京マイル合う"),
            dict(gate=4,no=7, name="クイーンズウォー",  odds=10.4, sex="牝5",jw=56,style="先",jockey="西村淳",index=86, prev="3W東京1600良 2着3人 3F33.0", wk="11.2",mark="☆",comment="好位抜け出し型"),
            dict(gate=4,no=8, name="カムニャック",     odds=5.3,  sex="牝4",jw=56,style="差",jockey="川田",  index=84, prev="4W阪神1600良 1着1人 3F32.7", wk="11.0",mark="",  comment="能力高いが展開鍵"),
            dict(gate=5,no=9, name="ココナッブラウ",   odds=32.7, sex="牝6",jw=56,style="差",jockey="北村友",index=82, prev="5W東京1600良 6着7人 3F33.4", wk="11.7",mark="穴",comment="差し展開穴候補"),
            dict(gate=5,no=10,name="ドロップオブライ",  odds=61.1, sex="牝7",jw=56,style="差",jockey="松若",  index=70, prev="8W阪神1600良 7着11人 3F33.9",wk="12.0",mark="",  comment="未勝届くか鍵"),
            dict(gate=6,no=11,name="ポンドガール",     odds=30.7, sex="牝5",jw=56,style="差",jockey="丹内",  index=90, prev="4W東京1600良 3着6人 3F32.8", wk="11.1",mark="▲",comment="東京替わり激走警戒"),
            dict(gate=6,no=12,name="エンブロイダリー",  odds=2.8,  sex="牝4",jw=56,style="差",jockey="ルメール",index=96,prev="3W東京1600良 1着1人 3F32.4", wk="10.8",mark="◎",comment="完成度最上位"),
            dict(gate=7,no=13,name="カナテープ",       odds=34.7, sex="牝7",jw=56,style="追",jockey="松山",  index=73, prev="6W中山2000良 8着12人 3F34.5",wk="11.9",mark="",  comment="展開嵌れば浮上"),
            dict(gate=7,no=14,name="ジョスラン",       odds=27.1, sex="牝4",jw=56,style="差",jockey="戸崎圭",index=78, prev="5W阪神1600良 4着7人 3F33.3", wk="11.6",mark="",  comment="器用さ魅力あり"),
            dict(gate=7,no=15,name="アイサンサン",     odds=37.8, sex="牝4",jw=56,style="先",jockey="幸",    index=75, prev="4W東京1600良 5着9人 3F33.8", wk="12.3",mark="",  comment="前残りなら注意"),
            dict(gate=8,no=16,name="ニシノティアモ",   odds=9.8,  sex="牝5",jw=56,style="差",jockey="津村",  index=87, prev="3W東京1600良 2着3人 3F32.9", wk="11.1",mark="☆",comment="末脚安定感高い"),
            dict(gate=8,no=17,name="バラディレーヌ",   odds=40.5, sex="牝4",jw=56,style="差",jockey="坂井",  index=74, prev="5W阪神1600良 9着10人 3F33.5",wk="11.8",mark="",  comment="流れ向けば注意"),
            dict(gate=8,no=18,name="チェルヴィニア",   odds=None, sex="牝5",jw=56,style="差",jockey="レーン", index=93, prev="4W東京1600良 1着2人 3F32.5", wk="10.9",mark="○",comment="能力上位明白"),
        ],
    },
]

# ============================================================
# DATAフォルダスキャン
# ============================================================
def scan_data_dir(data_dir: str):

    files = []

    for root, _, fs in os.walk(data_dir):
        for f in fs:
            if f.lower().endswith(".json") and not f.startswith("~$"):
                full_path = os.path.join(root, f)

                files.append({
                    "path": full_path,
                    "label": os.path.splitext(f)[0],
                    "dir": os.path.relpath(root, data_dir),
                })

    files.sort(key=lambda x: os.path.getmtime(x["path"]), reverse=True)

    return files

# ============================================================
# json ローダー
# ============================================================
def load_races_from_json(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] {path}: {e}")
        return []

    pyxel_rows   = data.get("pyxel",   [])
    summary_rows = data.get("summary", [])
    raw_rows     = data.get("rawdata", [])

    if not pyxel_rows:
        print(f"[ERROR] 'pyxel' キーが見つかりません: {path}")
        return []

    # summary / rawdata を馬名でインデックス化
    summary_dict = {}
    for row in summary_rows:
        name = str(row.get("馬名", "")).strip()
        if name:
            summary_dict[name] = row

    raw_dict = {}
    for row in raw_rows:
        name = str(row.get("馬名", "")).strip()
        if name:
            raw_dict[name] = row

    def safe(v, default=""):
        if v is None:
            return default
        try:
            if math.isnan(float(v)):
                return default
        except (TypeError, ValueError):
            pass
        return v

    horses = []
    for row in pyxel_rows:
        try:
            no_val = row.get("馬番", "")
            if no_val == "" or no_val is None:
                continue
            no_val = int(no_val)

            gate = math.ceil(no_val / 2)

            odds_raw = str(row.get("オッズ戦績", ""))
            m    = re.search(r"(\d+\.\d+)", odds_raw)
            odds = float(m.group(1)) if m else None

            sex    = str(row.get("性齢", "")).split("/")[0]
            jw     = str(row.get("斤量", ""))
            jockey = str(row.get("騎手", ""))

            horse_name = str(row.get("馬名", "")).strip()

            horses.append(dict(
                gate     = gate,
                no       = no_val,
                name     = horse_name,
                odds     = odds,
                sex      = sex,
                jw       = jw,
                style    = str(row.get("脚質", "差")).strip(),
                jockey   = jockey,
                index    = int(row.get("総合指数", 0) or 0),
                prev1    = safe(row.get("前走")),
                prev2    = safe(row.get("前々")),
                prev3    = safe(row.get("3走")),
                prev_3F  = safe(row.get("前3F")),
                train_1F = safe(row.get("調1F")),
                mark     = str(row.get("印", "") or "").strip(),
                summary  = summary_dict.get(horse_name, {}),
                raw      = raw_dict.get(horse_name, {}),
            ))

        except Exception as ex:
            print(f"[WARN] 行スキップ: {ex}")
            continue

    if not horses:
        return []

    race_name = os.path.splitext(os.path.basename(path))[0]

    # 展開予想は summary の最終行の備考欄から取得
    pace = ""
    if summary_rows:
        last = summary_rows[-1]
        biko = str(last.get("備考", "") or "")
        m = re.search(r"予想ペース[：:]\s*(\S+)", biko)
        if m:
            pace = m.group(1)

    return [{
        "race_name": race_name,
        "course"   : f'{data.get("course","")} {data.get("distance","")}',
        "pace"     : pace,
        "horses"   : horses,
    }]


# ============================================================
# App クラス
# ============================================================
class KeibaApp:

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

        self.file_list   : list = []
        self.file_cursor : int  = 0
        self.file_scroll : int  = 0

        self.current_file : dict | None = None
        self.sheet_races  : list = []
        self.sheet_cursor : int  = 0
        self.sheet_scroll : int  = 0

        self.current_race  : dict | None = None
        self.horses_sorted : list = []
        self.list_cursor   : int  = 0
        self.list_scroll   : int  = 0
        self.sort_idx      : int  = 0
        self.sort_asc      : bool = True

        self.detail_horse  : dict | None = None
        self.detail_scroll : int  = 0

        self.scene   = SCENE_FILE
        self.err_msg = ""

        pyxel.init(W, H, title="競馬予想ビューア", fps=FPS)
        pyxel.mouse(True)
        self._scan_files()
        pyxel.run(self.update, self.draw)

    # ------ ファイルスキャン ----------------------------------
    def _scan_files(self):
        if os.path.isdir(self.data_dir):
            self.file_list = scan_data_dir(self.data_dir)
            if not self.file_list:
                self.err_msg  = f"jsonが見つかりません"
                self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
        else:
            self.err_msg  = f"フォルダ未検出: {self.data_dir}"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]

    # ------ ソート -------------------------------------------
    def _apply_sort(self):
        key = SORT_KEYS[self.sort_idx]
        asc = self.sort_asc
        hs  = list(self.current_race["horses"])
        if   key == "odds":  hs.sort(key=lambda h:(h["odds"] is None, h["odds"] or 9999), reverse=not asc)
        elif key == "index": hs.sort(key=lambda h: h["index"], reverse=not asc)
        else:                hs.sort(key=lambda h: h["no"],    reverse=not asc)
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
        if   self.scene == SCENE_FILE:   self._upd_file(mx, my, wh)
        elif self.scene == SCENE_LIST:   self._upd_list(mx, my, wh)
        elif self.scene == SCENE_DETAIL: self._upd_detail(mx, my, wh)

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
            races = DUMMY_RACES
            self.sheet_races = DUMMY_RACES
        else:
            races = load_races_from_json(fi["path"])
            self.sheet_races = races
            if not self.sheet_races:
                self.err_msg = f"読込失敗: {fi['label']}"
                return
            
        self.current_file = fi

        # 先頭レースを開く
        self.current_race = races[0]
        self.current_race["race_name"] = fi["label"]

        # _open_race() がやっていた処理
        self.list_cursor = 0
        self.list_scroll = 0
        self.sort_idx = 0
        self.sort_asc = True

        self._apply_sort()

        self.scene = SCENE_LIST

    def _open_race(self, idx):
        self.current_race = self.sheet_races[idx]
        self.list_cursor = 0; self.list_scroll = 0
        self.sort_idx = 0; self.sort_asc = True
        self._apply_sort()
        self.scene = SCENE_LIST

    # ---- 出走表一覧 ------------------------------------------
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
            self._apply_sort(); self.list_cursor = 0; self.list_scroll = 0
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            if 2 <= mx <= 80 and 2 <= my <= 16: self.scene = SCENE_FILE; return
            HDRH = 30
            if my >= HDRH:
                row_i = (my - HDRH) // ROW_H + self.list_scroll
                if 0 <= row_i < n:
                    if row_i == self.list_cursor: self._open_detail(row_i)
                    else: self.list_cursor = row_i

    def _open_detail(self, idx):

        self.detail_horse = self.horses_sorted[idx]
        self.detail_scroll = 0
        self.scene = SCENE_DETAIL

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
        if   self.scene == SCENE_FILE:   self._drw_file()
        elif self.scene == SCENE_LIST:   self._drw_list()
        elif self.scene == SCENE_DETAIL: self._drw_detail()

    # ------ 共通パーツ ----------------------------------------
    def _hdr(self, title: str, sub: str = "", back: str = ""):
        pyxel.rect(0, 0, W, 18, COL_BG)
        draw_rectb(0, 0, W, 18, COL_BORDER)
        ox = 4
        if back:
            draw_btn(2, 2, text_px(back) + 10, back)
            ox = text_px(back) + 16
        draw_text(ox, 3, truncate(title, W - ox - 4), COL_TITLE, FONT_M)
        if sub:
            draw_text(ox, 3 + FONT_M_SIZE + 1, truncate(sub, W - ox - 4), COL_MUTED, FONT_S)

    def _footer(self, msg: str):
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

    # ------ ファイル選択 --------------------------------------
    def _drw_file(self):
        pyxel.rect(0, 0, W, 44, COL_BG)
        draw_rectb(0, 0, W, 44, COL_BORDER)
        draw_text(6,  3, "★ KEIBA ANALYZER ★",                     COL_TITLE,  FONT_M)
        draw_text(6, 20, "DATAフォルダ: " + truncate(self.data_dir, W-80), COL_HEADER, FONT_S)
        cnt = sum(1 for f in self.file_list if f["path"] != "__DUMMY__")
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
            bg  = COL_BG if sel else (COL_BG2 if rel % 2 == 0 else COL_BG3)
            pyxel.rect(0, ry, W - 5, ITEM_H, bg)
            if sel: draw_rectb(0, ry, W - 5, ITEM_H, COL_HEADER)
            sub = fi["dir"] if fi["dir"] not in (".", "") else ""
            sw  = text_px(sub, FONT_S) + 4 if sub else 0
            draw_text(4, ry + 3, truncate(fi["label"], W - 12 - sw),
                      COL_TITLE if sel else COL_TEXT, FONT_S)
            if sub:
                draw_text(W - 5 - sw, ry + 3, sub, COL_MUTED, FONT_S)

        self._scrollbar(TOP, len(self.file_list), vis, self.file_scroll)
        self._footer("↑↓:選択  Enter/クリック2回:決定  Q:終了")


    # ------------------------------------
    # 指数色
    # ------------------------------------
    def rating_color(self,v):

        try:
            v = float(v)
        except:
            return COL_TEXT

        if v >= 100:
            return pyxel.COLOR_RED

        elif v >= 90:
            return pyxel.COLOR_YELLOW

        return COL_TEXT


    # ------------------------------------
    # 前走3F色
    # ------------------------------------
    def last3f_color(self,v):

        try:
            v = float(v)
        except:
            return COL_TEXT

        if v < 33.5:
            return pyxel.COLOR_RED

        elif v < 34.0:
            return pyxel.COLOR_YELLOW

        return COL_SC_HI


    # ------------------------------------
    # 調教1F色
    # ------------------------------------
    def train1f_color(self,v):

        try:
            v = float(v)
        except:
            return COL_TEXT

        if v < 11.0:
            return pyxel.COLOR_RED

        elif v <= 11.5:
            return pyxel.COLOR_YELLOW

        return COL_SC_HI

    # ------ 出走表一覧 ----------------------------------------
    def _drw_list(self):
        race = self.current_race
        # ---- ヘッダ
        pyxel.rect(0, 0, W, 18, COL_BG)
        draw_rectb(0, 0, W, 18, COL_BORDER)
        draw_btn(2, 2, text_px("◀ レース選択") + 10, "◀ レース選択")
        ox = text_px("◀ レース選択") + 16
        draw_text(ox, 3, truncate(race["race_name"], W - ox - 80), COL_TITLE, FONT_M)
        slbl = SORT_LABELS[self.sort_idx]
        draw_btn(W - text_px(slbl) - 14, 3, text_px(slbl) + 10, slbl, active=True)

        # ---- 列ヘッダ
        cx = self._cx()
        yh = 19
        pyxel.rect(0, yh, W, ROW_H + 1, COL_BG)
        draw_rectb(0, yh, W, ROW_H + 1, COL_BORDER)
        for k, lbl in [("no","番"),("name","馬名"),("odds","オッズ"),
                       ("sex","性齢"),("style","脚"),("jkey","騎手"),
                       ("idx","指数"),("prev1","前走"),("prev2","前々"),
                       ("prev3","3走"),("prev_3F","前3F"),("train_1F","調1F"),
                       ("mark","印")]:
            draw_text(cx[k], yh + 2, lbl, COL_HEADER, FONT_S)

        # ---- 行
        vis = self._vis_rows()
        for rel in range(vis):
            ai = self.list_scroll + rel
            if ai >= len(self.horses_sorted): break
            h  = self.horses_sorted[ai]
            ry = 31 + rel * ROW_H
            sel= (ai == self.list_cursor)
            bg = COL_BG if sel else (COL_BG2 if rel % 2 == 0 else COL_BG3)
            pyxel.rect(0, ry, W - 5, ROW_H, bg)
            if sel: draw_rectb(0, ry, W - 5, ROW_H, COL_HEADER)
            ty = ry + 1

            # 枠ドット
            gcol = GATE_COLS[min((h["gate"] - 1) * 2, len(GATE_COLS) - 1)]
            pyxel.rect(cx["gate"], ty + 2, 6, 6, gcol)

            draw_text(cx["no"], ty,
                    f"{h['no']:2d}",
                    COL_TEXT, FONT_S)

            nw = cx["odds"] - cx["name"] - 2
            draw_text(cx["name"], ty,
                    truncate(h["name"], nw),
                    COL_TITLE if sel else COL_TEXT,
                    FONT_S)

            odds = h["odds"]
            if odds:
                odds_text = f"{odds:.0f}" if odds >= 100 else f"{odds:.1f}"
            else:
                odds_text = "---"
            draw_text(cx["odds"], ty,odds_text,odds_col(odds),FONT_S)

            draw_text(cx["sex"], ty,
                    truncate(h["sex"], 24),
                    COL_TEXT,
                    FONT_S)

            draw_text(cx["style"], ty,
                    h["style"],
                    STYLE_COL.get(h["style"], COL_TEXT),
                    FONT_S)

            jw2 = cx["idx"] - cx["jkey"] - 2
            draw_text(cx["jkey"], ty,
                    truncate(h["jockey"], jw2),
                    COL_MUTED,
                    FONT_S)

            # 総合指数バー
            bw = clamp(h["index"] * 30 // 100, 1, 30)
            pyxel.rect(cx["idx"], ty + 3, bw, 5, score_col(h["index"]))

            draw_text(cx["idx"] + 32, ty,f"{h['index']:3d}",
                    score_col(h["index"]),FONT_S)

            # 前走指数
            draw_text(
                cx["prev1"], ty,str(h.get("prev1", "")),
                self.rating_color(h.get("prev1", 0)),
                FONT_S
            )

            # 前々走指数
            draw_text(
                cx["prev2"], ty,str(h.get("prev2", "")),
                self.rating_color(h.get("prev2", 0)),
                FONT_S
            )

            # 3走前指数
            draw_text(
                cx["prev3"], ty,str(h.get("prev3", "")),
                self.rating_color(h.get("prev3", 0)),
                FONT_S
            )   


            # 前走上がり3F
            draw_text(
                cx["prev_3F"], ty,str(h.get("prev_3F", "")),
                self.last3f_color(h.get("prev_3F", "")),FONT_S
            )

            # 追切ラスト1F
            draw_text(
                cx["train_1F"], ty,str(h.get("train_1F", "")),
                self.train1f_color(h.get("train_1F", "")),FONT_S
            )

            # 印
            draw_text(cx["mark"], ty,
                    h.get("mark", ""),
                    mark_col(h.get("mark", "")),
                    FONT_S)

        self._scrollbar(31, len(self.horses_sorted), vis, self.list_scroll)
        self._footer("Enter:詳細  Tab:ソート切替  ESC:戻る  Q:終了")

    def _cx(self):
        return dict(gate=2, no=10, name=22, odds=130, sex=170,
                    style=200, jkey=220, idx=252, prev1=310, prev2=340, prev3=370,
                    prev_3F=400, train_1F=435, mark=470)


    # ------ 詳細 ---------------------------------------------
    def _drw_detail(self):
        h  = self.detail_horse
        sc = self.detail_scroll        
        s = h["summary"]
        r = h["raw"]

        pyxel.rect(0, 0, W, 18, COL_BG)
        draw_rectb(0, 0, W, 18, COL_BORDER)
        draw_btn(2, 2, text_px("◀ 一覧") + 10, "◀ 一覧")
        gcol = GATE_COLS[min((h["gate"]-1)*2, len(GATE_COLS)-1)]
        ox   = text_px("◀ 一覧") + 16
        pyxel.rect(ox, 5, 8, 8, gcol)
        draw_text(ox + 12, 3, truncate(f"{h['no']}番  {h['name']}", W - ox - 16), COL_TITLE, FONT_M)

        def oy(dy): return 22 + dy - sc * (FONT_S_SIZE + 3)

        def line(dy, label, val, vc=COL_TEXT):
            y = oy(dy)
            if not (18 < y < H - 13): return
            draw_text(4, y, label, COL_HEADER, FONT_S)
            # 本文開始位置を固定
            VALUE_X = 64
            # draw_text(16 + text_px(label, FONT_S) + 16, y, str(val), vc, FONT_S)
            draw_text(VALUE_X, y, str(val), vc, FONT_S)

        def section(dy, title_s):
            y = oy(dy)
            if not (18 < y < H - 13): return
            pyxel.rect(2, y, W - 8, FONT_S_SIZE + 4, COL_BG)
            draw_rectb(2, y, W - 8, FONT_S_SIZE + 4, COL_BORDER)
            draw_text(6, y + 2, title_s, COL_HEADER, FONT_S)

        LH = FONT_S_SIZE + 5   # 行高さ
        SH = FONT_S_SIZE + 8   # セクション高さ

        section(0,       "基本情報")
        line(SH,"", f'【{h["mark"]}】 {h["odds"]:.1f}倍  'f'{h["sex"]}  {h["jw"]}kg  'f'{h["jockey"]}  'f'脚質:{h["style"]}')

        base2 = SH + LH * 1
        section(base2,   "総合指数")
        line(base2+SH,   "指数    ", str(h["index"]),                score_col(h["index"]))
        by = oy(base2 + SH + LH + 2)
        if 18 < by < H - 13:
            bw = clamp(h["index"] * (W - 24) // 100, 1, W - 24)
            pyxel.rect(4, by, W - 8, 7, COL_BG)
            pyxel.rect(4, by, bw,    7, score_col(h["index"]))
            draw_rectb(4, by, W - 8, 7, COL_BORDER)

        base3 = base2 + SH + LH * 2
        section(base3,   "調教")
        line(base3+SH,   "調教場所 ", r["調教場所・馬場"])      
        line(base3+SH*2, "調教時計 ", r["時計"])   

        base4 = base3 + SH + LH * 2
        section(base4, "近走成績")

        y = base4 + SH

        for i, key in enumerate(["前走", "前々走", "3走前", "4走前"]):
            txt = str(r.get(key, ""))

            pos = txt.find("kg ")
            if pos >= 0:
                lines = [
                    txt[:pos + 3],      # 55.0kgまで
                    txt[pos + 3:]       # その後全部
                ]
            else:
                lines = [txt]

            y = base4 + SH + i * (LH * 2)

            line(y, key, lines[0])

            if len(lines) > 1:
                line(y + LH, "", lines[1], COL_TITLE)

        # base5 = base4 + SH + LH * 5 + 6
        # section(base5,   "コメント")
        # for ci, cl in enumerate(wrap_text(h["comment"], W - 16, FONT_S)[:4]):
        #     line(base5 + SH + LH * ci, "  ", cl, COL_TEXT)

        self._footer("↑↓/ホイール:スクロール  ESC:戻る  Q:終了")


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    KeibaApp(data_dir)
