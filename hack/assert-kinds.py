#!/usr/bin/env python3
"""Every kind must be selectable, and selectable by its own name.

`kinds` in values.yaml picks what renders, and each rd-* and configmap-* template carries its own
guard naming its Kind. Nothing else connects those names. A guard that names the wrong Kind, or a
template with no guard, renders a RestDefinition without its OpenAPI ConfigMap (or the reverse), and
the schema enum would then accept a name that selects nothing. Helm reports neither.

Usage: assert-kinds.py <repo root>
"""
import glob
import json
import os
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "."
templates = os.path.join(root, "chart", "templates")
GUARD = re.compile(r'\A\{\{- if include "github-provider-kog\.kindEnabled" \(list \. "(\w+)"\) -\}\}\n')
END = "{{- end }}\n"
KIND = re.compile(r"^  resource:\n(?:\s*#.*\n)*\s+kind:\s*(\w+)\s*$", re.M)

errors = []
kinds = {}
for path in sorted(glob.glob(os.path.join(templates, "rd-*.yaml"))):
    stem = os.path.basename(path)[len("rd-"):-len(".yaml")]
    match = KIND.search(open(path).read())
    if not match:
        errors.append(f"{path}: no spec.resource.kind")
        continue
    kinds[stem] = match.group(1)

for stem, kind in kinds.items():
    for path in (os.path.join(templates, f"rd-{stem}.yaml"), os.path.join(templates, f"configmap-{stem}.yaml")):
        if not os.path.exists(path):
            errors.append(f"{path}: missing")
            continue
        text = open(path).read()
        guard = GUARD.match(text)
        if not guard:
            errors.append(f"{path}: first line is not the kindEnabled guard")
        elif guard.group(1) != kind:
            errors.append(f"{path}: guard names {guard.group(1)}, the kind is {kind}")
        if not text.endswith(END):
            errors.append(f"{path}: does not close the guard")

rendered = {os.path.basename(p) for p in glob.glob(os.path.join(templates, "*.yaml"))}
expected = {f"rd-{s}.yaml" for s in kinds} | {f"configmap-{s}.yaml" for s in kinds}
for name in sorted(rendered - expected):
    errors.append(f"{name}: template with no kind")

schema = json.load(open(os.path.join(root, "chart", "values.schema.json")))
enum = schema["properties"]["kinds"]["items"]["enum"]
if sorted(enum) != sorted(kinds.values()):
    errors.append(f"schema enum differs from the kinds: {sorted(set(enum) ^ set(kinds.values()))}")

for error in errors:
    print(error, file=sys.stderr)
if errors:
    sys.exit(1)
print(f"{len(kinds)} kinds selectable.")
