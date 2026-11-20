"""社群的「內容」：趣味測驗（吃貨派別稱號）與飯局破冰字卡。

V1 不呼叫 AI：分數由規則計算，字卡從題庫依飯局內容挑選、填入共同點。
之後要換成 AI 產生，只要換掉 icebreaker_cards() 的實作，介面不用改。
"""
from __future__ import annotations

import random

# ---------- 趣味測驗：吃貨派別 ----------
TRIBES = {
    "taro":     ("芋頭派守護神", "火鍋沒有芋頭就不算開動。你相信軟綿是一種美德。"),
    "americano": ("期末考冰美式續命王", "三餐可以少一餐，冰美式不能少一杯。"),
    "nightowl": ("公館宵夜巡守隊", "十點後才是你的主場，哪家還開你都知道。"),
    "speed":    ("學餐效率派", "十分鐘吃完、五分鐘回教室，人生就是要有效率。"),
    "slow":     ("溫州街慢活派", "一頓早午餐可以吃到下午，聊天才是主菜。"),
    "explorer": ("新店開箱探險家", "看到沒吃過的店就忍不住，你的想去清單永遠滿的。"),
}

QUIZ = [
    ("火鍋要不要加芋頭？", [("一定要，還要煮到化開", {"taro": 2}), ("可以，但別太多", {"slow": 1}),
                         ("不要，會把湯弄糊", {"speed": 1}), ("看今天是哪家", {"explorer": 1})]),
    ("期末週靠什麼撐下去？", [("冰美式，大杯", {"americano": 2}), ("宵夜鹹酥雞", {"nightowl": 2}),
                          ("早點睡最實在", {"slow": 1}), ("學餐便當＋圖書館", {"speed": 1})]),
    ("空堂只有 40 分鐘，你會？", [("學餐速戰速決", {"speed": 2}), ("買杯咖啡邊走邊喝", {"americano": 1}),
                              ("衝去新開的那家", {"explorer": 2}), ("乾脆不吃，晚上再補", {"nightowl": 1})]),
    ("朋友說「隨便」，你會帶他去？", [("我的愛店，閉眼選", {"taro": 1}), ("最近排很長的那家", {"explorer": 2}),
                                ("最近的就好", {"speed": 1}), ("可以坐很久的咖啡廳", {"slow": 2})]),
    ("晚上十一點肚子餓？", [("公館走一圈，總有店開", {"nightowl": 2}), ("泡麵加蛋", {"speed": 1}),
                         ("忍到明天早午餐", {"slow": 1}), ("來杯咖啡騙自己", {"americano": 1})]),
    ("你的社團聚餐通常負責？", [("訂位、算錢、催人", {"speed": 1}), ("找新餐廳", {"explorer": 2}),
                            ("帶話題、炒氣氛", {"slow": 1}), ("點最多芋頭的那個", {"taro": 2})]),
    ("點餐時你會？", [("點上次那個", {"taro": 1}), ("點沒吃過的", {"explorer": 1}),
                   ("看誰點什麼再決定", {"slow": 1}), ("先問有沒有咖啡", {"americano": 2})]),
    ("理想的週末早上？", [("睡到中午，直接吃午餐", {"nightowl": 1}), ("溫州街早午餐", {"slow": 2}),
                       ("早起去排名店", {"explorer": 1}), ("咖啡廳趕報告", {"americano": 1})]),
]


def score_quiz(answers: list[int]) -> tuple[str, str, str]:
    """answers：每題選第幾個（0 開始）。回傳 (派別代號, 稱號, 一句話)。同分時依 TRIBES 順序。"""
    points = {k: 0 for k in TRIBES}
    for (_, options), pick in zip(QUIZ, answers):
        if 0 <= pick < len(options):
            for tribe, p in options[pick][1].items():
                points[tribe] += p
    best = max(points, key=lambda k: (points[k], -list(TRIBES).index(k)))
    title, quip = TRIBES[best]
    return best, title, quip


# ---------- 飯局破冰字卡 ----------
CARDS_GENERAL = [
    "如果{restaurant}只能點一道菜帶走，你選哪一道？",
    "你第一次來{area}吃飯是什麼時候？那天吃了什麼？",
    "說一個你覺得被低估的台大附近小店。",
    "學餐哪一攤你願意排最久？",
    "你吃過最「不像學生預算」的一餐是什麼？",
    "期末週你的續命食物是什麼？",
    "火鍋湯底你都選哪一種？有沒有絕對不加的料？",
    "如果要帶外地朋友吃一家台大附近的店，你會帶去哪裡？",
    "你有沒有一家「心情不好就會去」的店？",
    "宵夜派還是早餐派？為什麼？",
    "最近一次被朋友推坑的食物是什麼？",
    "說一道你小時候很討厭、現在卻很愛的食物。",
    "如果今天的飯局有主題曲，你會選哪首？",
    "你點餐比較常「點上次那個」還是「點沒吃過的」？",
]
CARDS_SHARED = [
    "你們都助力過{shared}，誰先發現這家的？",
    "{shared}的哪一道菜最值得再吃一次？",
]
CARDS_TITLE = [
    "桌上有一位「{title}」，請本人解釋一下這個稱號是怎麼來的。",
    "猜猜看：誰是「{title}」？",
]
GAMES = [
    ("二選一快問快答", "輪流出題，例如「珍奶還是鮮奶茶」，大家同時用手指比 1 或 2，跟多數人不同的人分享一個小故事。"),
    ("猜猜誰助力過", "每個人在心裡選一家自己助力過的店，其他人輪流猜。猜中的人可以指定下一個話題。"),
    ("菜單挑戰", "每個人幫左邊的人點一道他沒吃過的菜（在預算內），吃完說一句評語。"),
    ("最後一口猜拳", "共享的菜最後一口，用猜拳決定；輸的人負責拍今天的飯局合照。"),
]


def icebreaker_cards(meetup_id: int, restaurant: str, area: str, shared: list[str], titles: list[str],
                     n_cards: int = 8, n_games: int = 2) -> tuple[list[str], list[tuple[str, str]]]:
    """同一場飯局每個人看到的字卡都一樣（用飯局編號當亂數種子）。"""
    rnd = random.Random(meetup_id)
    fill = {"restaurant": restaurant or "這家店", "area": area or "台大附近"}
    cards: list[str] = []
    if shared:
        cards += [t.format(shared=rnd.choice(shared)) for t in rnd.sample(CARDS_SHARED, k=1)]
    real_titles = [t for t in titles if t]
    if real_titles:
        cards.append(rnd.choice(CARDS_TITLE).format(title=rnd.choice(real_titles)))
    pool = CARDS_GENERAL[:]
    rnd.shuffle(pool)
    for t in pool:
        if len(cards) >= n_cards:
            break
        cards.append(t.format(**fill))
    games = rnd.sample(GAMES, k=min(n_games, len(GAMES)))
    return cards, games
