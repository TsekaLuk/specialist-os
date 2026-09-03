"""Optional bridge to the compiled Rust core.

Build with maturin from ``rust-core`` to enable it. The Python fallback keeps
the package installable with only the standard library.
"""

try:
    from specialist_core import cache_key_py as rust_cache_key
    from specialist_core import validate_input_py as rust_validate_input

    AVAILABLE = True
except ImportError:
    AVAILABLE = False
    rust_cache_key = None
    rust_validate_input = None

__all__ = ["AVAILABLE", "rust_cache_key", "rust_validate_input"]

