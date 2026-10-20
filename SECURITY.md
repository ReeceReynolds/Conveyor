# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/ReeceReynolds/Conveyor/security/advisories/new).

Include a description, reproduction steps and the affected version. You should receive an
acknowledgement within 5 working days. Fixes are released as a patch version and disclosed in a
published advisory once a release is available.

## Supported versions

Conveyor is pre-1.0. Only the latest release receives security fixes.

## Threat model

Conveyor runs code-executing agents, so containment is a core design concern. The threat model
follows the [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/). Key principles:

- Agents can only use the tools, paths, network access and secrets their Capabilities declare.
- Permissions are enforced by the runtime and sandbox, never by the prompt.
- Agents with file or shell access run in hardened containers with no network by default.
- Credentials are configured per provider and never stored in agent definitions.
