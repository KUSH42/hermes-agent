---
name: Module split — mutable globals not live through re-export shims
description: After splitting a module, re-exported bool/int globals in __init__ are value copies — tests must target the source module directly
type: feedback
originSessionId: b9845435-17cd-4af2-8b39-b3bc8c0e767f
---
After splitting a Python module into a subpackage, `from ._sub import MY_FLAG` in `__init__.py` captures a **value copy** at import time. Setting `pkg._MY_FLAG = True` (on the package namespace) does NOT update the live variable in `_sub.py`.

**Why:** Python module `import` binds names to values; booleans are immutable. Mutations to the re-export don't propagate back to the original module's namespace, so any code reading `_sub._MY_FLAG` sees the old value.

**How to apply:** When a module is split and a mutable global (`_DISCOVERY_GLOBAL_SHOWN`, etc.) moves to a submodule, update all tests to target `pkg._submod._MY_FLAG` directly. Update autouse fixtures, setup/teardown, and any `assert` checks. Do not rely on `pkg._MY_FLAG` as a proxy for the live variable.
