#!/usr/bin/env python3
"""The config chart must render Configurations the main chart actually generates.

config-chart/ names two kinds that exist only because oasgen generates them from chart/. The two
charts share no code, so a renamed kind or a changed auth scheme in chart/assets would leave the
config chart rendering objects with no CRD, or with a field the CRD does not have. Only a cluster
would report that, and only after the component had started failing.

Usage: assert-config-chart.py <repo root>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

root = sys.argv[1] if len(sys.argv) > 1 else "."
NAMESPACE = "assert-ns"
errors = []

# helm refuses the CHART_VERSION placeholder, so render a copy with a version in it.
with tempfile.TemporaryDirectory() as tmp:
    chart = os.path.join(tmp, "config-chart")
    shutil.copytree(os.path.join(root, "config-chart"), chart)
    meta = os.path.join(chart, "Chart.yaml")
    text = open(meta).read().replace("CHART_VERSION", "0.0.0")
    open(meta, "w").write(text)
    rendered = subprocess.run(
        ["helm", "template", "x", chart, "-n", NAMESPACE],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
docs = [d for d in yaml.safe_load_all(rendered) if d]

schema = json.load(open(os.path.join(root, "chart", "values.schema.json")))
known = set(schema["properties"]["kinds"]["items"]["enum"])
group = schema["properties"]["resourceGroup"]["default"]

kinds = sorted(d["kind"] for d in docs)
if kinds != ["PullRequestConfiguration", "RepositoryConfiguration"]:
    errors.append(f"rendered kinds are {kinds}")

for doc in docs:
    kind = doc["kind"]
    base = kind[: -len("Configuration")]
    if base not in known:
        errors.append(f"{kind}: {base} is not a kind of chart/")
        continue

    asset = yaml.safe_load(open(os.path.join(root, "chart", "assets", f"{base.lower()}.yaml")))
    schemes = asset["components"]["securitySchemes"].values()
    if [s.get("scheme") for s in schemes] != ["bearer"]:
        errors.append(f"{kind}: the {base} asset is not bearer-only, so spec.authentication.bearer is wrong")

    if doc["apiVersion"] != f"{group}/v1alpha1":
        errors.append(f"{kind}: apiVersion {doc['apiVersion']}")

    ref = doc["spec"]["authentication"]["bearer"]["tokenRef"]
    if doc["metadata"]["namespace"] != NAMESPACE or ref["namespace"] != NAMESPACE:
        errors.append(f"{kind}: not in the release namespace")

for error in errors:
    print(f"FAIL {error}")
if errors:
    sys.exit(1)
print(f"OK: {len(docs)} Configurations, each a bearer kind of chart/")
