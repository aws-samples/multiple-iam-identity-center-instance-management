import argparse
import configparser
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import time
import typing
import urllib.parse
from re import Match

from lib import SSOTokenProviderWithoutProfile


def get_config(sso_session, config_string):
    config = configparser.ConfigParser()
    config.read(os.path.expanduser("~/.aws/config"))

    config_section = "sso-session " + sso_session
    if not config.has_section(config_section):
        print("error: No session entry found in ~/.aws/config", file=sys.stderr)
        sys.exit(1)

    if not config.has_option(config_section, "account_access_url"):
        print(
            f"error: No account access URL configured for {config_section}. Please use configure-account-access.py or add it manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    return config[config_section][config_string]


def get_tenant_id(sso_session):
    account_access_url = get_config(sso_session, "account_access_url")
    account_access_id_pattern = re.compile(r"^https?://(?P<id>aa-[a-z0-9]+)")
    m = account_access_id_pattern.match(account_access_url)

    if not m:
        print("error: Invalid account access portal URL configured", file=sys.stderr)
        sys.exit(1)

    return m.group("id")


def get_credentials(access_token, region, account_access_id, role_arn, session_name):
    access_type = "PROGRAMMATIC_ACCESS"  # shouldn't change
    session_duration = 3600  # doesn't need to be longer, credentials refreshed automatically until backing SSO session expires, unless it is desirable to have credentials past SSO session expiration
    host = f"account-access-runtime.{region}.api.aws"
    conn = http.client.HTTPSConnection(host)

    response_json = None

    condition = True
    backoff_factor = 1.3
    maximum_attempts = 5
    attempts = 0
    while condition:
        if attempts >= maximum_attempts:
            print("error: Unable to get credentials for role", file=sys.stderr)
            break

        params = {
            "tenantId": account_access_id,
            "roleArn": role_arn,
            "accessType": access_type,
            "sessionName": session_name,
            "sessionDuration": session_duration,
        }

        conn.request(
            "GET",
            f"/access/credentials?{urllib.parse.urlencode(params)}",
            headers={
                "authorization": f"Bearer {access_token.get_frozen_token().token}",
                "user-agent": "account access AWS CLI script",
            },
        )
        response = conn.getresponse()

        if response.status != 200:
            attempts += 1
            body = response.read().decode("utf-8", errors="replace")
            print(
                f"warning: Credentials request failed ({response.status} {response.reason}): {body}",
                file=sys.stderr,
            )
            time.sleep(0.3 * backoff_factor)
            backoff_factor *= 2
            continue

        response_json = json.loads(response.read().decode("utf-8"))

        condition = response.status != 200

    if response_json is None:
        print("error: Failed to get credentials", file=sys.stderr)
        sys.exit(1)

    output = {}
    output["Version"] = 1

    for key, value in response_json["credentialsDetails"]["programmaticAccess"].items():
        output[key[:1].upper() + key[1:]] = value

    return output


def cache_key(role_arn, sso_session):
    # see https://github.com/boto/botocore/blob/develop/botocore/credentials.py#L2280
    arn_pattern = re.compile(
        r"^arn:aws:iam::(?P<account>\d{12}):role/(?P<role_name>[/\w+=,.@-]+)$"
    )
    m = arn_pattern.match(role_arn)

    if m is None:
        print("error: invalid role ARN", file=sys.stderr)
        sys.exit(1)

    account = typing.cast(Match[str], m).group("account")
    role_name = typing.cast(Match[str], m).group("role_name")

    args = {"roleName": role_name, "accountId": account, "sessionName": sso_session}

    # NOTE: SHA256 is used here instead of botocore's SHA1 cache key algorithm.
    # This cache key is used only as a filename for credential caching and has
    # no security implications; SHA256 prevents security scanner false positives.
    return hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


CACHE_DIR = "~/.aws/cli/cache"


def cache_path(role_arn: str, sso_session: str):
    return os.path.join(
        os.path.expanduser(CACHE_DIR), cache_key(role_arn, sso_session) + ".json"
    )


def cache_credentials(role_arn: str, sso_session: str, creds):
    cache_dir = os.path.expanduser(CACHE_DIR)
    path = cache_path(role_arn, sso_session)
    cache_entry = {"ProviderType": "account-access", "Credentials": creds}

    os.makedirs(cache_dir, exist_ok=True)

    # Write to a temporary file, then rename it into place. tempfile.mkstemp()
    # creates the file with mode 0600, so the plaintext credentials are never
    # readable by other users. The rename is atomic, so a concurrent reader
    # never sees a partially written file. This matches botocore's
    # JSONFileCache.
    # https://github.com/boto/botocore/blob/develop/botocore/utils.py#L3594
    temp_fd, temp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w") as f:
            f.write(json.dumps(cache_entry))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except BaseException:
        # Do not leave a temporary file behind if the write fails.
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def parse_expiration(value: str):
    """Parse the ISO 8601 expiration timestamp that the API returns.

    The API returns a trailing "Z" for UTC. datetime.fromisoformat() accepts
    "Z" only from Python 3.11 onward, so replace it.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = dt.datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)

    return parsed


def cached_credentials_if_exist(role_arn: str, sso_session: str):
    """Return the cached entry, or None if it is absent or unusable.

    A cache problem must never stop the script. The caller gets fresh
    credentials instead.
    """
    path = cache_path(role_arn, sso_session)

    # Open the file directly. An os.path.exists() check first leaves a race
    # window, because a concurrent run can remove the file before the open.
    try:
        with open(path) as f:
            cached_creds_json = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        # OSError covers a permission problem. ValueError covers a truncated
        # or corrupt file. Neither is fatal.
        print(f"warning: Ignoring unusable cache file {path}: {e}", file=sys.stderr)
        return None

    # Confirm the entry holds the fields that the caller reads, so that a
    # malformed file cannot raise later.
    try:
        parse_expiration(cached_creds_json["Credentials"]["Expiration"])
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        print(f"warning: Ignoring malformed cache entry {path}: {e}", file=sys.stderr)
        return None

    return cached_creds_json


def creds_are_fresh(creds):
    now = dt.datetime.now(dt.timezone.utc)
    credential_expiration = parse_expiration(creds["Expiration"])

    buffer = dt.timedelta(minutes=15)

    return (now + buffer) < credential_expiration


def main():
    REQUIRED_ARGS = {
        "profile": "",
        "sso-session": "",
        "role-arn": "",
        "session-name": "",
    }

    parser = argparse.ArgumentParser(
        description="Account Access credentials refresh script (not intended for direct usage)",
        prog="python refresh-credentials.py",
    )

    for arg, desc in REQUIRED_ARGS.items():
        parser.add_argument("--" + arg, help=desc)

    args = parser.parse_args()

    cached_creds_entry = cached_credentials_if_exist(args.role_arn, args.sso_session)

    if cached_creds_entry is not None and creds_are_fresh(
        cached_creds_entry["Credentials"]
    ):
        print(json.dumps(cached_creds_entry["Credentials"], indent=4))
        return

    token_provider = SSOTokenProviderWithoutProfile(args.sso_session)
    access_token = token_provider.load_token()

    region = get_config(args.sso_session, "sso_region")
    account_access_id = get_tenant_id(args.sso_session)
    role_arn = args.role_arn
    session_name = args.session_name

    creds = get_credentials(
        access_token, region, account_access_id, role_arn, session_name
    )

    cache_credentials(args.role_arn, args.sso_session, creds)

    print(json.dumps(creds, indent=4))


if __name__ == "__main__":
    main()
