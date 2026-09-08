# Security

## Reporting

Report suspected vulnerabilities privately to the repository owner. Do not open a public issue containing credentials, exploit details, or personal data.

## Assessment — version 1.1.0

The application was reviewed for OWASP-style web risks, deployment weaknesses, dependency exposure, and unsafe update behavior.

### Findings fixed

- **Login throttle bypass by username rotation:** rate limiting now enforces both five failures per IP/username pair and 20 total failures per IP in 15 minutes.
- **Cross-site request defense in depth:** state-changing requests with an `Origin` header are rejected unless the origin matches the validated host, in addition to mandatory CSRF tokens.
- **Browser isolation hardening:** CSP now restricts base URLs, forms, and plugins; COOP, CORP, and cross-domain-policy denial headers were added.
- **Session-cookie hardening:** HTTPS deployments use a `__Host-` prefixed cookie, preventing Domain scoping and requiring a secure host-only cookie.
- **Visitor-data protection:** IP/ISP data is admin-only, automatically expires after a bounded retention period, and is disclosed on the public footer.
- **CSV injection prevention:** exported visitor fields that could be interpreted as spreadsheet formulas are neutralized.
- **ISP lookup isolation:** lookups use validated IP literals, a fixed HTTPS provider host, strict timeouts, bounded response fields, and background execution.
- **Server fingerprint reduction:** generated nginx configuration disables version tokens.
- **Brute-force login attempts:** added persistent per-IP and per-username throttling, bounded inputs, cleanup, and constant-work password verification for unknown users.
- **Stored script injection risk in admin confirmations:** removed inline JavaScript containing location data. Confirmations now use a same-origin static script and constant messages compatible with the strict CSP.
- **Sensitive-page caching:** admin responses now send `Cache-Control: no-store` and `Pragma: no-cache`.
- **Host-header protection:** deployments can set `TRUSTED_HOSTS`; the installer restricts it to the configured domain or server addresses.
- **Password resource abuse:** password processing is bounded to 256 characters while preserving the 12-character minimum and scrypt hashing.
- **Username ambiguity:** administrator names are constrained to a conservative allowlist.
- **Forecast rendering:** all provider and database strings are HTML-escaped and numeric values are validated before DOM insertion.

### Existing controls verified

- One-time, database-enforced administrator registration
- Scrypt password hashing
- Session rotation after authentication, HttpOnly/SameSite/Secure cookie options, and 30-minute lifetime
- CSRF tokens on every state-changing request
- Parameterized SQL, server-side coordinate/length validation, and authorization checks on location edits
- Strict CSP, anti-framing, MIME-sniffing prevention, referrer and permissions policies, and HSTS over HTTPS
- Unprivileged systemd service with filesystem sandboxing
- Fast-forward-only updater with fixed command arguments, explicit opt-in, atomic recovery metadata, and rollback restricted to the recorded ancestor commit
- No GitHub token or weather API secret stored in source

### Operational considerations

Use HTTPS, keep Ubuntu and Python dependencies patched, protect the server account and deploy key, back up `/var/lib/weatherwatch`, and leave web updates disabled unless required. A compromised upstream repository can deliver code through any automatic updater; protect the GitHub account with MFA and use least-privilege repository credentials.
