#!/usr/bin/env python3
"""githubBaseUrl must reach every RestDefinition, and only when it is set.

GitHub Enterprise support rests on RestDefinition.spec.serverURL (oasgen-provider >= 0.52.0), which
REPLACES each document's servers[0]; the endpoint host policy is built from it, so api.github.com
stops being permitted. A kind whose template forgot the include would keep calling api.github.com
with the Enterprise token, which is the failure this check exists to make impossible:

  - rendered with the default values, no RestDefinition carries spec.serverURL;
  - rendered with githubBaseUrl set, EVERY RestDefinition carries exactly that value;
  - every asset declares exactly one top-level server, https://api.github.com, and no operation
    declares its own `servers` (oasgen refuses such a document when serverURL is set).

Usage: assert-server-url.py <repo root>
"""
import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from github_oas import render_chart  # noqa: E402

root = sys.argv[1] if len(sys.argv) > 1 else "."
URL = "https://ghe.example.invalid/api/v3"
errors = []


def rds(docs):
    return [d for d in docs if d.get("kind") == "RestDefinition"]


default = rds(render_chart(root))
if not default:
    sys.exit("rendered 0 RestDefinitions: the render is broken, not the chart clean")
for d in default:
    if "serverURL" in d["spec"]:
        errors.append("%s: spec.serverURL rendered with githubBaseUrl unset" % d["metadata"]["name"])

withurl = rds(render_chart(root, {"githubBaseUrl": URL}))
if len(withurl) != len(default):
    errors.append("RestDefinition count differs: %d unset, %d with githubBaseUrl" % (len(default), len(withurl)))
for d in withurl:
    got = d["spec"].get("serverURL")
    if got != URL:
        errors.append("%s: spec.serverURL is %r with githubBaseUrl=%s" % (d["metadata"]["name"], got, URL))

for path in sorted(glob.glob(os.path.join(root, "chart", "assets", "*.yaml"))):
    doc = yaml.safe_load(open(path))
    servers = [s.get("url") for s in doc.get("servers") or []]
    if servers != ["https://api.github.com"]:
        errors.append("%s: top-level servers is %s, expected exactly [https://api.github.com]" % (path, servers))
    for p, item in (doc.get("paths") or {}).items():
        if "servers" in item:
            errors.append("%s: path %s declares its own servers" % (path, p))
        for m, op in item.items():
            if isinstance(op, dict) and "servers" in op:
                errors.append("%s: %s %s declares its own servers" % (path, m.upper(), p))

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("ok: %d RestDefinitions; serverURL absent by default, %s on all when set; %d assets single-server"
      % (len(default), URL, len(glob.glob(os.path.join(root, "chart", "assets", "*.yaml")))))
