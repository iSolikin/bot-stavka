"""
Mass collection of CS2 historical match data (6 months).
Run: python collect_cs2_history.py
"""
import asyncio
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///C:/Users/solikin/Desktop/ea/bot.db"
sys.path.insert(0, "C:/Users/solikin/Desktop/ea")

from bs4 import BeautifulSoup
from collectors.tournament_tiers import get_tier

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

ALL_CS2_TOURNAMENTS = [
    ("Intel_Extreme_Masters/2025/Katowice",        "Intel Extreme Masters/2025/Katowice"),
    ("Intel_Extreme_Masters/2025/Dallas",          "Intel Extreme Masters/2025/Dallas"),
    ("Intel_Extreme_Masters/2025/Cologne",         "Intel Extreme Masters/2025/Cologne"),
    ("Intel_Extreme_Masters/2025/Chengdu",         "Intel Extreme Masters/2025/Chengdu"),
    ("PGL/2025/Bucharest",                         "PGL/2025/Bucharest"),
    ("PGL/2025/Astana",                            "PGL/2025/Astana"),
    ("Intel_Extreme_Masters/2026/Atlanta",         "Intel Extreme Masters/2026/Atlanta"),
    ("PGL/2026/Astana",                            "PGL/2026/Astana"),
    ("PGL/2026/Bucharest",                         "PGL/2026/Bucharest"),
    ("PGL/2026/Masters/Europe",                    "PGL/2026/Masters/Europe"),
    ("PGL/2026/Masters/North_America",             "PGL/2026/Masters/North America"),
    ("PGL/2026/Masters/South_America",             "PGL/2026/Masters/South America"),
    ("Hero_Esports/Asian_Champions_League/2025",   "Hero Esports/Asian Champions League/2025"),
    ("NODWIN_Gaming/Clutch_Series/7",              "NODWIN Gaming/Clutch Series/7"),
    ("BLAST/Rivals/2025/Spring",                   "BLAST/Rivals/2025/Spring"),
    ("BLAST/Rivals/2025/Fall",                     "BLAST/Rivals/2025/Fall"),
    ("CS_Asia_Championships/2026",                 "CS Asia Championships/2026"),
    ("Hero_Esports/Asian_Champions_League/2026",   "Hero Esports/Asian Champions League/2026"),
    ("CCT/2026/Europe/Series_1",                   "CCT/2026/Europe/Series 1"),
    ("CCT/2026/Europe/Series_2",                   "CCT/2026/Europe/Series 2"),
    ("CCT/2026/Europe/Series_3",                   "CCT/2026/Europe/Series 3"),
    ("CCT/2026/Europe/Series_4",                   "CCT/2026/Europe/Series 4"),
    ("BLAST/Rivals/2026/Spring",                   "BLAST/Rivals/2026/Spring"),
    ("NODWIN_Gaming/Clutch_Series/8",              "NODWIN Gaming/Clutch Series/8"),
]


def parse_tournament(slug: str, tournament_name: str) -> list[dict]:
    url = f"https://liquipedia.net/counterstrike/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "esports-bot/1.0", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  SKIP {tournament_name}: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []
    seen: set = set()
    tier = get_tier(tournament_name, "cs2")

    for match in soup.find_all("div", class_="brkts-match"):
        full_names: list[str] = []
        for a in match.find_all("a", title=True):
            t = a["title"]
            if "does not exist" in t or len(t) < 2:
                continue
            if t not in full_names:
                full_names.append(t)
            if len(full_names) == 2:
                break

        span_names = [s.get_text(strip=True) for s in match.find_all("span", class_="name") if s.get_text(strip=True)]
        t1 = full_names[0] if len(full_names) >= 1 else (span_names[0] if span_names else None)
        t2 = full_names[1] if len(full_names) >= 2 else (span_names[-1] if len(span_names) >= 2 else None)
        if not t1 or not t2 or t1 == t2:
            continue

        score_els = match.find_all("div", class_="brkts-opponent-score-inner")
        scores = [s.get_text(strip=True) for s in score_els]
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

        key = (t1, t2, str(dt))
        if key not in seen:
            seen.add(key)
            results.append({"t1": t1, "t2": t2, "s1": s1, "s2": s2, "dt": dt,
                            "tournament": tournament_name, "game": "cs2", "tier": tier})
    return results


async def save_to_db(matches: list[dict]) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import select
    from db.models import Match, Team

    engine = create_async_engine(
        "sqlite+aiosqlite:///C:/Users/solikin/Desktop/ea/bot.db",
        poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Sess = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    updated = inserted = 0
    team_stats: dict[str, dict] = {}

    async with Sess() as db:
        for m in matches:
            existing = None
            if m["dt"]:
                res = await db.execute(
                    select(Match).where(
                        Match.game == "cs2",
                        Match.team1_name == m["t1"],
                        Match.team2_name == m["t2"],
                        Match.scheduled_at >= m["dt"] - timedelta(hours=3),
                        Match.scheduled_at <= m["dt"] + timedelta(hours=3),
                    )
                )
                existing = res.scalar_one_or_none()

            if existing:
                existing.score_team1 = m["s1"]
                existing.score_team2 = m["s2"]
                existing.status = "finished"
                existing.tier = m["tier"]
                updated += 1
            else:
                db.add(Match(
                    source="liquipedia", game="cs2",
                    team1_name=m["t1"], team2_name=m["t2"],
                    tournament=m["tournament"], scheduled_at=m["dt"],
                    status="finished", score_team1=m["s1"], score_team2=m["s2"],
                    tier=m["tier"],
                ))
                inserted += 1

            for team, is_t1 in [(m["t1"], True), (m["t2"], False)]:
                if team not in team_stats:
                    team_stats[team] = {"wins": 0, "losses": 0, "recent": []}
                s_own = m["s1"] if is_t1 else m["s2"]
                s_opp = m["s2"] if is_t1 else m["s1"]
                won = s_own > s_opp
                if won:
                    team_stats[team]["wins"] += 1
                else:
                    team_stats[team]["losses"] += 1
                team_stats[team]["recent"].append("W" if won else "L")

        await db.commit()
        print(f"Matches saved: updated={updated}, inserted={inserted}")

        teams_added = teams_updated = 0
        for team_name, stats in team_stats.items():
            res = await db.execute(select(Team).where(Team.name == team_name, Team.game == "cs2"))
            team = res.scalar_one_or_none()
            w, l = stats["wins"], stats["losses"]
            total = w + l
            wr = round(w / total, 3) if total else 0
            recent_str = "".join(stats["recent"][-10:])

            if team:
                team.wins = w
                team.losses = l
                team.win_rate_last_10 = wr
                team.recent_form = recent_str
                teams_updated += 1
            else:
                tag = "".join(c[0].upper() for c in team_name.split()[:3] if c)[:8]
                db.add(Team(
                    name=team_name,
                    normalized_name=team_name.lower().replace(" ", "").replace(".", "").replace("-", ""),
                    game="cs2", source="liquipedia", tag=tag,
                    wins=w, losses=l, win_rate_last_10=wr, recent_form=recent_str,
                ))
                teams_added += 1

        await db.commit()
        print(f"Teams: added={teams_added}, updated={teams_updated}")


def main():
    all_matches: list[dict] = []
    for slug, name in ALL_CS2_TOURNAMENTS:
        matches = parse_tournament(slug, name)
        print(f"  {len(matches):3d} matches: {name}")
        all_matches.extend(matches)
        time.sleep(2)

    print(f"\nTotal collected: {len(all_matches)} CS2 matches")
    asyncio.run(save_to_db(all_matches))


if __name__ == "__main__":
    main()
