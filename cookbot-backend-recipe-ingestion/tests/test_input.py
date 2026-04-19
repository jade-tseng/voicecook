import pytest
from app.ingestion.input import classify, normalize_url, normalize_name, normalize_input
from app.models.recipe import InputType


# --- classify ---

@pytest.mark.parametrize("raw,expected", [
    ("https://www.allrecipes.com/recipe/12345/spaghetti/", InputType.url),
    ("http://example.com/recipe", InputType.url),
    ("https://example.com", InputType.url),
    ("spaghetti carbonara", InputType.name),
    ("chicken tikka masala", InputType.name),
    ("  pad thai  ", InputType.name),
    ("not-a-url.txt but also not a url really", InputType.name),
])
def test_classify(raw, expected):
    assert classify(raw) == expected


# --- normalize_url: existing ---

def test_normalize_url_strips_fragment():
    url = "https://Example.COM/recipe/123#instructions"
    canonical, h = normalize_url(url)
    assert "#" not in canonical
    assert canonical == "https://example.com/recipe/123"
    assert len(h) == 64


def test_normalize_url_same_url_same_hash():
    url = "https://example.com/pasta"
    _, h1 = normalize_url(url)
    _, h2 = normalize_url(url)
    assert h1 == h2


def test_normalize_url_different_urls_different_hash():
    _, h1 = normalize_url("https://example.com/pasta")
    _, h2 = normalize_url("https://example.com/pizza")
    assert h1 != h2


# --- normalize_url: check 2a — tracking params stripped ---

@pytest.mark.parametrize("dirty", [
    "https://allrecipes.com/recipe/12345/tikka-masala?utm_source=pinterest&utm_campaign=xyz",
    "https://allrecipes.com/recipe/12345/tikka-masala?fbclid=abc123",
    "https://allrecipes.com/recipe/12345/tikka-masala?gclid=xyz&utm_medium=cpc",
    "https://allrecipes.com/recipe/12345/tikka-masala?ref=homepage",
    "https://allrecipes.com/recipe/12345/tikka-masala?mc_cid=111&mc_eid=222",
    "https://allrecipes.com/recipe/12345/tikka-masala?_ga=2.1234.567",
])
def test_tracking_params_stripped_same_hash(dirty):
    clean = "https://allrecipes.com/recipe/12345/tikka-masala"
    _, h_clean = normalize_url(clean)
    _, h_dirty = normalize_url(dirty)
    assert h_clean == h_dirty, f"hash mismatch for: {dirty}"


def test_non_tracking_params_kept():
    url_a = "https://example.com/recipe?servings=4"
    url_b = "https://example.com/recipe"
    _, h_a = normalize_url(url_a)
    _, h_b = normalize_url(url_b)
    assert h_a != h_b


def test_query_params_sorted():
    url_a = "https://example.com/recipe?z=1&a=2"
    url_b = "https://example.com/recipe?a=2&z=1"
    _, h_a = normalize_url(url_a)
    _, h_b = normalize_url(url_b)
    assert h_a == h_b


# --- normalize_url: check 2b — www. and trailing slash ---

def test_www_stripped_same_hash():
    _, h_www = normalize_url("https://www.allrecipes.com/recipe/12345/")
    _, h_bare = normalize_url("https://allrecipes.com/recipe/12345")
    assert h_www == h_bare


def test_trailing_slash_stripped():
    _, h_slash = normalize_url("https://allrecipes.com/recipe/12345/")
    _, h_no_slash = normalize_url("https://allrecipes.com/recipe/12345")
    assert h_slash == h_no_slash


# --- normalize_url: check 2c — case insensitive scheme+host, preserve path case ---

def test_scheme_host_case_insensitive():
    _, h_upper = normalize_url("HTTPS://AllRecipes.COM/recipe/12345")
    _, h_lower = normalize_url("https://allrecipes.com/recipe/12345")
    assert h_upper == h_lower


def test_path_case_preserved():
    _, h_upper = normalize_url("https://example.com/Recipe/ABC")
    _, h_lower = normalize_url("https://example.com/recipe/abc")
    assert h_upper != h_lower


# --- normalize_name: existing ---

def test_normalize_name_lowercase():
    assert normalize_name("Spaghetti Carbonara") == normalize_name("spaghetti carbonara")


def test_normalize_name_token_sorted():
    assert normalize_name("chicken tikka masala") == "chicken-masala-tikka"


def test_normalize_name_strips_punctuation():
    assert normalize_name("mac & cheese!") == "cheese-mac"


def test_normalize_name_whitespace():
    assert normalize_name("  pad  thai  ") == normalize_name("pad thai")


# --- normalize_name: check 3 — all five variants same result ---

@pytest.mark.parametrize("variant", [
    "chicken tikka masala",
    "Chicken Tikka Masala",
    "tikka masala chicken",
    "tikka-masala chicken!",
    "  chicken   tikka   masala  ",
])
def test_name_variants_same_hash(variant):
    assert normalize_name(variant) == "chicken-masala-tikka", f"failed for: {variant!r}"


# --- normalize_input ---

def test_normalize_input_url():
    ni = normalize_input("https://www.allrecipes.com/recipe/12345/")
    assert ni.input_type == InputType.url
    assert ni.canonical_url is not None
    assert ni.url_hash is not None
    assert ni.normalized_name is None


def test_normalize_input_name():
    ni = normalize_input("beef stew")
    assert ni.input_type == InputType.name
    assert ni.normalized_name is not None
    assert ni.canonical_url is None
    assert ni.url_hash is None


def test_normalize_input_strips_whitespace():
    ni1 = normalize_input("  beef stew  ")
    ni2 = normalize_input("beef stew")
    assert ni1.normalized_name == ni2.normalized_name
