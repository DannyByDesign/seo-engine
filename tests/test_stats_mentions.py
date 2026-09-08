from scripts.lib import mentions, stats


def test_wilson_zero_of_one_is_wide_but_zero_of_thirty_is_narrow():
    low, high = stats.wilson_interval(0, 1)
    assert low == 0.0 and high > 0.7
    low, high = stats.wilson_interval(0, 30)
    assert low == 0.0 and high < 0.15
    assert stats.wilson_interval(0, 0) == (0.0, 1.0)
    assert stats.rate(3, 12)["point"] == 0.25


def test_mentions_basic_and_alias_longest_first():
    hit = mentions.detect_mention("Open Hands and OpenHands are the same project.", ["OpenHands", "Open Hands"])
    assert hit["mentioned"] and hit["count"] == 2
    assert 0 <= hit["first_position"] < 0.05


def test_mentions_ignore_urls_but_count_link_labels():
    text = "See [Vercel](https://vercel.com/docs) and https://vercel.com for hosting."
    hit = mentions.detect_mention(text, ["Vercel"])
    assert hit["count"] == 1  # label counts, target and bare URL do not
    address_only = "Source: [vercel.com](https://vercel.com)"
    assert not mentions.detect_mention(address_only, ["Vercel"])["mentioned"]


def test_mentions_word_boundaries_and_dotted_names():
    assert not mentions.detect_mention("Everyone loves you today.", ["You.com"])["mentioned"]
    assert mentions.detect_mention("I searched on You.com yesterday.", ["You.com"])["mentioned"]
    assert not mentions.detect_mention("thradium is an element", ["thrad"])["mentioned"]


def test_domain_labels_are_never_terms():
    assert mentions.brand_terms("thrad", ["Thrad AI"]) == ["thrad", "Thrad AI"]
    assert mentions.build_regex(["a"]) is None
    assert mentions.detect_mention("", ["x"])["count"] == 0
