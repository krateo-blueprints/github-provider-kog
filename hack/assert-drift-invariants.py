#!/usr/bin/env python3
"""Assert the drift-reconciliation invariants that exist only as ABSENCES in an OAS asset.

Three fixes in this chart are shaped the same way: a field was removed from an update request
body so that drift reconciliation could no longer act on it. Nothing about that survives in the
generated CRD, and nothing validates it — the guarantee is a field NOT being written, plus a
`compareScope` that is not the default. Both are one careless edit from being undone, with no
error and nothing failing.

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
]


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
