---
name: Textual Widget.parent and .app are read-only properties — use PropertyMock
description: Widget.parent and Widget.app have no setter; direct assignment raises AttributeError in unit tests
type: feedback
originSessionId: bfaa96d5-8607-482c-b166-841d78544fb5
---
Use `patch.object(WidgetClass, "parent", new_callable=PropertyMock, return_value=mock)` (or `"app"`) inside a `with` block when mocking these in unit tests that call `Widget.__new__()` without mounting.

**Why:** Textual defines `parent` and `app` as read-only properties on `DOMNode`/`Widget`. Direct assignment (`widget.parent = mock`) raises `AttributeError: property 'parent' of 'X' object has no setter`. This came up when testing `FooterPane.on_button_pressed()` and `ToolBlock._render_body()`.

**How to apply:** Any time a test creates a widget with `__new__` and needs to stub `.parent` or `.app`, wrap the call under `patch.object(WidgetClass, "parent/app", new_callable=PropertyMock, return_value=...)`.

Also note: `rich.syntax.Syntax._theme` is a `PygmentsSyntaxTheme` object, not a string. To assert on the theme name, patch `rich.syntax.Syntax` at the call site and capture the `theme=` kwarg instead.
