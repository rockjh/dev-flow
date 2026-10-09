"""Explicit requirement inputs; bounded reads, no script execution."""
from __future__ import annotations

import http.client
import socket
import ssl
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from ..core.errors import DevflowError, ExitCode
from ..core.redaction import SENSITIVE_KEY, redact
from .models import ProjectContext, RequirementInput, RequirementSegment, RequirementSnapshot
from .repository import bytes_digest, confined, digest, now, stable_id

MAX_INPUT = 10 * 1024 * 1024


class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "br", "div", "h1", "h2", "h3", "tr"} and not self.hidden:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class SourceReader:
    def __init__(self, context: ProjectContext):
        self.context = context

    def _url(self, value: str):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise DevflowError("INVALID_ARGUMENT", "requirement URL must be credential-free HTTP(S)", ExitCode.ARGUMENT)
        if any(SENSITIVE_KEY.search(key) for key, _ in parse_qsl(parsed.query)):
            raise DevflowError("CREDENTIAL_INVALID", "credentials in requirement URLs are not supported", ExitCode.CREDENTIAL)
        try:
            parsed.port
        except ValueError as exc:
            raise DevflowError("INVALID_ARGUMENT", "invalid requirement URL port", ExitCode.ARGUMENT) from exc
        return parsed

    def _fetch(self, value: str, proxy: bool = False) -> tuple[bytes, bool]:
        initial = self._url(value)
        allowed = (initial.hostname, initial.port or (443 if initial.scheme == "https" else 80))
        current = value
        for redirect in range(4):
            parsed = self._url(current)
            origin = (parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            if origin != allowed or (initial.scheme == "https" and parsed.scheme != "https"):
                raise DevflowError("AUTHORIZATION_REQUIRED", "redirect leaves explicitly authorized origin", ExitCode.UNAUTHORIZED)
            cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            connection = cls("127.0.0.1" if proxy else parsed.hostname, 7890 if proxy else origin[1], timeout=5)
            if proxy and parsed.scheme == "https":
                connection.set_tunnel(parsed.hostname, origin[1])
            path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            if proxy and parsed.scheme == "http":
                path = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
            try:
                connection.connect()
                connection.sock.settimeout(30)
                connection.request("GET", path, headers={"Accept": "text/plain,text/markdown,text/html", "User-Agent": "devflow/sequence-diagram"})
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    if redirect == 3 or not response.getheader("Location"):
                        raise DevflowError("EXTERNAL_UNAVAILABLE", "too many or invalid requirement redirects", ExitCode.UNAVAILABLE)
                    current = urljoin(current, response.getheader("Location"))
                    continue
                if response.status in {401, 403}:
                    raise DevflowError("AUTHORIZATION_REQUIRED", "requirement URL requires an authorized host extraction", ExitCode.UNAUTHORIZED)
                if response.status != 200:
                    raise DevflowError("EXTERNAL_UNAVAILABLE", f"requirement HTTP status {response.status}", ExitCode.UNAVAILABLE)
                media = response.getheader("Content-Type", "text/plain").split(";", 1)[0].lower()
                if media not in {"text/plain", "text/markdown", "text/html", "application/xhtml+xml"}:
                    raise DevflowError("EXTERNAL_UNAVAILABLE", "requirement source is not supported text/HTML", ExitCode.UNAVAILABLE)
                if int(response.getheader("Content-Length", "0")) > MAX_INPUT:
                    raise DevflowError("GATE_FAILED", "requirement input exceeds 10MiB", ExitCode.GATE_FAILED)
                chunks, size, deadline = [], 0, time.monotonic() + 30
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("requirement read deadline")
                    connection.sock.settimeout(remaining) if connection.sock else None
                    chunk = response.read1(min(64 * 1024, MAX_INPUT + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_INPUT:
                        raise DevflowError("GATE_FAILED", "requirement input exceeds 10MiB", ExitCode.GATE_FAILED)
                return b"".join(chunks), media in {"text/html", "application/xhtml+xml"}
            finally:
                connection.close()
        raise AssertionError("unreachable redirect loop")

    def read(self, request: RequirementInput) -> RequirementSnapshot:
        html = False
        locator = "direct-text"
        if request.kind == "file":
            path = Path(request.value).absolute()
            if path.is_relative_to(self.context.project):
                path = confined(path, self.context.project)
            else:
                path = path.resolve()
            if path.suffix.lower() not in {".md", ".txt", ".html", ".htm"}:
                raise DevflowError("EXTERNAL_UNAVAILABLE", "only UTF-8 Markdown, text and HTML files are supported", ExitCode.UNAVAILABLE)
            try:
                if path.stat().st_size > MAX_INPUT:
                    raise DevflowError("GATE_FAILED", "requirement input exceeds 10MiB", ExitCode.GATE_FAILED)
                with path.open("rb") as stream:
                    raw = stream.read(MAX_INPUT + 1)
            except FileNotFoundError as exc:
                raise DevflowError("TARGET_NOT_FOUND", "requirement file does not exist", ExitCode.NOT_FOUND) from exc
            except OSError as exc:
                raise DevflowError("EXTERNAL_UNAVAILABLE", "requirement file cannot be read", ExitCode.UNAVAILABLE) from exc
            locator = str(path)
            html = path.suffix.lower() in {".html", ".htm"}
        elif request.kind == "url":
            parsed = self._url(request.value)
            locator = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            try:
                raw, html = self._fetch(request.value)
            except (ConnectionError, socket.timeout, OSError, http.client.HTTPException):
                # One explicit temporary proxy attempt; never change global settings.
                try:
                    raw, html = self._fetch(request.value, proxy=True)
                except (ConnectionError, OSError, http.client.HTTPException) as exc:
                    raise DevflowError("EXTERNAL_UNAVAILABLE", "requirement network source unavailable", ExitCode.UNAVAILABLE) from exc
        elif request.kind == "text":
            raw = request.value.encode("utf-8")
        else:
            raise DevflowError("INVALID_ARGUMENT", "unknown requirement input kind", ExitCode.ARGUMENT)
        if len(raw) > MAX_INPUT:
            raise DevflowError("GATE_FAILED", "requirement input exceeds 10MiB", ExitCode.GATE_FAILED)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DevflowError("EXTERNAL_UNAVAILABLE", "requirement source must be UTF-8", ExitCode.UNAVAILABLE) from exc
        if html:
            parser = _TextHTML()
            parser.feed(text)
            text = "".join(parser.parts)
        text = redact(text).strip()
        if not text:
            raise DevflowError("GATE_FAILED", "requirement source has no readable content", ExitCode.GATE_FAILED)
        if "[REDACTED]" in text:
            raise DevflowError("GATE_FAILED", "requirement redaction removed potentially required semantics; supply an authorized sanitized source", ExitCode.GATE_FAILED)
        # Each nonempty line is a candidate, including list items; blanks are anchors only.
        segments = tuple(RequirementSegment(stable_id("E", locator, index, line.strip()), f"line:{index}", line.strip(), digest(line.strip()))
                         for index, line in enumerate(text.splitlines(), 1) if line.strip())
        return RequirementSnapshot(request.kind, redact(locator), redact(request.source_anchor or locator), now(),
                                   bytes_digest(raw), digest((text, segments)), text, segments)
