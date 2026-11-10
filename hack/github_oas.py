"""Shared helpers for the checks that compare the chart with GitHub's OpenAPI description.

The description is downloaded at a PINNED commit and checked against its SHA-256, so a check
cannot change under the chart. Bump both together, on purpose.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

import yaml

GITHUB_OAS_COMMIT = "fa8d7bfb041cc9ef90ac51dcb8ed8cc8a0007166"  # github/rest-api-description main, 2026-11-10
GITHUB_OAS_SHA256 = "bd948bdc47be1b76d8ff25322f01820c5d65027a3a265bb4eb677aeda034dcf5"
GITHUB_OAS_URL = (
    "https://raw.githubusercontent.com/github/rest-api-description/%s/descriptions/api.github.com/api.github.com.json"
    % GITHUB_OAS_COMMIT
)


def load_github_oas():
    """GitHub's description at the pinned commit, verified, as a dict.

    GITHUB_OAS_FILE may name a local copy (for offline runs); it is held to the same SHA-256.
    """
    local = os.environ.get("GITHUB_OAS_FILE")
    data = open(local, "rb").read() if local else urllib.request.urlopen(GITHUB_OAS_URL, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != GITHUB_OAS_SHA256:
        raise SystemExit("GitHub OpenAPI at %s has sha256 %s, expected %s: refusing to check against an "
                         "unverified description" % (GITHUB_OAS_COMMIT, digest, GITHUB_OAS_SHA256))
    return json.loads(data)


def render_chart(root):
    """All documents `helm template` renders from <root>/chart.

    helm refuses the CHART_VERSION placeholder, so a copy with a version in it is rendered.
    """
    with tempfile.TemporaryDirectory() as tmp:
        chart = os.path.join(tmp, "chart")
        shutil.copytree(os.path.join(root, "chart"), chart)
        meta = os.path.join(chart, "Chart.yaml")
        text = open(meta).read().replace("CHART_VERSION", "0.0.0").replace("APP_VERSION", "0.0.0")
        with open(meta, "w") as f:
            f.write(text)
        out = subprocess.run(["helm", "template", "x", chart], check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def resolve(doc, node):
    """Follow local $refs until a non-ref node."""
    while isinstance(node, dict) and "$ref" in node:
        target = doc
        for key in node["$ref"][2:].split("/"):
            target = target[key.replace("~1", "/").replace("~0", "~")]
        node = target
    return node
