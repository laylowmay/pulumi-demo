"""
World Clock — GCP + Pulumi demo.

Reads the ``city`` config key and deploys a Cloud Run v2 service that displays
the current local time(s) for the given city.  Ambiguous queries (e.g.
"Springfield") show a table with every matching city and its local time.

Required stack config
---------------------
city         (string) – city name or partial name, e.g. "Tokyo", "Springfield"

Injected via ESC environment
-----------------------------
gcp:project  (string) – GCP project ID
gcp:region   (string) – GCP region (default: us-central1)
"""

import base64

import pulumi
import pulumi_gcp as gcp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
config = pulumi.Config()
city: str = config.require("city")

gcp_config = pulumi.Config("gcp")
region: str = gcp_config.get("region") or "us-central1"

# ---------------------------------------------------------------------------
# Enable the Cloud Run API
# ---------------------------------------------------------------------------
cloud_run_api = gcp.projects.Service(
    "cloud-run-api",
    service="run.googleapis.com",
    disable_on_destroy=False,
)

# ---------------------------------------------------------------------------
# Inline Python HTTP server — world clock
#
# The script is base64-encoded and passed as an environment variable so we
# can reuse the stock python:3.11-slim image without a custom Dockerfile.
#
# At startup it installs the ``tzdata`` pip package so the slim image has
# full IANA timezone data available for ``zoneinfo``.
# ---------------------------------------------------------------------------
_SERVER_SCRIPT = """\
import sys
import subprocess

# Ensure IANA timezone database is available in the slim image.
subprocess.check_call(
    [sys.executable, '-m', 'pip', 'install', '--quiet', 'tzdata'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

import os
import http.server
import datetime
import zoneinfo

CITY = os.environ.get('CITY', '').strip()

# ---------------------------------------------------------------------------
# City database: (display_name, location_hint, IANA_timezone)
# Multiple entries with the same display_name intentionally model real-world
# ambiguity (e.g. Springfield exists in many US states).
# ---------------------------------------------------------------------------
CITIES = [
    ('Abu Dhabi',         'UAE',              'Asia/Dubai'),
    ('Accra',             'Ghana',            'Africa/Accra'),
    ('Addis Ababa',       'Ethiopia',         'Africa/Addis_Ababa'),
    ('Adelaide',          'Australia',        'Australia/Adelaide'),
    ('Amsterdam',         'Netherlands',      'Europe/Amsterdam'),
    ('Anchorage',         'US-AK',            'America/Anchorage'),
    ('Athens',            'Greece',           'Europe/Athens'),
    ('Atlanta',           'US-GA',            'America/New_York'),
    ('Auckland',          'New Zealand',      'Pacific/Auckland'),
    ('Baghdad',           'Iraq',             'Asia/Baghdad'),
    ('Bangkok',           'Thailand',         'Asia/Bangkok'),
    ('Barcelona',         'Spain',            'Europe/Madrid'),
    ('Beijing',           'China',            'Asia/Shanghai'),
    ('Beirut',            'Lebanon',          'Asia/Beirut'),
    ('Berlin',            'Germany',          'Europe/Berlin'),
    ('Bogota',            'Colombia',         'America/Bogota'),
    ('Brisbane',          'Australia',        'Australia/Brisbane'),
    ('Brussels',          'Belgium',          'Europe/Brussels'),
    ('Bucharest',         'Romania',          'Europe/Bucharest'),
    ('Budapest',          'Hungary',          'Europe/Budapest'),
    ('Buenos Aires',      'Argentina',        'America/Argentina/Buenos_Aires'),
    ('Cairo',             'Egypt',            'Africa/Cairo'),
    ('Calgary',           'Canada-AB',        'America/Edmonton'),
    ('Cape Town',         'South Africa',     'Africa/Johannesburg'),
    ('Casablanca',        'Morocco',          'Africa/Casablanca'),
    ('Chicago',           'US-IL',            'America/Chicago'),
    ('Copenhagen',        'Denmark',          'Europe/Copenhagen'),
    ('Dallas',            'US-TX',            'America/Chicago'),
    ('Denver',            'US-CO',            'America/Denver'),
    ('Detroit',           'US-MI',            'America/Detroit'),
    ('Dhaka',             'Bangladesh',       'Asia/Dhaka'),
    ('Dubai',             'UAE',              'Asia/Dubai'),
    ('Dublin',            'Ireland',          'Europe/Dublin'),
    ('Edmonton',          'Canada-AB',        'America/Edmonton'),
    ('Frankfurt',         'Germany',          'Europe/Berlin'),
    ('Guangzhou',         'China',            'Asia/Shanghai'),
    ('Helsinki',          'Finland',          'Europe/Helsinki'),
    ('Ho Chi Minh City',  'Vietnam',          'Asia/Ho_Chi_Minh'),
    ('Hong Kong',         'Hong Kong',        'Asia/Hong_Kong'),
    ('Honolulu',          'US-HI',            'Pacific/Honolulu'),
    ('Houston',           'US-TX',            'America/Chicago'),
    ('Istanbul',          'Turkey',           'Europe/Istanbul'),
    ('Jakarta',           'Indonesia',        'Asia/Jakarta'),
    ('Johannesburg',      'South Africa',     'Africa/Johannesburg'),
    ('Kabul',             'Afghanistan',      'Asia/Kabul'),
    ('Karachi',           'Pakistan',         'Asia/Karachi'),
    ('Kathmandu',         'Nepal',            'Asia/Kathmandu'),
    ('Kyiv',              'Ukraine',          'Europe/Kyiv'),
    ('Kolkata',           'India',            'Asia/Kolkata'),
    ('Kuala Lumpur',      'Malaysia',         'Asia/Kuala_Lumpur'),
    ('Lagos',             'Nigeria',          'Africa/Lagos'),
    ('Lahore',            'Pakistan',         'Asia/Karachi'),
    ('Lima',              'Peru',             'America/Lima'),
    ('Lisbon',            'Portugal',         'Europe/Lisbon'),
    ('London',            'UK',               'Europe/London'),
    ('Los Angeles',       'US-CA',            'America/Los_Angeles'),
    ('Madrid',            'Spain',            'Europe/Madrid'),
    ('Manila',            'Philippines',      'Asia/Manila'),
    ('Melbourne',         'Australia',        'Australia/Melbourne'),
    ('Mexico City',       'Mexico',           'America/Mexico_City'),
    ('Miami',             'US-FL',            'America/New_York'),
    ('Milan',             'Italy',            'Europe/Rome'),
    ('Minneapolis',       'US-MN',            'America/Chicago'),
    ('Montreal',          'Canada-QC',        'America/Toronto'),
    ('Moscow',            'Russia',           'Europe/Moscow'),
    ('Mumbai',            'India',            'Asia/Kolkata'),
    ('Nairobi',           'Kenya',            'Africa/Nairobi'),
    ('New Delhi',         'India',            'Asia/Kolkata'),
    ('New Orleans',       'US-LA',            'America/Chicago'),
    ('New York',          'US-NY',            'America/New_York'),
    ('Osaka',             'Japan',            'Asia/Tokyo'),
    ('Oslo',              'Norway',           'Europe/Oslo'),
    ('Ottawa',            'Canada-ON',        'America/Toronto'),
    ('Paris',             'France',           'Europe/Paris'),
    ('Perth',             'Australia',        'Australia/Perth'),
    ('Philadelphia',      'US-PA',            'America/New_York'),
    ('Phoenix',           'US-AZ',            'America/Phoenix'),
    ('Prague',            'Czech Republic',   'Europe/Prague'),
    ('Rio de Janeiro',    'Brazil',           'America/Sao_Paulo'),
    ('Riyadh',            'Saudi Arabia',     'Asia/Riyadh'),
    ('Rome',              'Italy',            'Europe/Rome'),
    ('San Diego',         'US-CA',            'America/Los_Angeles'),
    ('San Francisco',     'US-CA',            'America/Los_Angeles'),
    ('San Jose',          'US-CA',            'America/Los_Angeles'),
    ('San Jose',          'Costa Rica',       'America/Costa_Rica'),
    ('Santiago',          'Chile',            'America/Santiago'),
    ('Sao Paulo',         'Brazil',           'America/Sao_Paulo'),
    ('Seattle',           'US-WA',            'America/Los_Angeles'),
    ('Seoul',             'South Korea',      'Asia/Seoul'),
    ('Shanghai',          'China',            'Asia/Shanghai'),
    ('Singapore',         'Singapore',        'Asia/Singapore'),
    ('Sofia',             'Bulgaria',         'Europe/Sofia'),
    ('Springfield',       'US-IL',            'America/Chicago'),
    ('Springfield',       'US-MA',            'America/New_York'),
    ('Springfield',       'US-MO',            'America/Chicago'),
    ('Springfield',       'US-OR',            'America/Los_Angeles'),
    ('Stockholm',         'Sweden',           'Europe/Stockholm'),
    ('Sydney',            'Australia',        'Australia/Sydney'),
    ('Taipei',            'Taiwan',           'Asia/Taipei'),
    ('Tehran',            'Iran',             'Asia/Tehran'),
    ('Tel Aviv',          'Israel',           'Asia/Jerusalem'),
    ('Tokyo',             'Japan',            'Asia/Tokyo'),
    ('Toronto',           'Canada-ON',        'America/Toronto'),
    ('Vancouver',         'Canada-BC',        'America/Vancouver'),
    ('Vienna',            'Austria',          'Europe/Vienna'),
    ('Warsaw',            'Poland',           'Europe/Warsaw'),
    ('Washington DC',     'US-DC',            'America/New_York'),
    ('Wellington',        'New Zealand',      'Pacific/Auckland'),
    ('Zurich',            'Switzerland',      'Europe/Zurich'),
]


def find_cities(query):
    q = query.lower().strip()
    if not q:
        return []
    # Exact name match first (case-insensitive)
    exact = [(n, loc, tz) for n, loc, tz in CITIES if n.lower() == q]
    if exact:
        return exact
    # Substring match (covers partial names and ambiguous inputs)
    return [(n, loc, tz) for n, loc, tz in CITIES if q in n.lower()]


def fmt_time(tz_name):
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.datetime.now(tz=tz)
        return now.strftime('%A, %d %b %Y  %H:%M:%S %Z')
    except Exception as exc:
        return 'Error: ' + str(exc)


CSS = (
    '* { box-sizing: border-box; margin: 0; padding: 0; }'
    'body {'
    '  display: flex; flex-direction: column; align-items: center;'
    '  justify-content: center; min-height: 100vh; gap: 28px;'
    '  background: #0f0f1a; color: #e8e8f0;'
    "  font-family: 'Segoe UI', Arial, sans-serif; padding: 24px;"
    '}'
    'h1 { font-size: clamp(1.8rem, 5vw, 3rem); letter-spacing: .03em; }'
    '.query { font-size: .9rem; opacity: .55; }'
    '.single { text-align: center; }'
    '.city-name { font-size: 1.4rem; font-weight: 700; }'
    '.location { font-size: .85rem; font-weight: 400; opacity: .5; margin-left: 6px; }'
    '.time { font-size: clamp(1.4rem, 4vw, 2.4rem); margin-top: 14px; color: #7ec8e3; }'
    'table { border-collapse: collapse; width: min(860px, 100%); }'
    'th {'
    '  background: #1a1a2e; padding: 10px 18px; text-align: left;'
    '  font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; opacity: .7;'
    '}'
    'td { padding: 14px 18px; border-bottom: 1px solid #1e1e30; vertical-align: middle; }'
    '.city-col { font-weight: 600; }'
    '.loc-tag { display: block; font-size: .75rem; font-weight: 400; opacity: .45; }'
    '.time-col { color: #7ec8e3; font-size: .95rem; }'
    '.no-match { opacity: .65; }'
    'footer { font-size: .75rem; opacity: .35; }'
)


def build_page(city):
    matches = find_cities(city)

    if not matches:
        content = (
            '<p class="no-match">No city found matching <em>' + city + '</em>. '
            'Try a broader search term (e.g. "san", "spring", "new").</p>'
        )
        title = 'Not Found'
    elif len(matches) == 1:
        name, loc, tz = matches[0]
        title = name
        content = (
            '<div class="single">'
            '<div class="city-name">' + name +
            ' <span class="location">(' + loc + ')</span></div>'
            '<div class="time">' + fmt_time(tz) + '</div>'
            '</div>'
        )
    else:
        title = str(len(matches)) + ' matches for \'' + city + '\''
        rows = ''
        for name, loc, tz in matches:
            rows += (
                '<tr>'
                '<td class="city-col">' + name +
                '<span class="loc-tag">' + loc + '</span></td>'
                '<td class="time-col">' + fmt_time(tz) + '</td>'
                '</tr>'
            )
        content = (
            '<table>'
            '<thead><tr><th>City / Region</th><th>Local Time</th></tr></thead>'
            '<tbody>' + rows + '</tbody>'
            '</table>'
        )

    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '  <meta charset="utf-8"/>'
        '  <meta name="viewport" content="width=device-width,initial-scale=1"/>'
        '  <meta http-equiv="refresh" content="10"/>'
        '  <title>World Clock \u2014 ' + title + '</title>'
        '  <style>' + CSS + '</style>'
        '</head>'
        '<body>'
        '  <h1>\U0001f310 World Clock</h1>'
        '  <p class="query">Query: <strong>' + city + '</strong></p>'
        + content +
        '  <footer>Powered by Cloud Run \u2014 Pulumi \u00b7 Auto-refreshes every 10 s</footer>'
        '</body>'
        '</html>'
    )


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = build_page(CITY).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # suppress per-request stdout noise


http.server.HTTPServer(('', 8080), _Handler).serve_forever()
"""

_SCRIPT_B64: str = base64.b64encode(_SERVER_SCRIPT.encode()).decode()

# ---------------------------------------------------------------------------
# Cloud Run v2 service — world clock
# ---------------------------------------------------------------------------
cloud_run = gcp.cloudrunv2.Service(
    "worldclock",
    location=region,
    ingress="INGRESS_TRAFFIC_ALL",
    deletion_protection=False,
    template=gcp.cloudrunv2.ServiceTemplateArgs(
        containers=[
            gcp.cloudrunv2.ServiceTemplateContainerArgs(
                # Stock Python image — no custom build or registry push required
                image="python:3.11-slim",
                # Decode and exec the embedded server script
                commands=["python3", "-c"],
                args=[
                    "import base64,os; exec(base64.b64decode(os.environ['SCRIPT']).decode())"
                ],
                envs=[
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="SCRIPT", value=_SCRIPT_B64
                    ),
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name="CITY", value=city
                    ),
                ],
                ports=gcp.cloudrunv2.ServiceTemplateContainerPortsArgs(
                    container_port=8080,
                ),
                resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                    limits={"cpu": "1", "memory": "512Mi"},
                ),
            )
        ],
    ),
    opts=pulumi.ResourceOptions(depends_on=[cloud_run_api]),
)

# Allow unauthenticated (public) invocation
gcp.cloudrunv2.ServiceIamMember(
    "all-users-invoker",
    name=cloud_run.name,
    location=region,
    role="roles/run.invoker",
    member="allUsers",
)

# ---------------------------------------------------------------------------
# Stack outputs
# ---------------------------------------------------------------------------
pulumi.export("worldclock_url", cloud_run.uri)
pulumi.export("city_query", city)
