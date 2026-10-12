# Security Policy

## Our Commitment

Security is a first-class concern in `local-ai-core`. The system is designed to run
entirely on infrastructure its operator controls: documents, conversations, embeddings
and model weights stay on the local machine unless an operator explicitly enables an
external provider. The API is protected by key-based authentication, secrets are kept
out of source control and loaded only from the environment, and personal data captured
from Discord can be reviewed and permanently erased on request. Retrieval behaviour is
tested against adversarial prompts, and changes pass an automated test suite before
they are released. Security for the project is led by
**Bùi Tiến Dũng**, who owns the vulnerability response process from first report to
published fix.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.3.x   | :white_check_mark: |
| < 1.3   | :x:                |

## Reporting a Vulnerability

Please **do not** open a public issue for security problems. Instead, report them
privately through one of these channels:

- GitHub's [private vulnerability reporting](https://github.com/BuiTienDunghe/Un/security/advisories/new)
- Email: **btndung06@gmail.com**, with the subject line `[SECURITY] local-ai-core`

A useful report includes the affected version or commit, the component involved
(API, Discord bot, ingestion, retrieval), steps to reproduce, and the impact you observed.

## What to Expect

| Stage                        | Target time         |
| ---------------------------- | ------------------- |
| Acknowledgement of report    | within 72 hours     |
| Initial assessment           | within 7 days       |
| Fix or mitigation for critical issues | within 30 days |

Reporters are kept informed throughout, and credited in the release notes unless they
prefer to remain anonymous. We ask that you allow time for a fix to be released before
any public disclosure.
