"""Incremental partial-JSON string field extractor for tool_gen_args_delta streaming."""
from __future__ import annotations


class PartialJSONCodeExtractor:
    """Extracts the value of a named string field from streaming JSON chunks.

    Given chunks like '{"code":"import ya', 'ml\\n"}', returns the decoded
    python characters in order as they become available: 'import ya' then 'ml\n'.

    Handles JSON string escapes (\\n \\t \\" \\\\ \\uXXXX) incrementally.
    Does NOT attempt to parse the full JSON structure — it's a targeted
    field extractor that seeks the opening of "<field_name>":" and then
    decodes the string body chunk by chunk until the closing unescaped ".
    """

    def __init__(self, field: str = "code") -> None:
        self._field = field
        self._seek_needle = f'"{field}"'
        self._buf = ""          # unprocessed chars
        self._state = "seek"   # seek | after_colon | before_open_quote | in_string | unicode_escape | done
        self._escape_next = False
        self._unicode_buf = ""

    def feed(self, chunk: str) -> str:
        """Append chunk, return any newly-decoded field characters."""
        if self._state == "done":
            return ""
        self._buf += chunk
        return self._drain()

    def _drain(self) -> str:
        out: list[str] = []
        needle = self._seek_needle

        while True:
            if self._state == "seek":
                pos = self._buf.find(needle)
                if pos == -1:
                    # Keep last len(needle)-1 chars for cross-chunk matching
                    keep = len(needle) - 1
                    if len(self._buf) > keep:
                        self._buf = self._buf[-keep:]
                    break
                self._buf = self._buf[pos + len(needle):]
                self._state = "after_colon"

            elif self._state == "after_colon":
                # consume whitespace then expect ':'
                moved = False
                while self._buf:
                    ch = self._buf[0]
                    self._buf = self._buf[1:]
                    if ch in ' \t\n\r':
                        continue
                    if ch == ':':
                        self._state = "before_open_quote"
                        moved = True
                        break
                    else:
                        # unexpected char, bail back to seek
                        self._state = "seek"
                        moved = True
                        break
                if not moved:
                    break  # need more data

            elif self._state == "before_open_quote":
                moved = False
                while self._buf:
                    ch = self._buf[0]
                    self._buf = self._buf[1:]
                    if ch in ' \t\n\r':
                        continue
                    if ch == '"':
                        self._state = "in_string"
                        moved = True
                        break
                    else:
                        self._state = "seek"
                        moved = True
                        break
                if not moved:
                    break

            elif self._state == "in_string":
                while self._buf:
                    ch = self._buf[0]
                    self._buf = self._buf[1:]
                    if self._escape_next:
                        self._escape_next = False
                        if ch == 'u':
                            self._state = "unicode_escape"
                            self._unicode_buf = ""
                            break  # handle in unicode branch
                        elif ch == 'n':
                            out.append('\n')
                        elif ch == 't':
                            out.append('\t')
                        elif ch == 'r':
                            out.append('\r')
                        elif ch == '"':
                            out.append('"')
                        elif ch == '\\':
                            out.append('\\')
                        elif ch == '/':
                            out.append('/')
                        elif ch == 'b':
                            out.append('\b')
                        elif ch == 'f':
                            out.append('\f')
                        else:
                            out.append(ch)
                    elif ch == '\\':
                        self._escape_next = True
                    elif ch == '"':
                        self._state = "done"
                        return "".join(out)
                    else:
                        out.append(ch)
                else:
                    break  # need more data; stay in in_string

            elif self._state == "unicode_escape":
                while self._buf:
                    ch = self._buf[0]
                    self._buf = self._buf[1:]
                    self._unicode_buf += ch
                    if len(self._unicode_buf) == 4:
                        try:
                            out.append(chr(int(self._unicode_buf, 16)))
                        except ValueError:
                            out.append(self._unicode_buf)
                        self._unicode_buf = ""
                        self._state = "in_string"
                        break
                else:
                    break  # need more data

            elif self._state == "done":
                break

        return "".join(out)
