# Security Analysis

> Scope: `apps/backend/` — Django settings, views (API endpoints), scrapers, proxy handling

---

## SEC-1 · CRITICAL · Hardcoded `SECRET_KEY` committed to source

**File:** [apps/backend/config/settings.py:49](../../apps/backend/config/settings.py#L49)

```python
SECRET_KEY = 'django-insecure-xnjav(kkizi)fm)3&#v9%tk15#zcue(%f5n0t9x5i8szb9sc7y'
```

The Django secret key is hardcoded and likely in git history. This key signs session cookies, CSRF tokens, password reset links, and all `django.core.signing` values. Anyone with this key can:

- Forge session cookies to authenticate as any user
- Bypass CSRF protection
- Forge password reset tokens

**Fix:**

```python
# settings.py
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable is not set")
```

Add `DJANGO_SECRET_KEY=<generated>` to `.env`. Generate a new key immediately since the current one must be considered compromised:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## SEC-2 · HIGH · All action API endpoints are unauthenticated

**File:** [apps/backend/events/views.py](../../apps/backend/events/views.py)

Every state-mutating API endpoint is decorated with `@csrf_exempt` and has no authentication check. Any anonymous HTTP client on the network can:

| Endpoint | Risk |
|---|---|
| `POST /api/scrapers/<key>/run/` | Trigger any scraper (high CPU, bandwidth, proxy cost) |
| `POST /api/scrapers/run-all/` | Launch all 23 scrapers simultaneously |
| `POST /api/scrapers/runs/<id>/cancel/` | Cancel any active run |
| `POST /api/scrapers/dedup/` | Run the dedup script (database mutations) |
| `POST /api/scripts/<name>/run/` | Execute AI scripts (spend Claude tokens) |
| `POST /api/settings/proxy/` | Disable proxy globally (unproxied scraping) |
| `PATCH /api/organizers/<slug>/` | Change any organizer's status |
| `POST /api/search-queries/` | Create search queries |
| `PATCH/DELETE /api/search-queries/<pk>/` | Modify/delete any search query |

The comments in views.py acknowledge this (`# SECURITY NOTE: This endpoint is unauthenticated intentionally`) and defer to a "Phase 2 roadmap." That deferral is appropriate for an internal dev tool, but it must be documented and the tool must remain strictly internal.

**Mitigations while auth is deferred:**

1. Bind Django to `127.0.0.1` only (never `0.0.0.0`) in the dev/staging environment
2. Add network-level restrictions if deployed to any server accessible externally
3. At minimum, add `SCRAPER_WEBHOOK_SECRET` token validation to the scraper-trigger endpoints

**Longer-term fix:**

```python
from django.contrib.admin.views.decorators import staff_member_required
from functools import wraps

def api_staff_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"error": "Forbidden"}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper
```

---

## SEC-3 · HIGH · `DEBUG = True` hardcoded

**File:** [apps/backend/config/settings.py:53](../../apps/backend/config/settings.py#L53)

```python
DEBUG = True
```

If this settings file is used in production without an environment override, Django exposes full stack traces, source code snippets, and local variables in 500 responses. It also disables `ALLOWED_HOSTS` enforcement.

**Fix:**

```python
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('1', 'true', 'yes')
```

---

## SEC-4 · HIGH · `ALLOWED_HOSTS` locked to localhost

**File:** [apps/backend/config/settings.py:54](../../apps/backend/config/settings.py#L54)

```python
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
```

Any production deployment that doesn't override this will serve a 400 to all real traffic. The `ALLOWED_HOSTS` setting is a security mechanism (prevents HTTP Host header injection) and must be configured for the real hostname(s).

**Fix:**

```python
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
```

---

## SEC-5 · HIGH · `--ignore-certificate-errors` passed to Chromium globally when using free proxies

**File:** [apps/backend/events/scrapers/facebook_events.py:795](../../apps/backend/events/scrapers/facebook_events.py#L795)

```python
if proxy:
    launch_kwargs["proxy"] = proxy
    launch_kwargs["args"].append("--ignore-certificate-errors")
```

When a free proxy is used, SSL certificate verification is disabled for the entire Chromium session. This means:

- A malicious free proxy can perform a Man-in-the-Middle attack on all traffic, including Facebook session data and any credentials that flow through the browser
- Even though these scrapers don't use Facebook credentials, any cookies, session tokens, or event data returned can be intercepted

Free public proxy lists (from GitHub) are an untrusted, potentially adversarial network. Operating without certificate verification through them is a meaningful attack surface.

**Mitigations:**
- Only disable cert errors when `_is_free_proxy()` is True (current behavior — correct)
- Document that free proxies should be used only for non-sensitive scraping
- Prefer DataImpulse (authenticated residential) which does not require cert bypass

---

## SEC-6 · MEDIUM · Free public proxy list sourced from unauthenticated GitHub repos

**File:** [apps/backend/events/scrapers/proxy_manager.py:35-42](../../apps/backend/events/scrapers/proxy_manager.py#L35-L42)

```python
_PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ...
]
```

These GitHub repositories are maintained by unknown third parties. The proxy entries can be:

- **Honeypots** operated by threat actors collecting scraped data
- **Interceptors** logging all plaintext (HTTP) traffic
- **Unreliable** (99%+ failure rate is typical for public proxy lists)

Any data transmitted through these proxies (URLs visited, page content, IP of the scraper host) may be logged. For the Facebook scraper this includes all event page URLs, which could reveal what the system is tracking.

**Recommendation:**
- Treat free proxies as a best-effort last resort only
- Never use free proxies for scrapers that handle credentials or PII
- Consider rotating DataImpulse plans as the primary proxy tier and removing free proxy fallback entirely for Facebook

---

## SEC-7 · MEDIUM · `SCRAPER_WEBHOOK_SECRET` read at module import time

**File:** [apps/backend/events/views.py:1055](../../apps/backend/events/views.py#L1055)

```python
_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")
```

The webhook secret is captured at module load. If the environment variable is set after Django starts (or is changed at runtime), the in-memory value does not update. More critically, when `_WEBHOOK_SECRET` is empty (not set), the webhook guard rejects **all** requests:

```python
if not _WEBHOOK_SECRET or key != _WEBHOOK_SECRET:
    return JsonResponse({"error": "unauthorized"}, status=401)
```

The `not _WEBHOOK_SECRET` check correctly blocks when the secret is unset. However this means the feature is silently off with no warning log when `SCRAPER_WEBHOOK_SECRET` is missing. Add a startup warning:

```python
import warnings
_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")
if not _WEBHOOK_SECRET:
    warnings.warn(
        "SCRAPER_WEBHOOK_SECRET is not set — /webhooks/ endpoints will reject all requests",
        RuntimeWarning,
        stacklevel=2,
    )
```

---

## SEC-8 · LOW · No CORS configuration

The Django backend exposes a JSON API consumed by the SvelteKit frontend. In development, the Vite dev server proxies `/api/*` to Django, so browser CORS checks are never triggered. In any other deployment topology (e.g., frontend served from a CDN, separate domains), the browser would block all API calls.

There is no `django-cors-headers` in the installed apps. Production deployment requires:

```python
INSTALLED_APPS = [..., 'corsheaders']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware', ...rest...]
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
```
