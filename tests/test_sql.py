"""資料庫函式測試：在本機 Postgres 模擬 Supabase 執行 supabase/schema.sql。

需要本機有 Postgres，預設略過；要跑的話：TABLE_SQL_TESTS=1 pytest tests/test_sql.py
"""
import os
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(os.environ.get("TABLE_SQL_TESTS") != "1", reason="需要本機 Postgres")
DB = "table_test"


def psql(sql: str, db: str = DB) -> str:
    r = subprocess.run(["su", "postgres", "-c", f"psql -X -q -v ON_ERROR_STOP=1 -At -d {db}"],
                       input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def as_user(uid, sql: str) -> str:
    return psql(f"set role authenticated; set request.jwt.claim.sub = '{uid}';\n{sql}")


@pytest.fixture(scope="module")
def db():
    psql(f"drop database if exists {DB}; create database {DB};", db="postgres")
    psql((ROOT / "tests" / "sql" / "supabase_stub.sql").read_text())
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    psql(schema)
    psql(schema)                                   # 可以重複執行
    users = {}
    for name in ["an", "yu", "leo", "max"]:            # 匿名登入：沒有信箱
        uid = str(uuid.uuid4())
        psql(f"insert into auth.users (id) values ('{uid}');")
        users[name] = uid
    yield users


def test_anyone_can_join_without_email(db):
    uid = str(uuid.uuid4())
    psql(f"insert into auth.users (id, email) values ('{uid}', 'someone@gmail.com');")   # 有信箱也沒關係
    assert '"circle" : "台大"' in as_user(uid, "select setup_profile('路人', '')::text;")
    with pytest.raises(RuntimeError, match="NAME_REQUIRED"):
        as_user(uid, "select setup_profile('   ', '');")


def test_profile_and_direct_table_access_denied(db):
    out = as_user(db["an"], "select setup_profile('安安', '資工系')::text;")
    assert '"display_name" : "安安"' in out and '"circle" : "台大"' in out
    as_user(db["yu"], "select setup_profile('小魚', '資工系');")
    as_user(db["leo"], "select setup_profile('Leo', '經濟系');")
    with pytest.raises(RuntimeError, match="permission denied"):
        as_user(db["an"], "select * from profiles;")
    with pytest.raises(RuntimeError, match="permission denied"):
        psql("set role anon; select me();")


def test_no_profile_cannot_act(db):
    with pytest.raises(RuntimeError, match="NO_PROFILE"):
        as_user(db["max"], "select boost('r1', '店', '公館');")


def test_boost_once_per_day_and_leaderboard(db):
    assert as_user(db["an"], "select boost('osm1', '巷尾麵舖', '公館')->>'new';") == "true"
    assert as_user(db["an"], "select boost('osm1', '巷尾麵舖', '公館')->>'new';") == "false"
    as_user(db["yu"], "select boost('osm1', '巷尾麵舖', '公館');")
    as_user(db["yu"], "select boost('osm2', '冬至食堂', '校內');")
    rows = as_user(db["leo"], "select restaurant_name, score, boosters from leaderboard(7, 10);").splitlines()
    assert rows[0] == "巷尾麵舖|2|2" and rows[1] == "冬至食堂|1|1"
    assert as_user(db["an"], "select my_boosts_today();") == "{osm1}"


def test_post_feed_cheer(db):
    with pytest.raises(RuntimeError, match="BAD_PHOTO_PATH"):
        as_user(db["an"], f"select share_post('osm1', '巷尾麵舖', '公館', '清湯', '{{}}', '{db['yu']}/x.jpg');")
    pid = as_user(db["an"], f"select share_post('osm1', '巷尾麵舖', '公館', '清湯很好喝', array['宵夜'], '{db['an']}/a.jpg');")
    assert as_user(db["yu"], f"select toggle_cheer({pid});") == "t"
    assert as_user(db["leo"], f"select toggle_cheer({pid});") == "t"
    assert as_user(db["leo"], f"select toggle_cheer({pid});") == "f"
    feed = as_user(db["an"], "select verb, actor_name, note, cheer_names, mine from feed(20);").splitlines()
    assert feed[0] == "post|安安|清湯很好喝|{小魚}|t"
    assert any(line.startswith("boost|小魚") for line in feed)


def test_meetups_join_capacity_and_shared_points(db):
    mid = as_user(db["an"], "select create_meetup('osm1', '巷尾麵舖', '公館', now() + interval '1 day', 2, '一起吃宵夜');")
    rows = as_user(db["yu"], "select host_name, member_names, joined, shared_places, same_dept from open_meetups();")
    assert rows.splitlines()[0] == "安安|{安安}|f|{巷尾麵舖}|1"
    assert as_user(db["yu"], f"select join_meetup({mid})->>'ok';") == "true"
    assert as_user(db["leo"], f"select join_meetup({mid})->>'reason';") == "人數已滿"
    assert as_user(db["leo"], f"select count(*) from meetup_members_of({mid});") == "0"   # 不是成員看不到名單
    assert as_user(db["yu"], f"select string_agg(display_name, ',') from meetup_members_of({mid});") == "安安,小魚"
    with pytest.raises(RuntimeError, match="BAD_TIME"):
        as_user(db["an"], "select create_meetup('', '店', '', now() - interval '1 day', 4, '', false);")


def test_radar_expires_and_host_leave_cancels(db):
    rid = as_user(db["leo"], "select create_meetup('osm9', '大狗麵線', '公館', null, 3, '12:10 求飯友', true);")
    assert "大狗麵線" in as_user(db["an"], "select restaurant_name from open_meetups() where kind = 'radar';")
    psql(f"update meetups set expires_at = now() - interval '1 minute' where id = {rid};")
    assert as_user(db["an"], "select count(*) from open_meetups() where kind = 'radar';") == "0"
    assert as_user(db["an"], "select count(*) from feed(50) where verb = 'radar';") == "0"
    mid = as_user(db["leo"], "select create_meetup('osm3', '三川拉麵', '公館', now() + interval '2 hours', 4, '');")
    as_user(db["leo"], f"select leave_meetup({mid});")
    assert as_user(db["an"], f"select count(*) from open_meetups() where id = {mid};") == "0"


def test_block_hides_and_prevents_join(db):
    mid = as_user(db["leo"], "select create_meetup('osm4', '劉記川味牛肉麵', '公館', now() + interval '3 hours', 6, '');")
    as_user(db["an"], f"select block_user('{db['leo']}');")
    assert as_user(db["an"], f"select count(*) from open_meetups() where id = {mid};") == "0"
    assert as_user(db["an"], f"select join_meetup({mid})->>'reason';") == "無法加入這個飯局"
    assert as_user(db["an"], f"select count(*) from feed(50) where actor_id = '{db['leo']}';") == "0"
    as_user(db["an"], f"select report('user', '{db['leo']}', '測試');")
    assert psql("select count(*) from reports;") == "1"


def test_title_and_delete_my_data(db):
    out = as_user(db["yu"], "select set_title('芋頭派守護神', 'taro')->>'title';")
    assert out == "芋頭派守護神"
    as_user(db["yu"], "select delete_my_data();")
    assert as_user(db["yu"], "select me() is null;") == "t"
    assert psql(f"select count(*) from boosts where user_id = '{db['yu']}';") == "0"
