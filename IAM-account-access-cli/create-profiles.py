import argparse
import configparser
import csv
import json
import os
import shlex
import sys
from pathlib import Path

OPTIONAL_ARGS = {
    "sso-session": {
        "description": "SSO session name to associate with access profiles | default [account-access-session]",
        "default": "account-access-session",
    },
    "from-file": {
        "description": "Read profile inputs from a file | default [None]",
        "default": None,
    },
    "input": {
        "description": "Input format | options [json|csv] | default [json] ",
        "default": "json",
    },
}

parser = argparse.ArgumentParser(
    description="AWS CLI profile creation based on output of `list-roles.py`. Reads from stdin by default. Can read from a CSV or JSON file.",
    prog="python create-profiles.py",
)

for arg, fields in OPTIONAL_ARGS.items():
    parser.add_argument(
        "--" + arg, help=fields["description"], default=fields["default"]
    )

args = parser.parse_args()

if args.input not in ["json", "csv"]:
    print("error: Invalid input file format specified")
    sys.exit(1)

if args.from_file is None:
    profiles_input = sys.stdin.read()
else:
    with open(os.path.expanduser(args.from_file)) as f:
        profiles_input = f.read()

profiles_input = profiles_input.strip()

if not profiles_input:
    print("error: No input provided")
    sys.exit(1)

profiles = []
if args.input == "json":
    if profiles_input[0] != "[":
        print("error: Input file has invalid format (expected JSON array)")
        sys.exit(1)
    profiles = json.loads(profiles_input)
elif args.input == "csv":
    if profiles_input[0] in ["[", "{"]:
        print(
            "error: Input file has invalid format (expected CSV file with named headers)"
        )
        sys.exit(1)
    reader = csv.DictReader(profiles_input.splitlines())
    profiles = list(reader)


config = configparser.ConfigParser()
new_config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.aws/config"))

existing = []
created = []
refresh_script_path = Path(__file__).resolve().parent / "refresh-credentials.py"

for profile in profiles:
    role_name = profile["roleArn"].split("/")[-1]
    # change this to override the name that profiles are created with by default
    # you can provide an override in the data, or modify this to generate names programmatically
    profile_name = profile.get("profileName", f"{role_name}-{profile['accountId']}")
    sts_session_name = profile.get(
        "sessionName", f"cli-{args.sso_session}-{profile_name}"
    )[:64]
    config_profile_section = "profile " + profile_name

    if config.has_section(config_profile_section) or new_config.has_section(config_profile_section):
        existing.append(config_profile_section)
        continue

    new_config.add_section(config_profile_section)
    new_config[config_profile_section]["credential_process"] = (
        shlex.join([sys.executable, str(refresh_script_path), "--profile", profile_name, "--sso-session", args.sso_session, "--role-arn", profile["roleArn"], "--session-name", sts_session_name])
    )
    created.append(config_profile_section)

with open(os.path.expanduser("~/.aws/config"), "a") as configfile:
    configfile.write("\n")
    new_config.write(configfile)

print("Profile creation completed:")

if len(created) != 0:
    print("Wrote these profiles entries:\n" + "\n".join(created))

if len(existing) != 0:
    print()
    print(
        "Failed to create these entries since they already exist in the file:\n"
        + "\n".join(existing)
    )
