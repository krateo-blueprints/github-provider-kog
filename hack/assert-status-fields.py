#!/usr/bin/env python3
"""Every additionalStatusFields path must exist in the response schema that fills it.

A status field is copied from the get response (findby when the kind has no get), and its CRD type
comes from that same schema. A path the schema does not have can never be filled: the CRD gains the
property, the resource goes Ready, and the field stays empty forever. Nothing at runtime says so.

Could not look is not the same as absent. Every failure to find the document, the verb, the
operation or a JSON response schema is reported as its own error, naming the step, and never as a
missing field. A schema this check cannot descend (oneOf, anyOf, an object with no properties) is
also its own error, because a path under it is unknown rather than wrong. Checking zero
declarations is an error too, since a check that looked at nothing proves nothing.

Adapted from krateo-blueprints/krateo-arubacloud-provider-kog scripts/validate.py (#56).
Usage: assert-status-fields.py <repo root>
"""
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
    chart = os.path.join(tmp, "chart")
    shutil.copytree(os.path.join(root, "chart"), chart)
    meta = os.path.join(chart, "Chart.yaml")
    text = open(meta).read().replace("CHART_VERSION", "0.0.0").replace("APP_VERSION", "0.0.0")
    open(meta, "w").write(text)
    rendered = subprocess.run(
        ["helm", "template", "x", chart, "-n", NAMESPACE],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
docs = [d for d in yaml.safe_load_all(rendered) if d]

configmaps = {
    (d["metadata"].get("namespace", NAMESPACE), d["metadata"]["name"]): d.get("data") or {}
    for d in docs
    if d.get("kind") == "ConfigMap"
}


def deref(doc, node):
    """Follow local $refs. Returns None when a ref cannot be followed."""
    seen = set()
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return None
        seen.add(ref)
        cur = doc
        for seg in ref[2:].split("/"):
            if not isinstance(cur, dict) or seg not in cur:
                return None
            cur = cur[seg]
        node = cur
    return node


def properties(doc, schema):
    """The properties a path segment can name, or a string saying why they cannot be known."""
    schema = deref(doc, schema)
    if not isinstance(schema, dict):
        return "a $ref that does not resolve"
    if schema.get("type") == "array":
        return properties(doc, schema.get("items"))
    if "oneOf" in schema or "anyOf" in schema:
        return "oneOf/anyOf"
    out = dict(schema.get("properties") or {})
    for sub in schema.get("allOf") or []:
        sub_props = properties(doc, sub)
        if isinstance(sub_props, str):
            return f"allOf member with {sub_props}"
        out.update(sub_props)
    if not out:
        return "an object that declares no properties"
    return out


examined = 0
for d in docs:
    if d.get("kind") != "RestDefinition":
        continue
    res = d["spec"]["resource"]
    kind = res["kind"]
    fields = res.get("additionalStatusFields") or []
    if not fields:
        continue

    oas = d["spec"].get("oasPath", "")
    parts = oas[len("configmap://"):].split("/") if oas.startswith("configmap://") else []
    if len(parts) != 3:
        errors.append(f"{kind}: cannot parse oasPath {oas!r}, so its status fields were NOT checked")
        continue
    data = configmaps.get((parts[0], parts[1]))
    if data is None or parts[2] not in data:
        errors.append(f"{kind}: no ConfigMap {parts[0]}/{parts[1]} with key {parts[2]!r}, so its status fields were NOT checked")
        continue
    try:
        doc = yaml.safe_load(data[parts[2]])
    except yaml.YAMLError as exc:
        errors.append(f"{kind}: {parts[2]} does not parse ({exc}), so its status fields were NOT checked")
        continue

    verbs = {v["action"]: v for v in res.get("verbsDescription") or []}
    which = "get" if "get" in verbs else "findby" if "findby" in verbs else None
    if which is None:
        errors.append(f"{kind}: declares additionalStatusFields but has no get or findby verb, so nothing can fill them")
        continue
    verb = verbs[which]
    op = ((doc.get("paths") or {}).get(verb["path"]) or {}).get(verb["method"].lower())
    if not op:
        errors.append(f"{kind}: {verb['method']} {verb['path']} ({which}) is not in {parts[2]}, so its status fields were NOT checked")
        continue
    schema = None
    for code in ("200", "201", "default"):
        resp = deref(doc, (op.get("responses") or {}).get(code))
        if isinstance(resp, dict):
            schema = ((resp.get("content") or {}).get("application/json") or {}).get("schema")
            if schema:
                break
    if not schema:
        errors.append(f"{kind}: the {which} operation has no JSON response schema, so its status fields were NOT checked")
        continue

    for field in fields:
        examined += 1
        node = schema
        segments = field.split(".")
        for i, seg in enumerate(segments):
            props = properties(doc, node)
            prefix = ".".join(segments[:i]) or "<response root>"
            if isinstance(props, str):
                errors.append(f"{kind}: cannot resolve {field!r}: {prefix} is {props} in the {which} response schema, so it was NOT checked")
                break
            if seg not in props:
                errors.append(
                    f"{kind}: additionalStatusFields {field!r} is absent from the {which} response schema "
                    f"(first missing segment {'.'.join(segments[:i + 1])!r}). It can never be filled."
                )
                break
            node = props[seg]

if examined == 0:
    errors.append("examined 0 additionalStatusFields declarations: the check looked at nothing")
print(f"Checked {examined} additionalStatusFields declaration(s)")
for error in errors:
    print(error, file=sys.stderr)
if errors:
    sys.exit(1)
