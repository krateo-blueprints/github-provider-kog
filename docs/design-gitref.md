---
type: Architecture
title: github-provider-kog — GitRef restoration design
description: How the GitRef kind would come back to github-provider-kog natively after the companion plugin is deleted — the ref-form asymmetry solved with a create-side requestTransform (or a findby hybrid), the base-sha dependent read that oasgen-provider 0.23.0 still cannot express, and why spec.sha must never be lifted to the response root.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [design, gitref, oasgen-provider, rest-dynamic-controller, github, plugin-removal]
timestamp: 2026-09-09T00:00:00Z
---

# GitRef — restoration design

`GitRef` is being removed from the chart along with `RepoContent`, `PullRequest` and the
companion plugin, because the frontend now publishes through a `BuilderPublish` claim over
`git-provider` (`AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"`), leaving the
`github.krateo.io` route as the `"false"` fallback nobody takes. This is the design that
brings it back **natively**, so the knowledge outlives the code.

Everything below is against **oasgen-provider / rest-dynamic-controller 0.23.0**
(`~/krateo/krateo-oasgen-provider`, tag `0.23.0`, monorepo layout `go/oasgen-provider` +
`go/rest-dynamic-controller`) and chart commit **be409bc**.

## 1. What the kind did

A `GitRef` CR is one git reference — in practice the `builder/*` branch the blueprint
author writes a chart tree onto. It is second in the authoring chain: `Repository` →
**`GitRef`** → `RepoContent` (per file) → `PullRequest`.

| verb | method + path (`rd-gitref.yaml:17-31`) | routed to |
|---|---|---|
| create | `POST /repos/{owner}/{repo}/git/refs` | **plugin** (`gitref.yaml:9-11` `servers:` override) |
| get | `GET /gitref/{owner}/{repo}/{ref}` | **plugin** (`gitref.yaml:38-40`) |
| update | `PATCH /repos/{owner}/{repo}/git/refs/{ref}` | GitHub |
| delete | `DELETE /repos/{owner}/{repo}/git/refs/{ref}` | GitHub |

Two of four verbs were proxied. The two that were not **did not work**: both address the
ref by `{ref}`, which auto-populates from `spec.ref` (`refs/heads/x`), and GitHub's per-ref
write endpoints take the ref *without* the `refs/` prefix. Probed today:

```
GET /repos/krateo-platformops/oasgen-provider/git/refs/refs%2Fheads%2Fmain  -> 404
GET /repos/krateo-platformops/oasgen-provider/git/refs/heads%2Fmain         -> 200
GET /repos/krateo-platformops/oasgen-provider/git/ref/heads/main            -> 200
GET /repos/krateo-platformops/oasgen-provider/git/ref/refs/heads/main       -> 404
```

So update never fired and delete always 404'd. That is fixed on branch
`fix/gitref-update-delete-short-ref` (commit `02da887`, PR #7), never merged — §3.1 folds
it in.

Percent-encoding is **not** the problem. `%2F` is decoded by GitHub, including
multi-segment refs, plain or escaped:

```
/git/ref/heads/feat/multi-version-restdef        -> 200
/git/ref/heads%2Ffeat%2Fmulti-version-restdef    -> 200
/git/refs/heads%2Ffeat%2Fmulti-version-restdef   -> 200
```

The leading `refs/` is the whole problem.

The chart cost of the two overrides: `configmap-gitref.yaml` is `tpl`-rendered so
`{{ include "webServiceUrl" . }}` resolves to `http://<release>-plugin.<ns>.svc:8080`
(`_helpers.tpl:14-16`). Native, it is copied verbatim like `configmap-repository.yaml`.

## 2. The plugin, line by line

### 2.1 `getGitRef` — the path asymmetry (`plugin/main.go:110-119`)

```go
func getGitRef(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	ref := strings.TrimPrefix(r.PathValue("ref"), "refs/") // "refs/heads/x" -> "heads/x"   // :113
	status, body, ok := proxy(w, r, http.MethodGet, ".../git/ref/"+ref, nil)
```

One line of load-bearing code. Everything else is a pass-through — the comment at
`:102-109` is explicit that GitHub's get-ref body already carries `{ref, node_id, url,
object}` at the root with `ref` in the full form matching the CR identifier.

**Why it was needed.** Without it the observe GET 404s, the controller reports the resource
absent, re-issues create, and GitHub answers `422 Reference already exists` — forever. The
CR never reaches Ready even though the branch exists.

### 2.2 `createGitRef` — the base-sha dependent read (`plugin/main.go:129-143`)

```go
	reqBody, _ := io.ReadAll(r.Body)
	if jsonStringField(reqBody, "sha") == "" {                       // :133
		if sha := defaultBranchHeadSha(r, owner, repo); sha != "" {  // :134
			reqBody = withJSONField(reqBody, "sha", sha)             // :135
		}
	}
```

and (`:148-161`):

```go
	branch := jsonStringField(githubGet(r, ".../repos/"+owner+"/"+repo), "default_branch")  // :149
	if branch == "" { branch = "main" }                                                     // :150-152
	json.Unmarshal(githubGet(r, ".../git/ref/heads/"+branch), &m)                           // :154
	if obj, ok := m["object"].(map[string]any); ok {                                        // :157
		if sha, ok := obj["sha"].(string); ok { return sha }                                // :158-159
	}
```

**Why it was needed.** GitHub's create-ref requires `sha` — the commit the new ref points
at. A portal author (or Autopilot) creating `builder/demo` has no idea what the default
branch's HEAD is, so the CR omits it, the POST 422s `sha ... Required`, and the whole
publish set aborts. The handler turns *one* CR field into *two* extra GitHub reads:
repo → `default_branch`, then that branch's ref → `object.sha`.

This is a **pre-call dependent read**: two network calls whose results shape the request
body of a third.

## 3. Native replacements

Four runtime facts govern everything below.

1. **Request-direction jq `valueMapping` is dead code.** `builder.applyFieldMapping` hits
   `default: continue` before the `inPath`/`inQuery`/`inBody` write
   (`rest-dynamic-controller internal/tools/client/builder/builder.go:348-356`), and
   nothing rejects it at admission — it applies green and silently drops the field. The
   package doc states it as the one remaining gap
   (`internal/tools/fieldmapping/fieldmapping.go:22-25`). **Never propose one.**
2. **Path parameters auto-populate by NAME** from spec, then status
   (`builder.go:441-446`; spec wins, "avoid overwriting existing values"), and explicit
   `fieldMapping` runs LAST and overwrites unconditionally (`builder.go:359-365`).
3. **A response `fieldMapping` REMOVES its source key** unless the mapping is in-place or
   another entry writes to that key (`fieldmapping.go` package doc; the same trap is
   documented on `rd-collaborator.yaml:126-131`).
4. **The drift comparison skips a spec key the response does not carry** —
   `rmValue, ok := rm[key]; if !ok { continue }`
   (`internal/tools/comparison/comparison.go:47-52`).

### 3.1 The ref-form asymmetry — natively solved, two ways

**PR #7 first, because its lesson survives both shapes.** It derives the short form on the
*response* side, where jq actually runs, and relocates it into the path with a plain
`inPath` mapping and no value transform
(`git show fix/gitref-update-delete-short-ref:chart/templates/rd-gitref.yaml`):

```yaml
      - action: get
        fieldMapping:
          # KEEP THIS FIRST ENTRY. A response mapping REMOVES its source key unless the mapping is
          # in-place or another entry writes to that key. `ref` is an identifier: losing it from the
          # body breaks BOTH status population (populateStatusFields reads the normalized body,
          # controllers/helpers.go:110-118) and the drift comparison. This identity relocation pins
          # it AND makes `ref` a write target, shielding it from the removal pass for the entry below.
          - inResponse: ref
            inCustomResource: status.ref
          - inResponse: ref
            inCustomResource: status.shortRef
            valueMapping: { type: jq, jq: { inline: 'ltrimstr("refs/")' } }
      - action: update            # and delete, identically
        fieldMapping:
          - inPath: ref
            inCustomResource: status.shortRef   # plain relocation; a request-side jq would vanish
```

That fix is correct and **still necessary** for update and delete. It is **not sufficient**
once the plugin is gone, because on that branch the *get* still went through the proxy. A
native get must address the ref itself, and `status.shortRef` does not exist before the
first observe — `GET /git/ref/refs/heads/main` is a probed 404, so a cold CR would report
absent, create, and 422-loop exactly as before. The chicken-and-egg is the real design
problem; the trim is not.

#### Shape B — recommended: short-form `spec.ref` + a create `requestTransform`

Invert it. Make `spec.ref` the form four of five endpoints want (`heads/builder/demo`) and
add the prefix on the one that does not, in the request direction where a **whole-document**
jq *is* implemented — `requestTransform` runs from Create/Update/Delete after body assembly
(`fieldmapping.go:26-29`; call site `restResources.go:894` for delete, mirrored on create).

`chart/assets/gitref.yaml` — no `servers:` overrides anywhere:

```yaml
servers:
- url: https://api.github.com          # the ONLY server. No per-operation override, no plugin.
paths:
  "/repos/{owner}/{repo}/git/refs":
    post:
      operationId: git/create-ref
      parameters: [ {$ref: '#/components/parameters/owner'}, {$ref: '#/components/parameters/repo'} ]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                ref:
                  type: string
                  # SHORT form: "heads/builder/demo". The create endpoint wants the FULL
                  # "refs/heads/..." in the body; the create requestTransform adds the prefix.
                  #
                  # The pattern is the GUARD, and it is the reason this shape is safe to ship: a CR
                  # carrying the full form is rejected at ADMISSION instead of creating a branch the
                  # observe verb can never address (a silent create->422 loop). `pattern` survives
                  # CRD generation verbatim (plumbing v1.14.2 crdgen/transpile.go:500). RE2 has no
                  # lookahead, so it is an allow-list, not a negation of "refs/".
                  pattern: '^(heads|tags)/.+'
                sha:
                  type: string
                  # REQUIRED. See §3.2 — the alternative is not expressible at 0.23.0.
              required: [ref, sha]
      responses: { '201': { $ref: ... GitRef } }
  "/repos/{owner}/{repo}/git/ref/{ref}":     # singular `ref` — GitHub's per-ref READ endpoint
    get: { operationId: git/get-ref, ... }
  "/repos/{owner}/{repo}/git/refs/{ref}":    # plural `refs` — the per-ref WRITE endpoints
    patch:  { operationId: git/update-ref, requestBody: { properties: { sha: {type: string}, force: {type: boolean} } } }
    delete: { operationId: git/delete-ref, responses: { '204': ... } }
```

`chart/templates/rd-gitref.yaml`:

```yaml
    kind: GitRef
    identifiers:
      - ref
    additionalStatusFields:
      - node_id
      - url
      # The branch's CURRENT head commit, addressed by its nested path (populateStatusFields
      # supports dot notation, controllers/helpers.go:117-136; nested selectors are an 0.23.0 fix,
      # #106). Deliberately NOT lifted to a root `sha` — see §3.3. additionalStatusFields is
      # read-only against the response body, so unlike a fieldMapping it cannot perturb the compare.
      - object.sha
    # Projects the spec down to identifiers + additionalStatusFields, i.e. exactly {ref} — the one
    # spec key that is also a response key, and a tautology (we found the ref BY that ref), so it can
    # never report false drift. Chosen over fullSpec because it excludes `sha` STRUCTURALLY rather
    # than by the accident that GitHub nests the commit under object{} (§3.3).
    compareScope: identifiersAndStatus
    configurationFields: []
    verbsDescription:
      - action: create
        method: POST
        path: /repos/{owner}/{repo}/git/refs
        # The ONE transform the plugin's getGitRef existed to avoid needing, moved to the side where
        # it belongs. Tolerant of an author who wrote the full form anyway (belt and braces with the
        # OAS pattern above), and idempotent.
        requestTransform:
          inline: '.ref |= (if startswith("refs/") then . else "refs/" + . end)'
        # The create RESPONSE also populates status (restResources.go:556-561), so it needs the same
        # normalization as the get, or status.ref would hold the full form until the next observe
        # rewrote it — a flapping identifier.
        responseTransform:
          inline: '.ref |= ltrimstr("refs/")'
      - action: get
        method: GET
        path: /repos/{owner}/{repo}/git/ref/{ref}     # {ref} auto-populates from spec.ref (short)
        # Normalizes GitHub's full-form `ref` into the CR domain BEFORE status population and drift
        # comparison (fieldmapping.NormalizeResponseBody, restResources.go:346). Without it,
        # spec.ref "heads/x" compares against response "refs/heads/x" — permanent drift, a PATCH
        # every reconcile, forever.
        responseTransform:
          inline: '.ref |= ltrimstr("refs/")'
      - action: update
        method: PATCH
        path: /repos/{owner}/{repo}/git/refs/{ref}
        responseTransform:
          inline: '.ref |= ltrimstr("refs/")'         # restResources.go:720-725
      - action: delete
        method: DELETE
        path: /repos/{owner}/{repo}/git/refs/{ref}
```

Why this is the recommendation:

- **One GET per observe.** No list, no second call, no status dependency.
- **Cold-start and adoption both work.** The first observe of a CR whose branch already
  exists finds it, so no create → no 422 loop.
- **Delete is always addressable.** Its path parameter comes from `spec`, which always
  exists. That matters more than it looks — see the hazard under Shape A.
- **Tags work** (`tags/v1.0.0`), which a branch-scoped `findby` would not observe.
- The cost is a **CR-contract change**: `spec.ref` is `heads/x`, not `refs/heads/x`. The
  `pattern` converts that from a silent forever-loop into an apply-time rejection, which is
  what makes it acceptable to ship.

#### Shape A — alternative: keep the full-form contract, pay with a `findby`

If `spec.ref` must stay `refs/heads/x` (an existing caller you cannot change), the cold
start needs an observe that matches on the **full** form. GitHub has one, and it is
unpaginated. Probed:

```
GET /git/matching-refs/heads            -> 200, array; items carry root "ref": "refs/heads/..."
GET /git/matching-refs/heads?per_page=2 -> 7 of 7 items   (per_page IGNORED, no Link header)
GET /git/matching-refs/?per_page=1      -> 151 of 151 items
GET /git/refs?per_page=1                -> 1 item          (paginated — NOT usable, see below)
```

`findby` matches each item's identifier against the CR's **spec first, status second**
(`internal/tools/client/clienttools.go:138-162`), so `identifiers: [ref]` matches
`refs/heads/x` exactly. And the controller picks `findby` over `get` automatically when the
get cannot be addressed: `IsResourceKnown` builds the get config and runs `ValidateRequest`
(`builder.go:416-431`), which fails on a missing required path parameter
(`clienttools.go:178-186`), and the else-branch takes `findby` (`restResources.go:218-222`).
Name the get's parameter something the spec does not carry and exclude it — the same
pattern `rd-autolink.yaml:19-23,50-52` and `rd-orgruleset.yaml` already use for a
server-assigned id:

```yaml
    identifiers: [ref]                       # full form
    additionalStatusFields: [node_id, url, object.sha, shortRef]
    excludedSpecFields: [short_ref]          # get/update/delete path param; never author-supplied
    compareScope: identifiersAndStatus
    verbsDescription:
      - action: create
        method: POST
        path: /repos/{owner}/{repo}/git/refs
        fieldMapping: &deriveShortRef
          - inResponse: ref                  # IDENTITY PIN — keep first (fact 3 above)
            inCustomResource: status.ref
          - inResponse: ref
            inCustomResource: status.shortRef
            valueMapping: { type: jq, jq: { inline: 'ltrimstr("refs/")' } }
      # COLD START and adoption. Unpaginated by GitHub's own behaviour (probed), which matters:
      # the controller's only pagination strategy is continuationToken, which re-sends a response
      # HEADER verbatim as a query parameter (types.go:40-74) and cannot read GitHub's Link header —
      # the same limitation documented on rd-collaborator.yaml:97-103. `/git/refs` IS paginated and
      # is therefore the wrong endpoint. Use `/git/matching-refs/` (no trailing segment) if the kind
      # must also observe TAGS cold; the body then carries every ref in the repository.
      - action: findby
        method: GET
        path: /repos/{owner}/{repo}/git/matching-refs/heads
        fieldMapping: *deriveShortRef
      - action: get                          # used from the second reconcile onward: one cheap GET
        method: GET
        path: /repos/{owner}/{repo}/git/ref/{short_ref}
        fieldMapping:
          - inPath: short_ref
            inCustomResource: status.shortRef
          - inResponse: ref
            inCustomResource: status.ref
          - inResponse: ref
            inCustomResource: status.shortRef
            valueMapping: { type: jq, jq: { inline: 'ltrimstr("refs/")' } }
      - action: update
        method: PATCH
        path: /repos/{owner}/{repo}/git/refs/{short_ref}
        fieldMapping: [ { inPath: short_ref, inCustomResource: status.shortRef } ]
      - action: delete
        method: DELETE
        path: /repos/{owner}/{repo}/git/refs/{short_ref}
        fieldMapping: [ { inPath: short_ref, inCustomResource: status.shortRef } ]
```

**The hazard that decides it.** Every write verb here is addressed from `status`. If
`status.shortRef` is ever missing on delete, `UnresolvedPathParams` fires and the
controller **releases the finalizer without calling the API**
(`restResources.go:883-892`) — the CR disappears and the branch is orphaned, with a `Warn`
log as the only trace. The comment there says so outright: "the identifier can also go
missing on a resource that DOES exist … that case orphans the external resource." Shape B
cannot reach that branch.

Both shapes are fully expressible at 0.23.0. Neither needs the plugin.

### 3.2 The base-sha resolution — NOT expressible

A pre-call dependent read has no representation in a RestDefinition:

- `FieldResolver.Type` is a one-value enum, `secretRef`
  (`oasgen-provider apis/restdefinitions/v1alpha1/types.go:172-182`).
- The jq engine has no network by construction, and a request-direction jq would be dropped
  anyway (§3, fact 1).
- `apiLookup` was removed; tracked as oasgen-provider **#120**.

There is no GitHub endpoint that creates a ref from a branch *name*: create-ref requires
`sha`, and `PUT /contents` will not create a branch either. Three honest options:

**(a) Require `spec.sha`.** *Recommended.* Fully native today, no new dependency, and it
makes the semantics honest (§3.3) instead of accidental. Cost: the caller must resolve the
base commit — one `GET /repos/{o}/{r}/git/ref/heads/{default_branch}` — before applying the
CR. That is precisely the work the plugin was doing, moved to the caller, and it is the
reason the plugin existed: the blueprint-publish path has no sha at hand. Note the branch
name need not be guessed if the composition also manages the repo — `Repository` publishes
`status.default_branch` (`rd-repository.yaml:22`) — but nothing in a RestDefinition can read
another CR's status, so a human or the composition must copy it.

**(b) `createApiRef`.** Delegate create to a snowplow RESTAction that runs the two GETs and
the POST (`types.go:535-546`). What it actually costs:

- The RDC needs `URL_SNOWPLOW` **and** `URL_AUTHN` set — plumbed only through
  `rdc.env`, whose default is `{}` (oasgen-provider `helm/oasgen-provider/values.yaml:220`,
  rendered by `assets/rdc/configmap.yaml:17-19`); empty disables apiRef resolution entirely
  (`rest-dynamic-controller main.go:57`, and `oasgen docs/configuration.md:94`).
- The RESTAction runs under **snowplow's** identity, not the CR's `configurationRef`, so the
  GitHub PAT must exist a second time as a credentialed Endpoint — a second credential, a
  different audit trail, different RBAC.
- The RESTAction **must be idempotent**: the controller re-invokes create every reconcile
  until observe reports existence, and create-ref answers 422 on an existing ref, so the
  RESTAction has to swallow that itself.
- A `get` or `findby` verb is CEL-required alongside it (`types.go:481`) — satisfied by §3.1.

Net: you delete a Deployment and a Service and gain a RESTAction, a chart dependency on
snowplow, and a duplicated secret. It removes the plugin *artifact*, not the moving part.

**(c) Wait for #120.** Nothing to build here, but the kind cannot ship sha-less create until
it lands. The precise shape of the fix: extend `FieldResolver.Type` past the `secretRef`
enum (`types.go:172-182`) with an API-call resolver, resolved in the hook that already
exists — `fieldmapping.ResolveRequestResolvers`, whose results are handed to
`BuildCallConfig` as `resolved` (`builder.go:44-47, 147`), with unresolved entries already
skipped rather than sent (`builder.go:325-330`). It would read:

```yaml
        fieldMapping:
          - inBody: sha
            resolver:
              type: apiCall          # DOES NOT EXIST — this is the #120 ask
              apiCall: { path: /repos/{owner}/{repo}/git/ref/heads/{base}, jq: .object.sha }
```

A `spec.base` field (default `main`) would reduce the plugin's *two* reads to one, so the
upstream ask is a single-GET resolver, not a chain.

**A second, cheaper upstream ask, worth stating separately:** wire jq in the request
direction — the `default: continue` at `builder.go:352-356`. It does **not** solve create
(jq has no network), but it dissolves §3.1 completely: `{ref}` on get/update/delete would be
`spec.ref` trimmed in place, with no contract change, no `findby`, and no status dependency.
Of the two, this is the smaller change and it retires more design debt.

### 3.3 `spec.sha` is a create-time input, not desired state

Found during this review and **not fixed anywhere**. Today `sha` escapes the drift
comparison only by luck: GitHub nests the commit under `object.sha`, so the response ROOT
has no `sha` key, and the comparison skips a spec key the response does not carry
(`comparison.go:47-52`). Had it been at the root, `fullSpec` would compare the *base* commit
the branch was cut from against its *current* head and issue `PATCH /git/refs/{ref}` to move
it back — destroying every commit made since (with `force: true`), or 422-looping on the
non-fast-forward (without).

The trap is one plausible-looking line away. Anyone adding

```yaml
        responseTransform:
          inline: '. + { sha: .object.sha }'    # DO NOT — makes the head commit a compared key
```

to expose the head commit "for convenience" arms it.

**Correct treatment.** Decide which resource the CR is, and say so:

1. **Branch-creation semantics (recommended).** `sha` is the base commit, an input consumed
   once. Never lift `object.sha` to a root `sha`; expose the head commit under a path that
   is not a spec key — `additionalStatusFields: [object.sha]` → `status.object.sha`, which
   reads the body without perturbing it. Set `compareScope: identifiersAndStatus` so `sha`
   is excluded *structurally* (the projected set is `{ref}`) rather than by GitHub's nesting.
   Drift that matters — someone deleted the branch — is the observe 404, not a body compare.
   The `PATCH` verb stays declared (it is the only way to force-move a ref, and
   `compareScope: updatable` requires an update verb) but under this scope it never fires.
2. **Ref-pin semantics.** `sha` is desired state: "this ref points here." Then `sha` should
   be required, `responseTransform` *should* lift `object.sha` to the root, `compareScope:
   updatable` compares exactly the PATCH body `{sha, force}`, and the controller reverts the
   ref on every push. Correct for a release tag. **Catastrophic for a working branch** — it
   would fight `RepoContent` on the very branch it created.

They are not compatible, and the CR must be one of them. For the blueprint-authoring chain,
(1) is the only defensible choice. Note that `force` never appears in any response, so it is
never compared under any scope; default it to `false` in the OAS.

## 4. Verdict

**Back today, with one caveat — and the caveat is a CR-contract change, not a workaround.**

- **observe, update, delete: fully native, no caveat.** Shape B needs three inline jq
  programs and no `fieldMapping` at all. Shape A costs one unpaginated ref listing per cold
  observe and carries the status-sourced-delete orphan hazard. Both are 0.23.0 features.
- **create: native only if `spec.sha` becomes required.** The sha-less convenience the
  plugin provided is **not expressible**, and no amount of RestDefinition YAML recovers it.
  `createApiRef` can host it, at the price of a snowplow dependency, a duplicated PAT under
  a different identity, and an idempotency requirement the RESTAction author must satisfy —
  a trade worth making only for a platform already committed to `*ApiRef` elsewhere.
- **What the caveat costs, concretely:** the caller performs one GitHub GET before applying
  the CR. For the legacy publish path, nobody was doing that — which is exactly why the
  plugin was written. Since that path now defaults to `BuilderPublish` over `git-provider`,
  the caveat lands on a caller that no longer exists, which is what makes a native
  restoration worth writing down rather than mourning.

Ranked, if someone picks this up: **Shape B + required `sha`** (native, one call per
observe, no new infrastructure) → **Shape A + required `sha`** (native, keeps the full-form
contract, accepts the listing and the delete hazard) → Shape B + `createApiRef` (only if
sha-less create is non-negotiable) → wait for #120 and the request-direction jq fix, which
together make the whole kind trivially native with **no** contract change at all.

## 5. What a reviewer must check

Traps specific to this kind, in the order they bite:

1. **`sha` must not be comparable.** Grep the RestDefinition for any `responseTransform` or
   `fieldMapping` writing a root-level `sha`. If one exists, the controller will PATCH the
   branch backwards. This is the highest-severity defect available in this file (§3.3).
2. **Which ref form is `spec.ref`?** Shape B's `pattern: '^(heads|tags)/.+'` must be present
   in the OAS and must reach the generated CRD (`kubectl explain gitref.spec.ref`, or read
   the CRD). Without it, an author writing `refs/heads/x` gets a green create followed by a
   permanent create→422 loop with no error pointing at the cause.
3. **Every response-side `ref` mapping needs its identity pin.** `ref` is the identifier; a
   `fieldMapping` that reads it without another entry writing to `ref` deletes it from the
   body, breaking both `populateStatusFields` and the comparison (§3, fact 3). Shape B avoids
   the class entirely by using `responseTransform` (whole-document, in place) instead.
4. **`responseTransform` must be on create, get AND update** — status is populated from all
   three responses (`restResources.go:346, 556, 720`). Miss one and `status.ref` flips
   between `heads/x` and `refs/heads/x` between reconciles.
5. **jq direction.** Any `valueMapping: {type: jq}` on an `inPath`/`inQuery`/`inBody` entry
   is dead on arrival and admits green (`builder.go:352-356`). Only `alias` runs in the
   request direction; a ref name is an open string, so `alias` is useless here.
6. **Shape A only — delete verification uses the GET, never the findby.**
   `externalResourceStillExists` builds `apiaction.Get` only
   (`internal/controllers/mutate_restaction.go:128-140`). A get whose path form is wrong
   404s, `resolveDeleteOutcome` reads that as "verifiably absent", and the finalizer is
   released over a branch that still exists — a silent orphan, not a wedged CR. (The wedged
   CR was the 0.21.1 behaviour; 0.23.0's arbiter fixed the wedge and made the failure quiet.)
7. **Shape A only — cold start must actually reach `findby`.** If the get's path parameter is
   named `ref` it auto-populates from `spec.ref` (`builder.go:441-446`), `IsResourceKnown`
   returns true, and `findby` is never called. It must be a distinct name (`short_ref`) and it
   must be in `excludedSpecFields`, or it becomes a required, author-supplied spec field.
8. **`identifiers` and `additionalStatusFields` are immutable**
   (`types.go:493, 497`, `self == oldSelf`). Iterating on the status shape means deleting and
   recreating the RestDefinition, which takes the generated CRD and every `GitRef` CR with it.
   Get the field set right before anything is applied to a shared cluster.
9. **Editing `spec.ref` on a live CR is not a rename.** Observe addresses the ref by that
   value; a change makes the CR observe a different ref, 404, and *create* it — orphaning the
   old branch rather than moving it. True under every `compareScope`; worth a docs line.
10. **The chart-level leftovers.** `configmap-gitref.yaml` must stop being `tpl`-rendered
    (copy `configmap-repository.yaml`), the `servers:` overrides must be gone from
    `assets/gitref.yaml`, and `webServiceUrl`/`pluginName` in `_helpers.tpl` must have no
    remaining callers before the plugin templates are deleted.
11. **Multi-segment refs, both encodings.** Verify `heads/builder/demo-branch` end to end.
    GitHub accepts both plain and `%2F`-escaped (probed above), and the `%252F` double-escape
    defect was real and is fixed in 0.23.0 (#113) — but that fix covered query values, and
    every ref here travels as a **path** parameter, so it is worth one live check rather than
    an inference.
