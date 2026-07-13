"""Tracks which C++ #include directives are needed and emits them sorted and deduplicated."""

from typing import Set, List, Optional, Dict


# Module path → C++ header(s)
MODULE_INCLUDES: Dict[str, List[str]] = {
    "std.io":     ["<iostream>"],
    "std.math":   ["<cmath>"],
    "std.string": ["<string>"],
    "std.algo":   ["<algorithm>"],
    "std.thread": ["<thread>", "<future>"],
}

# Feature → C++ header
FEATURE_INCLUDES: Dict[str, str] = {
    "string":          "<string>",
    "vector":          "<vector>",
    "array":           "<array>",
    "unordered_map":   "<unordered_map>",
    "map":             "<map>",
    "unordered_set":   "<unordered_set>",
    "deque":           "<deque>",
    "queue":           "<queue>",
    "tuple":           "<tuple>",
    "optional":        "<optional>",
    "expected":        "<expected>",
    "sstream":         "<sstream>",
    "future":          "<future>",
    "variant":         "<variant>",
    "cstdint":         "<cstdint>",
    "cmath":           "<cmath>",
    "algorithm":       "<algorithm>",
    "stdexcept":       "<stdexcept>",
    "functional":      "<functional>",
    "iostream":        "<iostream>",
}


class IncludeTracker:
    """Tracks which #include directives are needed during emission."""

    def __init__(self):
        self._includes: Set[str] = set()

    def need(self, feature: str) -> None:
        """Register that a feature requiring a specific header is used."""
        header = FEATURE_INCLUDES.get(feature)
        if header:
            self._includes.add(header)

    def need_header(self, header: str) -> None:
        """Directly add a header (e.g. '<iostream>')."""
        self._includes.add(header)

    def need_module(self, module_path: str) -> Optional[List[str]]:
        """
        Register an import by module path (e.g. 'std.io').
        Returns the list of headers if known, None otherwise.
        """
        headers = MODULE_INCLUDES.get(module_path)
        if headers:
            for h in headers:
                self._includes.add(h)
            return headers
        return None

    def emit(self) -> str:
        """Return sorted, deduplicated #include lines."""
        if not self._includes:
            return ""
        sorted_includes = sorted(self._includes)
        return "\n".join(f"#include {inc}" for inc in sorted_includes)

    def has_includes(self) -> bool:
        return len(self._includes) > 0
