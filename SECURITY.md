# Security Policy

## Supported versions

The latest released version on PyPI receives fixes.

## Reporting a vulnerability

Please report security issues privately via GitHub's **Report a vulnerability**
(repository → Security → Advisories → "Report a vulnerability"), rather than a
public issue. We'll acknowledge within a few days and keep you updated on a fix.

## Notes on running untrusted code

Selfsame executes the target project's code and tests in order to capture inputs
and replay versions. Run it only against code you trust, in an environment you
control (CI runner, container, or sandbox). Replay happens in isolated
subprocesses, but it is *not* a security sandbox against hostile code.
