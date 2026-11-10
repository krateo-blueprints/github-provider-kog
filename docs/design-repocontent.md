---
type: Architecture
title: github-provider-kog — restoring RepoContent natively
description: What the removed RepoContent kind did, exactly what the proxy plugin's putRepoContent/getRepoContent handlers did for it and why, and the oasgen-provider 0.23.0 RestDefinition that replaces each behaviour without a plugin.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [kog, design, repocontent, oasgen-provider, plugin-removal]
timestamp: 2026-09-09T00:00:00Z
---

> **IMPLEMENTED (2026-10-31).** This design shipped as written — `chart/assets/repocontent.yaml`,
> `chart/templates/{configmap,rd}-repocontent.yaml`, `chart/samples/test-repocontent.yaml` and a
> `RepoContentConfiguration` in `chart/samples/configurations.yaml`. The chart is now **31 kinds**;
> this document is the design record it was built from. The one deviation worth noting: RepoContent
> keeps its native **delete verb** (deleting the CR deletes the file). The oasgen-provider #125 CRD
> cascade that once made a delete verb dangerous on an uninstall is fixed: oasgen now refuses to drop
> a CRD that still has instances. `Repository` gained its delete verb on the same grounds.

Written against `be409bc` (the last commit that still carries the kind).

**Provenance of the runtime citations, stated because it matters:** the line numbers below were
read from a **rest-dynamic-controller `0.20.0`** tree — the standalone
`krateo-platformops/rest-dynamic-controller` repo, which is now **archived**; the engine was folded
into the `krateo-platformops/oasgen-provider` monorepo under `go/rest-dynamic-controller/` in
August 2026. The runtime this chart targets is **0.23.0**. The behaviour relied on here is
unchanged between the two (the one relevant difference, the `%252F` double-escape fixed by #113, is
called out where it matters), but **a reader implementing this should re-read the cited lines at
`0.23.0` in the monorepo rather than trusting the numbers verbatim.**

---

## 1. What the kind did

`RepoContent` committed **one file** into a repository on a branch — the middle step of the
blueprint-authoring chain `Repository → GitRef → RepoContent (per file) → PullRequest`
(`docs/api.md:157-159`). Its spec is `owner`/`repo`/`path`/`branch`/`message`/`content`
(base64 file bytes) plus an optional `sha` (`docs/api.md:173-189`,
`chart/samples/test-repocontent.yaml`).

| verb | method + path | routed where |
|---|---|---|
| create | `PUT /repos/{owner}/{repo}/contents/{path}` | **plugin** (`chart/assets/repocontent.yaml:11-13`) |
| update | same `PUT` | **plugin** (same operation object) |
| get | `GET /repos/{owner}/{repo}/contents/{path}` | **plugin** (`chart/assets/repocontent.yaml:65-67`) |
| delete | `DELETE` same path | **GitHub directly** — no override |

`identifiers: [path]`, `additionalStatusFields: [sha, html_url]`, `compareScope` left at the
default `fullSpec` (`chart/templates/rd-repocontent.yaml:11-16`).

The delete verb is the useful control: it was **always native**, and GitHub's delete body
*requires* `sha` (`chart/assets/repocontent.yaml:128-130`). Delete has worked all along. That
alone proves the mechanism section 3.4 depends on.

---

## 2. What the plugin handler actually does

### 2a. `putRepoContent` — the 422-then-retry

```go
// plugin/main.go:366-377
status, body, ok := proxy(w, r, http.MethodPut, target, reqBody)
...
if status == http.StatusUnprocessableEntity && jsonStringField(reqBody, "sha") == "" {
    if sha := currentFileSha(r, owner, repo, path, jsonStringField(reqBody, "branch")); sha != "" {
        status, body, ok = proxy(w, r, http.MethodPut, target, withJSONField(reqBody, "sha", sha))
```

`currentFileSha` (`plugin/main.go:327-352`) is a second, dependent GitHub GET.

**Why it was needed.** GitHub's `PUT /contents` 422s when the file exists and the body omits
`sha`. The commit that added it (`8b041e9`) says it enables "UPDATE an existing file … not
only create it".

**What it actually covers, precisely.** The retry fires *only* when the request carried no
`sha`. On the controller's **update** path the request always carries one (section 3.4), so
the retry never fires there. It fires exactly on the **create** path against a file that is
already present — and the create path only runs after Observe reported `ResourceExists:
false`, because a new CR enqueues `Observe`, not `Create`
(`unstructured-runtime@v1.4.0/pkg/controller/event/actionsevent.go:14-19`: `CRCreated →
Observe`). So the real trigger is narrow and specific:

- a `Create` that fails *after* GitHub accepted the PUT (status-write conflict, etc.) is
  requeued as `Create`, not `Observe`
  (`unstructured-runtime@v1.4.0/pkg/controller/worker.go:211-224`), and
  `clearStatusFields(mg)` at `restResources.go:545` has already wiped `status.sha`. Retry #2
  then PUTs sha-less against a file that now exists → 422, forever, until `maxRetries` (5,
  `main.go:95-97`).
- historically, the much larger trigger: before oasgen 0.23.0 the observe GET's `?ref` was
  double-escaped (2b), so observe **always** 404'd on a `builder/*` branch and the controller
  **always** took the create path — every reconcile a sha-less PUT into an existing file.

### 2b. `getRepoContent` — the decode-until-stable loop is now **dead code**. Confirmed.

```go
// plugin/main.go:406-412
for {
    dec, err := url.PathUnescape(branch)
    if err != nil || dec == branch { break }
    branch = dec
}
```

The defect it worked around is in the controller's URL builder, and it is still visible in
the stale 0.20.0 checkout, verbatim:

```go
// rest-dynamic-controller (0.20.0) internal/tools/client/clienttools.go:42-54
for key, param := range query {
    queryParam := url.QueryEscape(param)   // builder/x -> builder%2Fx
    params.Add(key, queryParam)
}
...
parsed.RawQuery = params.Encode()          // % -> %25  =>  builder%252Fx
```

**Fixed in 0.23.0**, recorded as #113 in `krateo-oasgen-provider/docs/log.md:22-27`
("`buildPath` called `url.QueryEscape` and then handed the escaped string to `url.Values`…
`builder%252Fsock-shop` … the CR looped `Creating` forever"), and the provider and controller
ship from one tag at identical versions (`docs/log.md:13-14`). Multi-segment values are not a
problem for GitHub either — it decodes `%2F` (probed to seven segments). **This half of the
handler needs no native replacement and must not be reproduced.**

### 2c. `flattenContent` — the stated reason is wrong; the real one is status

```go
// plugin/main.go:242-250
content, isObj := m["content"].(map[string]any)
if !isObj { return body }
for _, k := range []string{"path", "sha", "html_url", "name", "size", "type"} { ... }
```

The mux comment (`plugin/main.go:29-30`) says it exists "so the controller's same-level field
comparison succeeds". The task asked me to verify the "no-op for a single-file GET" claim
rather than repeat it. **Verified, and the comment's rationale is the wrong one:**

- **On the GET it is a genuine no-op.** Probed `GET
  /repos/krateo-platformops/oasgen-provider/contents/README.md`: top-level keys are `_links, content,
  download_url, encoding, git_url, html_url, name, path, sha, size, type, url`. `content` is a
  **string**, so `m["content"].(map[string]any)` fails and the body returns unchanged. (A
  directory GET is a JSON array; `json.Unmarshal` into a map fails — also unchanged.)
- **On the PUT it is load-bearing, for status, not comparison.** No drift comparison ever runs
  against a create/update response — `isCRUpdated` is called only in `Observe`
  (`restResources.go:393`). What *does* run is `populateStatusFields`
  (`restResources.go:561`, `:725`), and it reads **root** keys only
  (`helpers.go:116-136`). GitHub's PUT answers `{"content":{…},"commit":{…}}` with no root
  `sha`/`path`/`html_url`. And both write paths call `clearStatusFields(mg)` first
  (`restResources.go:545`, `:710`). So without the flatten, **every successful write wipes
  `status.sha`**. That matters, see 3.4.

### 2d. `normalizeContent`

```go
// plugin/main.go:279-291
delete(m, "encoding")
raw, ok := m["content"].(string)
if !ok { return body }
compact := strings.NewReplacer("\n", "", "\r", "").Replace(raw)
if decoded, err := base64.StdEncoding.DecodeString(compact); err == nil {
    m["content"] = base64.StdEncoding.EncodeToString(decoded)
} else {
    m["content"] = compact
}
```

**Why.** GitHub returns file `content` as RFC-2045-wrapped base64. Probe on the same README:
`content` is 3770 chars with **62 newlines**, line lengths `{60, 48, 0}`. `spec.content` is
emitted unwrapped, so a byte-identical file compares **unequal** at the string leaf and the CR
loops "update" forever. The earlier fix *stripped* `content` instead; that broke the other
way, because the comparison skips a spec key the response omits
(`internal/tools/comparison/comparison.go:47-49`), which made observe content-blind and left
`RepoContent` unable to update a file at all (`plugin/main.go:266-273`, commit `bbce268`).
Normalizing is the only shape that both detects real drift and does not false-flag.

`delete(m,"encoding")` is **not** load-bearing and the handler's own comment concedes it
(`plugin/main.go:272-273`): spec fields come from the request bodies and parameters, and no
PUT/GET-parameter carries `encoding`, so it is never on the compare's spec side.

### 2e. the `branch` → `?ref` rename (in `getRepoContent`, easy to miss)

```go
// plugin/main.go:396-399, 413-419
branch := q.Get("branch"); if branch == "" { branch = q.Get("ref") }
... v := url.Values{}; v.Set("ref", branch); target += "?" + v.Encode()
```

The OAS names the query parameter `branch`, not GitHub's `ref`, deliberately — "the
rest-dynamic-controller only populates a query param whose name matches a CR spec field, and
the CR carries `spec.branch`" (`chart/assets/repocontent.yaml:74-83`). Without the forward,
observe reads the **default** branch, 404s on a `builder/*` file, and the CR sticks
"Creating". This is a real behaviour that must be replaced, and it is the one the plugin
documented least loudly.

---

## 3. The native replacement

### 3.1 `spec.branch` → `?ref` — a request-direction `fieldMapping`, no jq

Declare GitHub's real parameter name in the OAS (a mapped parameter, so oasgen omits it from the
spec) and relocate the CR's `branch` onto it. `applyFieldMapping`'s `InQuery` branch writes
`reqConfiguration.Query["ref"]` directly (`builder/builder.go:359-365`), and a plain
relocation carries **no** `valueMapping`, so it is nowhere near the dead request-direction jq
path (`builder/builder.go:348-356`, `default: continue`).

```yaml
# chart/assets/repocontent.yaml — get operation: drop the `servers:` override, rename the param
    get:
      summary: Get repository content
      operationId: repos/get-content
      parameters:
        - $ref: '#/components/parameters/owner'
        - $ref: '#/components/parameters/repo'
        - $ref: '#/components/parameters/path'
        # GitHub's own name. A mapped parameter, which oasgen omits from the spec, so
        # excludedSpecFields: [ref] is a redundant no-op kept for immutability. The CR
        # expresses the branch once, as spec.branch, and the get verb's fieldMapping relocates it here.
        - name: ref
          in: query
          required: false
          schema:
            type: string
```

```yaml
# chart/templates/rd-repocontent.yaml
    excludedSpecFields:
      - ref
...
      - action: get
        method: GET
        path: /repos/{owner}/{repo}/contents/{path}
        fieldMapping:
          - inQuery: ref
            inCustomResource: spec.branch
```

An omitted `spec.branch` resolves to not-found and the entry is skipped
(`builder/builder.go:337-345`) — GitHub then reads the default branch, exactly as today.

*Smaller-diff alternative, rejected:* omit the parameter from the OAS entirely and let the
`fieldMapping` invent it. It works (`ValidateRequest` only checks that **required** declared
params are present, `clienttools.go:185-207`), but it leaves the document lying about the
call. Declare it.

### 3.2 base64 canonicalisation — a `responseTransform` on `get`

This is `normalizeContent`, written as jq, plus the ≥ 1 MB guard the plugin never had (3.5):

```yaml
      - action: get
        method: GET
        path: /repos/{owner}/{repo}/contents/{path}
        fieldMapping:
          - inQuery: ref
            inCustomResource: spec.branch
        # GitHub returns `content` as RFC-2045-wrapped base64 (probed: 62 soft newlines at 60
        # chars in a 3.7 KB README), while spec.content is unwrapped — a byte-identical file
        # would compare unequal at the string leaf and loop "update" forever. Stripping the
        # soft breaks yields exactly StdEncoding, because that is what GitHub wraps.
        #
        # `encoding: none` is GitHub's answer for a file of 1 MB or more: `content` comes back
        # EMPTY. Dropping the key makes the comparison skip it (comparison.go:47-49) — observe
        # is content-blind for such a file, which is the bounded failure. LEAVING it would
        # compare "" against spec.content forever: drift, a PUT, A NEW COMMIT, every reconcile.
        responseTransform:
          inline: |
            if .encoding == "none" then
              del(.content)
            elif (.content | type) == "string" then
              .content |= (split("\n") | join(""))
            else
              .
            end
```

Use `split`/`join`, **not** `@base64d | @base64`. gojq's `@base64d` returns
`string(decodedBytes)` (`gojq@v0.13.0/func.go:974-987`) and truncates at the first padding
byte; the round trip happens to be byte-safe inside one program, but it buys nothing —
GitHub's wrapping is standard-alphabet with padding, so removing the breaks *is* the canonical
form (probe: `base64(decode(compact)) == compact`).

`del(.encoding)` is deliberately not reproduced — see 2d.

### 3.3 status after a write — a `responseTransform` on `create` and `update`

This is `flattenContent`, and it replaces the half of it that was actually doing work:

```yaml
      - action: create
        method: PUT
        path: /repos/{owner}/{repo}/contents/{path}
        # GitHub's PUT answers {"content":{…},"commit":{…}} — no root sha/path/html_url. Both
        # write paths clearStatusFields() first (restResources.go:545, :710) and
        # populateStatusFields reads ROOT keys only (helpers.go:116-136), so without this every
        # successful write LEAVES STATUS EMPTY until the next observe. That is not cosmetic: a
        # spec edit enqueues Update DIRECTLY, skipping Observe
        # (unstructured-runtime worker/controller.go:378-405), and the update body sources `sha`
        # from status. Two quick edits in a row would send the second PUT sha-less.
        responseTransform:
          inline: |
            . + {
              path:     (.content.path     // .path),
              sha:      (.content.sha      // .sha),
              html_url: (.content.html_url // .html_url)
            }
```

The identical block goes on `update`. `//` fallbacks make it inert if GitHub ever flattens the
shape itself. `name`/`size`/`type` are not lifted: nothing reads them (they are neither
identifiers nor `additionalStatusFields`).

### 3.4 the `sha` — why **no retry is needed**, and what replaces it

**`status.sha` reaches the PUT body with no mapping at all.** Verified end to end:

- `RequestedBody` returns the **top-level property keys** of the operation's
  `application/json` request body (`clienttools.go:196-228`, the
  `for sch := schema.Properties.First()` loop). For this PUT that set is
  `{message, content, sha, branch, committer, author}` — `sha` is in it
  (`chart/assets/repocontent.yaml:26-48`).
- `BuildCallConfig` runs `processFields` over **spec first, then status**
  (`builder/builder.go:198-201`), and `processFields` writes any field whose name is in that
  body set: `if callInfo.ReqParams.Body.Contains(field) { if mapBody[field] == nil { mapBody[field] = value } }`
  (`builder/builder.go:458-464`). Spec wins by nil-guard; with `spec.sha` unset, `status.sha`
  lands in the body.
- The **delete verb already proves it in production**: delete never went through the plugin
  and GitHub requires `sha` in its body (`chart/assets/repocontent.yaml:128-130`).

**So the steady-state update needs nothing.** Observe's GET returns root `sha`,
`populateStatusFields` writes `status.sha` (`restResources.go:351`), and `UpdateStatus`
**persists it at `:355` — before** the comparison at `:393` decides there is drift. The
`Update` event is then enqueued and `handleUpdate` does a fresh live API-server GET
(`worker.go:736` → `fetch` → `dynamicClient.Resource(gvr).Get`, `worker.go:899-901`), so the
CR it builds the PUT from **already carries** the sha. There is no same-reconcile update and
none is needed.

**What replaces the retry is a one-line `requestTransform` on create**, which is strictly
better than the plugin's version because it removes the failure instead of recovering from it:

```yaml
      - action: create
        method: PUT
        path: /repos/{owner}/{repo}/contents/{path}
        # A create runs only after Observe reported the file ABSENT, so a sha is never correct
        # here — and status is NOT cleared when a create fails (clearStatusFields sits after the
        # call, restResources.go:512/545), so a stale status.sha from an earlier observe would
        # otherwise be sent on every create attempt of a file that no longer exists, and nothing
        # would ever clear it. Update keeps its sha; create is unconditionally sha-free.
        requestTransform:
          inline: del(.sha)
        responseTransform: { … as 3.3 … }
```

`ApplyRequestTransform` runs on the assembled body immediately before the call
(`restResources.go:505`). `del(.sha)` on a body without `sha` is a no-op.

**Convergence, honestly, per reconcile.**

| starting state | reconciles | what happens |
|---|---|---|
| file absent | 2 | Observe → 404 → `Create` → PUT (sha-free) → 201; status filled by 3.3 |
| file present, content equal | 1 | Observe → 200 → normalized content equal → **Ready, no write** |
| file present, content differs | 2 | Observe → 200 → `status.sha` persisted at `:355` → drift → `Update` → PUT **with** sha → 200 |
| spec edit on a Ready CR | 1 | `Update` enqueued directly; sha from the last observe |
| **create against a file that exists out of band** | **~5 failed + 1 resync** | PUT sha-free → 422 → the event is requeued **as `Create`** (`worker.go:211-224`) up to `max-error-retries`=5 with 1 s→90 s backoff (`main.go:89-97`); dropped; the next informer resync (`REST_CONTROLLER_RESYNC_INTERVAL`, default **3 m**, `main.go:74-76`) enqueues `Observe`, which now sees 200 → drift → `Update` → PUT with sha → Ready |

That last row is the whole cost of dropping the retry: **bounded, self-healing, worst case
roughly 3–6 minutes and five noisy 422s**, versus the plugin's one silent extra GitHub GET. It
is reachable only when Observe and the PUT disagree about existence — a genuine race, or a
create retried after a post-PUT failure.

**`tolerateCodes: [422]` on create would collapse that to one reconcile — do not use it.** A
tolerated code short-circuits to an empty successful response
(`internal/tools/client/restclient.go:167-172`), so a *genuine* 422 (malformed base64, illegal
path, branch not found) would also read as success: the CR would sit `Creating`, the next
Observe would 404, create again, tolerate again — a silent infinite loop with no condition to
read. The five loud failures are the better trade.

### 3.5 What is **not** expressible at 0.23.0

`currentFileSha` (`plugin/main.go:327-352`) is a **pre-call dependent read**: fetch the blob
sha, then send it in the same write. There is no native form. `resolver.type` is `secretRef`
only, the jq engine has no network by construction, and `apiLookup` was removed — tracked as
oasgen-provider **#120**. The documented workaround, `createApiRef` (a snowplow RESTAction
doing GET-then-PUT), is real but costs a platform-level dependency: `rdc.env.URL_SNOWPLOW`
defaults to `{}` and an empty value disables apiRef resolution altogether, plus a credentialed
Endpoint secret. **Do not take it for this kind** — 3.4 shows the read is not needed.

### 3.6 The finished RestDefinition

```yaml
apiVersion: ogen.krateo.io/v1alpha1
kind: RestDefinition
metadata:
  name: {{ .Release.Name }}-repocontent
  namespace: {{ .Release.Namespace }}
spec:
  oasPath: configmap://{{ .Release.Namespace }}/{{ .Release.Name }}-repocontent/repocontent.yaml
  resourceGroup: {{ .Values.resourceGroup }}
  resource:
    kind: RepoContent
    identifiers:
      - path
    additionalStatusFields:
      - sha        # the blob sha; the update and delete bodies auto-source it from here
      - html_url
    # `ref` is GitHub's query-parameter name for the branch on the get verb. The CR expresses
    # the branch ONCE, as spec.branch (which the PUT/DELETE bodies genuinely take), and the get
    # verb's fieldMapping relocates it. oasgen omits a mapped parameter from the spec, so this
    # excludedSpecFields entry is a redundant no-op kept for immutability; it records the intent
    # that authors never face a ref/branch pair to keep in sync.
    # IMMUTABLE once the CRD is generated.
    excludedSpecFields:
      - ref
    # Default fullSpec, deliberately. Walking the spec, the response carries only `path`,
    # `content` and (if the author set it) `sha`; owner/repo/branch/message/committer/author are
    # absent from the GET body and skipped (comparison.go:47-49). `updatable` would derive the
    # same set minus `path` — a path parameter that cannot drift — so it changes nothing here,
    # and fullSpec keeps this kind's declaration honest about comparing `content`, which is the
    # one thing it exists to manage.
    configurationFields: []
    verbsDescription:
      - action: create
        method: PUT
        path: /repos/{owner}/{repo}/contents/{path}
        requestTransform:
          inline: del(.sha)
        responseTransform:
          inline: |
            . + {
              path:     (.content.path     // .path),
              sha:      (.content.sha      // .sha),
              html_url: (.content.html_url // .html_url)
            }
      - action: update
        method: PUT
        path: /repos/{owner}/{repo}/contents/{path}
        responseTransform:
          inline: |
            . + {
              path:     (.content.path     // .path),
              sha:      (.content.sha      // .sha),
              html_url: (.content.html_url // .html_url)
            }
      - action: get
        method: GET
        path: /repos/{owner}/{repo}/contents/{path}
        fieldMapping:
          - inQuery: ref
            inCustomResource: spec.branch
        responseTransform:
          inline: |
            if .encoding == "none" then
              del(.content)
            elif (.content | type) == "string" then
              .content |= (split("\n") | join(""))
            else
              .
            end
      - action: delete
        method: DELETE
        path: /repos/{owner}/{repo}/contents/{path}
```

Asset changes: delete both `servers:` blocks (`chart/assets/repocontent.yaml:11-13, 65-67`),
rename the get query parameter `branch` → `ref` and replace its comment. The ConfigMap keeps
its `tpl` rendering harmlessly, but with the plugin gone it can become a plain `.Files.Get`
like the 28 native kinds.

---

## 4. Verdict

**RepoContent comes back fully native today, and comes back better than it was.** Nothing in
the plugin's RepoContent surface survives as a genuine gap:

| plugin behaviour | native status |
|---|---|
| decode-until-stable branch loop | **dead** — fixed upstream as #113 in 0.23.0; do not port |
| `flattenContent` on the GET | **dead** — probed no-op (`content` is a string at the root) |
| `flattenContent` on the PUT | **replaced** — `responseTransform` on create + update (3.3) |
| `normalizeContent` | **replaced** — `responseTransform` on get (3.2), plus a ≥ 1 MB guard the plugin lacks |
| `branch` → `?ref` forwarding | **replaced** — `fieldMapping.inQuery` + `excludedSpecFields` (3.1) |
| 422-then-retry (`currentFileSha`) | **not expressible** (#120) — and **not needed**: `status.sha` auto-populates the update body, proven by the always-native delete verb |

**The one caveat, and its price.** Losing the retry costs a *bounded* recovery on one narrow
race — a create issued against a file that exists out of band. Worst case ~5 failed PUTs over
1 s→90 s of backoff, the event dropped, then the next 3-minute resync converges it via
Observe → Update. Loud, visible in conditions, self-healing, ≈ 3–6 minutes. The alternative
(`tolerateCodes: [422]`) buys one reconcile at the price of turning every real 422 into a
silent loop, and is rejected on those grounds.

Two things get **strictly better**: `requestTransform: del(.sha)` removes a permanent wedge the
plugin never addressed (a stale `status.sha` sent on create after the file was deleted out of
band, which nothing clears because `clearStatusFields` sits *after* the call), and the
`encoding == "none"` guard removes an infinite-commit loop for files ≥ 1 MB that ships today.

---

## 5. What a reviewer should check

Traps specific to **this** kind, in the order they will bite:

1. **The ≥ 1 MB file is not hypothetical.** Probed: `torvalds/linux` `MAINTAINERS`, 927 975 B →
   `encoding: base64`, content present; `kubernetes/kubernetes`
   `api/openapi-spec/swagger.json`, 4 476 228 B → **`encoding: "none"`, `content: ""`**. Without
   the guard in 3.2 the CR drifts forever and **writes a new commit on every reconcile**
   (~every 3 minutes). Confirm the `del(.content)` branch, and confirm the reviewer understands
   the accepted consequence: observe is content-blind for such a file.
2. **Do not use `@base64d | @base64`.** It works but is fragile (gojq truncates at the first
   padding byte, `gojq@v0.13.0/func.go:977-979`) and buys nothing over stripping the soft
   breaks. Check the transform is `split("\n") | join("")` and is guarded by the string type
   test — `null | split(...)` raises and fails the whole reconcile.
3. **`excludedSpecFields` is immutable** once the CRD is generated
   (`oasgen-provider .../types.go:522`). Getting `ref` in on the first apply matters; adding it
   later means deleting and regenerating the RestDefinition.
4. **Never a request-direction jq `valueMapping`.** The `inQuery: ref` entry must carry no
   `valueMapping` at all. Nothing rejects one at admission and it applies green
   (`builder/builder.go:348-356`).
5. **Verify the create/update `responseTransform` by watching `status.sha` across two writes,
   not one.** A single write looks fine either way, because the next Observe repopulates
   status. The bug only shows on **two spec edits in a row**: a spec change enqueues `Update`
   directly, skipping Observe (`unstructured-runtime .../controller.go:378-405`), so the second
   PUT goes out with whatever the first write left in status — and both write paths call
   `clearStatusFields` (`restResources.go:545`, `:710`).
6. **Check `spec.sha` is left unset in every sample and in the frontend's emitted CRs.** It is
   still a spec field (it is a PUT body property), it still wins over `status.sha` by nil-guard
   (`builder/builder.go:461`), and a hand-set stale value produces a 409/422 the design does
   not recover from. Consider `excludedSpecFields: [sha]` as a hardening — it removes the field
   from the CRD only (`oas2jsonschema/spec_builder.go:342-349`) and does **not** disturb
   `status.sha` auto-population — at the cost of losing deliberate optimistic concurrency.
7. **Test the create-against-existing-file path end to end.** It is the one place the plugin's
   behaviour is genuinely not reproduced. Confirm the 422s appear in conditions, that the event
   is dropped after 5 tries, and that the resync-driven Observe recovers it. If the deployment
   overrides `REST_CONTROLLER_RESYNC_INTERVAL` upward, that recovery window grows with it.
8. **Do not re-introduce a `servers:` override or a `notFoundCodes`/`notFoundBody` entry.**
   GitHub's plain 404 on an absent file is already handled (`validators.go:49-51`,
   `restResources.go:203-211`).
9. **Branch ordering still applies.** `PUT /contents` against a branch that does not yet exist
   is a 404, not a create — the `GitRef` must be Ready first
   (`docs/api.md:157-159`). Unchanged by this design, but it is what a failing publish set will
   look like first.
