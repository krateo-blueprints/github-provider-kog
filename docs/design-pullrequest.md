---
type: Architecture
title: github-provider-kog — restoring `PullRequest` natively
description: What the plugin's `GET /repos/{owner}/{repo}/pulls/{number}` handler did for PullRequest, why it was needed, and the exact native replacement at oasgen-provider 0.23.0 — a whole-document `responseTransform` on the get verb plus `compareScope: updatable` — with the idempotency proof, the rejected alternatives, and the traps a reviewer must check.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, restdefinition, oasgen-provider, rest-dynamic-controller, github, pullrequest, plugin-removal]
timestamp: 2026-09-09T00:00:00Z
---

# Restoring `PullRequest` natively

`PullRequest` was removed from the chart with `GitRef` and `RepoContent`, and the proxy plugin with
it. This is the design that brings it back **without** the plugin.

> **IMPLEMENTED.** This design shipped as written — `chart/assets/pullrequest.yaml`,
> `chart/templates/{configmap,rd}-pullrequest.yaml` and `chart/samples/test-pullrequest.yaml`. The
> chart renders 29 ConfigMaps + 29 RestDefinitions and still ships no runtime component. The
> idempotency table in §3 was re-run against the shipped program with gojq 0.12.19 and reproduces
> exactly, including the live `octocat/Hello-World#2846` cross-repo body at 48 keys in and 48 out.
> `GitRef` and `RepoContent` remain out; their design documents remain proposals.
>
> _Update (2026-10-28): `GitRef` has since also returned natively — the chart is now 30 kinds and
> requires oasgen-provider ≥ 0.38.0, where the pattern admission guard reaches the CRD; its dependent lookups (0.36.0) resolve the base sha that blocked it.
> `RepoContent` is the one still out. See [log](./log.md) and [design-gitref](./design-gitref.md)._
>
> _Update (2026-10-31): `RepoContent` has since returned natively too — the chart is now **31 kinds**. See [design-repocontent](./design-repocontent.md)._

File references to the three removed kinds are to commit **`be409bc`** (`git show
HEAD:chart/templates/rd-pullrequest.yaml`); the deletions are already staged in the working tree.
Controller references are to `krateo-rest-dynamic-controller` (`0.20.0-4-g217ccd0`) and
`krateo-oasgen-provider` (tag `0.23.0`).

## 1. What the kind did

`PullRequest` opens the PR at the end of the legacy blueprint-publish chain — `Repository` →
`GitRef` → `RepoContent` (per file) → `PullRequest` (`docs/api.md:159`). One CR, one PR:

```yaml
# chart/samples/test-pullrequest.yaml@be409bc:9-17
spec:
  owner: krateo
  repo: krateo-blueprints
  head: builder/demo-branch
  base: main
  title: "Add demo blueprint (authored via Krateo)"
  body: "This blueprint chart was authored in the Krateo portal Autopilot rail."
```

| verb | route | through the plugin? |
|---|---|---|
| create | `POST /repos/{owner}/{repo}/pulls` | no — straight to `api.github.com` |
| get (observe) | `GET /repos/{owner}/{repo}/pulls/{pull_number}` | **yes** |
| update | `PATCH /repos/{owner}/{repo}/pulls/{pull_number}` | no — straight to `api.github.com` |
| delete | — | **does not exist**; see §7 |

`pull_number` is `excludedSpecFields` and get/update source it from `status.number` via
`requestFieldMapping` (`rd-pullrequest.yaml@be409bc:19-36`) — that half is already native and is not
in question. Exactly **one** verb was proxied, and exactly **one** behaviour lived there.

The routing was the per-operation `servers:` override:

```yaml
# chart/assets/pullrequest.yaml@be409bc:46-51
    get:
      # Observe goes through the plugin (getPullRequest) so head/base OBJECTS are flattened to
      # their ref STRINGS — otherwise the controller's spec(string)-vs-response(object) compare
      # loops "update" and 422s on the closed PR. Rendered via `tpl` (see configmap-pullrequest).
      servers:
      - url: {{ include "webServiceUrl" . }}
```

which resolves to `http://<release>-plugin.<ns>.svc:8080` (`_helpers.tpl@be409bc:14-16`) and only
works because the ConfigMap is `tpl`-rendered rather than a plain `.Files.Get`
(`configmap-pullrequest.yaml@be409bc:7-11`).

## 2. What the handler actually does

Two functions, ~40 lines, one behaviour.

```go
// plugin/main.go:196-213
func flattenPRRefs(body []byte) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	for _, k := range []string{"head", "base"} {
		if obj, isObj := m[k].(map[string]any); isObj {
			if ref, ok := obj["ref"].(string); ok {
				m[k] = ref
			}
		}
	}
	...
}
```

```go
// plugin/main.go:218-230 (getPullRequest) — proxy, then flatten on 2xx only
	status, body, ok := proxy(w, r, http.MethodGet, "https://api.github.com/repos/"+owner+"/"+repo+"/pulls/"+number, nil)
	if status >= 200 && status < 300 {
		body = flattenPRRefs(body)
	}
```

Note what it is **not**: no path rewriting (unlike `getGitRef`), no query translation, no retry, no
dependent read, no body canonicalization (unlike `getRepoContent`). It is a pure, stateless,
single-document reshape of the response — the cleanest of the three, exactly as expected.

**Why it was needed.** The plugin's own comment states the failure, and the runtime confirms every
step of it:

```go
// plugin/main.go:188-195
// GitHub's get-PR returns head/base as OBJECTS ({ref, sha, repo, ...}); the CR's spec.head /
// spec.base are the plain branch-name STRINGS the create body carried. The controller's
// spec-vs-response compare (compareExisting) then hits "types differ" (string vs map) at head,
// decides the CR needs an update, and issues a PATCH — which 422s on an already-merged/closed PR
// (and is spurious even on an open one) — so the CR loops "Creating" forever ...
```

Verified against a live PR (unauthenticated `GET`, 2026-09-09):

```console
$ curl -s https://api.github.com/repos/octocat/Hello-World/pulls/2846 | jq '.head|keys, .head.ref, .head.label'
["label","ref","repo","sha","user"]
"master"
"BotBox3-GmbH:master"
```

and the comparison path:

1. `spec.head` is a **string** (it is the create body's `head`, `assets/pullrequest.yaml@be409bc:22-25`);
   the response `head` is a **map**.
2. `CompareExisting` iterates the spec, finds `head` present in the response
   (`internal/tools/comparison/comparison.go:47`, so the "absent keys are skipped" escape does **not**
   apply), takes the scalar branch on the spec side (`comparison.go:147-149`) and calls `CompareAny`.
3. `CompareAny` stringifies both sides (`comparison.go:277-287`): `"builder/x"` vs
   `"map[label:... ref:builder/x ...]"` → **not equal**. No panic, no error — just permanent drift.
4. Drift → `Update` → `PATCH`. The modelled PATCH body is `title`, `body`, `state`, `base`
   (`assets/pullrequest.yaml@be409bc:78-86`) — **`head` is not in it**. The PATCH cannot change what
   the comparison objects to, so the next observe reports the same difference. One `GET` + one
   `PATCH` per reconcile, forever, against a 5000 req/hr budget — and on a closed or merged PR the
   PATCH itself fails.

The drift is **unfixable by construction**, which is why this is a hard loop rather than a slow one.

## 3. The native replacement

One field: a whole-document `responseTransform` on the get verb. It is
documented upstream as the declarative form of exactly this plugin
(`docs/USAGE_GUIDE.md` in [krateo-platformops/oasgen-provider](https://github.com/krateo-platformops/oasgen-provider)):

> For simple cases of this problem, the declarative `fieldMapping` (with an `inResponse` anchor) or a
> `responseTransform` jq program in the RestDefinition can do the same normalization without a plugin
> — oasgen-provider `docs/USAGE_GUIDE.md:595`

**It exists at 0.23.0** — `krateo-oasgen-provider` tag `0.23.0`,
`go/oasgen-provider/apis/restdefinitions/v1alpha1/types.go:297-302`:

> ResponseTransform is a whole-document gojq program applied to the raw response body once, at the
> reconcile chokepoint, before per-field fieldMapping, status population and drift comparison. […]
> It is the declarative form of a plugin's whole-body response normalizer.

**Where it runs**, verified in the controller rather than taken from the doc comment:

| step | citation |
|---|---|
| observe body arrives (get XOR findby; `observeAction = "get"`) | `internal/controllers/restResources.go:181-215` |
| `notFoundBody` predicate — reads the **raw** body, *before* normalization | `restResources.go:296-300` |
| `NormalizeResponseBody(…, []string{observeAction}, b)` | `restResources.go:346` |
| ├ whole-document `responseTransform` first | `internal/tools/fieldmapping/fieldmapping.go:71-76` |
| └ then per-entry response `fieldMapping` | `fieldmapping.go:78-102` |
| `populateStatusFields` (status sees the transformed body) | `restResources.go:351` |
| `compareScope` projection, then `isCRUpdated` | `restResources.go:375-393` |

So the ordering the brief asks about is: **`responseTransform` → per-field `fieldMapping` → status
population → drift comparison**. `PullRequest` declares no response `fieldMapping`, so the
"a response `fieldMapping` removes its source key" rule (`fieldmapping.go:96-101`) never fires here —
one less trap than `TeamRepo` or `Collaborator` carry.

### The program

```jq
. as $r
| ((($r.head | type) == "object") and (($r.base | type) == "object")
   and ((($r.head.repo.full_name) // "") != (($r.base.repo.full_name) // ""))) as $cross
| (if (.head | type) == "object" then .head = (if $cross then .head.label else .head.ref end) else . end)
| (if (.base | type) == "object" then .base = .base.ref else . end)
```

Three deliberate choices:

- **`base` is always `.ref`.** GitHub's create API requires `base` to be a branch that exists in the
  base repository, so `spec.base` is always a bare branch name. `.base.label` (`"octocat:master"` in
  the probe above) would be permanent drift.
- **`head` is `.ref` for a same-repo PR and `.label` for a cross-repo one.** This is a **fix** to the
  plugin, not a transcription of it: `flattenPRRefs` (`plugin/main.go:203`) always takes `obj["ref"]`,
  so a PR opened from a fork — whose `spec.head` must be written `"owner:branch"` — flattened to
  `"master"` and drifted anyway. The live probe is exactly that case (`head.ref` `"master"` vs
  `head.label` `"BotBox3-GmbH:master"`, `head.repo.full_name` `BotBox3-GmbH/Hello-World` ≠
  `base.repo.full_name` `octocat/Hello-World`). A deleted fork leaves `head.repo: null`, which
  `// ""` turns into the cross-repo branch — still `.label`, still right.
- **Type guards, not `//`.** See the idempotency proof.

### Idempotency, proved

Run through the same engine the controller uses — gojq **v0.12.19** (`krateo-rest-dynamic-controller/go.mod:10`),
same `helperLibrary` preamble and `WithEnvironLoader(nil)` sandbox as `jqengine.Compile`
(`internal/tools/jqengine/jqengine.go:43-77`), inputs including the live `pulls/2846` body:

| input | pass 1 | pass 2 | pass 3 |
|---|---|---|---|
| live cross-repo PR (48 keys) | `head:"BotBox3-GmbH:master"`, `base:"master"` | identical | identical |
| same-repo PR (the publish case) | `head:"builder/x"`, `base:"main"` | identical | identical |
| fork deleted (`head.repo: null`) | `head:"gone:x"`, `base:"main"` | identical | identical |
| `head`/`base` **absent** (`{"message":"Not Found"}`) | unchanged, 2 keys — **keys not resurrected** | identical | — |
| mixed: `head` string, `base` object | `head:"builder/x"`, `base:"main"` | identical | — |
| `head: null` | `head:null`, `base:"main"` | identical | — |

Key count 48 → 48 on the live body: the program **adds and removes nothing else**.

The naive form the brief warns about fails exactly as predicted, and worse than "wrong value" —
gojq's `//` does **not** swallow an indexing error:

```
prog:  . + {head: (.head.ref // .head), base: (.base.ref // .base)}
pass1  {"head":"builder/x","base":"main", ...}          ok
pass2  ERR  expected an object but got: string ("builder/x")
```

A jq runtime error is not cosmetic: `applyDocumentTransform` returns it (`fieldmapping.go:126-134`),
`NormalizeResponseBody` propagates it, and `Observe` returns `ExternalObservation{}, err`
(`restResources.go:346-349`) — the CR stops reconciling with a hard error.

The `. + {…}` shape has a second, quieter defect that the guarded form avoids: on a body that lacks
`head`/`base` it **creates them as `null`**, and a `null` on the response side against a spec string
is `"values differ (one is nil)"` (`comparison.go:57-68`) — inventing the very drift the transform
exists to remove. The `if … then … else . end` form leaves absent keys absent (row 4 above).

### The files, as they would be written

```yaml
# chart/templates/rd-pullrequest.yaml
apiVersion: ogen.krateo.io/v1alpha1
kind: RestDefinition
metadata:
  name: {{ .Release.Name }}-pullrequest
  namespace: {{ .Release.Namespace }}
spec:
  oasPath: configmap://{{ .Release.Namespace }}/{{ .Release.Name }}-pullrequest/pullrequest.yaml
  resourceGroup: {{ .Values.resourceGroup }}
  resource:
    kind: PullRequest
    identifiers:
      - number
    additionalStatusFields:
      - number
      - html_url
      - state
    # pull_number is a path parameter on get/update only, never a create parameter — and oasgen
    # builds the spec from the create operation alone — so it is not a spec field to begin with;
    # the excludedSpecFields entry below is a redundant no-op kept for immutability. get/update
    # source the path parameter from status.number via the requestFieldMapping below.
    excludedSpecFields:
      - pull_number
    # Compare exactly what the PATCH body can express. The CRD spec is built from the CREATE
    # body plus the create operation's own path/query parameters (getBaseSchemaForSpec hardcodes
    # the create action), so of the PATCH's four properties only title/body/base are spec fields —
    # `state` is not, because it lives in the PATCH body only — and the
    # effective compared set is {title, body, base}: all three are properties of the GET
    # response and all three are fixable by the PATCH.
    #
    # `fullSpec` is what this kind shipped with, and it is what made the plugin necessary; even
    # WITH the responseTransform below it stays wrong, because it also compares `draft` and
    # `maintainer_can_modify` — both in the create body, both echoed by the GET, neither in the
    # PATCH body. Mark a draft PR "ready for review" in the UI and a `draft: true` CR drifts
    # forever against an update that cannot carry `draft`.
    #
    # `identifiersAndStatus` would be actively dangerous: it projects the SPEC onto
    # identifiers + additionalStatusFields, and number/html_url/state are NONE of them spec
    # fields, so the projected set is EMPTY and CompareExisting returns equal unconditionally.
    # The CR would report Available whatever the PR's title, body or base said.
    compareScope: updatable
    configurationFields: []
    #
    # NO DELETE VERB — GitHub's REST API cannot delete a pull request. See the Issue kind for
    # the same shape; deleting the CR only stops Krateo managing the PR.
    verbsDescription:
      - action: create
        method: POST
        path: /repos/{owner}/{repo}/pulls
      - action: get
        method: GET
        path: /repos/{owner}/{repo}/pulls/{pull_number}
        requestFieldMapping:
          - inPath: pull_number
            inCustomResource: status.number
        # THE reason this kind needs no plugin. GitHub returns head/base as OBJECTS
        # ({ref,label,sha,repo,user}) while spec.head/spec.base are the branch STRINGS the
        # create body carried; compared raw, both read as permanent drift and the PATCH cannot
        # fix either (head is not even in the PATCH body). This rewrites them back into the CR
        # domain once, before status population and drift comparison.
        #
        # `base` is always .ref — GitHub requires base to be a branch of the base repository, so
        # spec.base is never the "owner:branch" form. `head` is .ref for a same-repo PR and
        # .label for a cross-repo one, because that is the form the create body must use; the
        # plugin always took .ref and therefore drifted on every fork PR.
        #
        # Type-guarded rather than `.head.ref // .head`: gojq does NOT swallow the indexing
        # error of `.ref` on a string, so the naive form fails the reconcile the second time it
        # sees an already-normalized body. This form is idempotent (verified over three passes
        # on a live PR body) and total — an absent head/base is left absent, not created as
        # null, which would itself be drift.
        responseTransform:
          inline: |
            . as $r
            | ((($r.head | type) == "object") and (($r.base | type) == "object")
               and ((($r.head.repo.full_name) // "") != (($r.base.repo.full_name) // ""))) as $cross
            | (if (.head | type) == "object" then .head = (if $cross then .head.label else .head.ref end) else . end)
            | (if (.base | type) == "object" then .base = .base.ref else . end)
      - action: update
        method: PATCH
        path: /repos/{owner}/{repo}/pulls/{pull_number}
        requestFieldMapping:
          - inPath: pull_number
            inCustomResource: status.number
```

The asset loses the `servers:` block and keeps everything else
(`assets/pullrequest.yaml@be409bc:45-64` → drop lines 47-51, keep the `summary`/`operationId`/
`parameters`/`responses`). Worth replacing the comment with one that says what the reader now
needs — the same convention `assets/branchprotection.yaml:185-199` uses:

```yaml
  "/repos/{owner}/{repo}/pulls/{pull_number}":
    get:
      # The controller does NOT see this body as GitHub sends it: the get verb in
      # rd-pullrequest.yaml carries a responseTransform that replaces head/base with their
      # branch-name strings before status population and drift comparison. head/base are
      # deliberately absent from the PullRequest schema below — they are neither identifiers
      # nor additionalStatusFields, so nothing is generated from them.
      summary: Get a pull request
```

And the ConfigMap becomes plain — nothing templated is left in the asset:

```yaml
# chart/templates/configmap-pullrequest.yaml
data:
  pullrequest.yaml: |
{{ .Files.Get "assets/pullrequest.yaml" | indent 4 }}
```

Also restore `PullRequestConfiguration` in `chart/samples/configurations.yaml` and
`chart/samples/test-pullrequest.yaml` (unchanged — no spec field moves).

## 4. The alternative, assessed honestly

**`compareScope: updatable` alone does not fix it.** `UpdatableBodyPaths` collects the leaf paths of
the update operation's `application/json` request-body schema
(`internal/tools/client/clienttools.go:251-277`, `collectLeafPaths` at `:283-308`). For this asset
that is `[title, body, state, base]` — **`base` is in the PATCH body**
(`assets/pullrequest.yaml@be409bc:85-86`), so it stays compared, stays a string-against-object, and
still loops. `updatable` removes `head` (and `draft`, `maintainer_can_modify`) from the comparison but
cannot reshape the one field that remains. The transform is load-bearing for `base`; for `head` it is
defence in depth.

**`identifiersAndStatus` is worse than doing nothing.** `scopeFields` = identifiers +
additionalStatusFields = `[number, number, html_url, state]` (`restResources.go:366-369`), and
`projectSpecFields` projects the **spec** onto those paths, skipping any that the spec does not
contain (`internal/controllers/helpers.go:72-90`). The CRD spec is the **create** body plus every
verb's parameters — `getBaseSchemaForSpec` hard-codes the create action
(`oas2jsonschema/extractor.go:32-38`: *"Right now we hardcode the action to 'create'"*) and
`addParametersToSpec` adds only path/query/header parameters (`spec_builder.go:78-140`). So:

- `number` — not in any request body, not a parameter (`pull_number` is, and it is excluded) → absent.
- `html_url` — response-only → absent.
- `state` — **PATCH-body-only, therefore not a spec field either**.

The projection is **empty**, and `CompareExisting` over an empty spec map returns `IsEqual: true` on
the first line (`comparison.go:40-162`). Not "compares less" — **compares nothing**. The CR would sit
Available while its title, body and base disagreed with GitHub. That is the failure mode the brief
names, and here it is unconditional rather than a risk. (`rd-deployment.yaml:63` relies on that same
emptiness deliberately, for an immutable record with no update verb; `rd-teamrepo.yaml:37-41` rejects
it for the same reason as here.)

**What I would ship: `responseTransform` + `compareScope: updatable`, together.** The transform makes
`base` comparable and truthful; `updatable` removes the three create-only fields (`head`, `draft`,
`maintainer_can_modify`) that the PATCH can never fix. Either alone leaves a loop: the transform alone
under `fullSpec` still exposes `draft` — a PR created with `draft: true` and later marked ready for
review in the UI drifts forever, because GitHub has no REST endpoint for that transition and `draft`
is not in the PATCH body. That is a **latent defect in the kind as it shipped**, independent of the
plugin, and this is the moment to close it.

Note the side effect of `updatable`, stated plainly: `spec.state` does not exist on this kind (create
bodies only), so `state` contributes nothing to the compared set and a PR **cannot be closed from the
CR**. That is true today too — it is not a regression — but it is the opposite of what `Issue` claims
for itself in `assets/issue.yaml:112-115`, and someone should check that claim against
`extractor.go:32-38` while they are here.

## 5. Verdict

**Fully native today, no caveat that costs anything.** `PullRequest` needs one `responseTransform` on
one verb, and everything that makes it work is present at oasgen-provider 0.23.0 and in the shipped
rest-dynamic-controller: the field exists (`types.go:297-302`), it runs at the right point
(`restResources.go:346` → `:351` → `:393`), and gojq executes the program in a sandbox with a 5s bound
and a one-in-one-out contract (`jqengine.go:31, 86, 98-101`).

The kind never needed a dependent read, so oasgen-provider **#120** (no pre-call lookup) does not
touch it; it needed no path rewriting, so the `%252F` history does not touch it either. Of the three
plugin kinds this is the one that comes back whole, and it comes back **better than the plugin**: the
fork case (`head` → `.label`) that `flattenPRRefs` got wrong is fixed by the same three lines.

The only thing that does not come back is a delete verb — and that was never the plugin's doing.

## 6. What a reviewer should check

Traps specific to this kind, in the order they bite:

1. **Did the `servers:` override actually go?** If `assets/pullrequest.yaml` keeps it while the
   plugin Service is gone, the controller dials a non-existent DNS name on every observe and the CR
   never leaves Creating. Grep the whole asset for `webServiceUrl`, and confirm
   `configmap-pullrequest.yaml` dropped `tpl` — a leftover `tpl` is harmless, a leftover `servers:`
   is fatal (`docs/configuration.md:364-370`).
2. **Is `base` normalized to `.ref` and never `.label`?** This is the single load-bearing line under
   `compareScope: updatable`. `"octocat:master"` against `spec.base: main` is the same loop with a
   new coat of paint.
3. **Run the program twice.** Feed it a real `pulls/{n}` body, then feed it its own output. Anything
   built on `//` instead of a type guard errors on the second pass, and the error fails the reconcile
   rather than degrading. Use gojq (`go.mod:10`), not `/opt/homebrew/bin/jq` — the engine is gojq.
4. **Check it against a FORK PR, not just a same-repo one.** Every CR the publish flow creates is
   same-repo, so a same-repo test passes with `.ref` hard-coded and hides the bug the plugin had.
   `octocat/Hello-World#2846` is a live, unauthenticated cross-repo example.
5. **Confirm the compared set is what you think.** `updatable` reads the OAS **PATCH body**, so
   adding a property there silently enlarges the drift comparison. If anybody adds `head` or
   `maintainer_can_modify` to that body to "make it updatable", GitHub's PATCH ignores `head`
   entirely and the loop returns.
6. **Do not add a `notFoundBody` predicate for merged/closed PRs.** It reads the **raw** response,
   before the transform (`restResources.go:296-300` precedes `:346`), and "absent" means the
   controller **re-creates** — a second PR from the same branch on every reconcile.
7. **Leave `head`/`base` out of `additionalStatusFields`.** Status is populated from the create and
   update responses too (`restResources.go:561`, `:725`) — and those run with `actions =
   {"create"}` / `{"update"}` (`fieldmapping.go:113-124`), so the get verb's transform does **not**
   apply to them. A `head` in status would be a string after observe and an object after update.
   This is the same trap `rd-branchprotection.yaml:16-22` documents. (Since **#14**, `merged` **is**
   in `additionalStatusFields` — safe exactly as noted here: a plain boolean in all three responses,
   not a spec field, so it cannot affect drift. It is what makes a merged PR distinguishable from a
   closed-but-unmerged one; see §8.)
8. **If you document the normalized shape in the OAS response schema, do it for one verb only and
   expect a warning.** `ValidateSchemas` compares the create/update response schemas against the get
   one (`oas2jsonschema/validator.go:17-37`); divergence is a non-fatal warning
   (`generator.go:52`), not a failure — but it will appear in the RestDefinition's events. The
   cleanest answer is what §3 proposes: keep `head`/`base` out of the schema entirely and say so in a
   comment.
9. **Sanity-check the whole chain end to end**, not just the CR: `Repository` → `GitRef` →
   `RepoContent` → `PullRequest` with `auto_init: true`, then `kubectl get pullrequest -o yaml` and
   confirm `Available` with **no** PATCH in the controller log on the second reconcile. A single
   PATCH on the first pass after create is not necessarily wrong; a PATCH on every pass is the loop.

## 7. Deleting the CR

GitHub's REST API has no endpoint that deletes a pull request (only the GraphQL mutation, which a
RestDefinition cannot reach), so the kind ships with no delete verb — the same shape as `Issue`
(`rd-issue.yaml:41-48`, `docs/overview.md:287-293`).

What the chart does today, and would continue to do: `APICallBuilder` finds no `delete` verb and
returns `(nil, nil, nil)` (`internal/tools/client/builder/builder.go:52-56` — the loop simply never
matches), and `Delete` logs *"API action delete not found"*, tears down any secretRef RBAC, and
**returns nil** (`restResources.go:845-856`). The finalizer is released, the CR disappears, and the
pull request stays open on GitHub, untracked.

That is the correct behaviour and it should be left alone — but it must stay **documented**, because
the alternative reading ("delete the CR to close the PR") is the one users try. Unlike `Issue`, this
kind cannot even close the PR through its spec: `state` lives in the PATCH body only and therefore
never becomes a spec field (§4). The honest instruction is: **merge or close the pull request on
GitHub, then delete the CR.** If closing from the cluster is ever wanted, it is a separate, checkable
change — add `state` (and only `state`) to the **create** body as an `enum: [open, closed]` so it
reaches the spec, keep it in the PATCH body so `updatable` still compares it, and accept that a
merged PR whose CR says `open` will PATCH-422 on every reconcile.

## 8. Observability, and why there is no findby (#14)

Two problems were reported against a real cluster, and they are not the same problem.

**8.1 The outcome of a PR was not observable — fixed.** `status` carried `number`, `html_url` and
`state`, and `state` collapses *merged* and *closed-unmerged* into the single value `closed`. GitHub
reports the difference only through a separate boolean, `merged`, and nothing in this kind read it, so
a consumer of the publish chain could not tell an accepted change from a rejected one without
inferring "closed?". This is closed by adding **`merged` to `additionalStatusFields`** — the option
§6 note 7 already flagged as safe (a plain boolean in the create, get and update responses; never a
spec field, so it cannot enter drift). `merged` is already a property of the `PullRequest` schema in
`assets/pullrequest.yaml`, so nothing else changes. After this, a merged PR reports `state: closed`
+ `merged: true`; a closed-unmerged one reports `state: closed` + `merged: false`.

**8.2 A CR that never recorded `status.number` can never be re-observed — FIXED (requires oasgen-provider >= 0.25.0).** Both
read paths (`get`, `update`) are keyed on `pull_number`, sourced from `status.number`
(`requestFieldMapping`, §1). A CR that never recorded a number therefore had no way to reach its PR:
`IsResourceKnown` cannot build the get call, the observe falls through to the findby branch, found no
findby verb, and reported `Available` with *"Resource is assumed to be up-to-date. API call not found
for FindBy."* (`restResources.go:237`, controller `217ccd0`). The reported cause is exactly this: a
create whose response never yielded a `number` (a 422 "a pull request already exists", an async/no-body
create) leaves a CR with intact `spec` and empty `status`, and there was no recovery path.

A findby resolving `owner`/`repo`/`head`/`base` → the PR via `GET /repos/{owner}/{repo}/pulls` is now
declared, keyed on `identifiers: [head, base]` with `identifiersMatchPolicy: AND`; observe falls
through to it exactly when `status.number` is absent (group B), while group A keeps observing via
`get`. It could **not** have been shipped against the controller as originally built, and the reason
is worth keeping because it is precisely what the upstream fix changed:

| step | citation | consequence |
|---|---|---|
| findby does the list call **and matches an item inside the client**, returning the single matched item | `restResources.go:263` → `restclient.go:253` `FindBy` → `:572` `findItemInList` → `:607` `isItemMatch` | matching sees the **raw** GitHub items |
| an item matches when an identifier's value equals `spec.<field>` (then `status.<field>`) by `DeepEqual` | `clienttools.go:123` `isInResource` (note its own `TODO`: no response mapping is applied here) | the compared value is raw |
| `NormalizeResponseBody` (the `head`/`base` → string `responseTransform`) runs **only afterwards**, on the already-matched item | `restResources.go:346` | too late to help matching |

So a findby keyed on `head`/`base` can never match: the raw list item carries them as **objects**
(`{ref,label,repo,…}`) while `spec.head`/`spec.base` are branch **strings**, and
`DeepEqual(string, object)` is always false. The `responseTransform` that reconciles the two shapes
for the get verb is applied one step too late to be usable as a match key. The only raw-item scalars
that equal a spec field are `title`, `body` and `draft` — none unique, and `title`/`body` are
user-editable, so keying on them would break recovery precisely when the spec has drifted. head/base
are the only stable, unique match keys, and they are the ones the raw-shape mismatch defeated.

(A note on the earlier worry that moving identity to `head`/`base` is a breaking CRD change: it is
not, in current oasgen. `IncludeIdentifiersInSpec` defaults off, so identifiers are not projected
into the **spec** schema; they are appended to the **status** schema, which is additive. There are no
immutability markers on identifiers and they are not used in naming or printer columns. `number`
stays in `additionalStatusFields`, so group-A status is unchanged and get/update still bind
`{pull_number}` from `status.number`.)

**What shipped.** The upstream fix — the controller normalizes each findby list item with the findby
verb's own `responseTransform` **before** `findItemInList` — landed as
[krateo-platformops/oasgen-provider#145](https://github.com/krateo-platformops/oasgen-provider/issues/145)
(merged via PR #155, released in **oasgen-provider >= 0.25.0**). With that in place this kind now
declares:

- `identifiers: [head, base]`, `identifiersMatchPolicy: AND` — a PR is identified by the branches it
  joins, both always present in spec, so a findby locates it from spec alone.
- a `findby` verb (`GET /repos/{owner}/{repo}/pulls`, `state=all`, `pageNumber` pagination walking every page) carrying the same
  `head`/`base` object→string `responseTransform` as `get`; applied per item before matching, it
  makes the compare string-vs-string and selects the right PR.
- that same `responseTransform` **on create, get, update AND findby** — status is written from all
  four responses and `NormalizeResponseBody` only runs the producing verb's transform, so without it
  on every verb `status.head` would be an object after a create and a string after an observe, and
  the string-typed status schema would reject the object. The four copies are byte-identical by
  necessity.
- `head`/`base` declared as `string` in `assets/pullrequest.yaml` so the status projection types
  them correctly.

A group-B CR (intact `spec`, empty `status`) now recovers on its next reconcile: observe finds no
`status.number`, runs the findby, matches its PR by head/base, and populates `status` — including
`number`, so subsequent reconciles use the cheap `get` path and `merged`/`merged_at` (§8.1) start
reporting. The chart therefore requires `oasgen-provider >= 0.25.0`; on an older controller the
findby match can never succeed and observe would re-create, so the requirement is load-bearing.
