import pyxel
import csv
import random
import os
import re

# --- スクリプトと同じフォルダを基準にする ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# セーブデータ（ハイスコア・間違えた単語など）の保存先。
# ローカル実行では BASE_DIR を仮の初期値にしておき、pyxel.init() の直後に
# pyxel.user_data_dir() の結果へ差し替える（Web版でもここに保存されるようにするため）。
SAVE_DIR = BASE_DIR
VENDOR_NAME = "kazu_home_page"
APP_NAME = "EnglishWord1900"

WORDS_CSV = os.path.join(BASE_DIR, "words_lv01.csv")
FONT_12 = os.path.join(BASE_DIR, "umplus_j12r.bdf")
FONT_10 = os.path.join(BASE_DIR, "umplus_j10r.bdf")

PLAYERS = ["ゆそ", "しん", "キャス", "ファザ","マザ"]

# --- 選択肢ボタンに使う、ぱきっと明るいカラーパレット（順番に回して使う） ---
CHOICE_COLORS = [
    pyxel.COLOR_PINK,
    pyxel.COLOR_LIGHT_BLUE,
    pyxel.COLOR_LIME,
    pyxel.COLOR_ORANGE,
    pyxel.COLOR_CYAN,
    pyxel.COLOR_PEACH,
]

STATE_PLAYER_SELECT = "player_select"
STATE_START = "start"
STATE_PLAY = "play"
STATE_RESULT = "result"

MODE_NORMAL = "normal"
MODE_REVIEW = "review"
MODE_TIMEATTACK = "timeattack"

REVIEW_QUESTIONS = 10
REVIEW_MASTERY_COUNT = 5  # 復習で連続して正解できたら卒業させる回数

FPS = 30
TIME_ATTACK_SECONDS = 5 * 60


class Word:
    """1つの単語データ。
    words.csv は行によって列数が異なる:
      2列: english, japanese
      3列: english, japanese, note        （使い方の補足メモ）
      4列: english, japanese, example_en, example_ja  （例文とその和訳）
    """
    __slots__ = ("english", "japanese", "example_en", "example_ja", "note")

    def __init__(self, english, japanese, example_en=None, example_ja=None, note=None):
        self.english = english
        self.japanese = japanese
        self.example_en = example_en
        self.example_ja = example_ja
        self.note = note


# --- 単語読み込み ---
def load_words(filename=WORDS_CSV):
    words = []
    if not os.path.exists(filename):
        return words
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            row = [c.strip() for c in row]
            if len(row) == 2:
                english, japanese = row
                if english and japanese:
                    words.append(Word(english, japanese))
            elif len(row) == 3:
                english, japanese, note = row
                if english and japanese:
                    words.append(Word(english, japanese, note=note))
            elif len(row) >= 4:
                english, japanese, example_en, example_ja = row[:4]
                if english and japanese:
                    words.append(Word(english, japanese, example_en=example_en, example_ja=example_ja))
    return words


# --- プレイヤーごとの「間違えた単語」ファイルパス ---
def missed_csv_path_for_player(player):
    safe = player if player else "unknown"
    return os.path.join(SAVE_DIR, f"missed_words_{safe}.csv")


# --- プレイヤーごとの「復習の連続正解数」ファイルパス ---
def review_stats_path_for_player(player):
    safe = player if player else "unknown"
    return os.path.join(SAVE_DIR, f"review_stats_{safe}.csv")


def load_review_stats(filename):
    stats = {}
    if not os.path.exists(filename):
        return stats
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 3:
                eng, jp, cnt = row[0].strip(), row[1].strip(), row[2].strip()
                try:
                    stats[(eng, jp)] = int(cnt)
                except ValueError:
                    continue
    return stats


def save_review_stats(filename, stats):
    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for (eng, jp), cnt in stats.items():
            writer.writerow([eng, jp, cnt])


# --- 復習をマスターした単語を「間違えた単語」ファイルから完全に削除する ---
def remove_missed_word(filename, english, japanese):
    if not os.path.exists(filename):
        return
    rows = []
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2 and row[0].strip() == english and row[1].strip() == japanese:
                continue  # この単語は卒業したので取り除く
            rows.append(row)
    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


# --- 間違えた単語を読み込む（重複はまとめる） ---
def load_missed_words_unique(filename):
    seen = {}
    for w in load_words(filename):
        seen[(w.english, w.japanese)] = w
    return list(seen.values())


# --- 間違えた単語を保存 ---
def save_missed_word(english, japanese, filename):
    with open(filename, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([english, japanese])


# --- タイムアタック用に、見つかる単語帳(words_lv01〜05.csv)を全部まとめて読み込む ---
def load_wordbank_all():
    combined = []
    for i in range(1, 6):
        fn = os.path.join(BASE_DIR, f"words_lv{i:02d}.csv")
        combined.extend(load_words(fn))
    if not combined:
        combined = load_words(WORDS_CSV)
    return combined


# --- ランキング（タイムアタックのスコア）読み込み・保存 ---
def ranking_csv_path():
    return os.path.join(SAVE_DIR, "ranking.csv")


def load_ranking(filename=None):
    filename = filename or ranking_csv_path()
    rows = []
    if not os.path.exists(filename):
        return rows
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                player = row[0].strip()
                try:
                    score = int(row[1].strip())
                except ValueError:
                    continue
                rows.append((player, score))
    return rows


def save_ranking_entry(player, score, filename=None):
    filename = filename or ranking_csv_path()
    with open(filename, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([player, score])


# --- ランキング表示用：プレイヤーごとの自己ベストだけを1件ずつ取り出す ---
def load_ranking_best_per_player(filename=None):
    best = {}
    for player, score in load_ranking(filename):
        if player not in best or score > best[player]:
            best[player] = score
    return sorted(best.items(), key=lambda kv: -kv[1])


# --- 例文中の対象単語を隠す ---
def mask_target_word(sentence, english):
    if not sentence:
        return None
    pattern = re.compile(r"\b" + re.escape(english) + r"\w*", re.IGNORECASE)

    def repl(m):
        return "_" * len(m.group(0))

    masked, n = pattern.subn(repl, sentence)
    if n == 0:
        # 語形が一致しない場合（不規則変化など）はそのまま表示する
        # （日本語の意味は表示していないため、答えが割れることはない）
        return sentence
    return masked


# --- 文を指定幅で折り返す（1行に収まらない場合は "..." で省略） ---
def wrap_text(font, text, max_width, max_lines=1):
    words = text.split(" ")
    lines = []
    current = ""
    for w in words:
        candidate = w if not current else current + " " + w
        width = font.text_width(candidate) if font else len(candidate) * 4
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = w
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines:
        last = lines[-1]
        while (font.text_width(last + "...") if font else (len(last) + 3) * 4) > max_width and len(last) > 0:
            last = last[:-1]
        joined_len = sum(len(l) for l in lines)
        if joined_len < len(text.replace(" ", "")):
            lines[-1] = last + "..."
    return lines


class WordGame:
    SCREEN_W = 240
    SCREEN_H = 320

    CHOICE_X = 20
    CHOICE_W = 200
    CHOICE_GAP = 8
    CHOICES_END_Y = 272  # この位置より下にはボタンを描かない（メッセージ欄の手前まで）

    STREAK_TO_LEVEL_UP = 5
    MAX_CHOICES = 5

    HEADER_H = 64  # 上部のカラフルなヘッダー帯の高さ（拡大文字がはみ出さない余裕を確保）

    def __init__(self):
        self.normal_words = load_words()
        self.normal_wordlist_name = os.path.basename(WORDS_CSV)

        self.words = self.normal_words
        self.current_wordlist = self.normal_wordlist_name

        pyxel.init(self.SCREEN_W, self.SCREEN_H, title="英単語選択ゲーム（スマホ＋PC対応）", fps=FPS)
        pyxel.mouse(True)  # マウスカーソルを表示する

        # --- セーブデータの保存先を確定する ---
        # pyxel.user_data_dir() は Web 版でもブラウザ側に永続化される専用の保存先。
        # スクリプトと同じ場所（BASE_DIR）に書き込むと、ローカルでは動いても
        # Web版では次回アクセス時に消えてしまうため、必ずこちらを使う。
        global SAVE_DIR
        try:
            SAVE_DIR = pyxel.user_data_dir(VENDOR_NAME, APP_NAME)
        except Exception as e:
            print(f"user_data_dir の取得に失敗したため、スクリプトと同じ場所に保存します: {e}")
            SAVE_DIR = BASE_DIR

        # --- 日本語フォント読み込み（BDFフォント） ---
        self.font_l = None  # 見出し・選択肢用（12px）
        self.font_s = None  # スコア・メッセージ・例文用（10px）
        try:
            self.font_l = pyxel.Font(FONT_12)
            self.font_s = pyxel.Font(FONT_10)
        except Exception as e:
            print(f"フォント読み込みに失敗しました: {e}")

        self.player = None
        self.missed_csv_path = None
        self.review_stats_path = None
        self.review_stats = {}

        self.score_correct = 0
        self.score_total = 0
        self.level = 1
        self.streak = 0

        self.mode = MODE_NORMAL
        self.review_progress = 0
        self.saved_words = None
        self.saved_wordlist_name = None

        # --- タイムアタック関連 ---
        self.ta_correct = 0
        self.ta_wrong = 0
        self.ta_score = 0
        self.ta_combo = 0
        self.ta_best_combo = 0
        self.ta_start_frame = 0
        self.ta_duration_frames = TIME_ATTACK_SECONDS * FPS
        self.ta_final_score = 0
        self.ta_is_new_best = False
        self.ranking_rows = []

        self.word_changed = False
        self.word_change_timer = 0

        self.notice = ""  # 画面上部などに一時的に出す小さいお知らせ
        self.notice_timer = 0

        # --- 背景を彩る、控えめな水玉模様（毎フレーム再計算しない固定パターン） ---
        rnd = random.Random(12345)
        self.bg_dots = [
            (rnd.randint(0, self.SCREEN_W), rnd.randint(self.HEADER_H + 10, self.SCREEN_H),
             rnd.choice([pyxel.COLOR_PINK, pyxel.COLOR_PEACH, pyxel.COLOR_LIGHT_BLUE]),
             rnd.randint(1, 2))
            for _ in range(18)
        ]

        self.state = STATE_PLAYER_SELECT
        self.reset_question()
        pyxel.run(self.update, self.draw)

    # ------------------------------------------------------------------
    # 大きく・くっきり見せるための拡大文字描画
    # 通常の pyxel.text() は等倍でしか描けないため、一度オフスクリーンの
    # Image に描いてから scale 倍で画面に貼り付けることで文字を拡大する。
    # ------------------------------------------------------------------
    def draw_big_text(self, x, y, s, col, font, scale=2, outline_col=None, font_h=16, max_width=None):
        if not s:
            return 0
        w = font.text_width(s)
        if max_width is not None:
            while scale > 1 and (w*1.5) * scale > max_width:
                scale -= 1

        if scale <= 1:
            # 等倍のときは pyxel.text() をそのまま使う（blt を経由しない）
            if outline_col is not None:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    pyxel.text(x + dx, y + dy, s, outline_col, font)
            pyxel.text(x, y, s, col, font)
            return w

        # --- 拡大表示 ---
        # 環境によっては pyxel.blt() の scale 引数の挙動が不安定なことがあるため、
        # ここでは使わず、1ピクセルずつ読み取って rect() で拡大描画する（確実な方法）。
        buf_w = max(1, w + 2)
        img = pyxel.Image(buf_w, font_h)
        img.cls(0)  # 0(黒)を透過色として使う（文字色に黒は使わない前提）
        if outline_col is not None:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                img.text(1 + dx, 2 + dy, s, outline_col, font)
        img.text(1, 2, s, col, font)

        for sy in range(font_h):
            for sx in range(buf_w):
                c = img.pget(sx, sy)
                if c == 0:
                    continue  # 透過色はスキップ
                pyxel.rect(x + sx * scale, y + sy * scale, scale, scale, c)
        return w * scale

    def current_num_choices(self):
        # レベルが上がるほど選択肢が増えて難しくなる（最大 MAX_CHOICES 個）
        return min(3 + self.level, self.MAX_CHOICES)

    def reset_question(self):
        if not self.words:
            self.correct_word = Word("-", "（単語がありません）")
            self.choices = ["（単語がありません）"]
            self.example_en_lines = []
            self.example_ja_lines = []
            self.choices_start_y = self.HEADER_H + 58
            self.choice_h = 40
            self.message = ""
            self.message_col = pyxel.COLOR_WHITE
            self.cooldown = 0
            return

        word = random.choice(self.words)
        self.correct_word = word

        num_choices = min(self.current_num_choices(), len(self.words)) if self.mode == MODE_NORMAL else min(4, len(self.words))
        num_choices = max(2, num_choices)
        choices = {word.japanese}
        tries = 0
        while len(choices) < num_choices and tries < 200:
            choices.add(random.choice(self.words).japanese)
            tries += 1

        self.choices = list(choices)
        random.shuffle(self.choices)

        # --- 例文（あれば対象単語を隠して整形。最大2行まで） ---
        self.example_en_lines = []
        if word.example_en:
            masked = mask_target_word(word.example_en, word.english)
            self.example_en_lines = wrap_text(self.font_s, masked, self.CHOICE_W, max_lines=2)

        # --- 例文の日本語訳（復習モード、または通常モードのレベル1のみ表示） ---
        self.example_ja_lines = []
        show_ja = self.mode == MODE_REVIEW or (self.mode == MODE_NORMAL and self.level < 2)
        if word.example_ja and show_ja:
            self.example_ja_lines = wrap_text(self.font_s, word.example_ja, self.CHOICE_W, max_lines=2)

        # --- レイアウトを動的に計算 ---
        content_y = self.HEADER_H + 38
        for _ in self.example_en_lines:
            content_y += 12
        if self.example_en_lines:
            content_y += 2
        for _ in self.example_ja_lines:
            content_y += 12
        if self.example_ja_lines:
            content_y += 4
        self.choices_start_y = max(self.HEADER_H + 58, content_y + 6)

        available_h = self.CHOICES_END_Y - self.choices_start_y
        n = len(self.choices)
        self.choice_h = max(20, (available_h - self.CHOICE_GAP * (n - 1)) // n)

        self.message = ""
        self.message_col = pyxel.COLOR_WHITE
        self.cooldown = 0

    def choice_rect(self, i):
        x = self.CHOICE_X
        y = self.choices_start_y + i * (self.choice_h + self.CHOICE_GAP)
        return x, y, self.CHOICE_W, self.choice_h

    def hovered_choice_index(self):
        mx, my = pyxel.mouse_x, pyxel.mouse_y
        for i in range(len(self.choices)):
            x, y, w, h = self.choice_rect(i)
            if x <= mx <= x + w and y <= my <= y + h:
                return i
        return -1

    # ------------------------------------------------------------------
    # プレイヤー選択画面
    # ------------------------------------------------------------------
    def player_select_rects(self):
        gap = 10
        bw = (self.CHOICE_W - gap) // 2
        bh = 70
        x0 = self.CHOICE_X
        y0 = 110
        rects = []
        for i in range(len(PLAYERS)):
            col = i % 2
            row = i // 2
            x = x0 + col * (bw + gap)
            y = y0 + row * (bh + gap)
            rects.append((x, y, bw, bh))
        return rects

    def update_player_select(self):
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            mx, my = pyxel.mouse_x, pyxel.mouse_y
            for name, (x, y, w, h) in zip(PLAYERS, self.player_select_rects()):
                if x <= mx <= x + w and y <= my <= y + h:
                    self.select_player(name)
                    return

    def select_player(self, name):
        self.player = name
        self.missed_csv_path = missed_csv_path_for_player(name)
        self.review_stats_path = review_stats_path_for_player(name)
        self.state = STATE_START

    def draw_player_select(self):
        pyxel.cls(pyxel.COLOR_PEACH)
        for x, y, col, r in self.bg_dots:
            pyxel.circ(x, y, r, col)

        pyxel.rect(0, 0, self.SCREEN_W, self.HEADER_H, pyxel.COLOR_PINK)
        pyxel.rect(0, self.HEADER_H, self.SCREEN_W, 3, pyxel.COLOR_ORANGE)
        pyxel.clip(0, 0, self.SCREEN_W, self.HEADER_H)
        self.draw_big_text(16, 16, "だれがやる？", pyxel.COLOR_WHITE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_PURPLE, max_width=self.SCREEN_W - 24)
        pyxel.clip()

        button_colors = [pyxel.COLOR_LIME, pyxel.COLOR_LIGHT_BLUE, pyxel.COLOR_ORANGE, pyxel.COLOR_PINK]
        best_scores = dict(load_ranking_best_per_player())
        for name, (x, y, w, h), col in zip(PLAYERS, self.player_select_rects(), button_colors):
            pyxel.rect(x, y, w, h, col)
            pyxel.rectb(x, y, w, h, pyxel.COLOR_WHITE)
            pyxel.clip(x, y, w, h)
            self.draw_big_text(x + 6, y + 6, name, pyxel.COLOR_PURPLE, self.font_l,
                                scale=2, outline_col=pyxel.COLOR_WHITE, max_width=w - 10)
            score = best_scores.get(name)
            score_text = f"Hi-Score:{score}" if score is not None else "記録なし"
            pyxel.text(x + 4, y + h - 12, score_text, pyxel.COLOR_WHITE, self.font_s)
            pyxel.clip()

        pyxel.text(20, 290, "タップして自分の名前を選んでね", pyxel.COLOR_GRAY, self.font_s)

    # ------------------------------------------------------------------
    # スタート画面
    # ------------------------------------------------------------------
    def start_screen_rects(self):
        normal_rect = (20, 100, self.CHOICE_W, 50)
        review_rect = (20, 158, self.CHOICE_W, 50)
        timeattack_rect = (20, 216, self.CHOICE_W, 50)
        return normal_rect, review_rect, timeattack_rect

    def player_switch_button_rect(self):
        return (self.SCREEN_W - 80, 4, 74, 16)

    def back_button_rect(self):
        # ヘッダー右上の「スタート画面へ」タップ領域
        return (self.SCREEN_W - 50, 4, 44, 16)

    def update_start(self):
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            mx, my = pyxel.mouse_x, pyxel.mouse_y

            bx, by, bw, bh = self.player_switch_button_rect()
            if bx <= mx <= bx + bw and by <= my <= by + bh:
                self.state = STATE_PLAYER_SELECT
                return

            normal_rect, review_rect, timeattack_rect = self.start_screen_rects()

            def hit(r):
                x, y, w, h = r
                return x <= mx <= x + w and y <= my <= y + h

            if hit(normal_rect):
                self.start_normal_mode()
            elif hit(review_rect):
                self.start_review_mode()
            elif hit(timeattack_rect):
                self.start_time_attack_mode()

    def start_normal_mode(self):
        self.mode = MODE_NORMAL
        self.words = self.normal_words
        self.current_wordlist = self.normal_wordlist_name
        self.state = STATE_PLAY
        self.reset_question()

    def start_review_mode(self):
        missed = load_missed_words_unique(self.missed_csv_path)
        if not missed:
            self.notice = "まだ復習できる単語がありません"
            self.notice_timer = 90
            return

        # 現在の通常モードの単語帳を退避しておく（復習が終わったら戻す）
        self.saved_words = self.words
        self.saved_wordlist_name = self.current_wordlist

        self.mode = MODE_REVIEW
        self.words = missed
        self.current_wordlist = "復習モード（間違えた単語）"
        self.review_progress = 0
        self.review_stats = load_review_stats(self.review_stats_path)
        self.state = STATE_PLAY
        self.reset_question()

    def start_time_attack_mode(self):
        pool = load_wordbank_all()
        if not pool:
            pool = self.normal_words

        self.mode = MODE_TIMEATTACK
        self.words = pool
        self.current_wordlist = "タイムアタック（全単語）"
        self.ta_correct = 0
        self.ta_wrong = 0
        self.ta_score = 0
        self.ta_combo = 0
        self.ta_best_combo = 0
        self.ta_start_frame = pyxel.frame_count
        self.state = STATE_PLAY
        self.reset_question()

    def end_time_attack(self):
        final_score = self.ta_score
        self.ta_final_score = final_score

        prior = load_ranking()
        player_scores = [s for p, s in prior if p == self.player]
        player_best = max(player_scores) if player_scores else None
        self.ta_is_new_best = (player_best is None) or (final_score > player_best)

        save_ranking_entry(self.player, final_score)
        self.ranking_rows = load_ranking_best_per_player()[:5]

        self.state = STATE_RESULT

    def update_result(self):
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT) or pyxel.btnp(pyxel.KEY_R):
            self.mode = MODE_NORMAL
            self.words = self.normal_words
            self.current_wordlist = self.normal_wordlist_name
            self.state = STATE_START

    def back_to_normal_after_review(self):
        self.mode = MODE_NORMAL

        # 復習が終わったらスコア・レベル・連続記録を0から仕切り直す
        self.score_correct = 0
        self.score_total = 0
        self.level = 1
        self.streak = 0

        # 単語帳も最初（lv01）からやり直す
        self.normal_words = load_words(WORDS_CSV)
        self.normal_wordlist_name = os.path.basename(WORDS_CSV)
        self.words = self.normal_words
        self.current_wordlist = self.normal_wordlist_name

        self.saved_words = None
        self.saved_wordlist_name = None
        self.review_progress = 0
        self.notice = "通常モードを最初からやり直します"
        self.notice_timer = 90

    # ------------------------------------------------------------------
    def update(self):
        if pyxel.btnp(pyxel.KEY_Q):
            pyxel.quit()

        if self.notice_timer > 0:
            self.notice_timer -= 1
            if self.notice_timer <= 0:
                self.notice = ""

        if self.state == STATE_PLAYER_SELECT:
            self.update_player_select()
            return

        if self.state == STATE_START:
            self.update_start()
            return

        if self.state == STATE_RESULT:
            self.update_result()
            return

        # STATE_PLAY 以降
        if pyxel.btnp(pyxel.KEY_R):
            self.state = STATE_START
            return

        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            bx, by, bw, bh = self.back_button_rect()
            mx, my = pyxel.mouse_x, pyxel.mouse_y
            if bx <= mx <= bx + bw and by <= my <= by + bh:
                self.state = STATE_START
                return

        if self.mode == MODE_TIMEATTACK:
            remaining = self.ta_duration_frames - (pyxel.frame_count - self.ta_start_frame)
            if remaining <= 0:
                self.end_time_attack()
                return

        if self.word_changed:
            self.word_change_timer -= 1
            if self.word_change_timer <= 0:
                self.word_changed = False
            return  # 演出中は他の操作を受け付けない

        if self.cooldown > 0:
            self.cooldown -= 1
            return

        # スマホのタッチも PC のクリックも両方これでOK
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            i = self.hovered_choice_index()
            if i >= 0:
                self.check_answer(self.choices[i])

    def check_answer(self, choice):
        if self.mode == MODE_TIMEATTACK:
            self.check_answer_timeattack(choice)
            return

        self.score_total += 1
        leveled_up = False

        if choice == self.correct_word.japanese:
            self.score_correct += 1
            self.streak += 1
            if self.mode == MODE_NORMAL and self.streak >= self.STREAK_TO_LEVEL_UP:
                self.streak = 0
                self.level += 1
                leveled_up = True

            if leveled_up:
                self.message = f"正解！ レベルアップ！ Lv.{self.level} !!"
                self.message_col = pyxel.COLOR_ORANGE

                # レベルに応じて単語リストを切り替える（超シンプル）
                stage = (self.level - 1) // 2   # 0,1,2,...
                if stage > 4:
                    stage = 4

                # 2桁にする（lv01, lv02, lv03…）
                filename = os.path.join(BASE_DIR, f"words_lv{stage + 1:02d}.csv")

                # 単語帳が変わるかどうかを判定
                if os.path.exists(filename) and os.path.basename(filename) != self.current_wordlist:
                    new_words = load_words(filename)
                    if new_words:
                        self.words = new_words
                        self.normal_words = new_words
                        self.current_wordlist = os.path.basename(filename)
                        self.normal_wordlist_name = self.current_wordlist
                        self.word_changed = True
                        self.word_change_timer = 60

            else:
                self.message = "正解！"
                self.message_col = pyxel.COLOR_LIME
        else:
            self.streak = 0
            self.message = f"不正解… 正解は「{self.correct_word.japanese}」"
            self.message_col = pyxel.COLOR_RED
            save_missed_word(self.correct_word.english, self.correct_word.japanese, self.missed_csv_path)

        if self.mode == MODE_REVIEW:
            mastered_word = self.update_review_mastery(choice == self.correct_word.japanese)
            if mastered_word:
                self.message = f"『{mastered_word}』を復習卒業！おめでとう！"
                self.message_col = pyxel.COLOR_ORANGE
            self.review_progress += 1

        self.cooldown = 45 if leveled_up else 25
        self.reset_question_keep_message()

        # 復習モードは REVIEW_QUESTIONS 問終わったら自動的に通常モードへ
        if self.mode == MODE_REVIEW and self.review_progress >= REVIEW_QUESTIONS:
            self.back_to_normal_after_review()
            self.reset_question()

    def update_review_mastery(self, is_correct):
        """復習モードで単語の連続正解数を記録し、既定回数に達したら
        「間違えた単語」リストから卒業させる。卒業した場合は英単語を返す。"""
        key = (self.correct_word.english, self.correct_word.japanese)
        mastered_word = None

        if is_correct:
            count = self.review_stats.get(key, 0) + 1
            if count >= REVIEW_MASTERY_COUNT:
                self.review_stats.pop(key, None)
                remove_missed_word(self.missed_csv_path, *key)
                self.words = [w for w in self.words if (w.english, w.japanese) != key]
                mastered_word = self.correct_word.english
            else:
                self.review_stats[key] = count
        else:
            self.review_stats[key] = 0  # 間違えたら連続記録はリセット

        save_review_stats(self.review_stats_path, self.review_stats)
        return mastered_word

    def check_answer_timeattack(self, choice):
        if choice == self.correct_word.japanese:
            self.ta_correct += 1
            self.ta_combo += 1
            self.ta_best_combo = max(self.ta_best_combo, self.ta_combo)

            bonus = self.ta_combo // 5  # 5連続ごとにボーナスが+1ずつ増えていく
            gain = 1 + bonus
            self.ta_score += gain

            if self.ta_combo % 5 == 0:
                self.message = f"コンボ x{self.ta_combo}！ +{gain}点"
                self.message_col = pyxel.COLOR_ORANGE
            elif bonus > 0:
                self.message = f"正解！ +{gain}点（コンボ x{self.ta_combo}）"
                self.message_col = pyxel.COLOR_LIME
            else:
                self.message = "正解！"
                self.message_col = pyxel.COLOR_LIME
        else:
            self.ta_wrong += 1
            self.ta_combo = 0
            self.ta_score -= 1
            self.message = f"不正解… 正解は「{self.correct_word.japanese}」"
            self.message_col = pyxel.COLOR_RED
            save_missed_word(self.correct_word.english, self.correct_word.japanese, self.missed_csv_path)

        self.cooldown = 12  # タイムアタックはテンポよく次の問題へ
        self.reset_question_keep_message()

    def reset_question_keep_message(self):
        # メッセージだけ保持したまま次の問題を用意する
        msg = self.message
        col = self.message_col
        self.reset_question()
        self.message = msg
        self.message_col = col

    # ------------------------------------------------------------------
    def draw(self):
        if self.state == STATE_PLAYER_SELECT:
            self.draw_player_select()
        elif self.state == STATE_START:
            self.draw_start()
        elif self.state == STATE_RESULT:
            self.draw_result()
        else:
            self.draw_play()

    def draw_start(self):
        pyxel.cls(pyxel.COLOR_PEACH)
        for x, y, col, r in self.bg_dots:
            pyxel.circ(x, y, r, col)

        pyxel.rect(0, 0, self.SCREEN_W, self.HEADER_H, pyxel.COLOR_PINK)
        pyxel.rect(0, self.HEADER_H, self.SCREEN_W, 3, pyxel.COLOR_ORANGE)
        pyxel.clip(0, 0, self.SCREEN_W, self.HEADER_H)
        self.draw_big_text(16, 8, "英単語トレーニング", pyxel.COLOR_WHITE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_PURPLE, max_width=self.SCREEN_W - 90)
        pyxel.text(16, 40, f"プレイヤー: {self.player}", pyxel.COLOR_WHITE, self.font_s)
        pyxel.clip()

        bx, by, bw, bh = self.player_switch_button_rect()
        pyxel.rect(bx, by, bw, bh, pyxel.COLOR_PURPLE)
        pyxel.rectb(bx, by, bw, bh, pyxel.COLOR_WHITE)
        pyxel.clip(bx, by, bw, bh)
        pyxel.text(bx + 4, by + 5, "人を変える", pyxel.COLOR_WHITE, self.font_s)
        pyxel.clip()

        self.draw_big_text(30, 72, "モードをえらんでね", pyxel.COLOR_PURPLE, self.font_s,
                            scale=2, outline_col=pyxel.COLOR_WHITE, max_width=self.SCREEN_W - 44)

        normal_rect, review_rect, timeattack_rect = self.start_screen_rects()
        missed_count = len(load_missed_words_unique(self.missed_csv_path))

        # 通常モードボタン
        x, y, w, h = normal_rect
        pyxel.rect(x, y, w, h, pyxel.COLOR_LIME)
        pyxel.rectb(x, y, w, h, pyxel.COLOR_WHITE)
        pyxel.clip(x, y, w, h)
        self.draw_big_text(x + 14, y + 12, "通常モード", pyxel.COLOR_PURPLE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_WHITE, max_width=w - 20)
        pyxel.clip()

        # 復習モードボタン
        x, y, w, h = review_rect
        review_col = pyxel.COLOR_ORANGE if missed_count > 0 else pyxel.COLOR_GRAY
        pyxel.rect(x, y, w, h, review_col)
        pyxel.rectb(x, y, w, h, pyxel.COLOR_WHITE)
        pyxel.clip(x, y, w, h)
        self.draw_big_text(x + 14, y + 4, "復習モード", pyxel.COLOR_WHITE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_PURPLE, max_width=w - 20)
        pyxel.text(x + 14, y + 34, f"間違えた単語: {missed_count}問", pyxel.COLOR_WHITE, self.font_s)
        pyxel.clip()

        # タイムアタックモードボタン
        x, y, w, h = timeattack_rect
        pyxel.rect(x, y, w, h, pyxel.COLOR_CYAN)
        pyxel.rectb(x, y, w, h, pyxel.COLOR_WHITE)
        pyxel.clip(x, y, w, h)
        self.draw_big_text(x + 14, y + 4, "タイムアタック", pyxel.COLOR_PURPLE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_WHITE, max_width=w - 20)
        pyxel.text(x + 14, y + 34, "5分間で連続正解のコンボを狙え！", pyxel.COLOR_PURPLE, self.font_s)
        pyxel.clip()

        if self.notice:
            pyxel.rect(0, 280, self.SCREEN_W, 20, pyxel.COLOR_WHITE)
            pyxel.text(20, 286, self.notice, pyxel.COLOR_RED, self.font_s)
        else:
            pyxel.text(20, 290, "タップしてモードを選んでね", pyxel.COLOR_GRAY, self.font_s)

    # ------------------------------------------------------------------
    def draw_play(self):
        pyxel.cls(pyxel.COLOR_PEACH)

        # --- 背景の水玉模様（控えめな装飾） ---
        for x, y, col, r in self.bg_dots:
            pyxel.circ(x, y, r, col)

        # --- 上部カラフルヘッダー（3行ぶんの高さに余裕を持たせてある） ---
        pyxel.rect(0, 0, self.SCREEN_W, self.HEADER_H, pyxel.COLOR_PINK)
        pyxel.rect(0, self.HEADER_H, self.SCREEN_W, 3, pyxel.COLOR_ORANGE)

        pyxel.clip(0, 0, self.SCREEN_W, self.HEADER_H)  # ヘッダー帯の外には絶対にはみ出させない

        if self.mode == MODE_TIMEATTACK:
            header1 = f"タイムアタック  スコア {self.ta_score}"
        else:
            mode_label = "復習モード" if self.mode == MODE_REVIEW else f"Lv.{self.level}"
            header1 = f"{mode_label}  正解 {self.score_correct}/{self.score_total}"
        self.draw_big_text(10, 4, header1, pyxel.COLOR_WHITE, self.font_s,
                            scale=2, outline_col=pyxel.COLOR_PURPLE, max_width=self.SCREEN_W - 66)

        if self.mode == MODE_REVIEW:
            header2 = f"復習 {self.review_progress}/{REVIEW_QUESTIONS}問"
        elif self.mode == MODE_TIMEATTACK:
            remaining_frames = max(0, self.ta_duration_frames - (pyxel.frame_count - self.ta_start_frame))
            remaining_sec = remaining_frames // FPS
            header2 = f"残り {remaining_sec // 60}:{remaining_sec % 60:02d}"
        else:
            header2 = f"連続 {self.streak}/{self.STREAK_TO_LEVEL_UP}"
        pyxel.text(10, 36, header2, pyxel.COLOR_YELLOW, self.font_s)

        if self.mode == MODE_TIMEATTACK:
            pyxel.text(10, 48, f"コンボ x{self.ta_combo}　正{self.ta_correct} 誤{self.ta_wrong}",
                       pyxel.COLOR_YELLOW, self.font_s)
        elif self.mode == MODE_REVIEW:
            key = (self.correct_word.english, self.correct_word.japanese)
            streak = self.review_stats.get(key, 0)
            pyxel.text(10, 48, f"連続正解 {streak}/{REVIEW_MASTERY_COUNT}回で卒業",
                       pyxel.COLOR_YELLOW, self.font_s)
        else:
            pyxel.text(10, 48, f"単語帳: {self.current_wordlist}", pyxel.COLOR_YELLOW, self.font_s)

        pyxel.clip()  # クリップ解除

        # --- 「スタート画面へ」タップボタン（ヘッダー右上） ---
        bx, by, bw, bh = self.back_button_rect()
        pyxel.rect(bx, by, bw, bh, pyxel.COLOR_PURPLE)
        pyxel.rectb(bx, by, bw, bh, pyxel.COLOR_WHITE)
        pyxel.clip(bx, by, bw, bh)
        pyxel.text(bx + 4, by + 5, "戻る", pyxel.COLOR_WHITE, self.font_s)
        pyxel.clip()

        # --- 出題単語（見出しの下に目立つカードを敷く） ---
        card_y = self.HEADER_H + 8
        card_h = 26
        pyxel.rect(16, card_y, self.CHOICE_W + 8, card_h, pyxel.COLOR_LIGHT_BLUE)
        pyxel.rectb(16, card_y, self.CHOICE_W + 8, card_h, pyxel.COLOR_WHITE)
        pyxel.clip(16, card_y, self.CHOICE_W + 8, card_h)  # カードの外にはみ出させない
        self.draw_big_text(24, card_y + 5, f"英単語: {self.correct_word.english}",
                            pyxel.COLOR_PURPLE, self.font_l, scale=2,
                            outline_col=pyxel.COLOR_WHITE, max_width=self.CHOICE_W - 10)
        pyxel.clip()

        # --- 例文（あれば、対象単語を隠して表示） ---
        y = self.HEADER_H + 38
        for line in self.example_en_lines:
            pyxel.text(20, y, line, pyxel.COLOR_PURPLE, self.font_s)
            y += 12
        if self.example_en_lines:
            y += 2
        for line in self.example_ja_lines:
            pyxel.text(20, y, line, pyxel.COLOR_GRAY, self.font_s)
            y += 12

        # --- 選択肢（マウスが乗っている項目はハイライト、色はカラフルに） ---
        hover_i = self.hovered_choice_index() if (self.cooldown == 0 and not self.word_changed) else -1
        choice_scale = 2 if self.choice_h >= 34 else 1
        for i, choice in enumerate(self.choices):
            x, yb, w, h = self.choice_rect(i)
            base_col = CHOICE_COLORS[i % len(CHOICE_COLORS)]
            if i == hover_i:
                pyxel.rect(x - 2, yb - 2, w + 4, h + 4, pyxel.COLOR_YELLOW)
            pyxel.rect(x, yb, w, h, base_col)
            pyxel.rectb(x, yb, w, h, pyxel.COLOR_WHITE)
            pyxel.clip(x, yb, w, h)  # ボタンの外にはみ出させない
            self.draw_big_text(x + 10, yb + max(2, (h - 12 * choice_scale) // 2), choice,
                                pyxel.COLOR_PURPLE, self.font_l, scale=choice_scale,
                                outline_col=pyxel.COLOR_WHITE, max_width=w - 20)
            pyxel.clip()

        # --- 正解／不正解メッセージ（バナー風に目立たせる） ---
        pyxel.rect(0, 276, self.SCREEN_W, 18, pyxel.COLOR_WHITE)
        pyxel.clip(0, 276, self.SCREEN_W, 18)
        self.draw_big_text(10, 278, self.message, self.message_col, self.font_s,
                            scale=1, max_width=self.SCREEN_W - 20)
        pyxel.clip()
        pyxel.text(20, 300, "Qキー:終了　右上「戻る」で最初へ", pyxel.COLOR_GRAY, self.font_s)

        if self.word_changed:
            pyxel.rect(20, 120, self.SCREEN_W - 40, 80, pyxel.COLOR_ORANGE)
            pyxel.rectb(20, 120, self.SCREEN_W - 40, 80, pyxel.COLOR_WHITE)
            pyxel.clip(20, 120, self.SCREEN_W - 40, 80)
            self.draw_big_text(35, 140, "単語帳が変わったよ！",
                                pyxel.COLOR_WHITE, self.font_l, scale=2,
                                outline_col=pyxel.COLOR_PURPLE, max_width=self.SCREEN_W - 90)
            pyxel.text(35, 175, f"Now: {self.current_wordlist}", pyxel.COLOR_WHITE, self.font_s)
            pyxel.clip()

    # ------------------------------------------------------------------
    def draw_result(self):
        pyxel.cls(pyxel.COLOR_PEACH)
        for x, y, col, r in self.bg_dots:
            pyxel.circ(x, y, r, col)

        pyxel.rect(0, 0, self.SCREEN_W, self.HEADER_H, pyxel.COLOR_PINK)
        pyxel.rect(0, self.HEADER_H, self.SCREEN_W, 3, pyxel.COLOR_ORANGE)
        pyxel.clip(0, 0, self.SCREEN_W, self.HEADER_H)
        self.draw_big_text(16, 16, "タイムアタック結果", pyxel.COLOR_WHITE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_PURPLE, max_width=self.SCREEN_W - 24)
        pyxel.clip()

        y = self.HEADER_H + 10
        pyxel.text(20, y, f"プレイヤー: {self.player}", pyxel.COLOR_PURPLE, self.font_s)
        y += 16

        pyxel.rect(16, y, self.CHOICE_W + 8, 28, pyxel.COLOR_LIGHT_BLUE)
        pyxel.rectb(16, y, self.CHOICE_W + 8, 28, pyxel.COLOR_WHITE)
        pyxel.clip(16, y, self.CHOICE_W + 8, 28)
        self.draw_big_text(24, y + 5, f"スコア: {self.ta_final_score}", pyxel.COLOR_PURPLE, self.font_l,
                            scale=2, outline_col=pyxel.COLOR_WHITE, max_width=self.CHOICE_W - 10)
        pyxel.clip()
        y += 34

        pyxel.text(20, y, f"最高コンボ: x{self.ta_best_combo}　正解{self.ta_correct} 不正解{self.ta_wrong}",
                   pyxel.COLOR_PURPLE, self.font_s)
        y += 16

        if self.ta_is_new_best:
            pyxel.rect(16, y, self.CHOICE_W + 8, 26, pyxel.COLOR_YELLOW)
            pyxel.rectb(16, y, self.CHOICE_W + 8, 26, pyxel.COLOR_WHITE)
            pyxel.clip(16, y, self.CHOICE_W + 8, 26)
            self.draw_big_text(24, y + 4, "Hi-Score!!", pyxel.COLOR_RED, self.font_l,
                                scale=2, outline_col=pyxel.COLOR_WHITE, max_width=self.CHOICE_W - 10)
            pyxel.clip()
            y += 32

        pyxel.text(20, y, "ランキング TOP5", pyxel.COLOR_PURPLE, self.font_s)
        y += 14

        for i, (p, s) in enumerate(self.ranking_rows):
            is_this_entry = (p == self.player)
            col = pyxel.COLOR_ORANGE if is_this_entry else pyxel.COLOR_GRAY
            pyxel.text(20, y, f"{i + 1}. {p}  {s}点", col, self.font_s)
            y += 13
            if y > 292:
                break

        pyxel.text(20, 300, "タップしてスタート画面へ", pyxel.COLOR_GRAY, self.font_s)


WordGame()
