import pyxel
import csv
import random
import os
import re

# --- スクリプトと同じフォルダを基準にする ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WORDS_CSV = os.path.join(BASE_DIR, "words.csv")
MISSED_CSV = os.path.join(BASE_DIR, "missed_words.csv")
FONT_12 = os.path.join(BASE_DIR, "umplus_j12r.bdf")
FONT_10 = os.path.join(BASE_DIR, "umplus_j10r.bdf")


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
    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            row = [c.strip() for c in row]
            if len(row) == 2:
                english, japanese = row
                words.append(Word(english, japanese))
            elif len(row) == 3:
                english, japanese, note = row
                words.append(Word(english, japanese, note=note))
            elif len(row) >= 4:
                english, japanese, example_en, example_ja = row[:4]
                words.append(Word(english, japanese, example_en=example_en, example_ja=example_ja))
    return words


# --- 間違えた単語を保存 ---
def save_missed_word(english, japanese, filename=MISSED_CSV):
    with open(filename, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([english, japanese])


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
    CHOICE_GAP = 6
    CHOICES_END_Y = 268  # この位置より下にはボタンを描かない（メッセージ欄の手前まで）

    STREAK_TO_LEVEL_UP = 10
    MAX_CHOICES = 6

    def __init__(self):
        self.words = load_words()

        pyxel.init(self.SCREEN_W, self.SCREEN_H, title="英単語選択ゲーム（スマホ＋PC対応）")
        pyxel.mouse(True)  # マウスカーソルを表示する

        # --- 日本語フォント読み込み（BDFフォント） ---
        self.font_l = None  # 見出し・選択肢用（12px）
        self.font_s = None  # スコア・メッセージ・例文用（10px）
        try:
            self.font_l = pyxel.Font(FONT_12)
            self.font_s = pyxel.Font(FONT_10)
        except Exception as e:
            print(f"フォント読み込みに失敗しました: {e}")

        self.score_correct = 0
        self.score_total = 0
        self.level = 1
        self.streak = 0

        self.reset_question()
        pyxel.run(self.update, self.draw)

    def current_num_choices(self):
        # レベルが上がるほど選択肢が増えて難しくなる（最大 MAX_CHOICES 個）
        return min(3 + self.level, self.MAX_CHOICES)

    def reset_question(self):
        word = random.choice(self.words)
        self.correct_word = word

        num_choices = self.current_num_choices()
        choices = {word.japanese}
        while len(choices) < num_choices:
            choices.add(random.choice(self.words).japanese)

        self.choices = list(choices)
        random.shuffle(self.choices)

        # --- 例文（あれば対象単語を隠して整形。最大2行まで） ---
        self.example_en_lines = []
        if word.example_en:
            masked = mask_target_word(word.example_en, word.english)
            self.example_en_lines = wrap_text(self.font_s, masked, self.CHOICE_W, max_lines=2)

        # --- 例文の日本語訳（あれば整形。最大2行まで） ---
        if self.level < 2 :
            self.example_ja_lines = []
            if word.example_ja:
                self.example_ja_lines = wrap_text(self.font_s, word.example_ja, self.CHOICE_W, max_lines=2)
        else :
            self.example_ja_lines = wrap_text(self.font_s, "", self.CHOICE_W, max_lines=2)

        # --- レイアウトを動的に計算 ---
        content_y = 60
        for _ in self.example_en_lines:
            content_y += 12
        if self.example_en_lines:
            content_y += 2
        for _ in self.example_ja_lines:
            content_y += 12
        if self.example_ja_lines:
            content_y += 4
        self.choices_start_y = max(92, content_y + 6)

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

    def update(self):
        if pyxel.btnp(pyxel.KEY_Q):
            pyxel.quit()

        if self.cooldown > 0:
            self.cooldown -= 1
            return

        # スマホのタッチも PC のクリックも両方これでOK
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            i = self.hovered_choice_index()
            if i >= 0:
                self.check_answer(self.choices[i])

    def check_answer(self, choice):
        self.score_total += 1
        leveled_up = False

        if choice == self.correct_word.japanese:
            self.score_correct += 1
            self.streak += 1
            if self.streak >= self.STREAK_TO_LEVEL_UP:
                self.streak = 0
                self.level += 1
                leveled_up = True

            if leveled_up:
                self.message = f"正解！ レベルアップ！ Lv.{self.level} !!"
                self.message_col = pyxel.COLOR_ORANGE
            else:
                self.message = "正解！"
                self.message_col = pyxel.COLOR_LIME
        else:
            self.streak = 0
            self.message = f"不正解… 正解は「{self.correct_word.japanese}」"
            self.message_col = pyxel.COLOR_RED
            save_missed_word(self.correct_word.english, self.correct_word.japanese)

        self.cooldown = 45 if leveled_up else 25
        self.reset_question_keep_message()

    def reset_question_keep_message(self):
        # メッセージだけ保持したまま次の問題を用意する
        msg = self.message
        col = self.message_col
        self.reset_question()
        self.message = msg
        self.message_col = col

    def draw(self):
        pyxel.cls(1)

        # --- スコア・レベル表示（10pxフォント） ---
        pyxel.text(20, 10, f"Lv.{self.level}   正解数: {self.score_correct} / {self.score_total}",
                   pyxel.COLOR_WHITE, self.font_s)
        pyxel.text(20, 22, f"連続正解: {self.streak} / {self.STREAK_TO_LEVEL_UP}",
                   pyxel.COLOR_CYAN, self.font_s)

        # --- 出題単語（12pxフォント） ---
        pyxel.text(20, 40, f"英単語: {self.correct_word.english}", pyxel.COLOR_WHITE, self.font_l)

        # --- 例文（あれば、対象単語を隠して表示） ---
        y = 60
        for line in self.example_en_lines:
            pyxel.text(20, y, line, pyxel.COLOR_LIGHT_BLUE, self.font_s)
            y += 12
        if self.example_en_lines:
            y += 2
        for line in self.example_ja_lines:
            pyxel.text(20, y, line, pyxel.COLOR_GRAY, self.font_s)
            y += 12

        # --- 選択肢（マウスが乗っている項目はハイライト） ---
        hover_i = self.hovered_choice_index() if self.cooldown == 0 else -1
        for i, choice in enumerate(self.choices):
            x, yb, w, h = self.choice_rect(i)
            fill = pyxel.COLOR_DARK_BLUE if i == hover_i else pyxel.COLOR_NAVY
            border = pyxel.COLOR_YELLOW if i == hover_i else pyxel.COLOR_LIGHT_BLUE
            pyxel.rect(x, yb, w, h, fill)
            pyxel.rectb(x, yb, w, h, border)
            pyxel.text(x + 10, yb + max(4, (h - 12) // 2), choice, pyxel.COLOR_YELLOW, self.font_l)

        # --- 正解／不正解メッセージ（10pxフォント） ---
        pyxel.text(20, 285, self.message, self.message_col, self.font_s)
        pyxel.text(20, 300, "Qキーで終了", pyxel.COLOR_GRAY, self.font_s)


WordGame()
