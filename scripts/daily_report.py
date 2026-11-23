#!/usr/bin/env python3
"""Send the daily portfolio report: unique visitors and CV downloads.

Everything personal (API token, SMTP credentials, addresses) is read from
environment variables, so no address or credential lives in this repository.
Only the Python standard library is used.

Reporting day = the previous full calendar day in Asia/Manila (UTC+8), sent as
a UTC window to the GoatCounter API.
"""

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")
CV_EVENT = "cv-download"
ATTEMPTS = 3  # first try plus two retries
RETRY_DELAY = 5  # seconds between retries
TIMEOUT = 30  # seconds per network call
STALE_DAYS = 45
STALE_WARNING = (
    "No repository activity for {days} days. GitHub can disable scheduled "
    "workflows after 60 days without activity. Push a small commit to keep "
    "this report running."
)
FOOTER_NOTE = "Counts are approximate; visitors using ad blockers are not counted."


class ConfigError(RuntimeError):
    """A required environment variable is missing or unusable."""


class StepError(RuntimeError):
    """A step failed after its retries; the message never contains secrets."""


def env(name, required=True):
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise ConfigError("missing required environment variable: " + name)
    return value


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url, headers, step):
    """GET a JSON document, retrying twice with a short delay."""
    last = None
    for attempt in range(ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            last = exc
            if attempt < ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    code = getattr(last, "code", None)
    raise StepError(step + " failed" + (" (HTTP " + str(code) + ")" if code else ""))


def goatcounter_base():
    site = env("GOATCOUNTER_SITE").rstrip("/")
    parsed = urllib.parse.urlsplit(site if "//" in site else "//" + site)
    host = (parsed.netloc or parsed.path).strip("/")
    if not host:
        raise ConfigError("GOATCOUNTER_SITE is empty")
    if "." not in host:
        host = host + ".goatcounter.com"
    return "https://" + host + "/api/v0"


def gc_get(path, params):
    query = urllib.parse.urlencode(params, doseq=True)
    return http_json(
        goatcounter_base() + path + "?" + query,
        {
            "Authorization": "Bearer " + env("GOATCOUNTER_TOKEN"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        "GoatCounter stats request",
    )


def report_window(now=None):
    """Return the previous Manila day plus the 7-day window, in UTC."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(MANILA).date()
    day = today - timedelta(days=1)
    start_local = datetime.combine(day, dtime(0, 0), MANILA)
    end_local = start_local + timedelta(days=1)  # exclusive
    return {
        "day": day,
        "start": start_local.astimezone(timezone.utc),
        "end": end_local.astimezone(timezone.utc),
        "week_start": (start_local - timedelta(days=6)).astimezone(timezone.utc),
    }


def fetch_counts(start, end):
    """Return (visitors, cv_downloads) for a UTC window.

    ``total`` counts visitor sessions and includes event sessions, so the
    event sessions are removed to leave page visitors. The event's own count
    comes from the per-path statistics.
    """
    totals = gc_get("/stats/total", {"start": iso(start), "end": iso(end)})
    try:
        total = int(totals["total"])
        events = int(totals.get("total_events") or 0)
    except (KeyError, TypeError, ValueError):
        raise StepError("GoatCounter stats response was not in the expected shape")

    hits = gc_get("/stats/hits", {"start": iso(start), "end": iso(end), "limit": 100})
    rows = hits.get("hits")
    if not isinstance(rows, list):
        raise StepError("GoatCounter hits response was not in the expected shape")

    downloads = 0
    for row in rows:
        if str(row.get("path", "")).lstrip("/") == CV_EVENT:
            downloads += int(row.get("count") or 0)
    return max(0, total - events), downloads


def repo_staleness_days(now):
    """Days since the latest commit on the default branch, or None if unknown."""
    token = env("GITHUB_TOKEN", required=False)
    repo = env("GITHUB_REPOSITORY", required=False)
    if not token or not repo:
        return None
    data = http_json(
        "https://api.github.com/repos/" + repo + "/commits?per_page=1",
        {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-daily-report",
        },
        "GitHub commit lookup",
    )
    try:
        stamp = data[0]["commit"]["committer"]["date"]
        committed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (IndexError, KeyError, TypeError, ValueError):
        raise StepError("GitHub commit lookup returned an unexpected shape")
    return max(0, (now - committed).days)


def plural(count, word):
    return word if count == 1 else word + "s"


def build_report(day, visitors, downloads, week_visitors, week_downloads, stale_days):
    subject = "Portfolio report: {} | {} {}, {} CV {}".format(
        day.strftime("%d %b %Y"),
        visitors,
        plural(visitors, "visitor"),
        downloads,
        plural(downloads, "download"),
    )
    warn = stale_days is not None and stale_days > STALE_DAYS
    warning_text = STALE_WARNING.format(days=stale_days) if warn else ""

    lines = []
    if warn:
        lines.extend([warning_text, ""])
    lines.extend(
        [
            "Portfolio report - " + day.strftime("%d %b %Y"),
            "",
            "Visitors: " + str(visitors),
            "CV downloads: " + str(downloads),
            "",
            "Last 7 days: {} {}, {} CV {}".format(
                week_visitors,
                plural(week_visitors, "visitor"),
                week_downloads,
                plural(week_downloads, "download"),
            ),
            "",
            FOOTER_NOTE,
        ]
    )
    text = "\n".join(lines) + "\n"

    warning_html = ""
    if warn:
        warning_html = (
            '<p style="margin:0 0 22px;padding:12px 14px;border-radius:8px;'
            "background:#fdf3e3;border:1px solid #ecd2a6;color:#6b4a12;"
            'font-size:14px;line-height:1.55;">' + warning_text + "</p>"
        )

    html = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Portfolio report</title></head>
<body style="margin:0;padding:24px 12px;background:#f2f2ef;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1b1b1b;">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e3e3df;border-radius:12px;padding:28px;">
{warning}<p style="margin:0 0 4px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b6b66;">Portfolio report</p>
<p style="margin:0 0 26px;font-size:20px;font-weight:600;line-height:1.3;">{day}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="50%" style="padding:0 12px 0 0;vertical-align:top;">
<div style="font-size:36px;line-height:1.05;font-weight:700;">{visitors}</div>
<div style="margin-top:6px;font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:#6b6b66;">Visitors</div>
</td>
<td width="50%" style="padding:0 0 0 12px;vertical-align:top;">
<div style="font-size:36px;line-height:1.05;font-weight:700;">{downloads}</div>
<div style="margin-top:6px;font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:#6b6b66;">CV downloads</div>
</td>
</tr>
</table>
<p style="margin:26px 0 0;font-size:14px;line-height:1.55;color:#3c3c38;">Last 7 days: {week_visitors} {week_visitors_word}, {week_downloads} CV {week_downloads_word}</p>
<p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #ecece8;font-size:12px;line-height:1.55;color:#7a7a74;">{footer}</p>
</div>
</body>
</html>
""".format(
        warning=warning_html,
        day=day.strftime("%d %b %Y"),
        visitors=visitors,
        downloads=downloads,
        week_visitors=week_visitors,
        week_visitors_word=plural(week_visitors, "visitor"),
        week_downloads=week_downloads,
        week_downloads_word=plural(week_downloads, "download"),
        footer=FOOTER_NOTE,
    )
    return subject, text, html


def deliver(subject, text, html):
    """Send one message over TLS with certificate verification on."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = env("REPORT_FROM")
    message["To"] = env("REPORT_TO")
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    host = env("SMTP_HOST")
    port = int(env("SMTP_PORT") or "587")
    context = ssl.create_default_context()

    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=TIMEOUT)
    try:
        if port != 465:
            client.starttls(context=context)
        client.login(env("SMTP_USER"), env("SMTP_PASS"))
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            try:
                client.close()
            except Exception:
                pass


def send(subject, text, html):
    last = None
    for attempt in range(ATTEMPTS):
        try:
            deliver(subject, text, html)
            return
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            last = exc
            if attempt < ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    raise StepError("email send failed (" + type(last).__name__ + ")")


def send_failure_notice(step):
    """Best-effort short notice; never includes a credential or a stack trace."""
    subject = "Portfolio report failed: " + step
    text = (
        "The daily portfolio report did not run.\n\n"
        "Failing step: " + step + "\n\n"
        "Open the workflow log in GitHub Actions for details. No credentials are included in this message.\n"
    )
    html = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1b1b1b;\">"
        '<p style="margin:0 0 8px;font-size:18px;font-weight:600;">The daily portfolio report did not run.</p>'
        '<p style="margin:0 0 8px;font-size:14px;">Failing step: <strong>' + step + "</strong></p>"
        '<p style="margin:0;font-size:13px;color:#6b6b66;">Open the workflow log in GitHub Actions for details. '
        "No credentials are included in this message.</p></body></html>"
    )
    try:
        deliver(subject, text, html)
        print("Sent a failure notice.", file=sys.stderr)
    except Exception:
        print("Could not send the failure notice.", file=sys.stderr)


def main():
    dry_run = os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
    now = datetime.now(timezone.utc)
    window = report_window(now)
    last_second = window["end"] - timedelta(seconds=1)

    try:
        visitors, downloads = fetch_counts(window["start"], last_second)
        week_visitors, week_downloads = fetch_counts(window["week_start"], last_second)
    except StepError as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        if not dry_run:
            send_failure_notice(str(exc))
        return 1

    stale_days = None
    try:
        stale_days = repo_staleness_days(now)
    except StepError as exc:
        print("Note: " + str(exc) + "; continuing without the staleness check.", file=sys.stderr)

    subject, text, html = build_report(
        window["day"], visitors, downloads, week_visitors, week_downloads, stale_days
    )

    if dry_run:
        print("Dry run: nothing was sent.")
        print("Subject: " + subject)
        print("To: [redacted]")
        print("")
        print(text)
        print("--- HTML version ---")
        print(html)
        return 0

    try:
        send(subject, text, html)
    except StepError as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        send_failure_notice(str(exc))
        return 1

    print(
        "Report sent for {}: {} visitors, {} CV downloads.".format(
            window["day"].isoformat(), visitors, downloads
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
