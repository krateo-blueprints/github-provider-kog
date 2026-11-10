#!/usr/bin/env python3
"""Assert the drift-reconciliation invariants that exist only as ABSENCES in an OAS asset.

Several fixes in this chart are shaped the same way: a guarantee that exists only as the
PRESENCE or ABSENCE of something in an asset/RD, with nothing in the generated CRD to enforce it
and nothing that fails when it is undone. Two are a field removed from an update request body so
drift can no longer act on it (plus a non-default `compareScope`); one is the get/update/delete path
parameter `name` keyed on status.name so a GitHub-normalised name stays addressable (#386). Each
is one careless edit from being undone, with no error and nothing failing.

  0.2.2  `name` out of Repository's PATCH body. It was in the `updatable` compare set, so a repo
         RENAMED on GitHub read as drift; the PATCH hit GitHub's rename redirect and returned 307.
         Had the redirect been followed, the reconcile would have renamed a live repository back
         to a stale name.

  0.3.1  `private` and `visibility` out of Repository's PATCH body (#11). Consumers render a
         Repository on every composition and core-provider's default UpgradePolicy is Automatic,
         so with these compared, a consumer changing its rendered value did not only affect NEW
         repositories — the next reconcile PATCHed the ones that already existed. portal#227 would
         have flipped live private repos public, believing it only affected new ones. Irreversible:
         forks, clones, caches and search indexing survive a flip back.

How the two halves work, so a future reader can check this file is still asserting the right thing
(rest-dynamic-controller, restResources.go + clienttools.go + builder/builder.go):

  * `compareScope: updatable` derives the compare set from the UPDATE verb's declared request body
    (`UpdatableBodyPaths`). A field absent from that body is never compared.
  * The outgoing request body is filtered to the fields the operation declares (`processFields`),
    so the field is not even SENT on a PATCH some other field's drift triggered.
  * The CRD spec is built by oasgen-provider from the CREATE body plus path/query params only
    (`getBaseSchemaForSpec` hardcodes the create action), so a create-body field still exists on
    the CR and is still honoured at create. That is why "create-only" works at all.

The second half matters as much as the first: under the DEFAULT `fullSpec`, every spec key the GET
echoes is compared regardless of the update body, and GitHub echoes `private`, `visibility` and
`name` on every GET. So `compareScope: updatable` is load-bearing on Repository, and removing the
line is the same regression as re-adding the field.

UserRepository (0.1.6) is Repository's user-owned sibling and is asserted identically: same three
fields out of its PATCH body, same load-bearing `compareScope: updatable`.

Exit 1 if any invariant is broken.
"""
import sys

import yaml

# (asset, update-operation path, HTTP method, create-operation path, {field: why})
ASSET_INVARIANTS = [
    (
        "chart/assets/repository.yaml",
        "/repos/{org}/{name}",
        "patch",
        "/orgs/{org}/repos",
        {
            "name": "drift would RENAME a live repository (0.2.2; GitHub's rename redirect returned 307)",
            "private": "drift would flip the exposure of repositories that already exist (#11) — irreversible",
            "visibility": "same hazard as `private`, and the more likely re-entry path (#11)",
        },
    ),
    # UserRepository is Repository's user-owned sibling (create POST /user/repos) and carries the
    # identical hazard: GitHub echoes name/private/visibility on every GET of a user repo too.
    (
        "chart/assets/userrepository.yaml",
        "/repos/{owner}/{name}",
        "patch",
        "/user/repos",
        {
            "name": "drift would RENAME a live user repository (same 307 redirect trap as Repository)",
            "private": "drift would flip the exposure of user repositories that already exist — irreversible",
            "visibility": "same hazard as `private`, and the more likely re-entry path",
        },
    ),
]

# (template, kind, how many verbs must key `name` on status.name, why it is load-bearing)
#
# 0.1.x  The get/update/delete own-identity path parameter `name` sources from status.name (the name
#        GitHub ACTUALLY assigned), not spec.name (oasgen-provider #386). GitHub normalises a
#        disallowed character on create ("my repo" -> "my-repo"); a GET built from spec.name then
#        404s while the repo exists, and the controller re-creates and loops on 422. Keying on
#        status.name addresses the real name instead. This holds ONLY because `name` is out of the
#        PATCH body (asserted above): otherwise tracking the real name would PATCH it back to
#        spec.name every reconcile. Removing either mapping silently re-opens #386, with nothing
#        failing — the same shape of invisible regression the rest of this file guards.
#
# Checked by text, not YAML: these are Helm templates, so `{{ ... }}` is not parseable.
NAME_STATUS_KEYING_INVARIANTS = [
    (
        "chart/templates/rd-repository.yaml",
        "Repository",
        3,  # get + update + delete
        "a GET/PATCH/DELETE built from spec.name misses a GitHub-normalised name: the GET 404s and loops on "
        "re-create (#386), and the DELETE would 404 or, worse, address a different repository",
    ),
    (
        "chart/templates/rd-userrepository.yaml",
        "UserRepository",
        3,  # get + update + delete (owner is keyed separately on status.owner.login)
        "same as Repository: the user-repo get/update/delete must address the name GitHub assigned, not spec.name (#386)",
    ),
]

# (template, kind, required compareScope, why it is load-bearing)
COMPARESCOPE_INVARIANTS = [
    (
        "chart/templates/rd-repository.yaml",
        "Repository",
        "updatable",
        "GitHub echoes name/private/visibility on every GET, so the default fullSpec would compare "
        "them back into the drift set even though the PATCH body omits them",
    ),
    (
        "chart/templates/rd-userrepository.yaml",
        "UserRepository",
        "updatable",
        "same as Repository: GitHub echoes name/private/visibility on every GET of a user repo, so "
        "the default fullSpec would compare them back into the drift set",
    ),
]


# (template, kind, field, why it is load-bearing)
#
# oasgen takes the spec BODY from create but merges PARAMETERS from every verb, so a findby query
# parameter is a spec field unless a mapping supplies it or excludedSpecFields names
# it. These entries are what keep them off the CRD (measured by rendering without them on oasgen
# 0.43.0 and 0.51.0). excludedSpecFields is immutable (#290), but that protects a live CRD, not a
# fresh install: removing an entry here would ship the field to every new cluster.
#
# Checked by text, not YAML: these are Helm templates, so `{{ ... }}` is not parseable.
LOAD_BEARING_EXCLUSIONS = [
    ("chart/templates/rd-collaborator.yaml", "Collaborator", "affiliation",
     "pinned to direct by the verb's static query, which wins over spec: a spec field would be silently ignored"),
    ("chart/templates/rd-collaborator.yaml", "Collaborator", "per_page",
     "the paginator owns page size: not a field a CR can use"),
    ("chart/templates/rd-userrepository.yaml", "UserRepository", "affiliation",
     "pinned to owner by the verb's static query, which wins over spec: a spec field would be silently ignored"),
    ("chart/templates/rd-userrepository.yaml", "UserRepository", "sort",
     "pinned by the verb's static query, which wins over spec: a spec field would be silently ignored"),
    ("chart/templates/rd-userrepository.yaml", "UserRepository", "direction",
     "pinned by the verb's static query, which wins over spec: a spec field would be silently ignored"),
    ("chart/templates/rd-userrepository.yaml", "UserRepository", "per_page",
     "the paginator owns page size: not a field a CR can use"),
    ("chart/templates/rd-userrepository.yaml", "UserRepository", "page",
     "the paginator owns the page cursor: not a field a CR can use"),
]


def excluded_spec_fields(path):
    """The `- name` items of the excludedSpecFields block, by text."""
    entries, inside = [], False
    with open(path) as fh:
        for raw in fh:
            ln = raw.split("#", 1)[0].rstrip()
            if ln.strip() == "excludedSpecFields:":
                inside = True
            elif inside and ln.strip():
                if not ln.strip().startswith("- "):
                    break
                entries.append(ln.strip()[2:].strip())
    return entries


def body_properties(asset, doc, path, method):
    """The declared application/json request-body properties of one operation."""
    try:
        op = doc["paths"][path][method]
    except (KeyError, TypeError):
        sys.exit("%s: no %s operation on %s — this guard is stale, fix it deliberately"
                 % (asset, method.upper(), path))
    schema = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema", {})
    return set((schema.get("properties") or {}).keys())


def main(root="."):
    failures = []

    for asset, upd_path, upd_method, create_path, fields in ASSET_INVARIANTS:
        with open("%s/%s" % (root, asset)) as fh:
            doc = yaml.safe_load(fh)
        updatable = body_properties(asset, doc, upd_path, upd_method)
        creatable = body_properties(asset, doc, create_path, "post")
        for field, why in fields.items():
            if field in updatable:
                failures.append(
                    "%s: `%s` is back in the %s %s request body.\n    %s\n"
                    "    It must stay out of the update body: that is the whole mechanism."
                    % (asset, field, upd_method.upper(), upd_path, why))
            # A create-only field that left the CREATE body is no longer settable at all.
            if field != "name" and field not in creatable:
                failures.append(
                    "%s: `%s` is missing from the POST %s create body, so it is no longer a CR "
                    "spec field and cannot be set even at creation."
                    % (asset, field, create_path))

    for template, kind, expected, why in NAME_STATUS_KEYING_INVARIANTS:
        with open("%s/%s" % (root, template)) as fh:
            keyed = sum(
                1 for ln in fh if ln.split("#", 1)[0].strip() == "inCustomResource: status.name"
            )
        if keyed != expected:
            failures.append(
                "%s: %s must key `name` on status.name on exactly %d verb(s) (get, update and delete), "
                "found %d `inCustomResource: status.name` mapping(s).\n    %s\n"
                "    This is the #386 fix; a verb keyed on spec.name misses a normalised name."
                % (template, kind, expected, keyed, why))

    for template, kind, field, why in LOAD_BEARING_EXCLUSIONS:
        if field not in excluded_spec_fields("%s/%s" % (root, template)):
            failures.append(
                "%s: %s no longer lists `%s` in excludedSpecFields, so it becomes a spec field "
                "(oasgen merges parameters from every verb).\n    %s"
                % (template, kind, field, why))

    for template, kind, required, why in COMPARESCOPE_INVARIANTS:
        with open("%s/%s" % (root, template)) as fh:
            lines = [ln.strip() for ln in fh if ln.strip().startswith("compareScope:")]
        found = [ln.split(":", 1)[1].strip() for ln in lines]
        if found != [required]:
            failures.append(
                "%s: %s must declare exactly `compareScope: %s`, found %s.\n    %s\n"
                "    Note the default IS fullSpec, so DELETING the line breaks this too."
                % (template, kind, required, found or "none", why))

    if failures:
        print("drift-invariant check FAILED:\n")
        for f in failures:
            print("  - %s\n" % f)
        return 1
    print("drift invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
