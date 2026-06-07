"""
Tournament tier classification for CS2 and Dota 2.
Returns 1 (top-tier / S-A), 2 (mid-tier / B), 3 (everything else / C and below).
"""

# Ключевые слова для понижения тира (проверяются ДО tier-1/2, перебивают их)
_DOWNGRADE_TO_2 = [
    "qualifier", "qualifiers", "closed qualifier", "open qualifier",
    "division 2", "div 2", "division ii",
    "regional league",
]
_DOWNGRADE_TO_3 = [
    "division 3", "div 3", "division iii",
    "open cup", "amateur",
]

# CS2
_CS2_TIER1 = [
    "pgl",                  # PGL Astana, PGL Major, PGL Copenhagen
    "iem", "intel extreme masters",
    "blast premier",
    "esl one",
    "esl pro league",
    " major",               # CS Major (пробел чтобы не матчить "minor")
    "cs major",
    "blast world final",
]
_CS2_TIER2 = [
    "cs asia",
    "hero esports",
    "betboom storm",
    "cct",                  # CCT EU/NA series
    "republ.iq",
    "esl impact",
    "esea premier",
    "esea main",
    "bc.game masters",
    "thunderpick world championship",
]

# Dota2
_DOTA2_TIER1 = [
    "the international",
    "dreamleague",          # DL Season/Group Stage — основной турнир (Division 2/квалы упадут через downgrade)
    "esl one",
    "blast slam",           # BLAST SLAM — топовый турнир
    "blast",
    "pgl wallachia",
    "pgl",                  # PGL мейджоры/серии
    "bali major",
    "riyadh masters",
    "lima major",
    "berlin major",
    "major",                # любой Major
    "esports world cup",
    "gaimin gladiators",    # крупные инвайт-турниры
]
_DOTA2_TIER2 = [
    "immortal cup",
    "betboom streamers",
    "betboom dacha",
    "dpc",
    "divine knockout",
    "cringe station",
    "lunar horse",
    "destiny league",
    "epl",                  # EPL World Series — региональные
    "european pro league",
    "champions league",
]


def get_tier(tournament_name: str, game: str) -> int:
    """Return tier 1, 2, or 3 for the given tournament name and game."""
    if not tournament_name:
        return 3

    name_lower = tournament_name.lower()

    # Сначала ищем маркеры снижения тира
    for kw in _DOWNGRADE_TO_3:
        if kw in name_lower:
            return 3
    is_qualifier_or_div2 = any(kw in name_lower for kw in _DOWNGRADE_TO_2)

    if game == "cs2":
        for kw in _CS2_TIER1:
            if kw in name_lower:
                return 2 if is_qualifier_or_div2 else 1
        for kw in _CS2_TIER2:
            if kw in name_lower:
                return 3 if is_qualifier_or_div2 else 2
        return 3

    elif game == "dota2":
        for kw in _DOTA2_TIER1:
            if kw in name_lower:
                return 2 if is_qualifier_or_div2 else 1
        for kw in _DOTA2_TIER2:
            if kw in name_lower:
                return 3 if is_qualifier_or_div2 else 2
        return 3

    return 3
