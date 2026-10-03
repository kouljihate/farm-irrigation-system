"""Naming and placement rules for valves."""

DEFAULT_MAX_SECTORS_PER_MV = 5


def build_mv_groups(
    sector_codes: list[str],
    max_per_group: int = DEFAULT_MAX_SECTORS_PER_MV,
) -> dict[str, list[str]]:
    """Group sorted sector codes into manifolds of at most ``max_per_group``.

    Returns e.g. ``{"MV1": ["S1", ..., "S5"], "MV2": ["S6", "S7", "S8"]}``.
    """
    codes = sorted(sector_codes)
    if max_per_group < 1:
        max_per_group = DEFAULT_MAX_SECTORS_PER_MV
    groups: dict[str, list[str]] = {}
    for i in range(0, len(codes), max_per_group):
        groups[f"MV{i // max_per_group + 1}"] = codes[i:i + max_per_group]
    return groups


def group_sector_map(
    sector_codes: list[str],
    max_per_group: int = DEFAULT_MAX_SECTORS_PER_MV,
) -> dict[str, str]:
    """Return ``{sector_code: mv_name}`` for the given sectors."""
    out: dict[str, str] = {}
    for mv, sectors in build_mv_groups(sector_codes, max_per_group).items():
        for s in sectors:
            out[s] = mv
    return out


def zv_name(sector_code: str, zone_index: int) -> str:
    return f"{sector_code}-ZV{zone_index}"
