#!/usr/bin/env python3
"""Every kind's requests must match GitHub's OpenAPI, except where an exception says why not.

The chart follows GitHub's REST description as published (github/rest-api-description). For every
verb of every rendered RestDefinition, this check finds GitHub's operation on the same method and
path, and compares what the asset declares with what GitHub declares:

  param-renamed     a path parameter is spelled differently (positionally)
  query-dropped     a query parameter GitHub defines is not declared
  query-added       a query parameter GitHub does not define is declared
  body-dropped      GitHub takes a request body and the asset declares none (body-added: the reverse)
  dropped           a body property GitHub defines is not declared (recursing into nested objects)
  added             a body property GitHub does not define is declared
  required-added    the asset requires a property GitHub does not
  required-dropped  the asset declares a property GitHub requires, without requiring it
  union-flattened   GitHub declares a oneOf/anyOf of objects where the asset declares one object; the
                    asset is then also compared, field by field, with the merge of GitHub's members
  type-narrowed     the asset allows a strict subset of GitHub's types (e.g. string for string|integer)
  type-changed      the asset's type is not a subset of GitHub's (e.g. string for integer)
  enum-dropped      GitHub restricts the value to an enum the asset does not declare
  enum-added        the asset declares an enum where GitHub has none, or values GitHub does not list
  enum-narrowed     the asset's enum is a strict subset of GitHub's
  param-type        a path or query parameter's type differs (narrowed or changed)
  default           the asset declares a `default` (see DEFAULTS below)

Types ignore `nullable` and a `null` member, which oasgen does not carry into the CRD; a oneOf/anyOf
whose members are all bare types counts as the union of those types. Formats are NOT compared.

Every difference must be covered by an entry in hack/oas-adherence-exceptions.yaml, and every
entry must still match a difference: a restored field makes its entry stale, and the check fails
until the entry is removed. So the exceptions file is the complete, current list of deviations.

DEFAULTS. A CRD `default` is written by the apiserver into every CR, existing ones included, and
cannot be withdrawn afterwards (oasgen-provider#562). GitHub's own default applies only to a create
that omits the field, so leaving the field out is what keeps GitHub's behaviour. The rule
(Diego, 2026-11-10): new fields never copy GitHub's `default`; the defaults the chart already had
are frozen, each listed under `defaults:` with its value and GitHub's own (checked here, so the
file cannot misstate either).

RESPONSE DEFAULTS. A `default` in a RESPONSE schema is refused outright, with no exceptions list.
oasgen carries it into the generated CRD's status (measured with oasgen-render 0.63.1, 2026-11-13),
and there the apiserver's null pruning skips a defaulted field: a null that GitHub returns (for
example `merged_at` on an open pull request) would be stored as the default, so status would show a
value GitHub never sent. GitHub's own response schemas for these operations carry hundreds of
defaults, so copying one verbatim brings them along.

Usage: assert-oas-adherence.py <repo root> [exceptions file]
"""
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from github_oas import GITHUB_OAS_COMMIT, load_github_oas, render_chart, resolve  # noqa: E402

root = sys.argv[1] if len(sys.argv) > 1 else "."
exc_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, "hack", "oas-adherence-exceptions.yaml")
github = load_github_oas()
exc = yaml.safe_load(open(exc_path))
errors = []

if exc.get("github_oas_commit") != GITHUB_OAS_COMMIT:
    sys.exit("%s was written against GitHub OpenAPI %s, but the check pins %s: review the exceptions "
             "against the new description and update github_oas_commit with it"
             % (exc_path, exc.get("github_oas_commit"), GITHUB_OAS_COMMIT))


def norm(path):
    return re.sub(r"\{[^}]+\}", "{}", path)


github_paths = {norm(p): p for p in github["paths"]}


def flatten(doc, node):
    """A schema with allOf merged into one properties/required view."""
    node = resolve(doc, node)
    if not isinstance(node, dict):
        return {}
    if "allOf" not in node:
        return node
    out = {k: v for k, v in node.items() if k != "allOf"}
    props, req = dict(node.get("properties") or {}), list(node.get("required") or [])
    for part in node["allOf"]:
        part = flatten(doc, part)
        props.update(part.get("properties") or {})
        req += part.get("required") or []
        out.setdefault("type", part.get("type"))
    out["properties"], out["required"] = props, req
    return out


def join(path, key):
    return key if not path else path + "." + key


def types_of(doc, node):
    """The set of JSON types a schema admits, `null` excluded; None when it states none."""
    node = flatten(doc, node)
    if not isinstance(node, dict):
        return None
    t = node.get("type")
    if t:
        return frozenset([t] if isinstance(t, str) else t) - {"null"} or None
    members = node.get("oneOf") or node.get("anyOf")
    if members:
        out = set()
        for m in members:
            mt = types_of(doc, m)
            if mt is None:
                return None
            out |= mt
        return frozenset(out) - {"null"} or None
    return None


def compare_type_enum(adoc, a, g, path, out):
    ta, tg = types_of(adoc, a), types_of(github, g)
    if ta is not None and tg is not None and ta != tg:
        out.append(("type-narrowed" if ta < tg else "type-changed", path, None))
    a, g = flatten(adoc, a), flatten(github, g)
    ae = {json.dumps(v, sort_keys=True) for v in (a.get("enum") or []) if v is not None}
    ge = {json.dumps(v, sort_keys=True) for v in (g.get("enum") or []) if v is not None}
    if ge and not ae:
        out.append(("enum-dropped", path, None))
    elif ae and not ge:
        out.append(("enum-added", path, None))
    elif ae and ge and ae != ge:
        out.append(("enum-narrowed" if ae < ge else "enum-added", path, None))


def merge_union(node):
    """One object schema standing for every member of a oneOf/anyOf of objects (GitHub's side only).

    A flattened union in an asset is compared against this: a key any member defines is a key the
    union defines; enums are the union of the members' values; a key is required only when every
    member requires it. That is what an asset modelling the union as one object has to match.
    """
    members = [flatten(github, m) for m in (node.get("oneOf") or node.get("anyOf"))]
    props, req = {}, None
    for m in members:
        mreq = set(m.get("required") or [])
        req = mreq if req is None else (req & mreq)
        for k, v in (m.get("properties") or {}).items():
            props.setdefault(k, []).append(flatten(github, v))
    merged = {}
    for k, vs in props.items():
        if len(vs) == 1:
            merged[k] = vs[0]
            continue
        objs = [v for v in vs if v.get("properties")]
        if objs:
            merged[k] = merge_union({"oneOf": objs})
        else:
            base = dict(vs[0])
            enums = [e for v in vs for e in (v.get("enum") or [])]
            if enums and all(v.get("enum") for v in vs):
                base["enum"] = sorted(set(json.dumps(e, sort_keys=True) for e in enums))
                base["enum"] = [json.loads(e) for e in base["enum"]]
            merged[k] = base
    return {"type": "object", "properties": merged, "required": sorted(req or [])}


def compare(adoc, a, g, path, out, gdefaults):
    compare_type_enum(adoc, a, g, path, out)
    a, g = flatten(adoc, a), flatten(github, g)
    if "default" in a:
        out.append(("default", path, a["default"]))
        gdefaults[path] = g.get("default", None)
    ap, gp = a.get("properties") or {}, g.get("properties") or {}
    if not gp and (g.get("oneOf") or g.get("anyOf")) and ap:
        out.append(("union-flattened", path, None))
        g = merge_union(g)
        gp = g["properties"]
        if not gp:
            return
    if not ap and not gp:
        if "items" in a and "items" in g:
            compare(adoc, a["items"], g["items"], path + "[]", out, gdefaults)
        return
    for k in sorted(set(gp) - set(ap)):
        out.append(("dropped", join(path, k), None))
    for k in sorted(set(ap) - set(gp)):
        out.append(("added", join(path, k), None))
    areq, greq = set(a.get("required") or []), set(g.get("required") or [])
    for k in sorted(areq - greq):
        out.append(("required-added", join(path, k), None))
    for k in sorted((greq - areq) & set(ap)):
        out.append(("required-dropped", join(path, k), None))
    for k in sorted(set(ap) & set(gp)):
        compare(adoc, ap[k], gp[k], join(path, k), out, gdefaults)


def parameters(doc, path_item, op, where="query"):
    """{name: schema} of the operation's parameters in `where`, path-item ones included."""
    found = [resolve(doc, p) for p in (path_item.get("parameters") or []) + (op.get("parameters") or [])]
    return {p["name"]: p.get("schema") or {} for p in found if p.get("in") == where}


def param_type(adoc, aschema, gschema, label, out):
    ta, tg = types_of(adoc, aschema), types_of(github, gschema)
    if ta is not None and tg is not None and ta != tg:
        out.append(("param-type", label, None))


def body(op):
    return (((op or {}).get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")


docs = render_chart(root)
configmaps = {d["metadata"]["name"]: d.get("data") or {} for d in docs if d.get("kind") == "ConfigMap"}
found = {}      # (kind, METHOD, path, deviation, field) -> default value (None otherwise)
gh_default = {}
examined = 0
for rd in (d for d in docs if d.get("kind") == "RestDefinition"):
    kind = rd["spec"]["resource"]["kind"]
    for verb in rd["spec"]["resource"]["verbsDescription"]:
        oas_path = verb.get("oasPath") or rd["spec"]["oasPath"]
        _, cm, key = oas_path[len("configmap://"):].split("/", 2)
        adoc = yaml.safe_load(configmaps[cm][key])
        path, method = verb["path"], verb["method"].lower()
        aop = adoc["paths"][path][method]
        gpath = github_paths.get(norm(path))
        gop = github["paths"].get(gpath, {}).get(method) if gpath else None
        if gop is None:
            errors.append("%s %s %s: GitHub's description has no such operation" % (kind, method.upper(), path))
            continue
        examined += 1
        out, gdefaults = [], {}
        for mine, theirs in zip(re.findall(r"\{([^}]+)\}", path), re.findall(r"\{([^}]+)\}", gpath)):
            if mine != theirs:
                out.append(("param-renamed", "%s<-%s" % (mine, theirs), None))
        ap_ = parameters(adoc, adoc["paths"][path], aop, "path")
        gp_ = parameters(github, github["paths"][gpath], gop, "path")
        for mine, theirs in zip(re.findall(r"\{([^}]+)\}", path), re.findall(r"\{([^}]+)\}", gpath)):
            if mine in ap_ and theirs in gp_:
                param_type(adoc, ap_[mine], gp_[theirs], mine, out)
        aq = parameters(adoc, adoc["paths"][path], aop)
        gq = parameters(github, github["paths"][gpath], gop)
        out += [("query-dropped", q, None) for q in sorted(set(gq) - set(aq))]
        out += [("query-added", q, None) for q in sorted(set(aq) - set(gq))]
        for q in sorted(set(aq) & set(gq)):
            param_type(adoc, aq[q], gq[q], "?" + q, out)
        ab, gb = body(aop), body(gop)
        if ab is not None and gb is None:
            out.append(("body-added", "", None))
        elif ab is None and gb is not None:
            out.append(("body-dropped", "", None))
        elif ab is not None:
            compare(adoc, ab, gb, "", out, gdefaults)
        for deviation, field, value in out:
            k = (kind, method.upper(), path, deviation, field)
            found[k] = value
            if deviation == "default":
                gh_default[k] = gdefaults[field]

if examined == 0:
    sys.exit("examined 0 operations: the render or the RestDefinition walk is broken, not the chart clean")


def response_defaults(doc, node, path, out, seen, counter):
    """Every `default` under a response schema node; counter[0] counts the nodes visited."""
    if isinstance(node, dict) and "$ref" in node:
        if node["$ref"] in seen:
            return
        seen = seen | {node["$ref"]}
        node = resolve(doc, node)
    if not isinstance(node, dict):
        return
    counter[0] += 1
    if "default" in node:
        out.append((path or ".", node["default"]))
    for k, v in (node.get("properties") or {}).items():
        response_defaults(doc, v, join(path, k), out, seen, counter)
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            response_defaults(doc, node[key], path + ("[]" if key == "items" else ".*"), out, seen, counter)
    for key in ("allOf", "anyOf", "oneOf"):
        for member in node.get(key) or []:
            response_defaults(doc, member, path, out, seen, counter)


response_nodes = [0]
for rd in (d for d in docs if d.get("kind") == "RestDefinition"):
    kind = rd["spec"]["resource"]["kind"]
    for verb in rd["spec"]["resource"]["verbsDescription"]:
        oas_path = verb.get("oasPath") or rd["spec"]["oasPath"]
        _, cm, key = oas_path[len("configmap://"):].split("/", 2)
        adoc = yaml.safe_load(configmaps[cm][key])
        aop = adoc["paths"][verb["path"]][verb["method"].lower()]
        for code, resp in sorted((aop.get("responses") or {}).items()):
            schema = ((resolve(adoc, resp).get("content") or {}).get("application/json") or {}).get("schema")
            hits = []
            if schema is not None:
                response_defaults(adoc, schema, "", hits, frozenset(), response_nodes)
            for field, value in hits:
                errors.append("DEFAULT IN RESPONSE %s %s %s %s %s = %s: oasgen carries it into status, where a null "
                              "from GitHub would be stored as this value; remove it (see RESPONSE DEFAULTS in this "
                              "script's docstring)" % (kind, verb["method"].upper(), verb["path"], code, field, json.dumps(value)))
if response_nodes[0] == 0:
    sys.exit("walked 0 response schema nodes: the response walk is broken, not the chart clean")

# Every difference must be covered exactly once, and every exception must still match one.
covered = {}
for i, e in enumerate(exc.get("exceptions") or []):
    for field in e["fields"]:
        k = (e["kind"], e["method"], e["path"], e["deviation"], field)
        if k in covered:
            errors.append("exception %s and %s both cover %s" % (covered[k], e.get("row", i), k))
        covered[k] = e.get("row", i)
        if k not in found:
            errors.append("stale exception (row %s): %s %s %s %s %s is no longer a deviation; remove it"
                          % (e.get("row", i), *k))
for i, d in enumerate(exc.get("defaults") or []):
    k = (d["kind"], d["method"], d["path"], "default", d["field"])
    if k in covered:
        errors.append("default %s is listed twice" % (k,))
    covered[k] = "defaults[%d]" % i
    if k not in found:
        errors.append("stale default: %s %s %s %s is no longer declared; remove it" % (d["kind"], d["method"], d["path"], d["field"]))
        continue
    if found[k] != d["value"]:
        errors.append("default %s %s %s %s is %s in the asset, the exceptions file says %s"
                      % (d["kind"], d["method"], d["path"], d["field"], json.dumps(found[k]), json.dumps(d["value"])))
    if gh_default[k] != d["github"]:
        errors.append("default %s %s %s %s: GitHub's default is %s, the exceptions file says %s"
                      % (d["kind"], d["method"], d["path"], d["field"], json.dumps(gh_default[k]), json.dumps(d["github"])))
for k in sorted(set(found) - set(covered)):
    if k[3] == "default":
        errors.append("NEW DEFAULT %s %s %s %s = %s: do not copy a default into an asset (it is materialized "
                      "into every existing CR, oasgen-provider#562); see this script's docstring"
                      % (k[0], k[1], k[2], k[4], json.dumps(found[k])))
    else:
        errors.append("undocumented deviation from GitHub's OpenAPI: %s %s %s %s %s; follow GitHub's "
                      "description, or add an exception that says why not" % k)

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("ok: %d operations, %d deviations, every one covered by a reasoned exception; %d response schema nodes, "
      "none with a default (GitHub OpenAPI %s)" % (examined, len(found), response_nodes[0], GITHUB_OAS_COMMIT[:12]))
