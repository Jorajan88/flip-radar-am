# radar.py — FLIP RADAR AM v0.4.4 | RENT | Геворг + Нана
from playwright.sync_api import sync_playwright
import re, os, time, sqlite3, requests
from statistics import median
from config import TG_TOKEN, TG_CHATS

AMD_PER_USD = 385.0
DISCOUNT = 0.85
DROP_MIN = 0.03
MAX_PAGES = 2
CITIES = ["ереван", "цахкадзор", "раздан"]
DISTRICTS = ["Кентрон", "Арабкир", "Давташен", "Аван", "Ачапняк", "Шенгавит",
             "Малатия-Себастия", "Нор Норк", "Канакер-Зейтун", "Эребуни",
             "Норк-Мараш", "Нубарашен"]
STATE = "cf_state.json"
DB = "radar.db"


DROPS = []
HEADERS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

def init_db():
    con = sqlite3.connect(DB)
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listings'").fetchone():
        cols = [r[1] for r in con.execute("PRAGMA table_info(listings)")]
        if "price_usd" not in cols or "pets" not in cols:
            con.execute("DROP TABLE listings")
    con.execute("""CREATE TABLE IF NOT EXISTS listings(
        url TEXT PRIMARY KEY, title TEXT, zone TEXT, rooms INTEGER,
        area REAL, price_usd REAL, ppm REAL, pets INTEGER,
        sig_at TEXT, seen_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cols = [r[1] for r in con.execute("PRAGMA table_info(listings)")]
    if "last_seen" not in cols:
        con.execute("ALTER TABLE listings ADD COLUMN last_seen TEXT")
    cols = [r[1] for r in con.execute("PRAGMA table_info(listings)")]
    if "sig_at" not in cols:
        con.execute("ALTER TABLE listings ADD COLUMN sig_at TEXT")
    con.commit()
    return con

def clean_title(txt):
    t = txt.replace("\n", " ").strip()
    patterns = [
        r"(\d+\s*[-–]?\s*комн\.\s*квартира.*)",
        r"(\d+\s*[-–]?\s*комнатная\s*квартира.*)",
        r"(студия.*)",
        r"(квартира.*)"
    ]
    for p in patterns:
        m = re.search(p, t, re.IGNORECASE)
        if m:
            return m.group(1)[:180]
    return t[:180]

def parse_card(txt):
    if "посуточ" in txt.lower() or "в сутки" in txt.lower():
        return None
    m = re.search(r"([\d,]+)\s*֏", txt)
    if not m: return None
    price_usd = float(m.group(1).replace(",", "")) / AMD_PER_USD
    m = re.search(r"(\d+(?:\.\d+)?)\s*кв\.м", txt)
    if not m: return None
    area = float(m.group(1))
    m = re.search(r"(\d+)\s*[-.]?\s*ком", txt)
    rooms = int(m.group(1)) if m else None
    low = txt.lower()
    district = next((d for d in DISTRICTS if d[:8].lower() in low), None)
    if district: zone = district
    elif "цахкадзор" in low: zone = "Цахкадзор"
    elif "раздан" in low: zone = "Раздан"
    else: zone = "Ереван (другой)"
    pets = 1 if any(k in low for k in ["животн", "питом", "кошк", "собак", "pet"]) else 0
    return dict(zone=zone, rooms=rooms, area=area, price=price_usd,
                ppm=price_usd / area, pets=pets, title=clean_title(txt))

def crawl_rent(city):
    url = f"https://www.list.am/ru/category/56?q={city}"
    cards, seen = [], set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            storage_state=STATE if os.path.exists(STATE) else None,
            locale="ru-RU", timezone_id="Asia/Yerevan", user_agent=HEADERS_UA)
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        for _ in range(MAX_PAGES):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("a[href*='/item/']", timeout=20000)
            except Exception:
                for _ in range(5):
                    page.mouse.wheel(0, 1500)
                    time.sleep(1.5)
            title = page.title()
            content_start = page.content()[:3000].lower()
            if "Just a moment" in title or "проверк" in content_start:
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                              json={"chat_id": TG_CHATS[0],
                                    "text": "🚨 Радар: Cloudflare на сервере, куки протухли, нужен ручной заход!"})
            for a in page.query_selector_all("a[href*='/item/']"):
                href = a.get_attribute("href") or ""
                m = re.search(r"/item/(\d+)", href)
                if not m or m.group(1) in seen: continue
                seen.add(m.group(1))
                node, best = a, None
                for _ in range(5):
                    if node is None: break
                    txt = node.inner_text().strip()
                    if len(txt) > 800: break
                    if "֏" in txt and "кв.м" in txt: best = txt
                    node = node.evaluate_handle("el => el.parentElement")
                    if not node: break
                if best:
                    c = parse_card(best)
                    if c:
                        c["url"] = href if href.startswith("http") else "https://www.list.am" + href
                        cards.append(c)
            nxt = page.query_selector("a:has-text('Следующая')")
            if not nxt: break
            nxt_href = nxt.get_attribute("href") or ""
            url = nxt_href if nxt_href.startswith("http") else "https://www.list.am" + nxt_href
            time.sleep(2)
        ctx.storage_state(path=STATE)
        browser.close()
    return cards

def tg_send(text):
    if not TG_TOKEN:
        return
    for chat in TG_CHATS:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": chat,
                "text": text,
                "disable_web_page_preview": False
            }
        )
        time.sleep(0.4)

def report(con):
    for (zone,) in con.execute("SELECT DISTINCT zone FROM listings"):
        rows = con.execute(
            "SELECT url,title,area,price_usd,ppm,pets,sig_at FROM listings WHERE zone=?",
            (zone,)
        ).fetchall()
        if len(rows) < 5:
            continue
        med = median(r[4] for r in rows)
        fresh = [r for r in rows if r[4] <= med * DISCOUNT and r[6] is None]
        if not fresh:
            continue
        fresh = sorted(fresh, key=lambda r: r[3])
        header = f"📍 {zone} | сигналов: {len(fresh)} | медиана ${med:.1f}/м²"
        print("\n" + header)
        tg_send(header)
        for url, title, area, price_usd, ppm, pets, sig_at in fresh:
            flags = " 🐾 можно с животными" if pets else ""
            price_amd = int(price_usd * AMD_PER_USD)
            msg = (
                f"💰 {price_amd:,}֏ (${price_usd:.0f})/мес{flags}\n"
                f"📐 {area:.0f}м² = {ppm:.1f}$/м²\n"
                f"📊 медиана района: {med:.1f}$/м²\n\n"
                f"{title}\n\n"
                f"{url}"
            )
            print(msg)
            tg_send(msg)
            con.execute(
                "UPDATE listings SET sig_at=? WHERE url=?",
                (time.strftime("%Y-%m-%d"), url)
            )
            time.sleep(0.7)
        con.commit()

def main():
    con = init_db()
    con.execute("DELETE FROM listings WHERE last_seen IS NOT NULL AND last_seen < datetime('now', '-15 days')")
    con.execute("DELETE FROM listings WHERE last_seen IS NULL AND seen_at < date('now', '-45 days')")
    con.commit()
    con.execute("UPDATE listings SET sig_at='seeded' WHERE sig_at IS NULL")
    con.commit()
    for city in CITIES:
        print(f"[{city}]")
        cards = crawl_rent(city)
        new = dropped = 0
        now = time.strftime("%Y-%m-%d %H:%M")
        for c in cards:
            row = con.execute("SELECT price_usd FROM listings WHERE url=?", (c["url"],)).fetchone()
            if row is None:
                con.execute("INSERT INTO listings(url,title,zone,rooms,area,price_usd,ppm,pets,last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                            (c["url"], c["title"], c["zone"], c["rooms"], c["area"], c["price"], c["ppm"], c["pets"], now))
                new += 1
            else:
                old = row[0]
                con.execute("UPDATE listings SET last_seen=? WHERE url=?", (now, c["url"]))
                if old and c["price"] and abs(old - c["price"]) / old >= DROP_MIN:
                    con.execute("UPDATE listings SET price_usd=?, ppm=? WHERE url=?", (c["price"], c["ppm"], c["url"]))
                    if c["price"] < old:
                        old_amd = int(old * AMD_PER_USD)
                        new_amd = int(c["price"] * AMD_PER_USD)
                        DROPS.append(f"📉 {c['zone']} | 💰 было {old_amd:,}֏ → стало {new_amd:,}֏ "
                                     f"(${old:.0f} → ${c['price']:.0f}, -{(1 - c['price'] / old) * 100:.0f}%)\n"
                                     f"{c['title']}\n{c['url']}")
                        dropped += 1
        con.commit()
        print(f"  собрано: {len(cards)} (новых: {new}, снижений: {dropped})")
    report(con)
    if DROPS:
        tg_send("📉 СНИЗИЛИ ЦЕНУ | " + time.strftime("%d.%m %H:%M"))
        for drop in DROPS:
            tg_send(drop)
    print("\nГотово. База: radar.db")

if __name__ == "__main__":
    main()