"""
Collect all available 2026 CS2 tournament data from Liquipedia.
Run: python collect_cs2_2026.py
"""
import asyncio, os, ssl, sys, time, urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///C:/Users/solikin/Desktop/ea/bot.db"
sys.path.insert(0, "C:/Users/solikin/Desktop/ea")

from bs4 import BeautifulSoup
from collectors.tournament_tiers import get_tier

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

TOURNAMENTS_2026 = [
    # T1 — главные события 2026
    ("Intel Extreme Masters/2026/Atlanta",                  "Intel Extreme Masters/2026/Atlanta"),
    ("Intel Extreme Masters/2026/China",                    "Intel Extreme Masters/2026/China"),
    ("Intel Extreme Masters/2026/Rio",                      "Intel Extreme Masters/2026/Rio"),
    ("Intel Extreme Masters/2026/Cologne",                  "Intel Extreme Masters/2026/Cologne"),
    ("PGL/2026/Astana",                                     "PGL/2026/Astana"),
    ("PGL/2026/Bucharest",                                  "PGL/2026/Bucharest"),
    ("PGL/2026/Cluj-Napoca",                                "PGL/2026/Cluj-Napoca"),
    ("PGL/2026/Masters/Europe",                             "PGL/2026/Masters/Europe"),
    ("PGL/2026/Masters/North_America",                      "PGL/2026/Masters/North America"),
    ("PGL/2026/Masters/South_America",                      "PGL/2026/Masters/South America"),
    # T2
    ("CS_Asia_Championships/2026",                          "CS Asia Championships/2026"),
    ("Hero_Esports/Asian_Champions_League/2026",            "Hero Esports/Asian Champions League/2026"),
    ("CCT/2026/Europe/Series_1",                            "CCT/2026/Europe/Series 1"),
    ("CCT/2026/Europe/Series_2",                            "CCT/2026/Europe/Series 2"),
    ("CCT/2026/Europe/Series_3",                            "CCT/2026/Europe/Series 3"),
    ("CCT/2026/Europe/Series_4",                            "CCT/2026/Europe/Series 4"),
    ("CCT/2026/Europe/Series_5",                            "CCT/2026/Europe/Series 5"),
    ("CCT/2026/Europe/Series_6",                            "CCT/2026/Europe/Series 6"),
    ("CCT/2026/South_America/Series_1",                     "CCT/2026/South America/Series 1"),
    ("CCT/2026/South_America/Series_2",                     "CCT/2026/South America/Series 2"),
    ("BLAST/Rivals/2026/Spring",                            "BLAST/Rivals/2026/Spring"),
    ("BLAST/Rivals/2026/Fall",                              "BLAST/Rivals/2026/Fall"),
    ("BLAST/Bounty/2026/Winter",                            "BLAST/Bounty/2026/Winter"),
    ("BLAST/Bounty/2026/Summer",                            "BLAST/Bounty/2026/Summer"),
    ("Thunderpick/World_Championship/2026",                 "Thunderpick/World Championship/2026"),
    ("Thunderpick/World_Championship/2026/North_America",   "Thunderpick/World Championship/2026/North America"),
    ("BetBoom/RUSH_B!_Summit/2026",                         "BetBoom/RUSH B! Summit/2026"),
    # T3
    ("NODWIN_Gaming/Clutch_Series/8",                       "NODWIN Gaming/Clutch Series/8"),
]


def parse_tournament(slug: str, name: str) -> list[dict]:
    import urllib.parse
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in slug.split("/"))
    url = f"https://liquipedia.net/counterstrike/{encoded}"
    html = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "esports-bot/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=25, context=_ctx) as r:
                html = r.read().decode("utf-8", errors="replace")
            break
        except Exception as e:
            print(f"  Retry {attempt+1}/3 {name}: {type(e).__name__}")
            time.sleep(5)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    tier = get_tier(name, "cs2")
    results, seen = [], set()

    for match in soup.find_all("div", class_="brkts-match"):
        full: list[str] = []
        for a in match.find_all("a", title=True):
            t = a["title"]
            if "does not exist" in t or len(t) < 2:
                continue
            if t not in full:
                full.append(t)
            if len(full) == 2:
                break

        spans = [s.get_text(strip=True) for s in match.find_all("span", class_="name") if s.get_text(strip=True)]
        t1 = full[0] if len(full) >= 1 else (spans[0] if spans else None)
        t2 = full[1] if len(full) >= 2 else (spans[-1] if len(spans) >= 2 else None)
        if not t1 or not t2 or t1 == t2:
            continue

        sc_els = match.find_all("div", class_="brkts-opponent-score-inner")
        scores = [s.get_text(strip=True) for s in sc_els]
        if not scores or not any(s.isdigit() for s in scores):
            continue
        s1 = int(scores[0]) if scores[0].isdigit() else None
        s2 = int(scores[1]) if len(scores) > 1 and scores[1].isdigit() else None
        if s1 == 0 and s2 == 0:
            continue
        if s1 is None or s2 is None:
            continue

        timer = match.find("span", class_="timer-object")
        dt = None
        if timer and timer.get("data-timestamp"):
            dt = datetime.utcfromtimestamp(int(timer["data-timestamp"]))

        # Только 2026 данные
        if dt and dt.year < 2026:
            continue

        key = (t1, t2, str(dt))
        if key in seen:
            continue
        seen.add(key)
        results.append({"t1": t1, "t2": t2, "s1": s1, "s2": s2,
                        "dt": dt, "tournament": name, "game": "cs2", "tier": tier})
    return results


async def save_to_db(matches: list[dict]) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import select, delete
    from db.models import Match, Team

    engine = create_async_engine(
        "sqlite+aiosqlite:///C:/Users/solikin/Desktop/ea/bot.db",
        poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Sess = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Sess() as db:
        # Удаляем старые finished CS2 чтобы не было дублей
        await db.execute(delete(Match).where(Match.game == "cs2", Match.status == "finished"))
        await db.commit()
        print(f"Cleared old CS2 finished matches. Inserting {len(matches)} new...")

        team_stats: dict[str, dict] = {}
        for m in matches:
            db.add(Match(
                source="liquipedia", game="cs2",
                team1_name=m["t1"], team2_name=m["t2"],
                tournament=m["tournament"], scheduled_at=m["dt"],
                status="finished", score_team1=m["s1"], score_team2=m["s2"],
                tier=m["tier"],
            ))
            for nm, is1 in [(m["t1"], True), (m["t2"], False)]:
                if nm not in team_stats:
                    team_stats[nm] = {"wins": 0, "losses": 0, "form": []}
                won = (m["s1"] > m["s2"]) if is1 else (m["s2"] > m["s1"])
                team_stats[nm]["wins" if won else "losses"] += 1
                team_stats[nm]["form"].append("W" if won else "L")

        await db.commit()
        print(f"Inserted {len(matches)} matches. Updating {len(team_stats)} teams...")

        added = updated = 0
        for nm, st in team_stats.items():
            res = await db.execute(select(Team).where(Team.name == nm, Team.game == "cs2"))
            team = res.scalar_one_or_none()
            w, l = st["wins"], st["losses"]
            total = w + l
            wr = round(w / total, 3) if total else 0
            form = "".join(st["form"][-10:])

            if team:
                team.wins = w
                team.losses = l
                team.win_rate_last_10 = wr
                team.recent_form = form
                updated += 1
            else:
                tag = "".join(c[0].upper() for c in nm.split()[:3] if c)[:8]
                db.add(Team(
                    name=nm,
                    normalized_name=nm.lower().replace(" ", "").replace(".", "").replace("-", ""),
                    game="cs2", source="liquipedia", tag=tag,
                    wins=w, losses=l, win_rate_last_10=wr, recent_form=form,
                ))
                added += 1

        await db.commit()
        print(f"Teams: updated={updated}, added={added} new")


def main():
    all_matches: list[dict] = []
    for slug, name in TOURNAMENTS_2026:
        m = parse_tournament(slug, name)
        print(f"  {len(m):3d}: {name}")
        all_matches.extend(m)
        time.sleep(3)

    print(f"\nTotal collected: {len(all_matches)} CS2 2026 matches")
    asyncio.run(save_to_db(all_matches))


if __name__ == "__main__":
    main()
