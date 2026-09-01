#!/usr/bin/env bash
#
# scripts/regen_client.sh
# ------------------------
# Regenerates client/packages/tastefinder_api_client/ from the server's
# current OpenAPI schema. The generated package is a Dio-based Dart client
# (openapi-generator, generator id `dart-dio`), added to client/pubspec.yaml
# as a path dependency.
#
# Not under client/lib/: a Dart package's pubspec.yaml nested inside another
# package's lib/ directory hits a compiler bug where the two packages'
# default language versions make part-file resolution fail. Confirmed to
# break `flutter build`, not just analysis -- see docs/00_BOOTSTRAP.md,
# Phase 4.
#
# Requirements, one-time:
#   - The server's dev dependencies installed (tastefinder/server/.venv).
#   - A Java runtime, and openapi-generator-cli.jar. This script does not
#     download the jar itself: set OPENAPI_GENERATOR_JAR to its path, or
#     place it at the default location below. Failing loudly here, rather
#     than silently fetching a jar from the network on every regeneration,
#     matches the rest of this project's stance on unstated dependencies.
#
# Usage: scripts/regen_client.sh   (from anywhere; paths below are relative
#                                    to this script's location)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$SCRIPT_DIR/../server"
CLIENT_DIR="$SCRIPT_DIR/../client"
GENERATOR_JAR="${OPENAPI_GENERATOR_JAR:-$HOME/install/openapi-generator/openapi-generator-cli.jar}"

if [ ! -f "$GENERATOR_JAR" ]; then
  echo "openapi-generator-cli.jar not found at: $GENERATOR_JAR" >&2
  echo "Set OPENAPI_GENERATOR_JAR, or download it:" >&2
  echo "  https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/" >&2
  exit 1
fi

if [ ! -x "$SERVER_DIR/.venv/bin/python3" ]; then
  echo "Server venv not found at $SERVER_DIR/.venv -- run 'make setup' first." >&2
  exit 1
fi

SCHEMA_FILE="$(mktemp -t tastefinder-openapi-XXXXXX.json)"
trap 'rm -f "$SCHEMA_FILE"' EXIT

echo "Extracting OpenAPI schema from app.main:create_app..."
(
  cd "$SERVER_DIR"
  .venv/bin/python3 -c "
import json
from app.main import create_app
with open('$SCHEMA_FILE', 'w') as f:
    json.dump(create_app().openapi(), f, indent=2)
"
)

GENERATED_DIR="$CLIENT_DIR/packages/tastefinder_api_client"

echo "Generating Dart client into client/packages/tastefinder_api_client/..."
rm -rf "$GENERATED_DIR"
java -jar "$GENERATOR_JAR" generate \
  -i "$SCHEMA_FILE" \
  -g dart-dio \
  -o "$GENERATED_DIR" \
  --additional-properties=pubName=tastefinder_api_client,pubLibrary=tastefinder_api_client

# dart-dio's models are built_value-based (source_gen), so the generator's
# own output is not runnable yet -- the .g.dart serializer parts still need
# to be built, same as in any project using built_value. Its own .dart_tool
# is removed afterward: it is transient build state local to this pub get,
# not something to leave lying around in a directory meant to be committed.
echo "Running build_runner to emit built_value serializers..."
(
  cd "$GENERATED_DIR"
  dart pub get
  dart run build_runner build --delete-conflicting-outputs
  rm -rf .dart_tool
)

echo "Done. Review the diff under client/packages/tastefinder_api_client/ before committing."
