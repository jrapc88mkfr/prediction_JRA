# ============================================================
# keiba_pyxel_ANT_json.py  競馬予想ビューア  (Pyxel版 WEB対応修正版)
#
# 【WEB版で動かなかった主な原因と修正】
#
# 1. urllib.request が Pyxel Web版(Emscripten/Pyodide)で使えない
#    → JavaScript の fetch API を pyodide.ffi / js モジュール経由で呼ぶ
#      非同期取得を pyxel の update ループ内でポーリングして実現
#
# 2. fetch_json / scan_data_dir が同期処理だった
#    → Web版では JS Promise ベースの非同期フェッチに全面変更
#      _AsyncLoader クラスで「取得中 / 完了 / 失敗」を管理
#
# 3. アプリ初期化時に同期ネットワークアクセスしていた
#    → __init__ では非同期ジョブを「投げる」だけにし、
#      update() でポーリング → 完了後に画面遷移
#
# 4. BASE_DIR / DATA_DIR の混在
#    → IS_WEB 時は BASE_URL のみ使用、ローカルパスを参照しない
#
# 5. フォント PATH
#    → Web 版は DATA/ 以下に bdf を配置しているため
#      IS_WEB 時は DATA/ プレフィックスを使う
#
# 依存(ローカル実行):
#   pip install pyxel pandas openpyxl
#
# 起動:
#   python keiba_pyxel_ANT_json.py
# ============================================================

import sys, os, re, io, math, glob, json
import pyxel
import platform


# ============================================================
# WEB / ローカル判定
# ============================================================
IS_WEB = platform.system() == "Emscripten"
if IS_WEB:
    import js

import threading
try:
    if not IS_WEB:
        import requests
        from bs4 import BeautifulSoup
    else:
        requests = None
        BeautifulSoup = None
except Exception:
    # requests/bs4 が入っていない環境でも起動だけはできるようにする
    requests = None
    BeautifulSoup = None
# ============================================================
# パス設定
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if not IS_WEB else ""
BASE_URL = "https://jrapc88mkfr.github.io/prediction_JRA"

if IS_WEB:
    DATA_DIR = ""
    FONT_DIR = ""          # Web版はDATAフォルダ以下にフォントを配置
else:
    DATA_DIR = os.path.join(BASE_DIR, "DATA")
    FONT_DIR = BASE_DIR

# ============================================================
# 設定
# ============================================================
CONTENT_W = 512          # 既存レイアウト（ファイル/一覧/詳細）の幅
PANEL_W   = 176          # ★追加: 右側「レース結果」パネルの幅
W, H = CONTENT_W + PANEL_W, 320
FPS  = 30
TOP_MARGIN = 12
# ============================================================
# Pyxel カラーパレット
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
COL_BTN_A   = 6
COL_ST_E    = 8
COL_ST_S    = 9
COL_ST_D    = 12
COL_ST_O    = 14

PALETTE_RGB = [
    (0,0,0),(29,43,83),(126,37,83),(0,135,81),
    (171,82,54),(95,87,79),(194,195,199),(255,241,232),
    (255,0,77),(255,163,0),(255,236,39),(0,228,54),
    (41,173,255),(131,118,156),(255,119,168),(255,204,170),
]

GATE_COLS  = [7,7,8,8,9,9,12,12,10,10,11,11,14,14,13,13]
STYLE_COL  = {'逃':COL_ST_E,'先':COL_ST_S,'差':COL_ST_D,'追':COL_ST_O}

ROW_H   = 12
ITEM_H  = 16

FONT_S_SIZE = 10
FONT_M_SIZE = 12

# ============================================================
# フォント初期化 (パスを IS_WEB で切替)
# ============================================================
_font_s_path = os.path.join(FONT_DIR, "umplus_j10r.bdf")
_font_m_path = os.path.join(FONT_DIR, "umplus_j12r.bdf")
FONT_S = pyxel.Font(_font_s_path)
FONT_M = pyxel.Font(_font_m_path)

# ============================================================
# シーン定数
# ============================================================
SCENE_LOADING = "loading"   # ★追加: 非同期ロード待ち
SCENE_FILE    = "file"
SCENE_LIST    = "list"
SCENE_DETAIL  = "detail"

SORT_KEYS   = ["no","odds","index"]
SORT_LABELS = ["馬番順","オッズ順","指数順"]

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

def wrap_text(text, max_px, size=FONT_S):
    lines, buf = [], ""
    for ch in text:
        if text_px(buf + ch, size) > max_px:
            if buf: lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf: lines.append(buf)
    return lines

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

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def draw_rectb(x, y, w, h, col):
    pyxel.rectb(x, y, w, h, col)

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
DUMMY_RACES = [
    {
        "race_name": "ヴィクトリアマイル 2026",
        "course"   : "東京 芝1600m  G1",
        "pace"     : "ミドル〜スロー",
        "horses"   : [
            dict(gate=1,no=1, name="カピリナ",        odds=94.2, sex="牝5",jw=56,style="差",jockey="横山典", index=67, prev1="",prev2="",prev3="",prev_3F="33.8",train_1F="11.8",mark="",  summary={},raw={}),
            dict(gate=2,no=3, name="マビュース",       odds=65.8, sex="牝4",jw=56,style="差",jockey="ゴンサル",index=88, prev1="",prev2="",prev3="",prev_3F="32.9",train_1F="11.3",mark="△",summary={},raw={}),
            dict(gate=4,no=7, name="クイーンズウォー",  odds=10.4, sex="牝5",jw=56,style="先",jockey="西村淳",index=86, prev1="",prev2="",prev3="",prev_3F="33.0",train_1F="11.2",mark="☆",summary={},raw={}),
            dict(gate=4,no=8, name="カムニャック",     odds=5.3,  sex="牝4",jw=56,style="差",jockey="川田",  index=84, prev1="",prev2="",prev3="",prev_3F="32.7",train_1F="11.0",mark="",  summary={},raw={}),
            dict(gate=6,no=11,name="ポンドガール",     odds=30.7, sex="牝5",jw=56,style="差",jockey="丹内",  index=90, prev1="",prev2="",prev3="",prev_3F="32.8",train_1F="11.1",mark="▲",summary={},raw={}),
            dict(gate=6,no=12,name="エンブロイダリー",  odds=2.8,  sex="牝4",jw=56,style="差",jockey="ルメール",index=96,prev1="",prev2="",prev3="",prev_3F="32.4",train_1F="10.8",mark="◎",summary={},raw={}),
            dict(gate=8,no=16,name="ニシノティアモ",   odds=9.8,  sex="牝5",jw=56,style="差",jockey="津村",  index=87, prev1="",prev2="",prev3="",prev_3F="32.9",train_1F="11.1",mark="☆",summary={},raw={}),
            dict(gate=8,no=18,name="チェルヴィニア",   odds=None, sex="牝5",jw=56,style="差",jockey="レーン", index=93, prev1="",prev2="",prev3="",prev_3F="32.5",train_1F="10.9",mark="○",summary={},raw={}),
        ],
    },
]

# ============================================================
# ★ 非同期フェッチ (Web / ローカル 共通インターフェース)
# ============================================================
class _AsyncLoader:
    """
    Web版: JS fetch → Promise → Pyxel update()でポーリング
    ローカル版: 即時同期読み込み、同じインターフェースで返す
    """
    STATE_IDLE    = "idle"
    STATE_LOADING = "loading"
    STATE_DONE    = "done"
    STATE_ERROR   = "error"

    def __init__(self):
        self.state   = self.STATE_IDLE
        self.result  = None     # 取得した Python オブジェクト
        self.error   = ""
        self._promise = None    # JS Promise (Web版のみ)


    def fetch(self, url: str):
        """非同期フェッチ開始"""
        self.state  = self.STATE_LOADING
        self.result = None
        self.error  = ""

        if IS_WEB:
            self._fetch_web(url)
        else:
            self._fetch_local(url)

    # ---- ローカル版 (同期) ----------------------------------
    def _fetch_local(self, path: str):

        try:
            with open(path, "r", encoding="utf-8") as f:
                self.result = json.load(f)

            self.state = self.STATE_DONE

        except Exception as e:
            self.error = str(e)
            self.state = self.STATE_ERROR

    # ---- Web版 (JS fetch, 非同期) ---------------------------
    def _fetch_web(self, url: str):
            try:
                import pyodide.http
                
                async def _do_fetch():
                    try:
                        self.err_msg = f"fetch開始: {url[:60]}"
                        response = await pyodide.http.pyfetch(url)
                        self.err_msg = f"status={response.status}"
                        text = await response.string()
                        self.err_msg = f"取得OK len={len(text)}"
                        import json as _json
                        self.result = _json.loads(text)
                        self.state = self.STATE_DONE
                    except Exception as e:
                        self.error = f"INNER:{type(e).__name__}:{e}"
                        self.err_msg = self.error
                        self.state = self.STATE_ERROR

                import asyncio
                asyncio.ensure_future(_do_fetch())

            except Exception as e:
                self.error = f"OUTER:{type(e).__name__}:{e}"
                self.err_msg = self.error
                self.state = self.STATE_ERROR

    def is_loading(self): return self.state == self.STATE_LOADING
    def is_done(self):    return self.state == self.STATE_DONE
    def is_error(self):   return self.state == self.STATE_ERROR


# ============================================================
# JSON → レースデータ変換
# ============================================================
def parse_races_from_json(data: dict, label: str) -> list:
    """ロード済み dict からレースリストを生成"""
    pyxel_rows   = data.get("pyxel",   [])
    summary_rows = data.get("summary", [])
    raw_rows     = data.get("rawdata", [])

    if not pyxel_rows:
        return []

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
            if no_val == "" or no_val is None: continue
            no_val = int(no_val)

            gate = math.ceil(no_val / 2)

            odds_raw = str(row.get("オッズ戦績", ""))
            m    = re.search(r"(\d+\.\d+)", odds_raw)
            odds = float(m.group(1)) if m else None

            horse_name = str(row.get("馬名", "")).strip()

            horses.append(dict(
                gate     = gate,
                no       = no_val,
                name     = horse_name,
                odds     = odds,
                sex      = str(row.get("性齢", "")).split("/")[0],
                jw       = str(row.get("斤量", "")),
                style    = str(row.get("脚質", "差")).strip(),
                jockey   = str(row.get("騎手", "")),
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

    if not horses:
        return []

    pace = ""
    if summary_rows:
        biko = str(summary_rows[-1].get("備考", "") or "")
        m = re.search(r"予想ペース[：:]\s*(\S+)", biko)
        if m: pace = m.group(1)

    return [{
        "race_name": label,
        "course"   : f'{data.get("course","")} {data.get("distance","")}',
        "pace"     : pace,
        "horses"   : horses,
    }]


# ============================================================
# ★追加: レース結果オンライン取得 (netkeiba)
#
#   ファイル名 "260712_福島芝2000m_七夕賞_予想中" のような
#   ラベルから 開催日・競馬場・レース名 を推測し、
#   netkeiba の「結果・払戻」ページを取得して
#   1着/2着/3着 と 馬連・3連複 の払戻を抜き出す。
#
#   ・ローカル実行時のみ有効 (IS_WEB では無効)
#   ・取得結果は DATA フォルダ内にキャッシュして再取得を避ける
#   ・利用規約への配慮として1レースにつき2回だけ通信し、
#     同じレースは一度キャッシュしたら再アクセスしない
# ============================================================
RESULT_CACHE_SUBDIR = "_result_cache"
_DEBUG = os.environ.get("KEIBA_DEBUG") == "1"   # KEIBA_DEBUG=1 で診断ログを出す
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

def _parse_race_key_from_label(label: str):
    """ 'YYMMDD_場芝距離m_レース名_...' -> (date8, track, race_name) """
    parts = label.split("_")
    if len(parts) < 3:
        return None
    ymd = parts[0]
    if not re.fullmatch(r"\d{6}", ymd):
        return None
    date8 = "20" + ymd  # 20YYMMDD

    m = re.match(r"^([^\d芝ダ]+)(芝|ダ)", parts[1])
    track = m.group(1) if m else ""

    race_name = re.sub(r"[（(].*?[）)]", "", parts[2]).strip()
    if not track or not race_name:
        return None
    return date8, track, race_name


def _http_get(session, url, timeout=10):
    r = session.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    raw = r.content
    # netkeiba は EUC-JP で配信されていることが多く、apparent_encoding だけに
    # 頼ると文字化けして本文が一切マッチしなくなることがあるため、
    # 複数の候補で実際にデコードして「日本語として読めるか」で選ぶ。
    tried = []
    for enc in ("euc-jp", "cp932", "utf-8", r.apparent_encoding or "utf-8"):
        if not enc or enc.lower() in tried:
            continue
        tried.append(enc.lower())
        try:
            text = raw.decode(enc)
        except Exception:
            continue
        if ("レース" in text) or ("馬" in text) or ("払戻" in text):
            if _DEBUG: print(f"[DEBUG] decode success enc={enc} url={url}")
            return text
    if _DEBUG: print(f"[DEBUG] decode fallback (garbled?) url={url}")
    return raw.decode(r.apparent_encoding or "utf-8", errors="replace")


def _find_kaisai_id(session, date8, track):
    """その日の開催一覧から、場名に一致する kaisai_id を探す"""
    url = f"https://race.netkeiba.com/top/payback_list.html?kaisai_date={date8}"
    html = _http_get(session, url)
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.select('a[href*="kaisai_id="]'):
        href = a.get("href", "")
        m = re.search(r"kaisai_id=(\d+)", href)
        if m:
            found.append((a.get_text(strip=True), m.group(1)))
        if m and track in a.get_text(strip=True):
            return m.group(1)
    if _DEBUG:
        print(f"[DEBUG] kaisai_id not found for track={track!r} date={date8}. "
              f"candidates on page: {found}")
    return None


def _find_race_section(soup, race_name):
    """
    実際のnetkeibaマークアップに基づく確実な検索。
    各レースの見出しは <p class="AllResultRaceTitle"> の中の
    <span class="RacePaybackType">11R 北九州記念</span> のような形で、
    そのレース全体(結果表+払戻表)は <div id="tab_PaybackRaceNum_N_con"> に
    包まれている。
    """
    candidates = [race_name]
    if " " in race_name or "　" in race_name:
        candidates.append(re.split(r"[ 　]+", race_name)[-1])

    found_titles = []
    for p in soup.find_all("p", class_="AllResultRaceTitle"):
        span = p.find("span", class_="RacePaybackType")
        if not span:
            continue
        title_txt = span.get_text(strip=True)            # 例: "11R 北九州記念"
        name_only = re.sub(r"^\d+R\s*", "", title_txt)    # 例: "北九州記念"
        found_titles.append(title_txt)
        for cand in candidates:
            if cand == name_only or cand in name_only or name_only in cand:
                container = p.find_parent("div", id=re.compile(r"^tab_PaybackRaceNum_\d+_con$"))
                if container:
                    return container, title_txt

    if _DEBUG:
        print(f"[DEBUG] race section not matched. candidates={candidates} "
              f"page has: {found_titles}")
    return None, None


def _debug_dump_day_html(html, date8, track, data_dir):
    """KEIBA_DEBUG=1 のとき、取得した日付ページの生HTMLを保存する(調査用)"""
    try:
        d = os.path.join(data_dir, RESULT_CACHE_SUBDIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"_debug_{date8}_{track}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[DEBUG] day html saved to: {path}")
    except Exception as e:
        print(f"[DEBUG] dump failed: {e}")


def _parse_race_section(container):
    """該当レースの <div id="tab_PaybackRaceNum_N_con"> から 1-3着 / 馬連 / 3連複 を取り出す"""
    result = {"top3": [], "umaren": "", "sanrenpuku": ""}

    result_table = container.find("table", class_="TablePaybackResult")
    if result_table:
        for tr in result_table.select("tbody tr"):
            rank_div = tr.select_one("td.Result_Num div.Rank")
            name_div = tr.select_one("td.Horse_Info div.Horse_Name")
            if not rank_div or not name_div:
                continue
            rank = rank_div.get_text(strip=True)
            name = name_div.get_text(strip=True)
            if rank and name:
                result["top3"].append({"rank": rank, "name": name})

    for table in container.find_all("table", class_="Payout_Detail_Table"):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            if not th:
                continue
            label = th.get_text(strip=True)
            if label not in ("馬連", "3連複", "３連複"):
                continue
            combo_items = [li.get_text(strip=True)
                           for li in tr.select("td.Result li")
                           if li.get_text(strip=True)]
            combo = "-".join(combo_items)
            payout_td = tr.find("td", class_="Payout")
            payout = payout_td.get_text(" ", strip=True) if payout_td else ""
            payout = re.sub(r"\s+", " ", payout).strip()
            text = f"{combo}  {payout}".strip()
            if label == "馬連":
                result["umaren"] = text
            else:
                result["sanrenpuku"] = text

    if not result["top3"] and not result["umaren"] and not result["sanrenpuku"]:
        return None
    return result


def fetch_race_result_online(label: str, timeout=10, data_dir=None):
    """
    ラベルからレースを特定し、netkeiba から結果を取得する。
    戻り値: dict または None (未確定/取得失敗)
    ローカル実行 (requests/bs4 あり) でのみ動作。
    """
    if IS_WEB or requests is None or BeautifulSoup is None:
        return None

    key = _parse_race_key_from_label(label)
    if not key:
        if _DEBUG: print(f"[DEBUG] label parse failed: {label!r}")
        return None
    date8, track, race_name = key
    if _DEBUG:
        print(f"[DEBUG] parsed key: date8={date8} track={track!r} race_name={race_name!r}")

    session = requests.Session()
    try:
        kaisai_id = _find_kaisai_id(session, date8, track)
        if not kaisai_id:
            return None
        if _DEBUG: print(f"[DEBUG] kaisai_id={kaisai_id}")
        day_url = (f"https://race.netkeiba.com/top/payback_list.html"
                   f"?kaisai_id={kaisai_id}&kaisai_date={date8}")
        html = _http_get(session, day_url, timeout=timeout)
        if _DEBUG and data_dir:
            _debug_dump_day_html(html, date8, track, data_dir)
        soup = BeautifulSoup(html, "html.parser")
        container, title = _find_race_section(soup, race_name)
        if not container:
            return None
        if _DEBUG: print(f"[DEBUG] matched race section: {title!r}")
        return _parse_race_section(container)
    except Exception as e:
        print(f"[WARN] レース結果取得失敗: {e}")
        return None


def _cache_path(data_dir, label):
    d = os.path.join(data_dir, RESULT_CACHE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", label)
    return os.path.join(d, safe + "_result.json")


def load_cached_result(data_dir, label):
    path = _cache_path(data_dir, label)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_cached_result(data_dir, label, result):
    path = _cache_path(data_dir, label)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 結果キャッシュ保存失敗: {e}")


class _ResultLoader:
    """
    レース結果のオンライン取得をバックグラウンドスレッドで行う。
    (通信は数秒かかるため、Pyxelの描画ループを止めないためのラッパー)
    """
    def __init__(self):
        self.state  = "idle"     # idle / loading / done / error / none
        self.result = None
        self._thread = None

    def start(self, data_dir, label):
        cached = load_cached_result(data_dir, label)
        if cached is not None:
            self.result = cached
            self.state  = "done"
            return

        if IS_WEB or requests is None:
            self.state = "none"   # このモードでは取得不可
            return

        self.state  = "loading"
        self.result = None

        def _job():
            r = fetch_race_result_online(label, data_dir=data_dir)
            if r:
                save_cached_result(data_dir, label, r)
                self.result = r
                self.state  = "done"
            else:
                self.state = "none"   # 未確定 or 見つからない

        self._thread = threading.Thread(target=_job, daemon=True)
        self._thread.start()


# ============================================================
# App
# ============================================================
class KeibaApp:

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

        # ファイルリスト
        self.file_list   : list = []
        self.file_cursor : int  = 0
        self.file_scroll : int  = 0

        # レース
        self.current_race  : dict | None = None
        self.horses_sorted : list = []
        self.list_cursor   : int  = 0
        self.list_scroll   : int  = 0
        self.sort_idx      : int  = 0
        self.sort_asc      : bool = True

        # 詳細
        self.detail_horse  : dict | None = None
        self.detail_scroll : int  = 0

        # 非同期ローダー
        self._index_loader = _AsyncLoader()  # index.json 用
        self._race_loader  = _AsyncLoader()  # race.json 用
        self._pending_file : dict | None = None  # ロード待ちファイルエントリ

        # ★追加: レース結果 (netkeiba) ローダー
        self._result_loader = _ResultLoader()

        # 状態
        self.scene   = SCENE_LOADING
        self.err_msg = ""
        self._loading_msg = "データ読み込み中..."
        self._dot_frame   = 0  # ローディングアニメ

        self.debug_state = "START"

        pyxel.init(W, H, title="競馬予想ビューア", fps=FPS)
        pyxel.mouse(True)

        # index.json の非同期フェッチを開始
        self._start_index_fetch()

        pyxel.run(self.update, self.draw)

    # ----------------------------------------------------------
    # index.json フェッチ開始
    # ----------------------------------------------------------
    def _start_index_fetch(self):
        if IS_WEB:
            url = f"{BASE_URL}/DATA/index.json"
        else:
            url = os.path.join(self.data_dir, "index.json")
            # ローカルに index.json がない場合はディレクトリスキャン
            if not os.path.isfile(url):
                self._scan_local_dir()
                return

        self._loading_msg = "index.json 読み込み中(local)..."
        self._index_loader.fetch(url)

    # ----------------------------------------------------------
    # ローカル版: ディレクトリスキャン (フォールバック)
    # ----------------------------------------------------------
    def _scan_local_dir(self):
        files = []
        if os.path.isdir(self.data_dir):
            for root, _, fs in os.walk(self.data_dir):
                for f in fs:
                    if (f.lower().endswith(".json")
                            and not f.startswith("~$")
                            and f.lower() != "index.json"):
                        full = os.path.join(root, f)
                        files.append({
                            "path" : full,
                            "label": os.path.splitext(f)[0],
                            "dir"  : os.path.relpath(root, self.data_dir),
                        })
            files.sort(key=lambda x: os.path.getmtime(x["path"]), reverse=True)

        if files:
            self.file_list = files
        else:
            self.err_msg   = "jsonが見つかりません (サンプル表示)"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]

        self.scene = SCENE_FILE

    # ----------------------------------------------------------
    # index.json ロード完了後の処理
    # ----------------------------------------------------------
    def _on_index_loaded(self, names: list):
        """names: ["race1.json", "race2.json", ...]"""
        if IS_WEB:
            self.file_list = [
                {
                    "path" : f"{BASE_URL}/DATA/{os.path.basename(n)}",
                    "label": os.path.splitext(os.path.basename(n))[0],
                    "dir"  : "DATA",
                }
                for n in names
            ]
        else:
            self.file_list = [
                {
                    "path" : os.path.join(self.data_dir, os.path.basename(n)),
                    "label": os.path.splitext(os.path.basename(n))[0],
                    "dir"  : ".",
                }
                for n in names
            ]

        if not self.file_list:
            self.err_msg   = "jsonが見つかりません (サンプル表示)"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]

        self.scene = SCENE_FILE

    # ----------------------------------------------------------
    # ソート
    # ----------------------------------------------------------
    def _apply_sort(self):
        key = SORT_KEYS[self.sort_idx]
        hs  = list(self.current_race["horses"])
        if   key == "odds":  hs.sort(key=lambda h:(h["odds"] is None, h["odds"] or 9999), reverse=not self.sort_asc)
        elif key == "index": hs.sort(key=lambda h: h["index"], reverse=not self.sort_asc)
        else:                hs.sort(key=lambda h: h["no"],    reverse=not self.sort_asc)
        self.horses_sorted = hs

    def _vis_rows(self):  return (H - 42) // ROW_H
    def _vis_items(self): return (H - 56) // ITEM_H

    # ==========================================================
    # UPDATE
    # ==========================================================
    def update(self):
            mx, my = pyxel.mouse_x, pyxel.mouse_y
            wh     = pyxel.mouse_wheel

            if pyxel.btnp(pyxel.KEY_Q):
                pyxel.quit()

            # index.json 待ち
            if self.scene == SCENE_LOADING:
                self._upd_loading()
                return

            # race.json 読み込み待ち
            if self._race_loader.is_loading() or self._pending_file is not None:
                self._poll_race_loader()
                return

            if self.scene == SCENE_FILE:
                self._upd_file(mx, my, wh)
            elif self.scene == SCENE_LIST:
                self._upd_list(mx, my, wh)
            elif self.scene == SCENE_DETAIL:
                self._upd_detail(mx, my, wh)

    # ---- index.json ポーリング ------------------------------
    def _upd_loading(self):
        self._dot_frame = (self._dot_frame + 1) % (FPS * 3)

        if self._index_loader.is_done():
            try:
                names = self._index_loader.result
                if isinstance(names, dict):
                    # {"files": [...]} 形式にも対応
                    names = names.get("files", list(names.values())[0] if names else [])
                if not isinstance(names, list):
                    names = []
                self._on_index_loaded(names)
            except Exception as e:
                self.err_msg = f"index解析エラー: {e}"
                self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
                self.scene = SCENE_FILE

        elif self._index_loader.is_error():
            self.err_msg = f"index取得失敗: {self._index_loader.error}"
            self.file_list = [{"path":"__DUMMY__","label":"サンプルデータ","dir":"."}]
            self.scene = SCENE_FILE

    # ---- race.json ポーリング -------------------------------
    def _poll_race_loader(self):
            self._dot_frame = (self._dot_frame + 1) % (FPS * 3)

            if self._race_loader.is_done():
                fi = self._pending_file
                if fi is None:
                    return
                try:
                    races = parse_races_from_json(self._race_loader.result, fi["label"])
                    if not races:
                        self.err_msg = f"レースデータなし: {fi['label']}"
                        self._pending_file = None
                        return
                    self.current_race = races[0]
                    self.current_race["race_name"] = fi["label"]
                    self.list_cursor = 0
                    self.list_scroll = 0
                    self.sort_idx    = 0
                    self.sort_asc    = True
                    self._apply_sort()
                    self.scene = SCENE_LIST
                    self._result_loader.start(self.data_dir, fi["label"])  # ★結果取得開始
                except Exception as e:
                    self.err_msg = f"解析エラー: {e}"
                self._pending_file = None

            elif self._race_loader.is_error():
                self.err_msg = f"読込失敗: {self._race_loader.error}"
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
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) and mx < CONTENT_W:
            TOP = 46 + TOP_MARGIN
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
        self.err_msg = fi["path"]
        if fi["path"] == "__DUMMY__":
            self.current_race = DUMMY_RACES[0]
            self.current_race["race_name"] = "サンプルデータ"
            self.list_cursor = 0; self.list_scroll = 0
            self.sort_idx = 0; self.sort_asc = True
            self._apply_sort()
            self.scene = SCENE_LIST
            self._result_loader = _ResultLoader()  # サンプルは結果なし
            return

        # 非同期フェッチ開始
        self._pending_file = fi
        self._loading_msg  = f"読込中: {fi['label']}..."
        self._dot_frame    = 0
        self._race_loader.fetch(fi["path"])
        # ロード完了は _poll_race_loader() が update() 内で検知

    def _open_detail(self, idx):
        self.detail_horse  = self.horses_sorted[idx]
        self.detail_scroll = 0
        self.scene         = SCENE_DETAIL

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
            if 2 <= mx <= 80 and 2 <= my <= 16 + TOP_MARGIN: self.scene = SCENE_FILE; return
            # 右上ソートボタン
            slbl = SORT_LABELS[self.sort_idx]

            bx = CONTENT_W - text_px(slbl) - 40
            bw = text_px(slbl) + 40

            if bx <= mx <= bx + bw and (3 + TOP_MARGIN)  <= my <= (17 + TOP_MARGIN):
                self.sort_idx = (self.sort_idx + 1) % len(SORT_KEYS)
                self.sort_asc = (self.sort_idx == 0)
                self._apply_sort()
                return            
            HDRH = 30
            if my >= HDRH and mx < CONTENT_W:
                row_i = (my - HDRH) // ROW_H + self.list_scroll
                if 0 <= row_i < n:
                    if row_i == self.list_cursor: self._open_detail(row_i)
                    else: self.list_cursor = row_i

    # ---- 詳細 -----------------------------------------------
    def _upd_detail(self, mx, my, wh):
        if pyxel.btnp(pyxel.KEY_ESCAPE): self.scene = SCENE_LIST; return
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            if 2 <= mx <= 80 and 2 <= my <= 16 + TOP_MARGIN: self.scene = SCENE_LIST; return
        if wh: self.detail_scroll = clamp(self.detail_scroll - wh, 0, 40)
        if pyxel.btnp(pyxel.KEY_UP):   self.detail_scroll = max(0,  self.detail_scroll - 1)
        if pyxel.btnp(pyxel.KEY_DOWN): self.detail_scroll = min(40, self.detail_scroll + 1)

    # ==========================================================
    # DRAW
    # ==========================================================
    def draw(self):
        pyxel.cls(COL_BG2)

        # race.json ロード中オーバーレイ
        if self._race_loader.is_loading():
            self._drw_overlay_loading(self._loading_msg)
            return

        if   self.scene == SCENE_LOADING: self._drw_full_loading()
        elif self.scene == SCENE_FILE:    self._drw_file()
        elif self.scene == SCENE_LIST:    self._drw_list()
        elif self.scene == SCENE_DETAIL:  self._drw_detail()

    # ---- ローディング画面 ------------------------------------
    def _drw_full_loading(self):
        dots = "." * ((self._dot_frame // 10) % 4)
        msg  = self._loading_msg + dots
        draw_text(W // 2 - text_px(msg) // 2, H // 2 - 6, msg, COL_HEADER, FONT_M)

    def _drw_overlay_loading(self, msg: str):
        # 既存画面の上にオーバーレイ
        if   self.scene == SCENE_FILE:    self._drw_file()
        elif self.scene == SCENE_LIST:    self._drw_list()
        dots = "." * ((self._dot_frame // 10) % 4)
        full = msg + dots
        bw   = text_px(full) + 20
        bh   = 24
        bx   = (W - bw) // 2
        by   = (H - bh) // 2
        pyxel.rect(bx, by, bw, bh, COL_BG)
        draw_rectb(bx, by, bw, bh, COL_HEADER)
        draw_text(bx + 10, by + 7, full, COL_TITLE, FONT_S)

    # ------ 共通パーツ ----------------------------------------
    def _footer(self, msg):
        pyxel.rect(0, H - 12, CONTENT_W, 12, COL_BG)
        draw_rectb(0, H - 12, CONTENT_W, 12, COL_BORDER)
        draw_text(4, H - 10, msg, COL_MUTED, FONT_S)

    def _scrollbar(self, top_y, total, vis, scroll):
        if total <= vis: return
        area = H - top_y - 12
        bh   = max(6, area * vis // total)
        by   = top_y + area * scroll // total
        pyxel.rect(CONTENT_W - 4, top_y, 3, area, COL_BG)
        pyxel.rect(CONTENT_W - 4, by,    3, bh,   COL_BORDER)

    # ------ ファイル選択 --------------------------------------
    def _drw_file(self):
        pyxel.rect(0,TOP_MARGIN, CONTENT_W, 44, COL_BG)
        draw_rectb(0,TOP_MARGIN, CONTENT_W, 44, COL_BORDER)
        draw_text(6,  3+TOP_MARGIN, "★ KEIBA ANALYZER ★",                     COL_TITLE,  FONT_M)
        draw_text(6, 20+TOP_MARGIN, "DATAフォルダ: " + truncate(self.data_dir, CONTENT_W-80), COL_HEADER, FONT_S)
        cnt  = sum(1 for f in self.file_list if f["path"] != "__DUMMY__")
        info = self.err_msg if self.err_msg else f"{cnt} ファイル"
        draw_text(6, 32+TOP_MARGIN, info, COL_ODDS_LO if self.err_msg else COL_MUTED, FONT_S)

        vis = self._vis_items()
        TOP = 46 + TOP_MARGIN
        for rel in range(vis):
            idx = self.file_scroll + rel
            if idx >= len(self.file_list): break
            fi  = self.file_list[idx]
            ry  = TOP + rel * ITEM_H
            sel = (idx == self.file_cursor)
            bg  = COL_BG if sel else (COL_BG2 if rel % 2 == 0 else COL_BG3)
            pyxel.rect(0, ry, CONTENT_W - 5, ITEM_H, bg)
            if sel: draw_rectb(0, ry, CONTENT_W - 5, ITEM_H, COL_HEADER)
            sub = fi["dir"] if fi["dir"] not in (".", "") else ""
            sw  = text_px(sub) + 4 if sub else 0
            draw_text(4, ry + 3, truncate(fi["label"], CONTENT_W - 12 - sw),
                      COL_TITLE if sel else COL_TEXT, FONT_S)
            if sub:
                draw_text(CONTENT_W - 5 - sw, ry + 3, sub, COL_MUTED, FONT_S)

        self._scrollbar(TOP, len(self.file_list), vis, self.file_scroll)
        self._footer("↑↓:選択  Enter/クリック2回:決定  Q:終了")

    # ------ 色ヘルパー ----------------------------------------
    def rating_color(self, v):
        try:
            v = float(v)
        except: return COL_TEXT
        if v >= 100: return pyxel.COLOR_RED
        if v >= 90:  return pyxel.COLOR_YELLOW
        return COL_TEXT

    def last3f_color(self, v):
        try:
            v = float(v)
        except: return COL_TEXT
        if v < 33.5: return pyxel.COLOR_RED
        if v < 34.0: return pyxel.COLOR_YELLOW
        return COL_SC_HI

    def train1f_color(self, v):
        try:
            v = float(v)
        except: return COL_TEXT
        if v < 11.0:  return pyxel.COLOR_RED
        if v <= 11.5: return pyxel.COLOR_YELLOW
        return COL_SC_HI

    # ------ 出走表一覧 ----------------------------------------
    def _drw_list(self):
        race = self.current_race
        pyxel.rect(0, TOP_MARGIN, CONTENT_W, 18, COL_BG)
        draw_rectb(0, TOP_MARGIN, CONTENT_W, 18, COL_BORDER)
        draw_btn(2, 2+TOP_MARGIN, text_px("←レース選択") + 70, "←レース選択")
        ox = text_px("←レース選択") + 70
        draw_text(ox + 20, 3+TOP_MARGIN, truncate(race["race_name"], CONTENT_W - ox - 80), COL_TITLE, FONT_M)
        slbl = SORT_LABELS[self.sort_idx]
        draw_btn(CONTENT_W - text_px(slbl) - 40, 3+TOP_MARGIN, text_px(slbl) + 40, slbl, active=True)

        cx = self._cx()
        yh = 19 + TOP_MARGIN
        pyxel.rect(0, yh, CONTENT_W, ROW_H + 1, COL_BG)
        draw_rectb(0, yh, CONTENT_W, ROW_H + 1, COL_BORDER)
        for k, lbl in [("no","番"),("name","馬名"),("odds","オッズ"),
                       ("sex","性齢"),("style","脚"),("jkey","騎手"),
                       ("idx","指数"),("prev1","前走"),("prev2","前々"),
                       ("prev3","3走"),("prev_3F","前3F"),("train_1F","調1F"),
                       ("mark","印")]:
            draw_text(cx[k], yh + 2, lbl, COL_HEADER, FONT_S)

        vis = self._vis_rows()
        for rel in range(vis):
            ai = self.list_scroll + rel
            if ai >= len(self.horses_sorted): break
            h  = self.horses_sorted[ai]
            ry = 31 + rel * ROW_H
            sel = (ai == self.list_cursor)
            bg  = COL_BG if sel else (COL_BG2 if rel % 2 == 0 else COL_BG3)
            pyxel.rect(0, ry, CONTENT_W - 5, ROW_H, bg)
            if sel: draw_rectb(0, ry, CONTENT_W - 5, ROW_H, COL_HEADER)
            ty = ry + 1

            gcol = GATE_COLS[min((h["gate"] - 1) * 2, len(GATE_COLS) - 1)]
            pyxel.rect(cx["gate"], ty + 2, 6, 6, gcol)

            draw_text(cx["no"], ty, f"{h['no']:2d}", COL_TEXT, FONT_S)

            nw = cx["odds"] - cx["name"] - 2
            draw_text(cx["name"], ty, truncate(h["name"], nw),
                      COL_TITLE if sel else COL_TEXT, FONT_S)

            odds = h["odds"]
            if odds:
                odds_text = f"{odds:.0f}" if odds >= 100 else f"{odds:.1f}"
            else:
                odds_text = "---"
            draw_text(cx["odds"], ty, odds_text, odds_col(odds), FONT_S)

            draw_text(cx["sex"],   ty, truncate(h["sex"], 24), COL_TEXT, FONT_S)
            draw_text(cx["style"], ty, h["style"], STYLE_COL.get(h["style"], COL_TEXT), FONT_S)

            jw2 = cx["idx"] - cx["jkey"] - 2
            draw_text(cx["jkey"], ty, truncate(h["jockey"], jw2), COL_MUTED, FONT_S)

            bw = clamp(h["index"] * 30 // 100, 1, 30)
            pyxel.rect(cx["idx"], ty + 3, bw, 5, score_col(h["index"]))
            draw_text(cx["idx"] + 32, ty, f"{h['index']:3d}", score_col(h["index"]), FONT_S)

            draw_text(cx["prev1"],    ty, str(h.get("prev1","")),    self.rating_color(h.get("prev1",0)),    FONT_S)
            draw_text(cx["prev2"],    ty, str(h.get("prev2","")),    self.rating_color(h.get("prev2",0)),    FONT_S)
            draw_text(cx["prev3"],    ty, str(h.get("prev3","")),    self.rating_color(h.get("prev3",0)),    FONT_S)
            draw_text(cx["prev_3F"],  ty, str(h.get("prev_3F","")), self.last3f_color(h.get("prev_3F","")), FONT_S)
            draw_text(cx["train_1F"], ty, str(h.get("train_1F","")),self.train1f_color(h.get("train_1F","")),FONT_S)
            draw_text(cx["mark"],     ty, h.get("mark",""),          mark_col(h.get("mark","")),             FONT_S)

        self._scrollbar(31, len(self.horses_sorted), vis, self.list_scroll)
        self._footer("Enter:詳細  Tab:ソート切替  ESC:戻る  Q:終了")
        self._drw_result_panel()

    # ------ ★追加: 右側「レース結果」パネル -------------------
    def _drw_result_panel(self):
        px = CONTENT_W
        pw = PANEL_W
        pyxel.rect(px, TOP_MARGIN, pw, H - TOP_MARGIN, COL_BG2)
        draw_rectb(px, TOP_MARGIN, pw, H - TOP_MARGIN, COL_BORDER)

        y = TOP_MARGIN + 4
        draw_text(px + 6, y, "レース結果", COL_TITLE, FONT_M)
        y += 16
        pyxel.line(px + 4, y, px + pw - 4, y, COL_BORDER)
        y += 6

        rl = self._result_loader
        state = rl.state

        if state in ("loading",):
            dots = "." * ((pyxel.frame_count // 10) % 4)
            draw_text(px + 6, y, "取得中" + dots, COL_HEADER, FONT_S)
            return
        if state == "none":
            draw_text(px + 6, y, "未確定 / 取得不可", COL_MUTED, FONT_S)
            draw_text(px + 6, y + 14, "(レース前 or", COL_MUTED, FONT_S)
            draw_text(px + 6, y + 26, " 対応サイト未検出)", COL_MUTED, FONT_S)
            return
        if state != "done" or not rl.result:
            draw_text(px + 6, y, "-", COL_MUTED, FONT_S)
            return

        res = rl.result
        top3 = res.get("top3", [])
        RANK_LABEL = {"1": "1着", "2": "2着", "3": "3着"}
        for entry in top3[:3]:
            rank = str(entry.get("rank", "")).strip()
            name = str(entry.get("name", "")).strip()
            lbl  = RANK_LABEL.get(rank, rank + "着" if rank else "?")
            col  = COL_TITLE if rank == "1" else (COL_HEADER if rank == "2" else COL_TEXT)
            draw_text(px + 6, y, lbl, col, FONT_S)
            for line in wrap_text(name, pw - 16):
                y += 12
                draw_text(px + 12, y, line, col, FONT_S)
            y += 14

        y += 4
        pyxel.line(px + 4, y, px + pw - 4, y, COL_BORDER)
        y += 8

        draw_text(px + 6, y, "馬連", COL_HEADER, FONT_S)
        y += 12
        for line in wrap_text(res.get("umaren", "") or "---", pw - 16):
            draw_text(px + 10, y, line, COL_SC_HI, FONT_S)
            y += 12

        y += 6
        draw_text(px + 6, y, "3連複", COL_HEADER, FONT_S)
        y += 12
        for line in wrap_text(res.get("sanrenpuku", "") or "---", pw - 16):
            draw_text(px + 10, y, line, COL_SC_HI, FONT_S)
            y += 12

    def _cx(self):
        return dict(gate=2, no=10, name=22, odds=130, sex=170,
                    style=200, jkey=220, idx=252, prev1=310, prev2=340, prev3=370,
                    prev_3F=400, train_1F=435, mark=470)

    # ------ 詳細 ---------------------------------------------
    def _drw_detail(self):
        h  = self.detail_horse
        sc = self.detail_scroll
        r  = h.get("raw", {})

        pyxel.rect(0, TOP_MARGIN, CONTENT_W, 18, COL_BG)
        draw_rectb(0, TOP_MARGIN, CONTENT_W, 18, COL_BORDER)
        draw_btn(2, 2+TOP_MARGIN, text_px("◀ 一覧") + 10, "◀ 一覧")
        gcol = GATE_COLS[min((h["gate"]-1)*2, len(GATE_COLS)-1)]
        ox   = text_px("◀ 一覧") + 16
        pyxel.rect(ox, 5+TOP_MARGIN, 8, 8, gcol)
        draw_text(ox + 12, 3+TOP_MARGIN, truncate(f"{h['no']}番  {h['name']}", CONTENT_W - ox - 16), COL_TITLE, FONT_M)

        def oy(dy): return 22 + dy - sc * (FONT_S_SIZE + 3)

        def line(dy, label, val, vc=COL_TEXT):
            y = oy(dy) + TOP_MARGIN
            if not (18 < y < H - 13): return
            draw_text(4, y, label, COL_HEADER, FONT_S)
            VALUE_X = 64
            draw_text(VALUE_X, y, str(val), vc, FONT_S)

        def section(dy, title_s):
            y = oy(dy) + TOP_MARGIN
            if not (18 < y < H - 13): return
            pyxel.rect(2, y, CONTENT_W - 8, FONT_S_SIZE + 4, COL_BG)
            draw_rectb(2, y, CONTENT_W - 8, FONT_S_SIZE + 4, COL_BORDER)
            draw_text(6, y + 2, title_s, COL_HEADER, FONT_S)

        LH = FONT_S_SIZE + 5
        SH = FONT_S_SIZE + 8

        odds_str = f"{h['odds']:.1f}倍" if h['odds'] else "---"
        section(0,    "基本情報")
        line(SH, "", f'【{h["mark"]}】 {odds_str}  {h["sex"]}  {h["jw"]}kg  {h["jockey"]}  脚質:{h["style"]}')

        base2 = SH + LH
        section(base2,   "総合指数")
        line(base2+SH,   "指数    ", str(h["index"]), score_col(h["index"]))
        by = oy(base2 + SH + LH + 2) + TOP_MARGIN
        if 18 < by < H - 13:
            bw = clamp(h["index"] * (CONTENT_W - 24) // 100, 1, CONTENT_W - 24)
            pyxel.rect(4, by, CONTENT_W - 8, 7, COL_BG)
            pyxel.rect(4, by, bw,    7, score_col(h["index"]))
            draw_rectb(4, by, CONTENT_W - 8, 7, COL_BORDER)

        base3 = base2 + SH + LH * 2
        section(base3, "調教")
        line(base3+SH,   "調教場所", r.get("調教場所・馬場", ""))
        line(base3+SH*2, "調教時計", r.get("時計", ""))

        base4 = base3 + SH + LH * 2
        section(base4, "近走成績")

        for i, key in enumerate(["前走","前々走","3走前","4走前"]):
            txt = str(r.get(key, ""))
            pos = txt.find("kg ")
            lines = [txt[:pos+3], txt[pos+3:]] if pos >= 0 else [txt]
            y = base4 + SH + i * (LH * 2) 
            line(y, key, lines[0])
            if len(lines) > 1: line(y + LH, "", lines[1], COL_TITLE)

        self._footer("↑↓/ホイール:スクロール  ESC:戻る  Q:終了")


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    KeibaApp(data_dir)
