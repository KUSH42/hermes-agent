"""Alias layer for R3 overlay consolidation (§5 of spec).

Provides backward-compat class names for overlays that have been merged into
`ConfigOverlay` (picker tabs) and `InterruptOverlay` (interrupt variants).

Two mechanisms cooperate:

1. **CSS-type registration** — alias class names are added to the canonical's
   ``_css_type_names`` frozenset so ``query_one(Alias)`` matches the canonical
   pre-mounted instance regardless of active mode.

2. **Metaclass ``__instancecheck__``** — bare ``isinstance(obj, Alias)`` is
   mode-aware: returns True only when the canonical is in the matching mode.

Aliases are NOT subclasses of the canonical (would pollute mount targets);
they subclass ``Widget`` directly and rely on registration.
"""

from __future__ import annotations

from typing import ClassVar

from textual.widget import Widget


class _AliasMeta(type(Widget)):  # type: ignore[misc]
    """Metaclass making alias classes mode-aware for ``isinstance``.

    An alias class declares two attrs::

        _alias_target: type[Widget]      # canonical class
        _alias_mode:   str | None        # active-tab / kind discriminator, or None

    ``isinstance(obj, Alias)`` returns True when ``obj`` is an instance of the
    target and its ``active_tab`` (ConfigOverlay) or ``current_kind``
    (InterruptOverlay) matches ``_alias_mode``.
    """

    def __instancecheck__(cls, obj: object) -> bool:  # noqa: D401
        target = getattr(cls, "_alias_target", None)
        if target is None:
            return super().__instancecheck__(obj)
        if not isinstance(obj, target):
            return False
        mode = getattr(cls, "_alias_mode", None)
        if mode is None:
            return True
        # Check either active_tab (ConfigOverlay) or current_kind
        # (InterruptOverlay). Compare by string value so StrEnum works.
        for attr in ("active_tab", "current_kind"):
            val = getattr(obj, attr, None)
            if val is None:
                continue
            if getattr(val, "value", val) == mode:
                return True
        return False


def _make_config_alias(name: str, mode: str) -> type[Widget]:
    """Construct a config-tab alias subclass of Widget with _AliasMeta.

    The returned class's target is wired in ``register_aliases()`` after
    ``ConfigOverlay`` is defined (avoids circular import).
    """

    cls: type[Widget] = _AliasMeta(
        name,
        (Widget,),
        {
            "_alias_target": None,
            "_alias_mode": mode,
            "__module__": __name__,
        },
    )
    return cls


def _make_interrupt_alias(name: str, mode: str) -> type[Widget]:
    cls: type[Widget] = _AliasMeta(
        name,
        (Widget,),
        {
            "_alias_target": None,
            "_alias_mode": mode,
            "__module__": __name__,
        },
    )
    return cls


# ── Config-tab aliases ─────────────────────────────────────────────────────

ModelPickerOverlay = _make_config_alias("ModelPickerOverlay", "model")
VerbosePickerOverlay = _make_config_alias("VerbosePickerOverlay", "verbose")
SkinPickerOverlay = _make_config_alias("SkinPickerOverlay", "skin")
TabbedSkinOverlay = SkinPickerOverlay  # historical alias
ReasoningPickerOverlay = _make_config_alias("ReasoningPickerOverlay", "reasoning")
YoloConfirmOverlay = _make_config_alias("YoloConfirmOverlay", "yolo")


# ── Interrupt aliases ─────────────────────────────────────────────────────

ClarifyWidget = _make_interrupt_alias("ClarifyWidget", "clarify")
ApprovalWidget = _make_interrupt_alias("ApprovalWidget", "approval")
SudoWidget = _make_interrupt_alias("SudoWidget", "sudo")
SecretWidget = _make_interrupt_alias("SecretWidget", "secret")
UndoConfirmOverlay = _make_interrupt_alias("UndoConfirmOverlay", "undo")
NewSessionOverlay = _make_interrupt_alias("NewSessionOverlay", "new-session")
MergeConfirmOverlay = _make_interrupt_alias("MergeConfirmOverlay", "merge-confirm")


_CONFIG_ALIASES: tuple[type[Widget], ...] = (
    ModelPickerOverlay,
    VerbosePickerOverlay,
    SkinPickerOverlay,
    ReasoningPickerOverlay,
    YoloConfirmOverlay,
)

_INTERRUPT_ALIASES: tuple[type[Widget], ...] = (
    ClarifyWidget,
    ApprovalWidget,
    SudoWidget,
    SecretWidget,
    UndoConfirmOverlay,
    NewSessionOverlay,
    MergeConfirmOverlay,
)


def register_config_aliases(canonical: type[Widget]) -> None:
    """Wire alias targets + register names in canonical's _css_type_names."""
    names: set[str] = set()
    for alias in _CONFIG_ALIASES:
        alias._alias_target = canonical  # type: ignore[attr-defined]
        names.add(alias.__name__)
    names.add("TabbedSkinOverlay")  # historical alias name
    canonical._css_type_names = canonical._css_type_names | names  # type: ignore[attr-defined]


def register_interrupt_aliases(canonical: type[Widget]) -> None:
    names: set[str] = set()
    for alias in _INTERRUPT_ALIASES:
        alias._alias_target = canonical  # type: ignore[attr-defined]
        names.add(alias.__name__)
    canonical._css_type_names = canonical._css_type_names | names  # type: ignore[attr-defined]


__all__ = [
    "ApprovalWidget",
    "ClarifyWidget",
    "MergeConfirmOverlay",
    "ModelPickerOverlay",
    "NewSessionOverlay",
    "ReasoningPickerOverlay",
    "SecretWidget",
    "SkinPickerOverlay",
    "SudoWidget",
    "TabbedSkinOverlay",
    "UndoConfirmOverlay",
    "VerbosePickerOverlay",
    "YoloConfirmOverlay",
    "register_config_aliases",
    "register_interrupt_aliases",
]
