"""社群功能的設定。

到 Supabase 後台 → Project Settings → API，把下面兩個值換成你的專案的：
  SUPABASE_URL       Project URL，例如 https://abcdefgh.supabase.co
  SUPABASE_ANON_KEY  anon public key（這把是公開的，放在網頁裡沒關係；
                     千萬不要貼 service_role key）

兩個都空白時，App 照常運作，只是社群功能（登入、助力、動態、飯局）會顯示「尚未開通」。
"""

SUPABASE_URL = "https://giwuvndulfkfodbfrfyu.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_WF3Me6b9IH3iAaoMuBPdUg__q8cwkV7"

# 網站公開網址（分享到 Threads 時會附上）
SITE_URL = "https://elaborate-platypus-213a26.netlify.app"
