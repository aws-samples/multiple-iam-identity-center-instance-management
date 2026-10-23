import argparse
import configparser
import csv
import json
import os
import re
import sys

import requests
from lib import SSOTokenProviderWithoutProfile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OPTIONAL_ARGS = {
    "sso-session": {
        "description": "SSO session name to use to list roles | default [account-access-session]",
        "default": "account-access-session",
    },
    "output": {
        "description": "Output format | options [json|csv] | default [json] ",
        "default": "json",
    },
}

parser = argparse.ArgumentParser(
    description="Listing account access roles", prog="python list-roles.py"
)

for arg, fields in OPTIONAL_ARGS.items():
    parser.add_argument(
        "--" + arg, help=fields["description"], default=fields["default"]
    )

args = parser.parse_args()

if args.output not in ["json", "csv"]:
    print("error: Invalid output format specified")
    sys.exit(1)

token_provider = SSOTokenProviderWithoutProfile(args.sso_session)
access_token = token_provider.load_token()

config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.aws/config"))

config_section = "sso-session " + args.sso_session
if not config.has_section(config_section):
    print("error: No session entry found in ~/.aws/config")
    sys.exit(1)

if not config.has_option(config_section, "account_access_url"):
    print(f"error: No account access URL configured for {config_section}. Please use configure-account-access.py or add it manually.")
    sys.exit(1)

region = config[config_section]["sso_region"]
account_access_url = config[config_section]["account_access_url"]
account_access_id_pattern = re.compile(r"^https?://(?P<id>aa-[a-z0-9]+)")
m = account_access_id_pattern.match(account_access_url)

if not m:
    print("error: Invalid account access portal URL configured")
    sys.exit(1)

account_access_id = m.group("id")

base_url = f"https://account-access-runtime.{region}.api.aws"

# requests Session with automatic retry + backoff on transient failures.
# Retries on connection errors and 5xx responses (up to 5 attempts total,
# backoff: 0.3 * 2^attempt seconds between retries).
retry_strategy = Retry(
    total=5,
    backoff_factor=0.3,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("https://", adapter)
session.headers.update({
    "authorization": f"Bearer {access_token.get_frozen_token().token}",
    "user-agent": "account access AWS CLI script",
})

SOCKET_TIMEOUT = 30  # seconds

roles = []
next_token = None

while True:
    params = {"tenantId": account_access_id}
    if next_token is not None:
        params["nextToken"] = next_token

    response = session.get(f"{base_url}/access", params=params, timeout=SOCKET_TIMEOUT)

    if response.status_code != 200:
        print(
            f"error: Unable to list roles ({response.status_code} {response.reason}): {response.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    response_json = response.json()
    next_token = response_json["nextToken"]
    roles.extend(response_json["roles"])

    if next_token is None:
        break

unique_fields = sorted({key for role in roles for key in role})

if args.output == "json":
    print(json.dumps(roles, indent=4))
elif args.output == "csv":
    csvwriter = csv.DictWriter(sys.stdout, fieldnames=unique_fields)
    csvwriter.writeheader()
    csvwriter.writerows(roles)
