"""測試用的假雲端：和 Cloud 一樣的功能，但資料存在記憶體裡。

用途：自動測試、沒有網路時檢查介面。規則盡量和 supabase/schema.sql 一致。
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta

from .cloud import TAIPEI, CloudError, from_taipei, is_ntu_email


def _taipei_now():
    return datetime.now(TAIPEI).replace(tzinfo=None)


class FakeCloud:
    enabled = True

    def __init__(self, now=None):
        self._now = now or _taipei_now          # 和 App 一樣用台灣時間（不帶時區）
        self.session = None
        self.users: dict[str, dict] = {}          # email → {"id", "profile"}
        self.boosts: list[dict] = []
        self.posts: dict[int, dict] = {}
        self.cheers: set[tuple[int, str]] = set()
        self.meetups: dict[int, dict] = {}
        self.activities: list[dict] = []
        self.blocks: set[tuple[str, str]] = set()
        self.reports: list[tuple] = []
        self.uploads: dict[str, bytes] = {}
        self.sent_codes: dict[str, str] = {}
        self.friends: set[frozenset] = set()
        self.friend_reqs: set[tuple[str, str]] = set()      # (from, to)
        self.friend_codes: dict[str, str] = {}               # user id → code
        self._ids = itertools.count(1)

    # ---------- 帳號 ----------
    @property
    def logged_in(self):
        return bool(self.session)

    @property
    def user_id(self):
        return (self.session or {}).get("user_id", "")

    def dump_session(self):
        import json
        return json.dumps(self.session or {})

    def load_session(self, text):
        import json
        data = json.loads(text or "{}")
        self.session = data if data.get("user_id") else None

    def public_url(self, path):
        return ""                                    # 測試時不顯示網路圖片

    async def sign_in_anonymously(self):
        uid = f"u{next(self._ids)}"
        self.users[f"anon-{uid}"] = {"id": uid, "profile": None}
        self.session = {"user_id": uid, "email": "", "refresh_token": "x", "access_token": "x"}

    async def send_code(self, email):
        email = email.strip().lower()
        if not is_ntu_email(email):
            raise CloudError("目前只開放台大信箱（@ntu.edu.tw）")
        self.sent_codes[email] = "123456"

    async def verify_code(self, email, code):
        email = email.strip().lower()
        if self.sent_codes.get(email) != code.strip():
            raise CloudError("驗證碼錯誤或已過期")
        user = self.users.setdefault(email, {"id": f"u{next(self._ids)}", "profile": None})
        self.session = {"user_id": user["id"], "email": email, "refresh_token": "x", "access_token": "x"}

    def sign_out(self):
        self.session = None

    def _user(self):
        if not self.session:
            raise CloudError("請先登入")
        return next(u for u in self.users.values() if u["id"] == self.user_id)

    def _profile(self):
        p = self._user()["profile"]
        if not p:
            raise CloudError("請先完成個人資料")
        return p

    def _name(self, uid):
        return next(u["profile"]["display_name"] for u in self.users.values() if u["id"] == uid and u["profile"])

    def _blocked(self, a, b):
        return (a, b) in self.blocks or (b, a) in self.blocks

    async def me(self):
        u = self._user()
        return dict(u["profile"], circle="台大") if u["profile"] else None

    async def setup_profile(self, name, dept):
        u = self._user()
        if not name.strip():
            raise CloudError("取一個暱稱吧")
        u["profile"] = {"id": u["id"], "display_name": name.strip(), "dept": dept.strip(), "title": "", "tribe": ""}
        return await self.me()

    async def set_title(self, title, tribe):
        p = self._profile()
        p.update(title=title, tribe=tribe)
        self._act("title", extra=title)
        return await self.me()

    async def delete_my_data(self):
        self._user()["profile"] = None

    def _act(self, verb, rid="", name="", area="", ref=None, extra=""):
        self.activities.append({"id": next(self._ids), "verb": verb, "actor_id": self.user_id,
                                "restaurant_id": rid, "restaurant_name": name, "area": area,
                                "ref_id": ref, "extra": extra, "created_at": from_taipei(self._now())})

    # ---------- 助力 ----------
    async def boost(self, rid, name, area):
        self._profile()
        today = self._now().date()
        if any(b["user"] == self.user_id and b["rid"] == rid and b["day"] == today for b in self.boosts):
            return False
        self.boosts.append({"user": self.user_id, "rid": rid, "name": name, "area": area, "day": today})
        self._act("boost", rid, name, area)
        return True

    async def my_boosts_today(self):
        today = self._now().date()
        return {b["rid"] for b in self.boosts if b["user"] == self.user_id and b["day"] == today}

    async def leaderboard(self, days=7, limit=20):
        self._profile()
        since = self._now().date() - timedelta(days=days - 1) if days else None
        agg: dict[str, dict] = {}
        for b in self.boosts:
            if since and b["day"] < since:
                continue
            row = agg.setdefault(b["rid"], {"restaurant_id": b["rid"], "restaurant_name": b["name"],
                                            "area": b["area"], "score": 0, "users": set()})
            row["score"] += 1
            row["users"].add(b["user"])
        rows = sorted(agg.values(), key=lambda r: (-r["score"], -len(r["users"])))[:limit]
        return [dict({k: v for k, v in r.items() if k != "users"}, boosters=len(r["users"])) for r in rows]

    # ---------- 食記 ----------
    async def upload_photo(self, data):
        path = f"{self.user_id}/{len(self.uploads)}.jpg"
        self.uploads[path] = data
        return path

    async def share_post(self, rid, name, area, note, tags, photo_path):
        self._profile()
        pid = next(self._ids)
        self.posts[pid] = {"user": self.user_id, "note": note, "tags": list(tags)[:4], "photo": photo_path}
        self._act("post", rid, name, area, pid)
        return pid

    async def toggle_cheer(self, post_id):
        self._profile()
        key = (post_id, self.user_id)
        if key in self.cheers:
            self.cheers.discard(key)
            return False
        self.cheers.add(key)
        return True

    async def feed(self, limit=40):
        me = self.user_id
        self._profile()
        out = []
        for a in reversed(self.activities):
            if self._blocked(me, a["actor_id"]):
                continue
            m = self.meetups.get(a["ref_id"]) if a["verb"] in ("meetup", "radar") else None
            if m and (m["status"] != "open" or m["expires_at"] <= self._now()):
                continue
            post = self.posts.get(a["ref_id"]) if a["verb"] == "post" else None
            actor = next(u["profile"] for u in self.users.values() if u["id"] == a["actor_id"])
            out.append(dict(a, actor_name=actor["display_name"], actor_dept=actor["dept"],
                            actor_title=actor["title"], note=(post or {}).get("note", ""),
                            tags=(post or {}).get("tags", []), photo_path=(post or {}).get("photo", ""),
                            cheered=(a["ref_id"], me) in self.cheers if post else False,
                            cheer_names=[self._name(u) for (p, u) in self.cheers if p == a["ref_id"] and u != me][:2] if post else [],
                            meetup=self._meetup_brief(m) if m else None, mine=a["actor_id"] == me))
            if len(out) >= limit:
                break
        return out

    # ---------- 飯局 ----------
    def _meetup_brief(self, m):
        return {"id": m["id"], "kind": m["kind"], "starts_at": from_taipei(m["starts_at"]),
                "expires_at": from_taipei(m["expires_at"]), "capacity": m["capacity"], "theme": m["theme"],
                "status": m["status"], "count": len(m["members"]), "joined": self.user_id in m["members"]}

    async def create_meetup(self, rid, name, area, starts_at, capacity, theme, radar, friends_only=False):
        self._profile()
        now = self._now()
        if sum(1 for m in self.meetups.values() if m["host"] == self.user_id and m["status"] == "open"
               and m["expires_at"] > now) >= 3:
            raise CloudError("你已經開了 3 個飯局，先等它們結束再開新的")
        if not 2 <= capacity <= 6:
            raise CloudError("人數要在 2～6 人")
        if radar:
            s, e = now, now + timedelta(hours=1)
        else:
            if starts_at < now - timedelta(minutes=10) or starts_at > now + timedelta(days=14):
                raise CloudError("時間要在現在到 14 天內")
            s, e = starts_at, starts_at + timedelta(hours=2)
        mid = next(self._ids)
        self.meetups[mid] = {"id": mid, "host": self.user_id, "kind": "radar" if radar else "meal",
                             "rid": rid, "name": name, "area": area, "starts_at": s, "expires_at": e,
                             "capacity": capacity, "theme": theme, "status": "open", "members": [self.user_id],
                             "friends_only": friends_only}
        if not friends_only:                                 # 好友限定的飯局不上校園動態
            self._act("radar" if radar else "meetup", rid, name, area, mid, theme)
        return mid

    async def join_meetup(self, meetup_id):
        self._profile()
        m = self.meetups.get(meetup_id)
        if not m:
            return False, "找不到這個飯局"
        if m["status"] != "open" or m["expires_at"] <= self._now():
            return False, "這個飯局已經結束了"
        if any(self._blocked(self.user_id, u) for u in m["members"]):
            return False, "無法加入這個飯局"
        if self.user_id in m["members"]:
            return True, ""
        if m.get("friends_only") and not self._are_friends(self.user_id, m["host"]):
            return False, "這是好友限定的飯局"
        if len(m["members"]) >= m["capacity"]:
            return False, "人數已滿"
        m["members"].append(self.user_id)
        return True, ""

    async def leave_meetup(self, meetup_id):
        m = self.meetups[meetup_id]
        if m["host"] == self.user_id:
            m["status"] = "cancelled"
        elif self.user_id in m["members"]:
            m["members"].remove(self.user_id)

    async def open_meetups(self):
        me = self.user_id
        mine_boosts = {b["rid"]: b["name"] for b in self.boosts if b["user"] == me}
        my_dept = self._profile()["dept"]
        out = []
        for m in sorted(self.meetups.values(), key=lambda m: (m["kind"] != "radar", m["starts_at"])):
            if m["status"] != "open" or m["expires_at"] <= self._now() or self._blocked(me, m["host"]):
                continue
            if m.get("friends_only") and m["host"] != me and me not in m["members"] \
                    and not self._are_friends(me, m["host"]):
                continue
            others = [u for u in m["members"] if u != me]
            shared = sorted({mine_boosts[b["rid"]] for b in self.boosts if b["user"] in others and b["rid"] in mine_boosts})[:3]
            profiles = {u["id"]: u["profile"] for u in self.users.values() if u["profile"]}
            out.append({"id": m["id"], "kind": m["kind"], "host_id": m["host"], "host_name": self._name(m["host"]),
                        "restaurant_id": m["rid"], "restaurant_name": m["name"], "area": m["area"],
                        "starts_at": from_taipei(m["starts_at"]), "expires_at": from_taipei(m["expires_at"]),
                        "capacity": m["capacity"], "theme": m["theme"],
                        "member_names": [self._name(u) for u in m["members"]], "joined": me in m["members"],
                        "mine": m["host"] == me, "shared_places": shared,
                        "same_dept": sum(1 for u in others if my_dept and profiles[u]["dept"] == my_dept),
                        "friends_only": bool(m.get("friends_only")),
                        "host_is_friend": self._are_friends(me, m["host"])})
        return out

    async def meetup_members(self, meetup_id):
        m = self.meetups[meetup_id]
        if self.user_id not in m["members"]:
            return []
        profiles = {u["id"]: u["profile"] for u in self.users.values()}
        return [{"user_id": u, **{k: profiles[u][k] for k in ("display_name", "dept", "title", "tribe")}}
                for u in m["members"]]

    async def report(self, target_type, target_id, reason):
        self.reports.append((self.user_id, target_type, str(target_id), reason))

    async def block_user(self, user_id):
        if user_id != self.user_id:
            self.blocks.add((self.user_id, user_id))
            self.friends.discard(frozenset((self.user_id, user_id)))
            self.friend_reqs -= {(self.user_id, user_id), (user_id, self.user_id)}

    # ---------- 好友（規則和 schema.sql 一樣） ----------
    def _are_friends(self, a, b):
        return frozenset((a, b)) in self.friends

    def _make_friends(self, a, b):
        self.friends.add(frozenset((a, b)))
        self.friend_reqs -= {(a, b), (b, a)}

    async def my_friend_code(self):
        self._profile()
        me = self.user_id
        if me not in self.friend_codes:
            self.friend_codes[me] = f"F{len(self.friend_codes) + 1:07d}"
        return self.friend_codes[me]

    async def add_friend_by_code(self, code):
        self._profile()
        other = next((u for u, c in self.friend_codes.items() if c == (code or "").strip().upper()), None)
        if not other:
            return False, "這個好友連結無效"
        if other == self.user_id:
            return False, "這是你自己的好友連結"
        if self._blocked(self.user_id, other):
            return False, "無法加這位好友"
        self._make_friends(self.user_id, other)
        return True, self._name(other)

    async def request_friend(self, user_id):
        self._profile()
        me = self.user_id
        if user_id == me or self._blocked(me, user_id):
            return False, "無法加這位好友"
        if self._are_friends(me, user_id):
            return True, "已經是好友"
        if not any(me in m["members"] and user_id in m["members"] for m in self.meetups.values()):
            return False, "一起吃過飯局才能加好友"
        if (user_id, me) in self.friend_reqs:
            self._make_friends(me, user_id)
            return True, "已成為好友"
        self.friend_reqs.add((me, user_id))
        return True, "已送出邀請"

    async def friend_requests(self):
        profiles = {u["id"]: u["profile"] for u in self.users.values() if u["profile"]}
        return [{"user_id": f, "display_name": profiles[f]["display_name"], "dept": profiles[f]["dept"]}
                for f, t in self.friend_reqs if t == self.user_id and f in profiles]

    async def respond_friend(self, user_id, accept):
        if (user_id, self.user_id) not in self.friend_reqs:
            return
        if accept:
            self._make_friends(self.user_id, user_id)
        else:
            self.friend_reqs.discard((user_id, self.user_id))

    async def my_friends(self):
        me = self.user_id
        profiles = {u["id"]: u["profile"] for u in self.users.values() if u["profile"]}
        out = []
        for pair in self.friends:
            if me in pair:
                other = next(iter(pair - {me}))
                if other in profiles:
                    p = profiles[other]
                    out.append({"user_id": other, "display_name": p["display_name"], "dept": p["dept"],
                                "title": p.get("title", "")})
        return sorted(out, key=lambda f: f["display_name"])

    async def remove_friend(self, user_id):
        self.friends.discard(frozenset((self.user_id, user_id)))
