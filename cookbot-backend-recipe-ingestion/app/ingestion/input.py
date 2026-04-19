import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from slugify import slugify

from app.models.recipe import InputType, NormalizedInput

_URL_RE = re.compile(
    r"^(https?://)"                  # scheme
    r"([a-zA-Z0-9\-\.]+)"            # host
    r"(:\d+)?"                        # optional port
    r"(/[^\s]*)?"                     # path
    r"$",
    re.IGNORECASE,
)

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name", "utm_place",
    "fbclid", "gclid", "ref", "ref_src",
    "mc_cid", "mc_eid", "_ga",
})


def classify(raw: str) -> InputType:
    stripped = raw.strip()
    if _URL_RE.match(stripped):
        return InputType.url
    return InputType.name


def normalize_url(raw: str) -> tuple[str, str]:
    """Return (canonical_url, sha256_hex).

    Normalizations applied:
    - lowercase scheme and host
    - strip leading 'www.'
    - strip trailing slash from path
    - drop fragment
    - drop known tracking query params (utm_*, fbclid, gclid, ref, ...)
    - sort remaining query params alphabetically
    """
    parsed = urlparse(raw.strip())

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = parsed.path.rstrip("/")

    # filter and sort query params
    kept_params = sorted(
        (k, v) for k, v in parse_qsl(parsed.query)
        if k not in _TRACKING_PARAMS
    )
    query = urlencode(kept_params)

    canonical = urlunparse((
        parsed.scheme.lower(),
        host,
        path,
        parsed.params,
        query,
        "",  # no fragment
    ))
    url_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return canonical, url_hash


def normalize_name(raw: str) -> str:
    """Lowercase + token-sort, punctuation-stripped, hyphen-joined."""
    tokens = sorted(slugify(raw).split("-"))
    return "-".join(tokens)


def normalize_input(raw: str) -> NormalizedInput:
    raw = raw.strip()
    input_type = classify(raw)

    if input_type == InputType.url:
        canonical_url, url_hash = normalize_url(raw)
        return NormalizedInput(
            input_type=input_type,
            raw=raw,
            canonical_url=canonical_url,
            url_hash=url_hash,
        )

    normalized_name = normalize_name(raw)
    return NormalizedInput(
        input_type=input_type,
        raw=raw,
        normalized_name=normalized_name,
    )
