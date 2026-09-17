# WeatherWatch Security Vulnerability & Performance Assessment

**Target:** `https://weatherwatch.dreampixelmedia.uk`  
**Assessment date:** 17 September 2026 (Asia/Manila)  
**Application reviewed:** WeatherWatch 2.8.4, repository head `b967934`  
**Assessment type:** Non-destructive external review, TLS/HTTP edge checks, source-assisted review, dependency audit, static analysis, and local performance profiling

---

## 1. Executive summary

WeatherWatch has a **good application-security baseline**. The reviewed code uses strong session-cookie settings, CSRF protection, login throttling, parameterized SQL, strict input validation, a restrictive Content Security Policy, authenticated administration, a constrained updater, and fixed/validated weather-provider destinations. The dependency audit found **no known vulnerable Python packages**, Bandit found **no high-severity issues**, and all **33 automated tests passed**.

The largest practical opportunity is **front-end delivery performance**. The static directory is about **2.3 MB**, dominated by nine JPEG weather scenes. The browser currently preloads most weather scenes, potentially transferring roughly 2 MB even before a site is selected. The installer’s nginx configuration also does not explicitly enable long-lived immutable caching or compression for static assets. These issues are likely to have a noticeable impact on mobile connections.

The live site is protected by Cloudflare and returned a Cloudflare **403 challenge/block page to every automated request** from the assessment environment. This prevented direct validation of the origin application’s live headers, authenticated workflows, Core Web Vitals, and actual page payload. The edge itself responded quickly, but those timings measure the 403 response—not the WeatherWatch application.

### Overall assessment

| Area | Rating | Summary |
|---|---|---|
| Application security | **Good** | Strong controls; no confirmed critical/high vulnerability |
| Edge/TLS security | **Good, partially verified** | TLS 1.2/1.3 and valid certificate; HSTS/HTTP redirect not visible on blocked edge responses |
| Dependency security | **Good** | No known vulnerabilities in pinned runtime requirements |
| Update mechanism | **Good with hardening opportunity** | Fixed commands, clean-tree/fast-forward checks, locking and rollback; signed-release verification recommended |
| Performance | **Needs improvement** | Eager image preloading and no explicit nginx static caching/compression |
| Assessment confidence | **Moderate** | Source-assisted review was comprehensive; live application probing was blocked by Cloudflare |

No destructive testing, credential attacks, brute force, data modification, denial-of-service testing, or WAF bypass was attempted.

---

## 2. Scope and methodology

### In scope

- Public home page and static resources
- Public weather and radar API routes
- Unauthenticated behavior of `/admin`
- Authentication/session/CSRF implementation through source review
- Admin update and rollback implementation through source review
- TLS certificate and protocol support at the Cloudflare edge
- HTTP method behavior at the edge
- Python dependency vulnerabilities
- Static code analysis of `app.py`
- Asset weights and local Flask response timings

### Tools and checks

- `curl` HTTP status, headers, method checks, and connection timing
- OpenSSL certificate and TLS protocol negotiation
- `pip-audit` against `requirements.txt`
- Bandit static security analysis
- Git tracked-secret pattern scan
- Pytest application test suite
- Flask test-client header and response profiling
- Static asset inventory and byte-size analysis

### External-testing limitation

Cloudflare returned status **403** with a roughly **5,027-byte challenge/block response** for `/`, `/admin`, APIs, static assets, and common sensitive paths. Consequently, this assessment could not reliably inspect the live origin response body or origin-generated headers. Findings explicitly identify when evidence comes from source/local testing rather than the live edge.

---

## 3. Findings summary

| ID | Severity | Finding | Status |
|---|---|---|---|
| PERF-01 | High (performance) | Weather-scene images are eagerly preloaded, creating a large initial transfer | Open |
| PERF-02 | Medium (performance) | Installer nginx config lacks explicit static compression and immutable cache policy | Open |
| SEC-01 | Medium | HSTS and unconditional HTTP-to-HTTPS redirect could not be confirmed on Cloudflare-generated responses | Verify/configure at edge |
| SEC-02 | Low–Medium | Provider JSON bodies are parsed without explicit response-size limits | Open |
| SEC-03 | Low–Medium | Web updater trusts the configured Git remote without signed-release verification | Hardening opportunity |
| OPS-01 | Low–Medium | Cloudflare blocks synthetic monitoring/scanning from this assessment source | Review policy |
| PRIV-01 | Low | Raw visitor IP, ISP, user-agent, and visit history are retained | Accepted feature; governance needed |
| INFO-01 | Informational | Bandit flags fixed outbound URLs, updater subprocess usage, dummy password hash, and development bind address | Reviewed; mostly false-positive/accepted |

No confirmed SQL injection, command injection, reflected/stored XSS, CSRF bypass, authentication bypass, open redirect, exposed secret file, directory traversal, or SSRF was identified in the reviewed source.

---

## 4. Detailed security findings

### SEC-01 — Edge HTTPS policy is not fully visible

**Severity:** Medium  
**Evidence:**

- The HTTPS certificate is valid and covers `dreampixelmedia.uk` and `*.dreampixelmedia.uk`.
- Issuer: Google Trust Services WE1.
- Valid from 28 August 2026 through 26 November 2026.
- TLS 1.2 negotiated `ECDHE-ECDSA-CHACHA20-POLY1305`.
- TLS 1.3 negotiated `TLS_AES_256_GCM_SHA384`.
- Legacy TLS 1.0 and 1.1 were unavailable in the assessment client/environment.
- Requests to both HTTP and HTTPS received Cloudflare 403 responses.
- The Cloudflare-generated 403 did not include `Strict-Transport-Security`.

**Risk:** A browser’s first request over HTTP may not be upgraded as early as possible if Cloudflare “Always Use HTTPS” and edge HSTS are not enabled. Application-level HSTS is present in source for secure requests, but Cloudflare-generated responses may bypass it.

**Recommendation:**

1. Enable **Always Use HTTPS** in Cloudflare.
2. Enable edge **HSTS** only after verifying every required subdomain supports HTTPS.
3. Suggested policy: `max-age=31536000; includeSubDomains`; add `preload` only after satisfying preload requirements and confirming long-term commitment.
4. Verify that Cloudflare SSL/TLS mode is **Full (strict)**.
5. Re-test both normal content and Cloudflare challenge/error responses.

---

### SEC-02 — Outbound provider responses have no explicit body-size ceiling

**Severity:** Low–Medium  
**Affected integrations:** Open-Meteo/ECMWF, RainViewer metadata, and `ipwho.is` ISP lookup.

**Evidence:** Each destination has a timeout and is either fixed or derived from a validated IP address, which substantially limits SSRF risk. However, responses are passed directly to `json.load(response)` without reading through a maximum-size guard.

**Risk:** A compromised or malfunctioning upstream provider could return an unexpectedly large JSON body and increase process memory consumption.

**Recommendation:** Add a shared JSON-fetch helper that:

- permits HTTPS only;
- allowlists the exact destination host;
- rejects redirects to an unapproved host;
- checks `Content-Length` when supplied;
- reads no more than a configured maximum (for example, 1–5 MB depending on endpoint);
- validates JSON type/schema before processing.

---

### SEC-03 — Updater authenticity depends on Git remote integrity

**Severity:** Low–Medium  
**Evidence:** The updater has several strong controls:

- fixed command arguments and `shell=False`;
- refuses dirty staged or unstaged trees;
- fetches a fixed remote and branch;
- performs fast-forward-only merges;
- uses an atomic cross-worker lock;
- records exact rollback metadata;
- authenticates update/status routes and applies CSRF checks to update requests.

It does not independently require signed commits/tags or compare a release digest to a separately trusted value.

**Risk:** If the GitHub account, repository, deploy credential, DNS/trust path, or configured Git remote is compromised, malicious code could be accepted as a valid fast-forward update.

**Recommendation:**

- Deploy only signed release tags and verify the signing key locally.
- Alternatively, verify a release manifest/hash signed by an offline key.
- Keep the repository credential read-only on production.
- Protect GitHub with phishing-resistant MFA, branch protection, required review, and secret scanning.
- Rotate the previously exposed GitHub token if that has not already been completed.

---

### OPS-01 — Cloudflare policy blocks synthetic assessment traffic

**Severity:** Low–Medium operational risk  
**Evidence:** Every tested path returned Cloudflare 403, including `/`, `/admin`, `/api/weather`, `/api/radar`, static files, `/.env`, and `/.git/config`.

**Interpretation:** This may be an intentional bot/WAF rule, not an application defect. It is useful against automated abuse but can also block uptime monitoring, accessibility crawlers, search indexing, and legitimate API clients.

**Recommendation:**

- Review Cloudflare Security Events for the assessment timestamp.
- Keep strict rules for `/admin` and mutation routes.
- Consider a narrowly scoped allow rule for trusted uptime-monitor IPs or a dedicated health endpoint.
- Do not broadly disable bot protection.
- Ensure `/static/*` and the public home page are not challenged for normal browsers unless intentional.

---

### PRIV-01 — Visitor analytics store personal/network identifiers

**Severity:** Low security / privacy governance issue  
**Evidence:** The application stores visitor IP address, ISP, user-agent, first/last seen time, request counts, and timestamped visitor events. Access and CSV export are administrator-only, and retention cleanup exists.

**Recommendation:**

- Document the operational purpose and lawful basis.
- Keep retention to the minimum needed.
- Restrict database backups and exports.
- Record export events in an admin audit log.
- Consider truncating or keyed-hashing older IP records if exact addresses are not operationally necessary.
- Publish a concise privacy notice appropriate to the deployment jurisdiction.

---

## 5. Positive security controls confirmed in source

- One-time administrator registration.
- Scrypt password hashing through Werkzeug.
- Constant-work dummy password hash to reduce username-enumeration timing leakage.
- Login throttling by IP+username and aggregate IP attempts.
- Secure, HttpOnly, SameSite=Lax session cookies in production configuration.
- Thirty-minute permanent-session lifetime.
- CSRF token required for POST/PUT/PATCH/DELETE.
- Origin/host comparison for state-changing requests when an Origin header is present.
- Parameterized SQLite statements.
- Numeric bounds and length validation for admin-managed locations and matrix values.
- CSP with `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, and `frame-ancestors 'none'`.
- `X-Content-Type-Options: nosniff`.
- `X-Frame-Options: DENY`.
- `Referrer-Policy: strict-origin-when-cross-origin`.
- Camera, microphone, and geolocation disabled through Permissions Policy.
- COOP and CORP isolation headers.
- Admin/API responses explicitly marked no-store/no-cache.
- Fixed RainViewer host and validated radar paths; no open tile proxy.
- External provider requests use timeouts.
- Web updater uses `shell=False`, fixed arguments, clean-tree checks, fast-forward-only merge, update locking, and exact rollback metadata.
- nginx `server_tokens off` and 64 KB request-size ceiling in the installer.
- `.env` and `.git/config` return 404 in local application routing; the Cloudflare edge blocked them externally.
- No tracked GitHub PAT/private-key pattern found.

---

## 6. Static-analysis review

Bandit scanned approximately 807 lines of Python code and reported:

- **0 high-severity issues**
- **4 medium-severity warnings**
- **3 low-severity warnings**

### Warning disposition

| Bandit warning | Disposition |
|---|---|
| `urllib.request.urlopen` scheme warning | Destinations are fixed HTTPS URLs, or a validated IP inserted into a fixed HTTPS host. Not exploitable as ordinary user-controlled SSRF; add centralized allowlisting/body limits for defense in depth. |
| `subprocess` import/call | Updater uses `shell=False` and fixed server-side command lists. No request value becomes a command argument. Accepted with signed-update recommendation. |
| Hardcoded password string | This is a deliberately invalid dummy hash used for constant-work login checks, not a real credential. False positive. |
| Bind to `0.0.0.0` | Development entry point only; production is expected behind Gunicorn/nginx. Ensure port 8000 remains firewalled and Gunicorn binds loopback as installed. |

---

## 7. Dependency and test results

### Runtime dependencies

- Flask 3.1.3
- Gunicorn 23.0.0

`pip-audit -r requirements.txt` result:

> No known vulnerabilities found

Application test result:

> 33 passed in 5.35s

These results are point-in-time checks, not a guarantee against undisclosed vulnerabilities. Automate dependency auditing in CI and enable Dependabot/Renovate.

---

## 8. Performance assessment

### PERF-01 — Eager weather-scene loading

**Severity:** High performance impact  
**Evidence:** Static assets total approximately **2.3 MB**. The JavaScript preloads most weather-scene JPEGs during startup.

Largest files:

| Asset | Approx. size |
|---|---:|
| `weather/rainy.jpg` | 451 KB |
| `weather/drizzle.jpg` | 353 KB |
| `weather/partly-cloudy.jpg` | 254 KB |
| `weather/showers.jpg` | 211 KB |
| `weather/overcast.jpg` | 182 KB |
| `weather/sunny.jpg` | 174 KB |
| `weather/cloudy.jpg` | 156 KB |
| `weather/storm.jpg` | 139 KB |
| `weather/foggy.jpg` | 90 KB |
| Leaflet JavaScript | 144 KB |
| Application CSS | 35 KB |
| Application JavaScript | 17 KB |

**Risk:** On a mobile connection, eager image downloads can delay meaningful content, consume bandwidth, compete with map/weather requests, and increase memory use.

**Recommendation:**

1. Load only the default scene initially.
2. Lazy-load a site’s scene after the user selects that site.
3. Optionally idle-preload only the most likely next scene after first interaction.
4. Convert scenes to WebP and AVIF with JPEG fallback.
5. Provide viewport-appropriate variants rather than always serving full-resolution images.
6. Target 100–180 KB per full-screen scene where quality allows.
7. Add explicit image dimensions/aspect treatment where images enter document layout.

Estimated opportunity: avoid roughly **1.5–2.0 MB** of unnecessary initial transfer.

---

### PERF-02 — No explicit nginx static cache/compression policy

**Severity:** Medium performance impact  
**Evidence:** The installer proxies all paths to Gunicorn. Its generated nginx block does not define a dedicated `/static/` location, gzip/brotli policy, or long-lived asset caching.

**Risk:** Static files may repeatedly traverse Gunicorn and may not receive optimal compression/cache headers. Cloudflare may mitigate this, but live headers could not be inspected due to the 403 challenge.

**Recommendation:** Configure nginx to serve versioned static files directly, for example:

```nginx
location /static/ {
    alias /opt/weatherwatch/static/;
    access_log off;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
}

gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/css application/javascript application/json image/svg+xml;
```

Because application CSS/JS URLs include the application version, long-lived immutable caching is appropriate after confirming every deploy changes the version. Configure Brotli at Cloudflare if available.

---

### Local application timings

Ten local Flask test-client requests produced:

| Route | Median | Maximum | Notes |
|---|---:|---:|---|
| `/` | 1.71 ms | 24.10 ms | Server-side template generation only |
| `/admin` | 0.68 ms | 0.84 ms | Unauthenticated redirect |
| `/api/weather` | 5.33 ms | 954.72 ms | Warm cache vs. one provider-backed cold request |
| `/.env` | 0.43 ms | 1.41 ms | 404 |
| `/.git/config` | 0.39 ms | 0.47 ms | 404 |

These timings exclude internet latency, Cloudflare, browser parsing/rendering, map tiles, images, and full production Gunicorn/nginx behavior.

### Cloudflare edge timing

Five blocked HTTPS requests completed in approximately **35–103 ms**, after the first DNS/TLS setup. This indicates responsive Cloudflare edge handling but says nothing about WeatherWatch origin TTFB because all responses were 403 challenge pages.

### Front-end architecture positives

- Application JavaScript is small (~17 KB) and deferred.
- CSS is moderate (~35 KB).
- Leaflet is locally vendored, avoiding a third-party script dependency.
- Weather responses have a five-minute server cache.
- Radar metadata has a five-minute server cache.
- API requests explicitly bypass browser/proxy caches when fresh classifications are needed.
- Background scenes are CSS backgrounds and do not shift document layout.

---

## 9. Prioritized remediation plan

### Priority 1 — Performance quick wins

1. Remove eager loading of all weather scenes.
2. Convert JPEG scenes to WebP/AVIF and reduce dimensions/quality appropriately.
3. Serve `/static/` directly through nginx with immutable caching.
4. Enable gzip at nginx and Brotli at Cloudflare.
5. Confirm Cloudflare cache rules do not cache private/admin/API responses.

### Priority 2 — Edge verification

1. Enable/verify Full (strict) TLS.
2. Enable/verify Always Use HTTPS.
3. Add HSTS at the Cloudflare edge.
4. Review bot/WAF events to ensure normal visitors and monitoring are not blocked.
5. Repeat a live Mozilla Observatory/SecurityHeaders-style scan from an allowed source.

### Priority 3 — Defense in depth

1. Add host/scheme/body-size enforcement to all provider fetches.
2. Verify signed release tags or signed manifests before web updates.
3. Add nginx/Cloudflare rate limiting for expensive API and authentication endpoints.
4. Add administrator audit logging for login, location changes, severity changes, updates, rollback, and visitor export.
5. Automate `pytest`, `pip-audit`, Bandit, secret scanning, and installer syntax checks in GitHub Actions.

### Priority 4 — Measure real-user performance

1. Run Lighthouse from a normal browser session that passes Cloudflare.
2. Record mobile LCP, INP, CLS, TTFB, transferred bytes, and request count.
3. Add Cloudflare Web Analytics or a privacy-appropriate RUM system.
4. Set performance budgets, suggested starting points:
   - LCP ≤ 2.5 s at p75
   - INP ≤ 200 ms at p75
   - CLS ≤ 0.1 at p75
   - Initial compressed transfer ≤ 750 KB
   - Initial requests ≤ 25 excluding map tiles loaded after interaction

---

## 10. Retest checklist

After remediation, verify:

- HTTP redirects to HTTPS before application content.
- HSTS appears on normal, challenge, and error responses.
- TLS remains limited to modern protocol/cipher suites.
- Normal public browsing is not unintentionally challenged.
- `/admin`, APIs, and update-status responses remain `no-store`.
- Static assets receive immutable caching and compression.
- Initial page load does not download unselected weather scenes.
- Provider responses exceeding configured limits are rejected safely.
- Signed/untrusted update tests behave as intended.
- Login throttling works across multiple Gunicorn workers and, if applicable, multiple servers.
- A browser-based authenticated scan finds no CSRF, XSS, access-control, or session-management regressions.
- Lighthouse mobile results meet the established budgets.

---

## 11. Conclusion

No critical or high-severity security vulnerability was confirmed. WeatherWatch’s application controls are stronger than typical small operational dashboards, especially around CSRF, sessions, database access, radar URL validation, and updater restrictions. The most valuable immediate work is performance-oriented: stop eager-loading all scene images, optimize image formats, and add explicit static caching/compression. Edge HTTPS and security-header behavior should then be verified from a Cloudflare-allowed browser or scanner, because the current bot block prevented complete live-origin validation.

This assessment is a point-in-time review, not a guarantee of security. A higher-assurance engagement would include an authorized authenticated test account, temporary WAF allowlisting for the scanner, origin configuration review, database/host permission review, and browser-based dynamic testing.

---

## 12. Remediation update — WeatherWatch 2.9.0

The principal application-level performance recommendations were implemented after this assessment:

- Removed eager JavaScript preloading of all weather scenes.
- Converted all nine cinematic JPEG scenes to WebP.
- Reduced the static directory from approximately 2.3 MB to approximately 1.2 MB.
- Changed initial browser weather responses to include only the next 24 hourly records per site.
- Added a validated, cached, on-demand endpoint for future daily hourly details.
- Changed collapsed hourly panels to create their DOM content only when opened.
- Added direct nginx `/static/` delivery with seven-day browser caching.
- Enabled nginx gzip for CSS, JavaScript, JSON, and SVG.
- Moved visitor-retention deletion work from every public visit to at most once per hour per worker.
- Expanded automated coverage from 33 to 37 tests.

Cloudflare edge configuration recommendations—HSTS, Always Use HTTPS, cache policy verification, and WAF allowlisting for synthetic monitoring—still require review in the Cloudflare dashboard.