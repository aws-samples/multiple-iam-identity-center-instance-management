"""
setup.py — end-to-end Account Access Manager onboarding

Chains the full setup flow in a single command:
  1. Write the [sso-session] block to ~/.aws/config (skipped if it already exists)
  2. Open the browser for aws sso login and wait for completion
  3. Fetch every role the user has access to via Account Access Manager
  4. Create an AWS CLI profile for each role, named according to --profile-format

Profile format tokens (all optional, use any combination):
  {prefix}   - literal prefix string supplied via --prefix (default: "aws")
  {account}  - 12-digit AWS account ID
  {role}     - role name (last segment of the role ARN)

Example:
  python setup.py \\
      --sso-start-url https://d-aaabbb1111.awsapps.com/start \\
      --sso-region us-west-2 \\
      --account-access-url https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws \\
      --profile-format "{prefix}-{account}-{role}" \\
      --prefix aws
"""

import argparse
import configparser
import csv
import http.client
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from lib import SSOTokenProviderWithoutProfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ACCESS_HOST_TEMPLATE = "account-access-runtime.{region}.api.aws"

ACCOUNT_ACCESS_SCOPES = [
    "sso:account:access",
    "account_access:read_only",
    "account_access:assume"
]

DEFAULT_SESSION_NAME = "account-access-session"
DEFAULT_PROFILE_FORMAT = "{role}-{account}"

CACHE_DIR = "~/.aws/cli/cache"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Account Access Manager end-to-end setup: configure, login, list roles, create profiles.",
    prog="python setup.py",
)

# --- Session / login arguments (mirrors configure-account-access.py) ---
parser.add_argument(
    "--sso-session",
    default=DEFAULT_SESSION_NAME,
    help=f"SSO session name [default: {DEFAULT_SESSION_NAME}]",
)
parser.add_argument(
    "--sso-start-url",
    help="SSO start URL  e.g. https://d-aaabbb1111.awsapps.com/start",
)
parser.add_argument(
    "--sso-region",
    help="SSO / Identity Center region  e.g. us-west-2",
)
parser.add_argument(
    "--account-access-url",
    help="Account Access portal URL  e.g. https://aa-a1b2c3d4f5.account-access.us-west-2.app.aws",
)
parser.add_argument(
    "--sso-registration-scopes",
    default=",".join(ACCOUNT_ACCESS_SCOPES),
    help="SSO registration scopes (comma-separated)",
)

# --- Profile naming arguments ---
parser.add_argument(
    "--profile-format",
    default=DEFAULT_PROFILE_FORMAT,
    help=(
        "Profile name template. Available tokens: {prefix}, {account}, {role}, {path}. "
        "{path} is the IAM role path (e.g. 'prod/payments' from role/prod/payments/ReadOnlyAccess), "
        "empty string if the role has no path. "
        f"[default: {DEFAULT_PROFILE_FORMAT}]"
    ),
)
parser.add_argument(
    "--prefix",
    default="aws",
    help="Value substituted for the {prefix} token in --profile-format [default: aws]",
)

args = parser.parse_args()

# Validate sso_session: only allow alphanumeric characters and hyphens to
# prevent injection of unexpected values into subprocess and config calls.
if not re.match(r'^[a-zA-Z0-9-]+$', args.sso_session):
    print("error: --sso-session must contain only letters, numbers, and hyphens.", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 1 — Write [sso-session] block to ~/.aws/config
# ---------------------------------------------------------------------------

print(f"[1/4] Configuring SSO session '{args.sso_session}' ...")

config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.aws/config"))

config_session_section = "sso-session " + args.sso_session

if config.has_section(config_session_section):
    print(
        f"      Session '{args.sso_session}' already exists in ~/.aws/config — skipping write."
    )
else:
    # Prompt interactively for any required value not supplied as a flag.
    required = {
        "sso_start_url": ("--sso-start-url", args.sso_start_url, "SSO start URL"),
        "sso_region": ("--sso-region", args.sso_region, "SSO region"),
        "account_access_url": (
            "--account-access-url",
            args.account_access_url,
            "Account Access portal URL",
        ),
    }

    resolved = {}
    for key, (flag, value, prompt_label) in required.items():
        if value:
            resolved[key] = value
        else:
            resolved[key] = input(f"      {prompt_label} ({flag}): ").strip()
            if not resolved[key]:
                print(f"error: {prompt_label} is required.", file=sys.stderr)
                sys.exit(1)

    new_section = configparser.ConfigParser()
    new_section.add_section(config_session_section)
    new_section[config_session_section]["sso_start_url"] = resolved["sso_start_url"]
    new_section[config_session_section]["sso_region"] = resolved["sso_region"]
    new_section[config_session_section]["account_access_url"] = resolved[
        "account_access_url"
    ]
    new_section[config_session_section]["sso_registration_scopes"] = (
        args.sso_registration_scopes
    )

    with open(os.path.expanduser("~/.aws/config"), "a") as f:
        f.write("\n")
        new_section.write(f)

    print("      Session configuration written.")

# Reload config so subsequent steps see the full file.
config.read(os.path.expanduser("~/.aws/config"))

# ---------------------------------------------------------------------------
# Step 2 — Browser login via aws sso login
# ---------------------------------------------------------------------------

print(f"\n[2/4] Opening browser for SSO login (session: '{args.sso_session}') ...")
print("      Complete the login in your browser, then return here.")

result = subprocess.run(
    ["aws", "sso", "login", "--sso-session", args.sso_session],
    check=False,
)

if result.returncode != 0:
    print("error: 'aws sso login' exited with a non-zero status.", file=sys.stderr)
    sys.exit(result.returncode)

print("      Login complete.")

# ---------------------------------------------------------------------------
# Step 3 — List all roles via Account Access Manager
# ---------------------------------------------------------------------------

print("\n[3/4] Fetching roles from Account Access Manager ...")

# Read session config.
if not config.has_option(config_session_section, "account_access_url"):
    print(
        f"error: No account_access_url found for session '{args.sso_session}' in ~/.aws/config.",
        file=sys.stderr,
    )
    sys.exit(1)

sso_region = config[config_session_section]["sso_region"]
account_access_url = config[config_session_section]["account_access_url"]

tenant_id_pattern = re.compile(r"^https?://(?P<id>aa-[a-z0-9]+)")
m = tenant_id_pattern.match(account_access_url)
if not m:
    print("error: Invalid account_access_url — cannot extract tenant ID.", file=sys.stderr)
    sys.exit(1)

account_access_id = m.group("id")
host = ACCOUNT_ACCESS_HOST_TEMPLATE.format(region=sso_region)

token_provider = SSOTokenProviderWithoutProfile(args.sso_session)
access_token = token_provider.load_token()

SOCKET_TIMEOUT = 30  # seconds

roles = []
next_token = None
backoff_factor = 1.3
maximum_attempts = 5
attempts = 0

while True:
    if attempts >= maximum_attempts:
        print("error: Unable to list all roles after multiple retries.", file=sys.stderr)
        sys.exit(1)

    params = {"tenantId": account_access_id}
    if next_token is not None:
        params["nextToken"] = next_token

    try:
        # Re-create the connection each page so a server-side disconnect
        # between pages does not crash the script.
        conn = http.client.HTTPSConnection(host, timeout=SOCKET_TIMEOUT)
        conn.request(
            "GET",
            f"/access?{urllib.parse.urlencode(params)}",
            headers={
                "authorization": f"Bearer {access_token.get_frozen_token().token}",
                "user-agent": "account access AWS CLI script",
            },
        )
        response = conn.getresponse()
    except (http.client.HTTPException, OSError) as e:
        attempts += 1
        print(
            f"      warning: Connection error while fetching roles: {e}",
            file=sys.stderr,
        )
        time.sleep(0.3 * backoff_factor)
        backoff_factor *= 2
        continue

    if response.status != 200:
        attempts += 1
        body = response.read().decode("utf-8", errors="replace")
        print(
            f"      warning: Received {response.status} {response.reason}: {body}",
            file=sys.stderr,
        )
        time.sleep(0.3 * backoff_factor)
        backoff_factor *= 2
        continue

    response_json = json.loads(response.read().decode("utf-8"))
    roles.extend(response_json["roles"])
    next_token = response_json["nextToken"]
    attempts = 0
    backoff_factor = 1.3

    if next_token is None:
        break

print(f"      Found {len(roles)} role(s).")

# ---------------------------------------------------------------------------
# Step 4 — Create AWS CLI profiles
# ---------------------------------------------------------------------------

print("\n[4/4] Creating AWS CLI profiles ...")

refresh_script_path = Path(__file__).resolve().parent / "refresh-credentials.py"

config.read(os.path.expanduser("~/.aws/config"))  # re-read to catch any concurrent changes
new_config = configparser.ConfigParser()

created = []
existing = []

for role in roles:
    role_arn = role["roleArn"]
    account_id = role["accountId"]
    role_name = role_arn.split("/")[-1]

    # Extract the path segments between "role/" and the role name.
    # e.g. arn:aws:iam::123456789012:role/prod/payments/ReadOnlyAccess -> "prod/payments"
    # If there is no path, this will be an empty string.
    arn_parts = role_arn.split("/")
    role_path = "/".join(arn_parts[1:-1]) if len(arn_parts) > 2 else ""

    # Apply the user-supplied naming convention.
    profile_name = (
        args.profile_format
        .replace("{prefix}", args.prefix)
        .replace("{account}", account_id)
        .replace("{role}", role_name)
        .replace("{path}", role_path)
    )

    sts_session_name = f"cli-{args.sso_session}-{profile_name}"[:64]
    config_profile_section = "profile " + profile_name

    if config.has_section(config_profile_section) or new_config.has_section(
        config_profile_section
    ):
        existing.append(profile_name)
        continue

    new_config.add_section(config_profile_section)
    new_config[config_profile_section]["credential_process"] = shlex.join(
        [
            sys.executable,
            str(refresh_script_path),
            "--profile", profile_name,
            "--sso-session", args.sso_session,
            "--role-arn", role_arn,
            "--session-name", sts_session_name,
        ]
    )
    created.append(profile_name)

with open(os.path.expanduser("~/.aws/config"), "a") as f:
    f.write("\n")
    new_config.write(f)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n--- Setup complete ---")

if created:
    print(f"\nCreated {len(created)} profile(s):")
    for name in created:
        print(f"  {name}")

if existing:
    print(f"\nSkipped {len(existing)} profile(s) that already existed:")
    for name in existing:
        print(f"  {name}")

if created:
    print(
        f"\nYou can now use these profiles with the AWS CLI, for example:\n"
        f"  aws sts get-caller-identity --profile {created[0]}"
    )
