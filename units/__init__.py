"""The stratified stand-in corpus.

A deliberately tractable mix that mirrors the strata of real LLM-refactored OSS
code: pure, time, rng, io, stateful, concurrent, plus controls. NOT a real-world
coverage estimate (see README) — its job is to drive the engine end-to-end and
prove the controls fire.
"""

from .concurrent import UNITS as _concurrent
from .controls import UNITS as _controls
from .env import UNITS as _env
from .io import UNITS as _io
from .pure import UNITS as _pure
from .stateful import UNITS as _stateful

ALL_UNITS = _pure + _env + _io + _stateful + _concurrent + _controls
