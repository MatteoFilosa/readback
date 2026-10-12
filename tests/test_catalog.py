from cohort.text import slug


def test_every_group_has_members(cat):
    for key, ch in cat.chapters.items():
        assert len(ch["members"]) >= 2, key
    for key, area in cat.areas.items():
        assert len(area["members"]) >= 2, key


def test_regions_cover_italy(cat):
    assert len(cat.regions) == 20
    base = ["nord_ovest", "nord_est", "centro", "sud", "isole"]
    covered = sorted(r for a in base for r in cat.areas[a]["members"])
    assert covered == sorted(cat.regions)


def test_aliases_do_not_collide(cat):
    seen = {}
    for key, c in cat.conditions.items():
        for name in [key, c["name"]] + c["aliases"]:
            other = seen.setdefault(slug(name), key)
            assert other == key, f"{name!r} names both {other} and {key}"


def test_canonical_values(cat):
    assert cat.canonical("condition", "BPCO") == "copd"
    assert cat.canonical("condition", "ictus") == "cerebrovascular_disease"
    assert cat.canonical("condition", "Diabète") == "diabetes"
    assert cat.canonical("condition", "long covid") is None
    assert cat.canonical("region", "Lombardy") == "lombardia"
    assert cat.canonical("sex", "donne") == "female"
    assert cat.canonical("smoking", "ex-fumatore") == "former"


def test_cities_point_to_regions(cat):
    assert cat.cities["milano"]["region"] == "lombardia"
    assert all(c["region"] in cat.regions for c in cat.cities.values())
