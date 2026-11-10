#!/usr/bin/env python3
"""Every kind must expose every operation GitHub's OpenAPI defines on the paths it uses.

The chart follows GitHub's REST description as published (github/rest-api-description). A kind
that leaves out an operation GitHub defines on one of its own paths silently narrows what the CR
can do, the way Repository once had no DELETE. This check reads the rendered chart, collects the
paths each RestDefinition's verbs use, and requires every method GitHub defines on such a path to
appear as one of that kind's verbs, with the operation present in the kind's asset.

Two cases are allowed, both explicit:
  - a GET on the kind's own POST create path (the collection) is GitHub's LIST operation; a kind models
    one object, so a list is optional (some kinds use it as findby);
  - an entry in EXCEPTIONS below, each with the reason.

Deletion protection is not done by leaving operations out: annotate the CR
`krateo.io/deletion-policy: orphan` (docs/usage.md).

The GitHub description is downloaded at a PINNED commit and checked against its SHA-256
(hack/github_oas.py), so the check cannot change under the chart.

Usage: assert-oas-operations.py <repo root>
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from github_oas import GITHUB_OAS_COMMIT, load_github_oas, render_chart  # noqa: E402

METHODS = ("get", "post", "put", "patch", "delete")

# (kind, METHOD, path as the kind's verbs write it): why the kind does not expose it.
EXCEPTIONS = {
    ("Collaborator", "GET", "/repos/{owner}/{repo}/collaborators/{login}"):
        "GitHub's check-collaborator returns 204/404 with no body, so it cannot fill status; "
        "the kind observes through findby on the collaborator list, which also carries role_name.",
}

root = sys.argv[1] if len(sys.argv) > 1 else "."
errors = []

github = load_github_oas()["paths"]


def norm(path):
    return re.sub(r"\{[^}]+\}", "{}", path)


github_ops = {}
for path, ops in github.items():
    github_ops.setdefault(norm(path), set()).update(m.upper() for m in ops if m in METHODS)

docs = render_chart(root)
configmaps = {d["metadata"]["name"]: d.get("data") or {} for d in docs if d.get("kind") == "ConfigMap"}

examined = 0
used_exceptions = set()
for d in docs:
    if d.get("kind") != "RestDefinition":
        continue
    res = d["spec"]["resource"]
    kind = res["kind"]
    verbs = {(v["method"].upper(), v["path"]) for v in res.get("verbsDescription") or []}
    # Only a POST create is a collection; a PUT create (Collaborator, TeamMembership, ...) is on the item
    # path, where GitHub's GET is an item read, not a list.
    create_paths = {v["path"] for v in res.get("verbsDescription") or []
                    if v["action"] == "create" and v["method"].upper() == "POST"}
    parts = d["spec"]["oasPath"][len("configmap://"):].split("/")
    asset = yaml.safe_load(configmaps.get(parts[1], {}).get(parts[2], "") or "{}") or {}
    asset_paths = asset.get("paths") or {}
    examined += 1
    for path in sorted({p for _, p in verbs}):
        known = github_ops.get(norm(path))
        if known is None:
            errors.append("%s: %s is not a path in GitHub's OpenAPI at %s" % (kind, path, GITHUB_OAS_COMMIT[:12]))
            continue
        for method in sorted(known):
            if (method, path) in verbs:
                if method.lower() not in (asset_paths.get(path) or {}):
                    errors.append("%s: verb %s %s has no operation in the kind's asset" % (kind, method, path))
                continue
            if method == "GET" and path in create_paths:
                continue  # GitHub's list operation on the collection
            if (kind, method, path) in EXCEPTIONS:
                used_exceptions.add((kind, method, path))
                continue
            errors.append("%s: GitHub defines %s %s, but the kind does not expose it. Add the verb "
                          "(and the operation to its asset), or add an EXCEPTIONS entry with the reason."
                          % (kind, method, path))

for stale in sorted(set(EXCEPTIONS) - used_exceptions):
    errors.append("EXCEPTIONS entry %s no longer applies; remove it" % (stale,))
if examined == 0:
    errors.append("examined 0 RestDefinitions: the check looked at nothing")
print("Checked %d RestDefinition(s) against GitHub OpenAPI %s" % (examined, GITHUB_OAS_COMMIT[:12]))
for error in errors:
    print(error, file=sys.stderr)
if errors:
    sys.exit(1)
