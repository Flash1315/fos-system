# Fos harden pack ledger

One line per shipped pack after 0.7.230. Format: `VERSION | area | summary`

Baseline: 0.7.230
0.7.231 | main.py | send X-Permitted-Cross-Domain-Policies on every response
0.7.232 | main.py | deny API resource loading with default-src none CSP
0.7.233 | main.py | send Pragma no-cache on API responses
0.7.234 | main.py | send an immediate Expires value on API responses
0.7.235 | main.py | centralize security headers for normal and error responses
0.7.236 | main.py | reject malformed Content-Length headers
0.7.237 | main.py | buffer streamed request chunks with a linear-time list join
0.7.238 | config.py | make the JSON request ceiling configurable
0.7.239 | config.py | make the upload request ceiling configurable
0.7.240 | main.py | cap validation errors included in responses
0.7.241 | main.py | cap flattened validation detail length
0.7.242 | main.py | challenge unauthorized metrics requests with Bearer auth
0.7.243 | main.py | rate-limit readiness probes without limiting liveness
0.7.244 | main.py | bound concurrent readiness dependency checks
0.7.245 | config.py | ignore empty environment variables instead of erasing defaults
0.7.246 | config.py | load environment variable names case-insensitively
0.7.247 | config.py | add a configurable media-token lifetime
0.7.248 | email.py | make SMTP connection timeout configurable
0.7.249 | main.py | reject unsupported structured log formats
0.7.250 | main.py | reject unknown logging levels
0.7.251 | main.py | validate database pool recycle bounds
0.7.252 | main.py | validate database pool wait timeout bounds
0.7.253 | main.py | validate database connection timeout bounds
0.7.254 | main.py | require production metrics tokens to contain 32 characters
0.7.255 | main.py | validate SMTP ports before startup
