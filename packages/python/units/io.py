"""I/O units. External calls go through the recorded Effects shim, so the
ordered trace of effects is part of observed behavior. Equivalent refactors keep
the same calls in the same order."""

from probe.effects import Effects
from probe.model import Unit


def fetch_and_parse_orig(url: str, fx: Effects) -> int:
    body = fx.http_get(url)
    return len(body)


def fetch_and_parse_ref(url: str, fx: Effects) -> int:
    response = fx.http_get(url)
    return len(response)


def write_report_orig(s: str, fx: Effects) -> bool:
    fx.write("/tmp/report.txt", s.strip())
    fx.log("wrote report")
    return True


def write_report_ref(s: str, fx: Effects) -> bool:
    content = s.strip()
    fx.write("/tmp/report.txt", content)
    fx.log("wrote report")
    return True


def read_config_orig(path: str, fx: Effects) -> str:
    data = fx.read(path)
    if not data:
        return "default"
    return data


def read_config_ref(path: str, fx: Effects) -> str:
    data = fx.read(path)
    return data if data else "default"


_FETCH_FIXTURES = {
    ("http_get", "a"): "{}",
    ("http_get", "hello world"): '{"ok": true}',
}
_CONFIG_FIXTURES = {
    ("read", "a"): "loaded",
}

UNITS = [
    Unit("fetch_and_parse", "io", fetch_and_parse_orig, fetch_and_parse_ref,
         fixtures=_FETCH_FIXTURES),
    Unit("write_report", "io", write_report_orig, write_report_ref),
    Unit("read_config", "io", read_config_orig, read_config_ref,
         fixtures=_CONFIG_FIXTURES),
]
