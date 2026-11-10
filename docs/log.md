---
type: Log
title: github-provider-kog — log
description: Curated chronological history of github-provider-kog — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [log, history]
timestamp: 2026-09-15T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.

## 2026-11-10 — ci: every deviation from GitHub's OpenAPI is listed and checked

Diego asked for the chart to be 100% adherent to GitHub's OpenAPI. The deviation review that
followed found 55 field-level deviations; this adds the gate that keeps the list complete.

- **`hack/assert-oas-adherence.py`** (lint job `oas-adherence`) compares each of the 123
  verbs with GitHub's operation at the pinned commit: parameters, body properties and
  `required`, recursing into nested objects (the review compared top-level fields only, and
  the nested comparison adds 13 entries, e.g. RepoContent's author/committer `date` and the rulesets' flattened `rules[]` union).
- **`hack/oas-adherence-exceptions.yaml`** holds every difference (228 at main 39c9294, in 72
  entries) with its category and reason. Category D entries name the PR restoring them
  (#58–#62) or the issue holding them (oasgen-provider#563 for Issue `issue_field_values`).
- **Defaults are frozen** (Diego, 2026-11-10): no new asset copies a GitHub `default`; the 34
  existing declarations (29 kind/field pairs) are listed with GitHub's own value. Removing `make_latest`'s default from #58 was
  the first application.
- Negative controls: restoring a field without deleting its entry fails as stale; adding a
  `default` fails as NEW DEFAULT.

## 2026-11-10 — feat: Repository and UserRepository delete the GitHub repository, as GitHub's API defines

The chart now follows GitHub's OpenAPI description: every kind exposes every operation GitHub
defines on the paths it uses. `Repository` and `UserRepository` were the two exceptions, with no
`DELETE /repos/{owner}/{repo}`. They now have it.

- **Deleting the CR deletes the repository**, code and history included. To keep it, annotate the
  CR `krateo.io/deletion-policy: orphan` before deleting it: rest-dynamic-controller then releases
  the finalizer without calling GitHub (unstructured-runtime `ShouldDelete`).
- **A `UserRepository` that adopted an existing repository** deletes it too; annotate it to keep it.
- **Why it was absent:** oasgen-provider #125. oasgen dropped a RestDefinition's CRD unconditionally,
  which would have run this DELETE for every repository the kind created. oasgen now refuses to drop
  a CRD that still has instances, so the verb is safe to have.
- **The portal's builder-publish chart** annotates the `Repository` it renders with
  `deletion-policy: orphan`, so uninstalling a publish keeps the published repository. This release
  reaches 057 only after that portal change has rolled.
- **New CI check, `oas-operations`:** fails if a kind leaves out an operation GitHub defines on one of
  its paths. It reads GitHub's description at a pinned commit, verified by SHA-256. A list GET on a
  POST collection is allowed, and so is one documented exception (Collaborator's check-collaborator).

## 2026-11-07 — feat: publish both charts to the helm index, not only GHCR

The organisation adopted one publishing standard (krateo-blueprints/charts `PUBLISHING.md`):
a chart in GHCR and missing from the helm index is not published, because the Marketplace
installs from the index. Both of this repo's charts were GHCR-only.

- **Channel `operators`:** neither chart has a CompositionDefinition, so neither is a
  blueprint, and the publisher refuses a non-blueprint in `blueprints`.
- **Same bytes:** after the shared `release-oci` push, the release pulls both charts back from
  GHCR and hands those archives to the publisher. The shared workflow's own archives could
  differ (fresh timestamps, or a skipped push of an identical version). A dry run against
  0.7.5 pulled exactly the published digests.
- **Refuse before publishing:** the tag must be plain semver, the tagged commit must have a
  successful `lint.yaml` run, and `CHARTS_PUBLISH_TOKEN` must be set, all checked before GHCR
  holds anything.
- **Names are free:** neither `github-provider-kog` nor `github-provider-kog-config` had an
  entry in either channel's index, so the one-owner-per-name rule has nothing to refuse.

## 2026-11-07 — docs: fields only the PATCH body accepts cannot be set from a CR

The docs said `spec.state: closed` closes an `Issue`, and that `Repository` and `UserRepository`
compare and push `default_branch` and `archived`. Neither holds. oasgen builds the spec body from
the create verb alone and merges only *parameters* from the other verbs, so a field that exists
only in the PATCH body never becomes a spec field: it can't be set, compared or sent.

- **Measured on krateo-057:** the `Issue` CRD's spec has no `state` or `state_reason`. A server
  dry-run of the sample with `state: closed` is rejected by a strict apply (`unknown field
  "spec.state"`), and a non-strict apply silently drops it.
- **All 32 kinds checked** against the live CRDs. The affected PATCH-body-only fields are `Issue`
  `state`/`state_reason`, `PullRequest` `state` (already documented correctly), `Repository` and
  `UserRepository` `default_branch`/`archived`, and `GitRef` `force` (not reachable under its
  `identifiersAndStatus` scope anyway).
- **Corrected:** the `Issue` sample, `rd-issue.yaml`, `assets/issue.yaml`, `test-userrepository.yaml`,
  `api.md`, `configuration.md`, `usage.md`, `overview.md`, `examples.md` and `llms.txt`. The compared
  sets are `{title, body}` for `Issue` and `{description, homepage, has_issues, has_wiki,
  has_projects}` for both repository kinds.
- **No behaviour change.** The RestDefinitions are unchanged. The `assets/issue.yaml` comment edit
  moves that kind's `oasHash`, so the `Issue` CRD regenerates once on the next roll, with the same schema.
- **Upstream:** update-only spec fields are requested in
  [oasgen-provider#491](https://github.com/krateo-platformops/oasgen-provider/issues/491). Declaring
  such a field on the create body and deleting it with a create `requestTransform` was considered
  and rejected, because the asset would then misstate GitHub's create contract.

## 2026-11-06 — PullRequest findby read page 2 on a cluster

The 2026-11-02 pagination fix was checked by render and dry-run only. This run tested it on
krateo-057 with rest-dynamic-controller 0.48.0, against a throwaway repository with 105 pull
requests, so `per_page=100` left #1 to #5 on page 2.

- **Page 2:** a `PullRequest` CR with no `status.number`, whose PR exists only on page 2, adopted
  #2 in under 20 seconds. A control CR on page 1 adopted #104.
- **No write:** the repository stayed at 105 PRs, and neither PR's `updated_at` moved.
- **Stable:** both CRs were still `Synced=True` after the next poll, about 3 minutes later.

This also covers recovery by `head` and `base`, using a new CR rather than one that lost its
status. It does not cover running out of `maxPages`, or a list changing during the walk.

## 2026-11-06 — feat: a second chart for the publishing Configurations

No chart created the `RepositoryConfiguration` and `PullRequestConfiguration` that builder
publishing needs. The ones on krateo-057 were applied by hand, so a fresh install or a child
Krateo did not get them. They can't go in the main chart, because their CRDs don't exist until
oasgen-provider has processed its RestDefinitions, and a kind with no CRD can't be rendered.
`github-provider-kog-config` carries them as a separate component, which the installer holds
back with `deps` and `requiresApiGroups`.

- **Same repo, same tag.** The shared release workflow publishes every first-class chart, and
  the two charts are coupled by the auth scheme in `chart/assets`.
- **Verified:** the render equals both live objects on krateo-057 on apiVersion, name, namespace
  and spec; core-provider's generator gives a CRD with no warnings, and it passes the API
  server's CRD validation; `hack/assert-config-chart.py` fails on a kind `chart/` doesn't have
  and on a non-bearer asset.
- **Not yet verified:** the chart through a composition on any cluster, and taking over objects
  that were applied by hand.

## 2026-11-06 — feat: choose which kinds render

Every kind runs a controller pod, so a child Krateo with a 100-pod quota could not fit the chart and still
publish through the builders. `registerOnly` was not the answer: without the `github.krateo.io` group every
default `BuilderPublish` fails at render. The new `kinds` value lists the kinds to render, and
`kinds: [Repository, PullRequest]` takes the provider from 33 pods to 3.

- **The default changes nothing.** `kinds` is empty, and the render is byte-identical to published 0.7.3.
- **Empty means all** because a default of 32 names would be stored on the composition and would hide any kind
  a later chart adds.
- **Verified:** render of the default, an explicit empty list and the two-kind list, where both RestDefinitions
  and ConfigMaps equal 0.7.3's; an unknown name fails the schema; core-provider's generator gives a CRD with
  the 32-name enum and no warnings, and it passes the API server's own CRD validation.
- **Not yet verified:** a composition on a cluster using the list, and removing a kind from a running install.
  The removal note in `configuration` comes from reading oasgen-provider, not from a run.
- `hack/assert-kinds.py` runs in CI: nothing else ties the guard in each template to its Kind or to the
  schema enum.

## 2026-11-06 — docs: a RestDefinition is not free

`values.yaml`, `overview`, `index` and `configuration` said a RestDefinition costs nothing until a CR of its
kind exists. That was false: oasgen-provider runs one `rest-dynamic-controller` pod per RestDefinition, CR or
not. krateo-057 runs 32 controllers plus one composition controller, and only `Repository` and `PullRequest`
have resource CRs. The claim mattered when a child Krateo sized its pod quota, where the chart's 33 pods hit a
100-pod limit and 6 were refused. No chart behaviour changes. Controllers that scale to zero until a first CR
exists are proposed in oasgen-provider#481.

## 2026-11-05 — test(environment): 0.7.3 verified through a controller; sample corrected

The 0.7.3 entry below says no `Environment` CR had run through a controller. One has now: krateo-057, chart
0.7.3, RDC 0.48.0, one writer, on a throwaway public repo that was deleted after.

- **A CR setting `wait_timer`, `prevent_self_review` and `reviewers` converges:** `Ready=True` with no further
  updates over 400s.
- **Drift is reverted:** an out-of-band change to `wait_timer` and `reviewers` was undone in 130s, and the CR
  then stayed quiet for another 400s.
- **Weaker evidence, two copies of the test ran together:** a field the CR omits survived an update, and each
  field reverted on its own. Neither test copy wrote a target value, so only the controller could have
  restored them, but those arms were not repeated with one writer.
- **`chart/samples/test-environment.yaml` was wrong for 0.7.3.** Its comment called `reviewers` write-only,
  and it set `prevent_self_review: true` without reviewers, which re-applies forever. Fixed. No asset changed,
  so no CRD regenerates; the sample reaches users with the next chart release.
- **Still not through a controller on 0.7.3:** `Collaborator`, `RepoContent`, `UserRepository`.

`docs/upgrading.md` also gains the cleanup for the `DeploymentConfiguration` CRD the 0.6.0 rename left behind.

## 2026-11-05 — release 0.7.3 (appVersion 0.1.9): Environment drift, spec-parameter docs

Rolls up the three PRs merged since **0.7.2** (#35–#37). `appVersion` moves `0.1.8` → `0.1.9` because the
trimmed OpenAPI **assets** changed in #35 and #36. The chart `version` is still the release tag. No new
kinds; the count stays **32**.

- **#35: `Environment` observes `wait_timer`, `prevent_self_review` and `reviewers`.** They were write-only,
  so a UI edit was never seen or reverted. See the dated entry below, including the one non-convergent case.
- **#36: seven `findby` exclusions are documented as load-bearing.** Comments and docs only.
- **#37: the stale kind count is gone from the `resourceGroup` description.** It said 29, and it also appears
  in the composition CRD's field description. That description is the only change to the composition CRD.

This entry also restores the 0.7.2 release heading, which #35 overwrote.

Upgrade notes for this roll:

- **Plain `helm upgrade` from 0.7.2, no migration.** None of the oasgen-immutable fields moved on any of the
  32 kinds, and `Environment` is the only `RestDefinition` whose spec changed (its get `responseTransform`).
- **Four OpenAPI documents changed:** `Collaborator`, `Environment`, `RepoContent` and `UserRepository`. Their
  `oasHash` moves, so oasgen regenerates those four CRDs. Rendered with oasgen-render 0.51.0 and 0.52.0, all
  32 CRD specs, all 32 Configuration CRD specs and the findings match 0.7.2, so no schema change is expected.
  That is a render result, not a reading of a stored CRD.
- **`Environment` CRs now revert out-of-band changes to fields they set.** A CR that sets `wait_timer`,
  `prevent_self_review` or `reviewers` is compared against GitHub on those fields, so a UI edit is overwritten
  on the next update. A CR that omits a field still leaves it alone.
- **`prevent_self_review: true` without `reviewers` re-applies forever,** by GitHub's design. Set it only with
  a non-empty `reviewers` list.
- **Not tested end to end:** the transform was verified live against GitHub, but no `Environment` CR has run
  through a controller on this chart version.

## 2026-11-05 — fix(docs): seven findby `excludedSpecFields` entries are load-bearing, not redundant

The chart stated that oasgen builds the spec from the create operation alone, so a parameter of any
other verb could never be a spec field, and called the `findby` exclusions redundant no-ops (the
2026-11-02 entry). Half of that is wrong. `getBaseSchemaForSpec` takes the **body** from create, but
`addParametersToSpec` loops over every verb, so **parameters merge from all of them**. Authorization
headers aside, a parameter stays off the spec only if a mapping supplies it (on any verb) or
`excludedSpecFields` names it.

Measured by removing 9 exclusions from a scratch request and rendering with oasgen-render 0.43.0 and
0.51.0, with an unmodified render of each as the control. Both versions agree:

| kind | exclusion removed | result |
|---|---|---|
| `Collaborator` | `affiliation`, `per_page` | **added to the spec** |
| `UserRepository` | `affiliation`, `sort`, `direction`, `per_page`, `page` | **added to the spec** |
| `RepoContent` | `ref` | stays absent (mapped) |
| `UserRepository` | `owner` | stays absent (mapped) |

So those seven entries are what keep the fields off the CRD. What they protect is the CRD surface, not
the request. A verb's static `queries` are set before spec is read and win over it, so
`spec.affiliation: all` would still send `affiliation=direct` (measured with a `BuildCallConfig` test
at 0.51.0; the order is the same at 0.43.0 and 0.48.0). Dropping an entry would give users a field that
silently does nothing, and could not reintroduce the false-exists bug the old comments credited it
with preventing: the static query prevents that. The 15 server-assigned
ids and `RepoContent`'s `ref` and `UserRepository`'s `owner` are redundant as stated, but because they
are mapped, not because they are absent from create. oasgen-provider's own test showed the premise was
wrong: an unmapped required path parameter on `get` only is present and required in the generated
spec.

**Behaviour does not change.** Of 314 parameters across the 32 kinds, no spec field exists only through
a non-create verb's parameter, so the wrong belief left nothing accidentally user-settable. The risk
was to the next kind written from these docs. `docs/configuration.md` now says to exclude or map every
parameter a user must not set, and `hack/assert-drift-invariants.py` fails if any of the seven entries
goes. Comments in the Collaborator, RepoContent and UserRepository assets changed, which moves their
`oasHash`, so those three CRDs regenerate when this ships; a render before and after is identical.

## 2026-11-04 — feat(environment): observe wait_timer / prevent_self_review / reviewers via a responseTransform

`Environment` could SET `wait_timer`, `prevent_self_review` and `reviewers` through the create-or-update
PUT, but GitHub returns them only nested in the `anyOf`-typed `protection_rules` array, never as
top-level keys — and oasgen has no anyOf, so the asset omitted it and the three fields were write-only:
a UI edit was never observed or reverted. This closes that gap the same way `BranchProtection` closes
its GET/PUT shape asymmetry: a whole-document `responseTransform` on the get verb flattens
`protection_rules` back into the top-level PUT shape (`wait_timer` int, `prevent_self_review` bool,
`reviewers` as `[{type, id}]` sorted by `(type, id)`), passing `id` / `node_id` / `name` / `url` /
`html_url` / `created_at` / `updated_at` / `deployment_branch_policy` through unchanged so the identifier
and `additionalStatusFields` survive. The three are declared as plain top-level properties in the GET
response schema (no anyOf), so the generated CRD and the drift comparison see them; `deployment_branch_policy`
is unchanged.

Absent-rule defaults make a CR converge. **Verified live 2026-11-03** (public throwaway repo, since
deleted): the transform's output equals GitHub's actual stored state in every case. GitHub's
protection-rule PUT is a **merge** — omitting a key keeps the current value — and an explicit
`wait_timer: 0` removes the wait_timer rule while `reviewers: []` removes the required-reviewers rule.
So the transform normalizes an absent wait_timer rule to `0` and an absent required-reviewers rule to
`reviewers: []` + `prevent_self_review: false`, exactly the state an explicit `0` / `[]` / `false`
produces — those CRs converge; and a CR that OMITS a key never sends it (no requestTransform) and never
compares it, so the out-of-band value is left untouched. Environment therefore does **not** silently
overwrite, and it leaves the "write-only, silently overwritten" class in the whole-value docs.

One non-convergent case by GitHub's design (not a transform defect), confirmed live: `prevent_self_review`
is carried inside the required-reviewers rule, so `prevent_self_review: true` with an empty/absent
`reviewers` list creates no rule — GitHub stores nothing, the transform returns `false`, and the CR
re-applies forever (idempotent, never converges). It cannot be rejected at admission until oasgen passes
cross-field validation through ([oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396),
the same blocker as the BranchProtection `checks` form); the asset and usage docs tell authors to set
`prevent_self_review` only with a non-empty `reviewers` list. The `User` reviewer path is verified live;
the `Team` path is modelled identically but was not live-tested (the test org had no teams).

No oasgen-immutable RD field changed (the 7 are byte-identical); the three were already in the PUT body,
so the generated spec is unchanged. Offline-validated: helm lint, 32/32 render, drift-invariants,
preflight-refs, oasgen CRD render (0 errors, no anyOf choke), and a gojq unit suite (no-rules / wait-only
/ reviewers User+Team unsorted / both / branch_policy / absent) with convergence and sort-matters checks.

## 2026-11-04 — release 0.7.2 (appVersion 0.1.8): all 23 ruleset rule types, shared release workflow

Rolls up the three PRs merged since **0.7.1** (#31–#33). `appVersion` moves `0.1.7` → `0.1.8` because
the trimmed OpenAPI **assets** changed in #32 (the two ruleset assets). The chart `version` is still the
release tag. No new kinds; the count stays **32**.

- **#32: the remaining 8 ruleset rule types** (`RepoRuleset`/`OrgRuleset`). Modelled types go **15 → 23**,
  so a rule added in the GitHub UI is no longer deleted for being inexpressible. Six were verified live on
  a Team-plan org. `workflows` and `license_compliance_scanning` are modelled but `422`-rejected there,
  which shows up as `Synced=False` with GitHub's message. See the dated entry below.
- **#31: samples stop enabling verbose request logging.** It was docs-only; the rendered chart does not change.
- **#33: releases go through the org-wide `release-oci` workflow.** From this release on, each published
  chart carries OCI provenance annotations (`org.opencontainers.image.revision` = the release commit). A
  published version can no longer be replaced: re-publishing it with different contents is refused, and
  identical contents are skipped. Release tags must be on `main`. A dry run against the already-published
  0.7.1 was refused and pushed nothing, and its digest is unchanged.

Upgrade notes for this roll:

- **Plain `helm upgrade` from 0.7.1, no migration.** No file under `chart/templates/` changed since the
  `0.7.1` tag, so all 32 `RestDefinition`s are byte-identical. None of the oasgen-immutable fields
  (`kind`, `identifiers`, `configurationFields`, `excludedSpecFields`, `resourceGroup`,
  `additionalStatusFields`, `includedSpecFields`) moved, and the pre-roll gate in
  [upgrading](./upgrading.md) is a no-op.
- **Two CRDs regenerate.** Only the `RepoRuleset`/`OrgRuleset` OpenAPI documents changed, so oasgen
  regenerates those two CRDs with a 23-value rule `type` enum. The change is additive: every CR valid on 0.7.1 stays valid.
- **Ruleset CRs now own every rule type.** A rule that exists on GitHub but is not listed in the CR is now
  reverted on the next update, like any other declarative field. Before #32, a rule of an unmodelled type
  was deleted because the CR could not express it. In both cases the CR's `rules` list is the whole truth,
  so list every rule you want kept.

## 2026-11-04 — feat: model the remaining 8 ruleset rule types (all 23 now modelled)

Added the last eight `RepoRuleset`/`OrgRuleset` rule types to both assets, so the union now
covers **all 23** of GitHub's rule types (was 15 after #27): `workflows`, `code_scanning`,
`copilot_code_review`, `license_compliance_scanning`, and the four push-target rules
`file_path_restriction`, `max_file_path_length`, `file_extension_restriction`, `max_file_size`.
Parameters were taken from GitHub's current REST `repository-rule` schema (docs.github.com/rest/repos/rules),
not from memory: `workflows` → `workflows[]` (each `repository_id`+`path` required, `ref`/`sha`
optional) + optional `do_not_enforce_on_create`; `code_scanning` → `code_scanning_tools[]` (each
`tool` + `security_alerts_threshold` ∈ {none,critical,high_or_higher,medium_or_higher,all} +
`alerts_threshold` ∈ {none,errors,errors_and_warnings,all}); `copilot_code_review` →
`review_on_push`, `review_draft_pull_requests` (both optional); `license_compliance_scanning` →
parameterless; push rules → `restricted_file_paths`/`ignored_file_paths`,
`restricted_file_extensions`, `max_file_path_length`, `max_file_size`. Added to the same flat
`{type, parameters}` union as the existing 15 (oasgen drops `oneOf` at generation —
`libopenapi_adapter.go` — so GitHub remains the authority that `422`s an illegal key for a type).
Purely additive; the 15 existing types keep an identical shape. Schema-only change: no RD file was
touched, so none of the seven oasgen-immutable #290 fields moved.

With the gap closed, `RepoRuleset`/`OrgRuleset` `rules` leaves the whole-value **data-loss**
capability-gap class (a UI-added rule is now simply reverted, declarative-by-design) and moves to
that class in `docs/configuration.md`. Usage constraints documented: a `merge_queue` rule's ruleset
needs a concrete ref; the four push rules require `target: push`; `workflows`/`code_scanning` take
hand-supplied identifiers.

Validation: `helm lint` + render (32 RestDefinitions + 32 ConfigMaps); `hack/assert-drift-invariants.py`
and `hack/preflight-refs.py` pass; the generated `RepoRuleset`/`OrgRuleset` CRDs (rendered with
`oasgen-render` 0.50.0) now expose a 23-value `type` enum and accept one valid CR per new type
(including the nested `required` on `workflows[]`/`code_scanning_tools[]`), while rejecting bad-enum,
wrong-type, missing-nested-required, unknown-type and missing-`type` samples.

Live round-trip (2026-11-04, private throwaway repos on a **Team-plan** org, deleted afterwards):
**six of the eight verified** — `code_scanning` (`CodeQL`/`high_or_higher`/`errors`) and
`copilot_code_review` on a branch ruleset; all four push rules on a `push` ruleset — order preserved
and casing verbatim (`file_extension_restriction` kept `*.ZIP` exactly). `file_path_restriction` and
`max_file_size` carry an optional `ignored_file_paths` that GitHub echoes as `[]` when omitted;
harmless, as the comparison walks only CR-declared keys. The other **two were `422`-rejected** on that
org's repository rulesets and could not round-trip there: `workflows` → `Invalid rule 'workflows':
Invalid parameter workflows: Workflow error at index 0:` (empty reason, seen even with a real
`.github/workflows/ci.yml` supplying a valid `repository_id`/`path`/`ref`/`sha`) and
`license_compliance_scanning` → `Invalid rule 'license_compliance_scanning':` (empty reason). Both
stay modelled: they are in GitHub's REST schema and a `422` is a loud failure (`Synced=False` with the
message), not a silent drop. Not verified on Enterprise or at org level. (The branch-protection set,
`merge_queue` and the pattern rules were live-verified earlier, on 2026-11-03.)

Dropped the `krateo.io/connector-verbose: "true"` annotation from all 32 samples under
`chart/samples/` (docs only; no chart value or rendered RestDefinition/ConfigMap changes).

With the annotation on, rest-dynamic-controller dumps every request *including the body* and
every response to the pod log (`httputil.DumpRequestOut(req, true)` at
`go/rest-dynamic-controller/internal/tools/client/restclient.go:1185`, oasgen-provider tag
0.50.0). Redaction covers only `secretRef`-resolved values (`RedactValues`, :1179-1189, :1276)
and credential *header* names (`credentialHeaderRe`, :1289-1348); body redaction is deliberately
absent (:114). This chart uses no `secretRef`, so a copied-as-is sample had every spec body value
logged in cleartext — most dangerously a `RepoWebhook`/`OrgWebhook` `spec.config.secret` (the
HMAC key, sent on create/update), but also `RepoContent` file content and anything else in the
spec. Pod logs are typically readable more widely than the CR. People copy samples into
production, so shipping the annotation on by default leaked the webhook secret to the RDC pod log.

Verbose is now documented in [usage](./usage.md#verify) and [examples](./examples.md) as an
opt-in debug aid only: enable it briefly, on a single non-sensitive CR, and never on a webhook
CR that carries a secret. No functional change to any kind.

## 2026-11-03 — release 0.7.1 (appVersion 0.1.7): ruleset + branch-protection modelling, #386 fix

Rolls up the five PRs merged since **0.7.0** (#25–#29). `appVersion` moves `0.1.6` → `0.1.7` because
the trimmed OpenAPI **assets** (the mapping that `appVersion` tracks) changed substantively in three of
them; the chart `version` is still the release tag. No new kinds — the count stays **32**.

- **#27 — `merge_queue` and five `*_pattern` ruleset rules** (`RepoRuleset`/`OrgRuleset`): modelled rule
  types go **9 → 15**, closing six of the fourteen whole-value data-loss gaps. Purely additive to the
  `{type, parameters}` union; the nine existing types keep an identical shape.
- **#28 — `BranchProtection` review `dismissal_restrictions` and `bypass_pull_request_allowances`**:
  two review sub-controls the CR could not previously express, normalized GET-object → PUT-string-list by
  the existing whole-document `responseTransform`. `required_status_checks` is byte-identical to main; the
  `checks` form is still held pending oasgen-provider#396.
- **#29 — `Repository`/`UserRepository` get+update keyed on `status.name`** (oasgen-provider#386): fixes
  the re-create loop when GitHub normalises a repo name on create (e.g. `my repo` → `my-repo`). The
  mapping changes only the path parameter, not the compare set, so it cannot trigger a rename-back PATCH.
- **#25, #26 — docs only**: the "every parameter becomes a spec field" correction and the whole-value
  update-semantics / "what a CR owns" sections. No YAML value changed in either (asset edits in #25 were
  comment-only).

Each change has its own dated entry below with full mechanics. Upgrade notes for this roll:

- **Plain `helm upgrade` from 0.7.0 — no migration.** A field-by-field diff of every one of the 32
  `RestDefinition`s between the `0.7.0` tag and this release shows **zero** change to any
  oasgen-immutable surface: `kind`, `identifiers`, `configurationFields`, `excludedSpecFields` and
  `resourceGroup` are byte-identical, and `additionalStatusFields` / `includedSpecFields` are unchanged
  (not even appended). So no RestDefinition crosses an immutable field and the pre-roll gate in
  [upgrading](./upgrading.md) is a no-op here.
- **Existing `Repository`/`UserRepository` CRs want `status.name`.** The #386 fix falls back to
  `spec.name` only until `status.name` is set, then addresses the GitHub-assigned name. Every one of the
  15 `Repository` CRs on krateo-057 already carries `status.name` (equal to `spec.name`), so the roll is a
  no-op for them; a CR whose status was wiped simply re-observes once and repopulates it.
- **`BranchProtection` clear-semantics.** **Omitting** `dismissal_restrictions` or
  `bypass_pull_request_allowances` from the review object leaves whatever actors are set on GitHub in
  place — these two nested lists are not part of the wholesale replace. To **clear** them, send explicit
  empty `users` / `teams` / `apps` lists.
- **`merge_queue` needs a concrete ref.** A `merge_queue` rule `422`s with *"Wildcard ref names are not
  supported when merge queue is enabled"* when the ruleset's `conditions.ref_name` is a wildcard such as
  `~ALL`; target a concrete ref (e.g. `refs/heads/main`).

## 2026-11-03 — feat(branchprotection): model review dismissal_restrictions and bypass_pull_request_allowances

Modelled two `BranchProtection` sub-controls the CR previously could not express, additively:
`required_pull_request_reviews.dismissal_restrictions` and `.bypass_pull_request_allowances`
(`{users, teams, apps}`). GitHub returns these as user/team/app **objects** on GET but takes login/slug
**strings** on PUT, so the whole-document `responseTransform` normalizes them to sorted string lists
exactly as it already does for top-level `restrictions` — each guarded with the
`if x == null then null else … end` form, never `//` on an already-normalized value, so a jq runtime
error still fails the reconcile. No request-side change (the whole review object is already forwarded);
both requestTransforms stay byte-identical to main.

The `required_status_checks` `checks` (context + `app_id`) form was investigated and **held**, not
shipped. `checks` and `contexts` are two representations of one list GitHub keeps derived from each
other, so a CR that set both would drift-loop — and that misconfiguration cannot be rejected at
admission because oasgen carries no `oneOf`/`not`/`x-kubernetes-validations` from the asset into the
generated CRD (verified against the 0.43.0 renderer and oasgen source: `libopenapi_adapter.go` reads
only `allOf`, the domain `Schema` type has no `OneOf`/`Not`/`XValidations`). It will be added once
oasgen supports admission-time cross-field validation (CEL passthrough requested in
[oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396)).
Status checks remain managed through `contexts`, exactly as before.

Verified live on 2026-11-03 (public org-repo round-trip): dismissal/bypass users round-trip case-exact,
and — a correction to the earlier assumption — **omitting** `dismissal_restrictions` /
`bypass_pull_request_allowances` from the review object does **not** clear previously-set actors (these
two nested lists are not part of the wholesale replace); a CR clears them with explicit empty
`users`/`teams`/`apps`. No oasgen-immutable field changed, and `required_status_checks` is byte-identical
to main; a CR that sets neither new field produces a byte-identical request body and an identical drift
outcome. This moves the two review sub-restrictions out of the data-loss class in the 2026-11-02 "what a
CR owns" section; the `checks` form stays in it, flagged as held.
## 2026-11-03 — fix: Repository/UserRepository key get+update on status.name (oasgen #386)

`Repository` and `UserRepository` keyed the get/update path parameter `name` on `spec.name`.
GitHub normalises a disallowed character in a repo name on create — `POST` body `name: "my repo"`
creates the repo `my-repo` — so a `GET /repos/{org}/my%20repo` by `spec.name` 404s **while the repo
exists**. `rest-dynamic-controller` reads a present-but-404 key as "does not exist" and re-creates,
GitHub answers 422 "name already exists", and the reconcile loops forever (oasgen-provider
[#386](https://github.com/krateo-platformops/oasgen-provider/issues/386)).

Fixed by the `Team` model: get and update now map `inPath: name` ← `status.name` (the name GitHub
actually assigned, already captured because `name` is the identifier). `Repository` uses
`fieldMapping`, `UserRepository` extends its existing `requestFieldMapping` (alongside
`owner` ← `status.owner.login`). Mechanics, traced against rest-dynamic-controller 0.43.0 (the
cluster version) and HEAD:

- **No PATCH loop.** The mapping only changes the path parameter, not the drift comparison. `name`
  is deliberately out of the PATCH body (the 0.2.2 decision), so it is not in the `updatable`
  compare set; `spec.name "my repo"` is never compared against the observed `my-repo`, so tracking
  the real name never triggers a rename-back PATCH. This was the main risk to rule out, and it is
  why the fix is the status-keying alone — no admission `pattern` and no change to the compare set.
- **Pre-create** `status.name` is absent, so the parameter falls back to `spec.name` and the `GET`
  404s correctly (the repo does not exist yet) → one create → `status.name` set → every later
  observe addresses the assigned name. `UserRepository`'s findby is unchanged and still recovers a
  lost/pre-create status.
- **Out-of-band rename** now converges: the redirect-following `GET` reports the new name,
  `status.name` tracks it, the next observe addresses it directly, and the old-name-reused
  wrong-bind goes away.

No change to `identifiers`, `excludedSpecFields`, `additionalStatusFields`, `compareScope`,
`configurationFields` or `resourceGroup` (immutable / append-only surfaces untouched). All 15
`Repository` CRs on krateo-057 already carry `status.name` equal to `spec.name`, so the roll is a
no-op for them. `hack/assert-drift-invariants.py` gains a presence assertion that both verbs keep
the `status.name` mapping, so removing it (which silently re-opens #386) now fails the `lint`
workflow.

## 2026-11-03 — feat: model merge_queue and the five pattern ruleset rules

**The claimed "collision" was not real.** The `RepoRuleset`/`OrgRuleset` asset comment had omitted
the five pattern rules because their `name`/`pattern` parameter keys "would collide with the
ruleset's own name inside a union `parameters` object". Checked against the oasgen-provider monorepo
at tag **0.43.0** (what clusters run) and current `main`: there is no such collision. oasgen's ONLY
name-merge logic is `addParametersToSpec` in `internal/tools/oas2jsonschema/spec_builder.go`
(`propertyExists`/`propertyNamed`, #108/#257): it reconciles a **root-level** request-body property
against a **path/query/header parameter** of the same name (e.g. `ruleset_id`, `owner`, `org`). It
iterates only the root `schema.Properties`, never nested body keys, and never merges body against
body. The pattern keys live at `rules[].parameters.{name,pattern}`, two levels below the top-level
ruleset `name`, so that merge cannot reach them; and a property literally named `pattern` is read
from the `properties` map by its key (`libopenapi_adapter.go`), a different field from the `pattern`
validation keyword. Proven by generating the CRD and validating CRs (below), where the pattern
`name`/`pattern` coexist with the top-level `name` with no error. The misleading comment was replaced
with this explanation.

With the collision disproved, six of the fourteen rule-type capability gaps the 2026-11-02
whole-value audit flagged as **data loss** (a rule type a CR cannot express is deleted on reconcile,
because the PUT re-sends the whole `rules` array) are now closed: `merge_queue` and the five pattern
rules `commit_message_pattern`, `commit_author_email_pattern`, `committer_email_pattern`,
`branch_name_pattern`, `tag_name_pattern`. They were added to the existing `{type, parameters}`
union, every key optional, with each type's GitHub-required set documented — **purely additive**, so
the nine existing types keep an identical shape. Modelled rule types go from 9 to 15; eight remain
unmodelled by design — the four product-reference rules (`workflows`, `code_scanning`,
`license_compliance_scanning`, `copilot_code_review`, which key other GitHub products by IDs this
provider cannot resolve) and the four Enterprise-only push-target rules (`file_path_restriction`,
`max_file_path_length`, `file_extension_restriction`, `max_file_size`).

**Round-trip — verified live.** Captured 2026-11-03 on a throwaway public repo
(`krateo-blueprints/kog-rt-20261103`, deleted and confirmed gone at the end). A branch-target ruleset
carrying five of the new types plus two controls, and a separate tag-target ruleset for
`tag_name_pattern`, were POSTed, GET back, and PUT a second time. Results: the `rules` array came back
in the **exact submit order** (the central positional-comparison risk did not materialise); enum
casing was **verbatim** (`merge_method: SQUASH`, `grouping_strategy: HEADGREEN`, operators
`regex`/`ends_with`/`contains`/`starts_with`) and pattern strings were stored exactly as sent,
regex escapes included (`^(JIRA-[0-9]+):\s.+`, `^v[0-9]+\.[0-9]+\.[0-9]+$`); the keys GitHub adds for
omitted optional fields (a pattern rule's `negate: false` and empty `name`; pull_request's
response-only `required_reviewers`/`dismissal_restriction`) were **skipped** by the comparator, which
iterates only the keys the CR declares and skips any response-only key
(`krateo-rest-dynamic-controller internal/tools/comparison/comparison.go:43`, the `for key, value :=
range mg` loop over the CR map, with response-only keys skipped at `:47-53`); and a second PUT+GET was
**byte-identical**. Zero drift across all six new types and the two controls. The five pattern rules
are **not** Enterprise-gated — they worked on a **Team-plan** org. One constraint surfaced: a
`merge_queue` rule `422`s (`Wildcard ref names are not supported when merge queue is enabled`) when the
ruleset's `conditions.ref_name` is a wildcard such as `~ALL`; it must target a concrete ref (e.g.
`refs/heads/main`). `compareScope: updatable` and the positional array comparison are unchanged.

Proof: `helm lint` + render (32 RestDefinitions + 32 ConfigMaps); `hack/assert-drift-invariants.py`
and `hack/preflight-refs.py` pass; strict server dry-run of both RestDefinitions on krateo-057
accepted (never applied); the `RepoRuleset`/`OrgRuleset` CRDs generated with `oasgen-render` at tag
0.43.0 accept one valid CR per new rule type plus a `pull_request` regression control, and reject
wrong-typed, bad-enum, unknown-type and missing-`type` samples; field-by-field immutable-field diff
vs `origin/main` shows zero changes (`kind`, `identifiers`, `configurationFields`,
`excludedSpecFields`, `resourceGroup`, `additionalStatusFields`, `includedSpecFields` all unchanged).

## 2026-11-02 — docs: whole-value update semantics and what a CR owns

A whole-map overwrite audit of the chart established that `rest-dynamic-controller` assembles an
update/PUT body **by top-level spec key**, so every object/map/array spec field is sent **whole on
every update**. `compareScope` governs only what is *compared* (what can *trigger* an update), never
what is *sent* — so once an update fires, the complete value from spec goes on the wire, and where
GitHub replaces that value rather than merging it, anything present on GitHub but absent from the CR
is removed. Arrays are compared positionally, so an out-of-band element does not slip past — it
lengthens the array, reads as drift, and triggers the very replacing PUT that deletes it.

The audit classified every exposed object/array across the 32 kinds into: **data loss / capability
gap** (the 14 unmodelled `RepoRuleset`/`OrgRuleset` rule types; `BranchProtection`'s unmodelled
`dismissal_restrictions` / `bypass_pull_request_allowances` / `checks` app_id form; webhook
`config` keys `token`/`digest`/`username`/`password`), **silent** (webhook `config.secret` — cleared
on any config PATCH if set out-of-band, and masked on read, the most important case; `Environment`'s
write-only `reviewers` / `wait_timer` / `prevent_self_review`), and **declarative by design** (the
rest, where the CR can express the value and a revert is normal Kubernetes behaviour). This is
documented in a new `docs/configuration.md` section, with a webhook-secret guidance block (the CR is
authoritative for the secret; why it is not yet sourced from a `Secret` — the `secretRef` resolver is
all-or-nothing, so an upstream absent-guard is needed first, tracked in
[oasgen-provider#383](https://github.com/krateo-platformops/oasgen-provider/issues/383) but held until a
constraint on which Secrets a resolver may read is designed, before an
optional `config.secretRef` can be added additively), and pointers from `docs/api.md`, `docs/usage.md` and the six affected
`rd-<kind>.yaml` assets.

The audit was prompted by the openstack-ironic-operator-kog session's finding that a partial
`spec.extra` deleted previously-set Ironic keys — the same whole-value replace hazard, in a different
provider. The webhook-`config.secret` clearing specifically is MED-HIGH confidence (GitHub's
wholesale-replace config model plus the asset authors' statement), **not** live-verified. Docs and
comments only — **no YAML value was added, removed, reordered or changed.** Proof: `helm template` of
`origin/main` and this branch parsed to **identical** objects across all 64 rendered documents (32
RestDefinitions + 32 ConfigMaps, the embedded asset YAML re-parsed); `helm lint`,
`hack/assert-drift-invariants.py` and `hack/preflight-refs.py` all pass.

## 2026-11-02 — docs: correct the "every parameter becomes a spec field" claim

> **Superseded.** This entry over-corrected: see the 2026-11-05 entry. Parameters do merge from every
> verb, and the five `UserRepository` and two `Collaborator` findby exclusions it calls redundant are
> load-bearing. Kept as written because the log is history.

Several comments and docs stated that **every OAS parameter of every verb** becomes a CR spec
field, and framed each `excludedSpecFields` entry as what keeps a parameter out of the CRD. That is
wrong. oasgen-provider builds a CRD's `spec` from the **create operation alone** — its request body
plus the create operation's own path/query parameters (`getBaseSchemaForSpec` hardcodes the create
action). A parameter that appears only on the other verbs is therefore never a spec field in the
first place.

Measured on krateo-057's live CRDs: the get/update/delete-only path parameters listed in
`excludedSpecFields` (`pull_number`, `hook_id`, `autolink_id`, `ruleset_id`, `key_id`,
`branch_policy_id`, `issue_number`, `milestone_number`, `release_id`, `deployment_id`,
`runner_group_id`, `configuration_id`, `team_slug`) — plus `RepoContent`'s `ref` and
`UserRepository`'s `owner` — are **absent** from `spec.properties`/`spec.required`, and oasgen emits
`field '<x>' set in excludedSpecFields not found in schema` for each. So those entries, and the
findby `queries` parameters (`Collaborator`'s `affiliation`/`per_page`, `UserRepository`'s
`affiliation`/`sort`/`direction`/`per_page`/`page`), are **redundant no-ops**. What actually fills a
non-create path parameter is either a same-named spec field the create operation already produced
(the real reason `Repository` renames its parameters to `org`/`name`) or a `requestFieldMapping` /
`fieldMapping` from `status`.

**Why the no-op entries stay.** `excludedSpecFields` is oasgen-immutable (#290); removing a redundant
entry would break upgrades on every existing cluster. Each such comment was reworded to say the entry
is retained for immutability, is a no-op because the field is not a create parameter, and records the
intent that the value is never author-supplied — **no `excludedSpecFields` entry (or any other YAML
value) was added, removed, reordered or changed.** Comments and prose only. Proof: `helm template`
of `origin/main` and this branch parsed to **identical** objects across all 64 rendered documents
(32 RestDefinitions + 32 ConfigMaps, the embedded asset YAML re-parsed), every raw textual difference
being a comment line; `helm lint`, `hack/assert-drift-invariants.py` and `hack/preflight-refs.py` all
pass.

## 2026-11-02 — `Collaborator` and `PullRequest` findby now paginate

Both findby verbs — `Collaborator` (`GET /repos/{owner}/{repo}/collaborators`) and `PullRequest`
(`GET /repos/{owner}/{repo}/pulls`) — read only the first page: they pinned `per_page=100` as a
static query and configured no pagination, on the now-stale belief that the controller's only
strategy was `continuationToken` (which re-sends a response header verbatim and cannot read GitHub's
Link header). The `pageNumber` strategy has in fact existed since **oasgen-provider 0.24.0** (#142),
under the chart's 0.38.0 floor.

Consequence of the old behaviour: a repository with **more than 100 PRs** could leave a created PR on
page 2 invisible to findby recovery, so the reconciler re-created it and GitHub wedged on 422 *"pull
request already exists"*; **more than 100 direct collaborators** made observe misread the grant.

**Fix.** Each findby gains a `pagination` block (`type: pageNumber`, `pagePath: page`,
`sizePath: per_page`, `pageSize: 100`, `maxPages: 50`) and drops the `per_page` static query — the
paginator now sets both `page` and `per_page` on the URL. End-of-collection is the **short-page** rule
(no `response` block): the Link-header signal is deliberately avoided because GitHub omits that header
on single-page results and a declared-but-absent header is reported as Indeterminate. Exhausting
`maxPages` is also Indeterminate, never not-found, so it can never cause a duplicate create
(50 × 100 = 5000 items before the walk gives up). The seven oasgen-immutable fields are unchanged on
both kinds; `page` is not declared as an OAS parameter (the paginator sets it directly), so
`excludedSpecFields` is untouched. (`UserRepository`'s findby, added in #23, already uses this same
`pageNumber` block — it is the source of the pattern.) Verified with `helm lint`/`template` (32 kinds),
the drift and preflight hacks, and a strict server dry-run against krateo-057.

## 2026-10-31 — `UserRepository` added (user-owned repos, 32nd kind)

`UserRepository` closes the one remaining feature gap versus the legacy standalone `github-provider`: creating a repository under the **authenticated user** rather than an org. It is the user-owned sibling of `Repository` — a separate kind because a RestDefinition has exactly one create verb and cannot choose `POST /orgs/{org}/repos` vs `POST /user/repos` at runtime. `appVersion` → `0.1.6`; the chart is now **32 kinds**.

- Create is `POST /user/repos` (no path parameter — GitHub assigns the owner from the TOKEN). There is **no hand-set owner**: `owner` is excluded from the spec and read back into `status.owner.login`, which feeds the get/update path `/repos/{owner}/{name}`. Before that status exists, observe is a `findby` over `GET /user/repos` pinned to `affiliation=owner` (owned repos only, so names are unique), newest-first, walked with `pageNumber` pagination that ends on a short page — not the `Link` header, which GitHub omits entirely on single-page results and which would therefore read as Indeterminate. A same-name repo already in the token's account is adopted, not duplicated. This removes the failure a hand-set owner had: a mismatch created the repo in the token's account, then 404'd on observe and wedged on 422 "name already exists".
- **Identity is the token**: the repository lands in the account that owns the referenced Configuration's token, so the sample gives `UserRepository` its own Configuration (`github-user-config` / `gh-user-token`) instead of the shared org PAT.
- **No delete verb**, deliberately — deleting the CR orphans the repository, it does not destroy it, the same oasgen-provider #125 cascade-safety `Repository` takes.
- `name`, `private` and `visibility` are kept out of the PATCH body for the identical reasons documented for `Repository`: a compared `name` would let drift rename a live repo, and compared `private`/`visibility` would flip the exposure of repos that already exist. `compareScope: updatable` is load-bearing for the same reason.

Verified: `helm lint` clean; `helm template` renders 32 ConfigMaps + 32 RestDefinitions; `hack/assert-drift-invariants.py` (now asserting `UserRepository` too) and `hack/preflight-refs.py` pass; a server-side dry-run (`--validate=strict`) of both new RestDefinitions is admitted by krateo-057 (oasgen-provider 0.43.0).

## 2026-10-31 — `RepoContent` restored natively (31st kind)

`RepoContent` — the last git-write kind still out (`Repository` → `GitRef` → `RepoContent` per file →
`PullRequest`) — returns as a plain native `RestDefinition`, no proxy plugin, completing the git-write
restoration that `PullRequest` and `GitRef` began. `appVersion` → `0.1.5`; the chart is now **31 kinds**.

**How it is native** (full design in [design-repocontent](./design-repocontent.md)):

- The get verb relocates `spec.branch` onto GitHub's `?ref` query via a `fieldMapping` (the OAS
  parameter is declared `ref` and `excludedSpecFields`, so the CR expresses the branch once, and the
  PUT/DELETE bodies still take it as `branch`).
- A `responseTransform` on get strips GitHub's RFC-2045 line-wrapping from `content`, so a byte-identical
  file does not loop "update" forever — with a `del(.content)` guard for the `encoding: none` case GitHub
  returns for files ≥ 1 MB (leaving it would PUT a new commit every reconcile).
- `responseTransform`s on create/update lift GitHub's nested `content.{sha,path,html_url}` to the root, so
  `populateStatusFields` (root keys only) fills status after a write — without which a second quick spec
  edit would PUT sha-less.
- `requestTransform: del(.sha)` on create drops a stale `status.sha` (a create only ever runs against an
  absent file); update and delete auto-source `sha` from `status.sha`, so no pre-call read is needed — the
  reason this needs no `dependentLookups` the way `GitRef` did (oasgen-provider #120).

**Delete verb kept, deliberately.** Unlike `Repository` (which drops `delete` so the oasgen-provider #125
CRD cascade can never destroy a repo), `RepoContent` keeps its native delete — deleting the CR deletes the
file. A file is recoverable from git history and delete is the documented RepoContent lifecycle, but the
same cascade applies: dropping the RestDefinition or uninstalling the chart deletes every managed file.
A conscious trade, flagged in the design.

`compareScope` is left at the default `fullSpec`: the get response carries only `path`, `content` and an
optional `sha`, so the compared set is exactly `content` — the one thing the kind manages — and
`updatable` would derive the same set. It is the one non-`updatable` kind that *has* an update verb.

Verified: `helm template` renders **31 ConfigMaps + 31 RestDefinitions** with no error;
`hack/assert-drift-invariants.py` and `hack/preflight-refs.py` both pass.

## 2026-10-29 — `Deployment` kind renamed to `RepoDeployment` (fresh-install blocker, 0.6.0)

**A fresh install of any version carrying the `Deployment` kind cannot converge on oasgen-provider
≥ 0.32.0.** `kind: Deployment` in group `github.krateo.io` generates the plural `deployments`, which
`apps/v1` already serves; oasgen's shadowing guard ([krateo-platformops/oasgen-provider#200](https://github.com/krateo-platformops/oasgen-provider/issues/200),
since 0.32.0) **refuses to create** a CRD whose plural or singular collides with a built-in, so the
RestDefinition `…-deployment` stays `Creating`/`ReconcileError` and the whole chart never reaches
Ready. It had gone unnoticed because the guard only **warns** where the CRD already exists (krateo-057
has had it for weeks, unaffected) — it bites only a FRESH cluster. Surfaced by the snowplow session on
a fresh install (installer 0.3.467, oasgen 0.39.0).

**Fix: rename the kind to `RepoDeployment`** (→ plural `repodeployments`, collision-free; matches the
chart's repo-scoped naming). Same GitHub repository Deployments API, same verbs. An authoritative
screen of all 30 kinds against a live cluster's non-CRD api-resources (plural **and** singular)
confirmed `Deployment` is the only collision; `DeploymentBranchPolicy` → `deploymentbranchpolicies` is
clear and is untouched. Files renamed `*-deployment.yaml` → `*-repodeployment.yaml`; `appVersion`
→ `0.1.4`.

**Fresh clusters: nothing to migrate** — the rename alone converges (no existing `deployments.github.krateo.io`
CRs).

**Existing clusters — the migration, and oasgen already guards the scary part.** The old kind has a
`DELETE` verb (`DELETE /repos/{owner}/{repo}/deployments/{id}`), so the fear was that a rename-upgrade
removes the old RestDefinition, oasgen drops `deployments.github.krateo.io`, the CRs cascade-delete and
their finalizers destroy the real GitHub deployment records. **oasgen refuses to let that happen:**
`deploy.Undeploy` (`go/oasgen-provider/.../deploy.go:437`) counts live instances **at the moment of the
destructive act** (not from a prior reconcile) and returns `ErrLiveInstances` if any exist; a **failed
LIST also refuses** ("'I could not count' must never read as 'there were none'"). So removing the old RD
on a populated cluster **blocks** — the RD sits in `Deleting`, and the CRD, its CRs and their external
resources all survive. There is no cascade to race and no timing window. krateo-057 has **0** instances
(checked, clean); a mistaken roll to krateo-demo's `tenant-acme`/`globex` children would **stall, not
destroy**.

**Annotation (`krateo.io/deletion-policy=orphan`), after four code-backed passes — don't rely on it.**
It is real and lives in **unstructured-runtime** (`pkg/meta`), it's a **managed-resource (CR) annotation**
(not a Composition one — which is why core-provider's grep of *their own* tree missed it), and RDC
**does** honour it: RDC links unstructured-runtime (v1.4.0), whose worker removes the finalizer when the
policy is orphan. (An interim pass wrongly concluded "RDC never calls `ShouldDelete`" — that grep was
against RDC's own tree, not its dependency: a false negative.) **But it is non-deterministic — it races.**
The worker removes the finalizer with **no early return**, so execution falls through to `handleDelete`,
which fetches the object first; if that fetch wins the apiserver reap, the external DELETE fires anyway
on the very pass that honoured the policy. So an orphan-annotated delete is a timing coin-flip. The
missing-early-return bug is tracked as **oasgen-provider#276** (fix belongs in unstructured-runtime). And
`krateo.io/management-policy: observe-delete` forces `ShouldDelete` true, silently defeating orphan. So
the annotation is NOT a dependable lever; the deterministic route below is.

Whether orphan governs a given CR at all comes down to **which finalizer that CR carries** — the worker
removes exactly `composition.krateo.io/finalizer` and nothing else. Measured on 057: **every
github.krateo.io CR carries exactly that finalizer** (confirmed on the 15 `Repository` and 17
`PullRequest` CRs; it is the only finalizer value present across the group). So for github-provider-kog
the annotation does govern our CRs (it is *not* inert — that was true of provider-runtime kinds like
`git.krateo.io/LocalResource`, which carry `finalizer.managedresource.krateo.io`, a different runtime's
finalizer the block can't touch), and the strip command below targets the correct name. `Deployment`
(now `RepoDeployment`) had 0 instances on 057, so a migration runbook must **check the finalizer on the
actual cluster being migrated** rather than assume — `kubectl get <kind>.github.krateo.io -A -o
jsonpath='{.items[*].metadata.finalizers}'`. (Meta-lesson from four wrong answers in one afternoon: each
came from pinning two of three axes and assuming the third — *which repo* the annotation lives in
[dependency, not core-provider's tree], *which runtime version* [rdc `unstructured-runtime` v1.4.0 vs cdc
v1.6.0], and *which finalizer the CR carries*.)

**Completing a rename migration on a populated cluster** (so the old RD can finally be removed) means
clearing the old-kind CRs **without firing their finalizers**. The hazard: reaching zero by *deleting*
the CRs is itself the destructive act — each delete fires `composition.krateo.io/finalizer` and the
external DELETE, hand-executing the cascade oasgen's guard would otherwise have blocked. Safe sequence
per CR — **finalizer off first, then delete**:

```
kubectl patch <kind>.<group> <name> -n <ns> --type merge -p '{"metadata":{"finalizers":null}}'
kubectl delete <kind>.<group> <name> -n <ns>
```

Better: adopt the instances onto the new kind, confirm it observes the same external objects, *then*
strip finalizers and remove the old ones. Scaling the RDC controller to 0 is **not** a substitute — the
CRs keep their finalizers, sit `Terminating`, and the CRD hangs with them. (The other teardown path —
Composition deleted/re-rendered → cdc `drainFinalizerBoundChildren`, which *escorts* the external DELETE
through by design, cdc #108 — is guarded by `helm.sh/resource-policy: keep` on the rendered objects; a
kind rename is not that path.)

github-provider-kog itself: 0.6.0 is safe on fresh clusters and on krateo-057 (0 instances).

**Rehearsed and verified (2026-10-29)** on a throwaway kind cluster (k8s **v1.36.1**, RDC
`rest-dynamic-controller:0.38.0`, digest `sha256:1f2cdf22305b6617b55596d5c8a2b0ccca8708f2e3f8a99f4dce3bed1d4e8146`)
against the real GitHub Deployments API, using the shipped `RepoDeployment` kind (the pre-rename
`Deployment` kind is itself refused by the #200 guard on 0.38.0 — a bonus re-confirmation). Every
`RepoDeployment` CR carried exactly `composition.krateo.io/finalizer` **even after a successful reconcile
that created a real deployment record**. Four delete arms, external DELETE read off the RDC request log
and confirmed by the record's fate on GitHub:

- **strip finalizer → delete:** no external DELETE, record survived.
- **control (sole finalizer intact, no orphan):** DELETE fired, record 404 — proving the null results are real.
- **`deletion-policy=orphan` + sole finalizer:** no DELETE, record survived (synchronous reap; no GET/DELETE in the log at all).
- **orphan + a second finalizer:** DELETE fired, record 404 — the log shows **GET then DELETE**, i.e. the object survived the governed-finalizer removal and the fall-through ran. Orphan is defeated by any second finalizer.

So the deterministic model holds (no race; **multiplicity** is the variable, not timing), and
strip-the-governed-finalizer-first is the verified-safe migration. Caveat worth keeping: a second
finalizer protects the local object only from **that** delete pass, not permanently — the two-finalizer
CR was reaped by a later pass once the other holder released, so "a second finalizer keeps it alive" is
half true.

**Verified runbook for the krateo-demo roll** (when it eventually takes 0.6.0): (1) check which finalizer
the old-kind CRs carry on the *target* cluster — `kubectl get <kind>.github.krateo.io -A -o
jsonpath='{.items[*].metadata.finalizers}'`; (2) per CR, **strip the finalizer first, then delete** (the
two commands above) — never delete with it intact, never rely on `deletion-policy=orphan`; (3) only then
remove the old RestDefinition (oasgen's `deploy.go:437` blocks the CRD drop while instances exist, so a
premature RD removal just stalls — it does not cascade). Shared with the ironic-operator-kog session for
its identical `Node`→`nodes` rename against hardware.

## 2026-10-28 — `GitRef` restored natively: dependent lookups make a sha-less create work (30 kinds)

`GitRef` is back — the chart's 30th kind — and the plugin stays gone. The one blocker
[design-gitref §3.2/§4](./design-gitref.md) recorded as "NOT expressible" at 0.23.0, the pre-call
base-sha dependent read, shipped upstream as **dependent lookups** in **oasgen-provider 0.36.0**
([krateo-platformops/oasgen-provider#120](https://github.com/krateo-platformops/oasgen-provider/issues/120),
merged as #239). So the kind returns in the form the design ranked best and last: **Shape B +
dependent lookups**.

What shipped (`chart/assets/gitref.yaml`, `chart/templates/rd-gitref.yaml`):

- **Short-form `spec.ref`** (`heads/<branch>` / `tags/<tag>`), guarded by an OAS `pattern:
  '^(heads|tags)/.+'` so a full `refs/...` form is rejected at admission instead of looping
  create→422. The create verb's `requestTransform` adds the `refs/` prefix the POST body wants;
  create/get/update carry a `responseTransform` (`ltrimstr("refs/")`) so `status.ref` never flaps.
- **`spec.sha` is OPTIONAL.** A two-step `dependentLookups` chain (repo → `default_branch` → that
  branch's `git/ref/{ref}` → `object.sha`) fills the create body's `sha` **only when the CR omits
  it** (`when.customResourceFieldAbsent: spec.sha`); an explicit `spec.sha` wins and skips the
  lookups. This is exactly what the retired plugin's `createGitRef` did, now native.
- **Branch-creation semantics (§3.3):** `compareScope: identifiersAndStatus` projects the compared
  set to `{ref}`, so the base `sha` is excluded structurally and can never drive a branch-rewinding
  PATCH; the head commit is read-only under `status.object.sha`.

Chart requirement bumped to **oasgen-provider ≥ 0.38.0** (0.38.0 is where the `GitRef` pattern admission guard reaches the CRD; dependent lookups landed in 0.36.0 and are load-bearing).
appVersion → `0.1.3`. `RepoContent` is still out; nothing in the active publish path needs `GitRef`
(the frontend defaults to `BuilderPublish` over `git-provider`), so this is parity/completeness —
"the knowledge outlives the code" — not a revived dependency.

## 2026-10-19 — `PullRequest` group-B recovery: a findby keyed on head/base (#14 closed)

The other half of #14 is now fixable, because the upstream dependency shipped. The controller
normalizes each findby list item with the verb's own `responseTransform` **before** matching
([krateo-platformops/oasgen-provider#145](https://github.com/krateo-platformops/oasgen-provider/issues/145),
merged via PR #155, released in **oasgen-provider >= 0.25.0**) — the exact change §8.2 said it would
take. So `PullRequest` identity moves to **`identifiers: [head, base]`** (`identifiersMatchPolicy: AND`)
and a **`findby`** verb (`GET /repos/{owner}/{repo}/pulls`, `state=all`, `per_page=100`) is added.

A CR created without a `status.number` (the group-B case: a 422 "already exists", an async/no-body
create) now recovers on its next reconcile — observe finds no number, runs the findby, matches the PR
by head/base, and populates `status` (number included, so later reconciles use `get` and
`merged`/`merged_at` start reporting). Group A (number present) is unchanged: it still observes via
`get`; identifiers drive findby MATCHING only, not the get path.

Mechanics worth noting: moving identity to head/base is **not** a breaking CRD change —
`IncludeIdentifiersInSpec` is off by default so identifiers are not in the spec schema; they are
appended to the (additive) status schema, so `head`/`base` now appear in `status` as strings. That
forced the `head`/`base` object→string `responseTransform` onto **all four** verbs (create, get,
update, findby), since status is written from every response and only the producing verb's transform
runs — the four copies are byte-identical by necessity. `head`/`base` are declared `string` in
`assets/pullrequest.yaml` so the status projection types them. Chart now requires
**oasgen-provider >= 0.25.0** (load-bearing: on an older controller the findby match cannot succeed
and observe would re-create). `appVersion` → `0.1.2`.

## 2026-09-28 — `PullRequest` reports `merged` and `merged_at`; the group-B findby gap, documented (#14)

`PullRequest.status` gains **`merged`** (a plain boolean) and **`merged_at`** (an RFC3339 string, null
until merged), both via `additionalStatusFields`. `state` collapses
a merged and a closed-but-unmerged PR into the single value `closed`; GitHub reports the difference
only through `merged`, and nothing read it, so the publish chain could not tell an accepted change from
a rejected one without inferring "closed?"; `merged_at` carries when it merged. Both are safe where
`head`/`base` are not (scalars in all three responses, never spec fields, so they never enter drift),
and `merged` was the option [design-pullrequest §6 note 7](./design-pullrequest.md) already flagged as safe.
Both populate only while the CR keeps being re-observed (the get verb repopulates them each reconcile).
`appVersion` → `0.1.1` (mapping revision).

The other half of #14 — a CR that never recorded `status.number` can never be re-observed — is **not**
fixable in a RestDefinition, and [design-pullrequest §8](./design-pullrequest.md) now records why: the
controller (`217ccd0`) matches raw findby list items *before* the `head`/`base` `responseTransform`
runs, so a findby keyed on head/base can never match (object in the list, string in the spec). A
correct findby needs the controller to normalize items before matching — the change the
`isInResource` `TODO` anticipates, filed as
[krateo-platformops/oasgen-provider#145](https://github.com/krateo-platformops/oasgen-provider/issues/145).
Left for that upstream change rather than papered over with a fragile title-keyed findby that would
fall below this chart's correctness bar.

## 2026-09-17 — `Repository` exposure is create-only, and can no longer be flipped by a reconcile

`private` and `visibility` are out of the PATCH body, so they leave the `updatable` compare set.
Changing a repository's exposure is no longer something drift reconciliation can decide to do.

**Caught before it shipped, not after.** `portal#227` flips `builder-publish`'s destination repos
from private to public, on sound reasoning: a GHCR package inherits the visibility of the repo that
published it, and there is no API to change org container-package visibility afterwards, so a
private destination publishes a chart nobody outside the org can install. Its PR body said
*"existing ones keep their visibility."* That was not true. `builder-publish` renders a `Repository`
on every publish (`{{- if .Values.repository.create }}`, default `create: true`) with
`private: {{ .Values.repository.private }}`, and core-provider's default `UpgradePolicy` is
`Automatic` — so flipping the values default re-renders every live `Repository` CR, the GET echoes
the real visibility, the difference reads as drift, and the PATCH goes out against repositories
nobody was asked about. `portal#227`'s own table names a currently-private repo. That PR is on hold
behind this change.

The asymmetry is what makes this different from ordinary drift. For nearly every field,
"reconcile the CR back onto reality" is exactly right. For an exposure control it inverts the safe
default, and it inverts it in the direction that has no undo: a repository that was public for one
reconcile stays forked, cloned, cached and search-indexed after it is made private again. Which
repositories are public is a decision their owner makes, not one a chart version bump makes for
them.

`visibility` goes with `private` although #11 only names `private`. It is the same field by another
name in the same two bodies, GitHub echoes it on every GET, and it is the *more* likely re-entry
path — the product direction behind `portal#227` is a publish form offering repository visibility
and package visibility as independent choices. Fixing one and leaving the other would have left the
hazard fully live.

Three things this change is careful about:

- **It stops them being SENT, not merely compared.** The outgoing request body is filtered to the
  fields the operation declares (`processFields` in rest-dynamic-controller's `builder.go`), so a
  PATCH triggered by `description` drift now carries no visibility field at all. GitHub's PATCH is
  partial, so omitting it leaves the repository alone. There is no residual path by which a
  reconcile touches exposure.
- **The CRD does not change.** oasgen-provider builds the spec schema from the CREATE body plus
  path/query params only (`getBaseSchemaForSpec` hardcodes the create action), never from the
  update body. `spec.private` and `spec.visibility` still exist and are still honoured at create.
  Generated before and after the edit, the spec schema is byte-identical: no migration, no CR
  rewrite, no immutability problem. Create-only is cheap here precisely because of that.
- **`compareScope: updatable` is now LOAD-BEARING on this kind.** It was defensive until today and
  this repo said so, in a comment and in three doc pages. It no longer is: GitHub echoes `private`
  and `visibility` on every GET, so the default `fullSpec` compares every echoed spec key
  regardless of the PATCH body and would restore the hazard in full. Setting `Repository` back to
  `fullSpec`, or simply deleting the line, is the same regression as re-adding the fields — with
  no error, no condition and nothing failing.

That last point is why this change also adds `hack/assert-drift-invariants.py`, run by the `lint`
workflow. The guarantee here lives entirely in two absences and one word, in two different files,
and nothing in the CRD or the RestDefinition schema records it. The script asserts that `name`,
`private` and `visibility` are absent from the PATCH body, that `private` and `visibility` are
still present in the create body (a create-only field that leaves the create body stops being
settable at all), and that `Repository` still declares `compareScope: updatable`. It covers the
0.2.2 rename fix too, which was equally unguarded.

**Status changes on existing CRs, expected and not a convergence.** Any live `Repository` whose
`spec.private` disagreed with the real repository was reporting `Unavailable` with
`Resource is not up-to-date due to …private…`. After this it reports `Available` *without*
converging — the divergence is now ignored rather than fixed. Enumerate those CRs before rolling so
nobody reads the status flip as the fix having changed something on GitHub.

One upstream coupling worth recording, because nothing here would notice it breaking: this fix
depends on oasgen-provider continuing to build the spec from the create body alone, and on
rest-dynamic-controller continuing to derive `updatable` from the update body. If either ever
unions create and update, the behaviour changes with no edit to this chart.

Verified: the drift-compare set and the PATCH request body were computed by
rest-dynamic-controller's own `UpdatableBodyPaths`/`RequestedBody` against this asset, before and
after. Before — 9 compared fields, `private` and `visibility` both compared and both sent. After —
7 compared fields (`archived`, `default_branch`, `description`, `has_issues`, `has_projects`,
`has_wiki`, `homepage`), `private` and `visibility` neither compared nor sent, both still in the
11-field create body. The CRD spec schema was generated through oasgen-provider 0.23.1's
`BuildSpecSchema` from both versions of the asset and is byte-identical, 13 properties including
`private` and `visibility`. `helm lint` clean; the chart renders 29 ConfigMaps + 29
RestDefinitions. No live GitHub round trip — the create/flip/observe sequence in #11 is a bench
step, not something this repo can run.

## 2026-09-15 — `PullRequest` comes back, natively

`PullRequest` returns as the **29th kind**, and it returns without the plugin that carried it
before. The chart renders 29 ConfigMaps + 29 RestDefinitions and still ships **no runtime
component**: no Deployment, no Service, no image, no proxy.

One field does the work the plugin's `getPullRequest` handler used to do. GitHub returns
`head`/`base` as objects (`{ref,label,sha,repo,user}`) while `spec.head`/`spec.base` are the
branch strings the create body carried; compared raw they read as permanent drift, and the PATCH
cannot fix either — `head` is not even in the PATCH body. A `responseTransform` on the get verb
rewrites them back into the CR domain once, before status population and drift comparison:

```jq
. as $r
| ((($r.head | type) == "object") and (($r.base | type) == "object")
   and ((($r.head.repo.full_name) // "") != (($r.base.repo.full_name) // ""))) as $cross
| (if (.head | type) == "object" then .head = (if $cross then .head.label else .head.ref end) else . end)
| (if (.base | type) == "object" then .base = .base.ref else . end)
```

It is **better than the plugin it replaces**: `flattenPRRefs` always took `obj["ref"]`, so a PR
opened from a fork — whose `spec.head` must be written `"owner:branch"` — flattened to the bare
branch and drifted anyway. The cross-repo branch fixes that.

`compareScope: updatable` ships with it, and is load-bearing rather than cosmetic. The kind
previously shipped `fullSpec`, which also compares `draft` and `maintainer_can_modify` — both in
the create body, both echoed by the GET, neither in the PATCH body. That was a latent defect
independent of the plugin: mark a draft PR "ready for review" in the UI and a `draft: true` CR
drifts forever. `identifiersAndStatus` was rejected outright — it would project the spec onto
`number`/`html_url`/`state`, none of which are spec fields, leaving an empty set that compares
equal unconditionally.

No delete verb, the same shape as `Issue` and for the same reason: GitHub's REST API cannot delete
a pull request. Unlike `Issue`, this kind cannot close one from its spec either — `state` lives in
the PATCH body only, and the CRD spec is built from the create body plus path/query parameters.
Merge or close the PR on GitHub, then delete the CR.

The compareScope tally moves to 24 updatable, 2 unset, 1 explicit `fullSpec`,
2 `identifiersAndStatus` = 29.

Verified: `helm lint` clean; the chart renders exactly 29 ConfigMaps + 29 RestDefinitions and
nothing else, with zero plugin references and no per-operation `servers` override anywhere in the
rendered OAS; all 58 objects accepted by the **deployed** `restdefinitions.ogen.krateo.io` CRD at
oasgen-provider 0.23.0 on krateo-057 via `kubectl apply --dry-run=server`, confirmed absent after.
The transform was run under **gojq 0.12.19** — the engine in rest-dynamic-controller's `go.mod`,
not `jq` — over all six cases in the design document, three passes each: every one idempotent,
the live `octocat/Hello-World#2846` cross-repo body 48 keys in and 48 keys out, and the naive
`.head.ref // .head` form failing on pass 2 exactly as predicted (`expected an object but got:
string`). `GitRef` and `RepoContent` stay out; their design documents remain proposals.

This kind has still never reconciled against GitHub. Verified by inspection, schema validation and
engine-level replay, not by running.

## 2026-09-09 — 31 kinds become 28, and the plugin goes with them

`GitRef`, `RepoContent` and `PullRequest` are **deleted**, and the companion proxy plugin
is deleted with them. The chart is now **28 kinds and 100% native**: it renders 28
ConfigMaps + 28 RestDefinitions and nothing else — no Deployment, no Service, no image, no
proxy, and therefore **no runtime component at all**. Nineteen files went: those three
kinds' assets, ConfigMaps, RestDefinitions and samples, `deployment-plugin.yaml`,
`service-plugin.yaml`, `_helpers.tpl` (it held only the two plugin helpers), the whole
`plugin/` Go tree, and `.github/workflows/release-image.yaml`. The three
`<Kind>Configuration` entries left `chart/samples/configurations.yaml`, which now carries
28. Nothing is `tpl`-rendered any more either: the per-operation `servers` overrides that
forced it were the plugin's routing, so all 28 ConfigMaps are a plain `.Files.Get`.

**Why: the caller is gone.** Those three were the transport of the legacy
blueprint-publish path — the Autopilot builder writing a chart tree to a repo as
`github.krateo.io` CRs (`GitRef` → `RepoContent` per file → `PullRequest`). The frontend
now defaults to an SCM-agnostic route: `AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to
`"true"` in the frontend chart's `values.yaml` **and** its `values.schema.json`, so a
fresh install publishes through a `BuilderPublish` claim over `git-provider`, and the
`github.krateo.io` route is the explicit `"false"` fallback. They were also the only kinds
still routed through the plugin, so removing them and the plugin was one change rather than
two. This retires a superseded path; no current capability moved or was lost with it.

**The knowledge survives the deletion.** One design document per removed kind records what
the kind did, what the plugin's handlers did for it and why, and exactly what it would take
to bring the kind back **natively**: [design-gitref](./design-gitref.md),
[design-repocontent](./design-repocontent.md),
[design-pullrequest](./design-pullrequest.md). Their headline findings:

- **`PullRequest` comes back whole today.** Its only plugin behaviour was flattening
  `head`/`base` on observe; one whole-document `responseTransform` on the get verb (plus
  `compareScope: updatable`) replaces it, and fixes the fork case the plugin got wrong.
- **`RepoContent` comes back fully native today.** `status.sha` auto-populates the update
  body, `responseTransform`s replace the content normalisation, and the `%252F`
  double-escape that shaped the old handler is fixed upstream in 0.23.0 (#113). The one
  loss is a bounded 422-retry the next resync recovers.
- **`GitRef` comes back except for one thing.** Resolving the base HEAD sha on create is a
  pre-call dependent read `RestDefinition` cannot express — tracked as oasgen-provider
  **#120**. Natively, the kind returns with `spec.sha` as a required input; observe, update
  and delete are native with no caveat.

Release is simpler by exactly one artifact: the tag now drives `release-oci.yaml` alone,
publishing the chart, with no image to co-version ([release](./release.md)).

Verified: `helm lint` clean; `helm template` renders 28 ConfigMaps + 28 RestDefinitions
with zero plugin references anywhere in the output; every RestDefinition path and method
cross-checked against its own OAS document; and all 28 rendered RestDefinitions accepted by
the **deployed** `restdefinitions.ogen.krateo.io` CRD at oasgen-provider 0.23.0 on
krateo-057 via `kubectl apply --dry-run=server`. As before, there is **no** live end-to-end
run against GitHub for any kind.

## 2026-09-09 — four kinds become 31

The chart now ships 31 `RestDefinition`s. The 27 new ones are **native** — none of them
touches the companion plugin, which still serves only `GitRef`, `RepoContent` and
`PullRequest`. Coverage is now access (`Team`, `TeamRepo`, `TeamMembership`,
`Collaborator`, `OrgMembership`), repository configuration (`RepoWebhook`, `OrgWebhook`,
`DeployKey`, `Environment`, `RepoRuleset`, `OrgRuleset`, `Autolink`, `BranchProtection`),
CI/CD (`ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`,
`DeploymentBranchPolicy`, `Workflow`), work tracking (`Label`, `Milestone`, `Issue`,
`Release`, `Deployment`) and governance (`CustomProperty`, `CodeSecurityConfig`,
`AutomatedSecurityFixes`), on top of the four git-transport kinds. Each new kind is a
`RestDefinition` + a trimmed OpenAPI spec + the ConfigMap wrapping it, and a
`<Kind>Configuration` in `chart/samples/configurations.yaml`, which now carries all 31.
One PAT still drives the whole chart — the Configurations may all share one name — but
what that PAT must be *allowed* to do now varies by kind: the git-write kinds need only
contents/refs/pulls, `Repository` needs org repository creation, and the org-scoped kinds
(`Team`, `OrgMembership`, the rulesets, the runner group) need org admin rights.

**What is deliberately absent.** GitHub Actions, Dependabot and Codespaces *secrets* are
not expressible as a `RestDefinition` and were not attempted: writing one requires an
`encrypted_value` — a LibSodium sealed box — plus the `key_id` of a repository public key
that has to be fetched first, which is client-side crypto and a dependent lookup, neither
of which a RestDefinition can do. Variables are **not** secrets (GitHub stores and returns
`value` verbatim), which is why all three variable kinds are here and no secret kind is.
`VulnerabilityAlerts` was evaluated and dropped for an unrelated reason: `GET
/repos/{owner}/{repo}/vulnerability-alerts` answers 404 when the feature is off and **204
with no body** when it is on, so it never returns a body at all — nothing to derive a
status schema from, nothing for a drift predicate to read. `AutomatedSecurityFixes` is the
contrast that makes the rule concrete: its GET *does* return a body (`enabled`, `paused`),
so it is expressible, and it is covered.

**`compareScope`, split four ways.** 23 kinds declare `updatable` — compare exactly what
the update body can express, which needs both oasgen ≥ 0.23.0 and an update verb. Five
leave the default `fullSpec` (`GitRef`, `RepoContent`, `PullRequest`, `Workflow`,
`AutomatedSecurityFixes`); for the last two that is a checked conclusion rather than an
omission — their specs hold nothing but path parameters, so `fullSpec` compares nothing
and cannot report false drift, and the drift that matters is caught by a `notFoundBody`
predicate instead. `Autolink` sets `fullSpec` explicitly: it has no update verb, but its
GET echoes the whole resource, so an edited CR *should* report drift, because the fix is
delete-and-recreate and `identifiersAndStatus` would report Ready while the spec and the
repository disagreed. `DeployKey` and `Deployment` use `identifiersAndStatus` — both also
have no update verb, so `updatable` is unavailable to them, and for both the compared set
under `fullSpec` would be a field nothing could ever fix. With 23 kinds on `updatable`,
the chart's effective floor is now oasgen-provider **0.23.0**, not the 0.20.0 recorded
below.

**Four defects the verification pass caught**, each fixed in the file it belongs to:

- **`Team`'s update answers 201, not 200.** GitHub returns 201 when the PATCH actually
  changes something and 200 only "when the updated information already exists" — and the
  controller issues an update *only* after observing drift, i.e. exactly in the 201 case.
  rest-dynamic-controller accepts only the 2xx codes the operation declares, so a document
  listing 200 alone would have turned every real team rename into `invalid status code:
  201`, forever. Both codes are declared.
- **`Deployment`'s `auto_merge` defaults to true at GitHub.** When `ref` is behind the
  default branch, that default makes GitHub merge instead of deploying and answer 202 with
  a message body: no deployment, no id, nothing for status to hold, and a get verb that
  sources `{deployment_id}` from `status.id` can then never address anything — a green
  create with a permanently unobservable CR. The asset pins the default to `false`, the
  same call `repository.yaml` makes on `auto_init`.
- **`Milestone`'s `due_on` can be written but never compared.** GitHub treats a due date
  as a day: it discards the time and stores midnight *in the timezone of the account that
  owns the token*, then echoes it back in UTC. Measured over ~120 dated milestones on
  public repositories, only about half come back at midnight UTC, and within a single
  repository the offset flips exactly at the US daylight-saving boundaries — a server
  converting a date in a fixed timezone, not a client echo. For a positive UTC offset even
  the date differs (an Europe/Rome token writing `2026-12-31` reads back
  `2026-12-30T23:00:00Z`). Left in the update body it would have been a compared field and
  therefore a PATCH on every reconcile forever, one that "succeeds" each time. It is
  create-only; what GitHub stored is readable on `status.due_on`.
- **`Collaborator` over-reports the role.** The obvious observe endpoints are both wrong:
  `GET /collaborators/{username}` returns 204/404 with no body, and
  `.../permission` returns the *effective* permission, so any org member on an org repo
  reads back as an existing, up-to-date collaborator and the PUT never fires. Observe is a
  `findby` over the collaborator list pinned to `affiliation=direct`, the one view that
  reports the repository-level grant this CR owns, and a `fieldMapping` aliases GitHub's
  display vocabulary (`read`/`write`) onto the request's (`pull`/`push`). What remains is
  documented rather than papered over: when a user's effective role *exceeds* the grant
  (an org owner, or a team granting more), observe reports the higher role and the pair
  loops one findby + one PUT per reconcile — GitHub exposes no way to read the
  repository-level grant on its own.

Verified: `helm lint` clean; all 31 kinds render; every RestDefinition path and method
cross-checked against its own OAS document, with zero mismatches; and all 31 rendered
RestDefinitions accepted by the **deployed** `restdefinitions.ogen.krateo.io` CRD at
0.23.0 via `kubectl apply --dry-run=server` under throwaway names, with absence confirmed
afterwards. There is **no** live end-to-end run against GitHub for any kind — the
behaviours recorded above come from the API's own documents and from read-only
measurement, not from a round trip through a controller.

## 2026-09-10 — `Repository` has no delete verb, so a cascade cannot destroy repositories

Removing the CR now ORPHANS the GitHub repository instead of deleting it. `Repository` has
`create`, `get` and `update`, and no `delete`.

This is a safety change, not a tidy-up. oasgen-provider deletes a RestDefinition's CRD
**unconditionally** (`SkipCRD: false`), which cascade-deletes every CR of that kind, which runs
every finalizer. With a delete verb, that chain ended in `DELETE /repos/{org}/{name}`. So deleting
the RestDefinition, uninstalling the chart, or any CRD-version migration would have **destroyed
every repository this kind ever created, and the code in them.** That is oasgen-provider **#125**,
found on krateo-057 where a duplicate `github-provider-kog` install could not be hand-cleaned for
exactly this reason — the safe move was to leave the duplicate running.

Verified before making the change, because the obvious risk was reintroducing a finalizer wedge
like the one that killed GitRef: rest-dynamic-controller handles an absent delete verb by logging
"API action delete not found" and **returning nil** (`restResources.go` `Delete`, `apiCall == nil`
branch at 0.23.0). The finalizer is released, the CR goes, the external resource is left alone.
Nothing wedges.

The trade is deliberate and asymmetric. A leaked repository is an inconvenience someone can delete
in GitHub. A destroyed one is not recoverable from here, and for a blueprint DESTINATION repo
"removing the CR should never remove the code" is plainly the right default. Restore the verb only
once the #125 guard exists upstream, and then only behind a per-CR opt-in.

Docs corrected everywhere they claimed the opposite — `api.md`, `overview.md`, `usage.md` and
`examples.md` all said deleting the CR deletes the repository, which was true when written.

## 2026-09-10 — `Repository` no longer reconciles a rename

`name` is out of the PATCH body, so it leaves the `updatable` compare set. Renaming a repository is
no longer something drift reconciliation can decide to do.

Found in production on krateo-057, the first day this chart ran real traffic. `builder-publish`
1.8.0 created six `Repository` CRs from live BuilderPublish claims; two failed, and one of them was
this:

`publish-tk-petstore-repo` targets `krateo-platformops/krateo-oas`, which **has been renamed to
`krateo-platformops/oas`**. GitHub redirects a renamed repo, so the observe GET follows it and
reports `name: oas` while the spec still says `krateo-oas`. With `name` compared, that read as
drift and the controller issued a PATCH — which GitHub answered **307**, surfacing as
`update failed: unexpected status: 307`.

The error was the good outcome. Had that redirect been followed, the reconcile would have RENAMED a
live repository back to a stale name nobody asked for. A kind that quietly renames real
repositories to satisfy its own drift check is worse than one that errors.

`name` remains a path parameter and a create-body field, so creating and addressing a repository are
unchanged. Only rename-reconciliation is gone.

**The other failure is NOT fixed here and is not a bug in this chart.** `publish-cnpg-cluster-repo`
targets `EdmondDantes21/cnpg-cluster` — and `EdmondDantes21` is a **User**, not an Organization. This
kind models only `POST /orgs/{org}/repos`; GitHub's user-owned create is `POST /user/repos`, and a
RestDefinition has one create verb and cannot choose between two paths (recorded when the kind was
written). The observed 404 on PATCH is GitHub declining to confirm a repository the token cannot
write. The fix belongs upstream of here: either the publish destination should be org-owned, or
per-verb path selection has to exist. See oasgen-provider #120 for the shape of that gap.

## 2026-09-09 — oasgen-provider 0.23.0: `Repository` moves to `compareScope: updatable`

krateo-057 was upgraded to oasgen-provider **0.23.0**, which adds a third `compareScope`
value. `Repository` now uses it, replacing the `identifiersAndStatus` recorded below.

`updatable` compares exactly the fields the UPDATE verb's request body can express, derived
from the OAS. That is the set this kind wanted all along: the three create-only fields
(`auto_init`, `gitignore_template`, `license_template`) drop out — a field the update cannot
send is one the controller cannot fix, so comparing it can only produce an update that
changes nothing — while `description`, `homepage`, `private`, `visibility`, `has_issues`,
`has_wiki`, `has_projects`, `default_branch` and `archived` stay compared and stay fixable.
It requires an update verb, which `Repository` has.

So the documented cost of the earlier setting — that editing `description` or `private` on
an applied CR was silently never pushed — is gone. This strictly replaces it; there is no
reason to prefer `identifiersAndStatus` here.

Verified against the live cluster rather than inferred: all four RestDefinitions, plus the
`GitRef` short-ref fix on its branch, were accepted by the deployed
`restdefinitions.ogen.krateo.io` CRD at 0.23.0 via `kubectl apply --dry-run=server` under
throwaway names — including the CRD's own "requires an update verb" validation on
`updatable`. Nothing was created.

0.23.0 also carries four fixes this chart cares about: the `%252F` double-escape in query
values (#113), a delete-finalizer arbiter (#103), 200-tombstone-is-absence (#111), and
nested dotted identifier selectors (#106). The chart still requires **≥ 0.20.0** in general;
`compareScope: updatable` specifically requires **≥ 0.23.0**.

> **Corrected the same day** — the reason given above is wrong, and the wrong reasoning was
> copied into other kinds and into the docs before it was caught. The three create-only
> fields were never compared under `fullSpec` either: the drift comparison **skips** any
> spec key the observe response does not carry — `rmValue, ok := rm[key]; if !ok
> { continue }` in rest-dynamic-controller `internal/tools/comparison`, reached from
> `isCRUpdated` (`internal/controllers/helpers.go`), which projects the spec onto
> `scopeFields` only for `identifiersAndStatus` and `updatable`. An absent key therefore
> contributes nothing under *every* scope, and the same goes for path parameters. What
> genuinely loops is a key the response **does** carry, in a different shape or a
> server-normalised value the update cannot fix — `TeamRepo`'s string `owner` against an
> owner object, `PullRequest`'s `head`/`base`, `Milestone`'s re-timed `due_on`,
> `Collaborator`'s effective `role_name`, `Issue`'s `labels`/`assignees` — which is why
> *those* kinds genuinely need `updatable`. For `Repository` it is defensive rather than
> load-bearing: it and `fullSpec` should agree today, and it is kept because it states the
> intent explicitly and stays correct if a field the `PATCH` cannot send is ever added.
> **No `compareScope` value changed** as a result — only the reasoning was wrong.

## 2026-09-09 — renamed to `github-provider-kog`, chart included

The repository and the Helm chart are both now `github-provider-kog`; they were
`krateo-github-provider-kog`. The chart name is what consumers pin, so it was renamed while
**nothing pins it yet** — the installer's `component-pins.yaml` has no entry for it — rather than
after, when a rename would mean re-pinning and a stale package.

The name was not free until now: a forked alternative (`github-provider-kog-chart`, a copy of an
older upstream chart) already published `charts/github-provider-kog`.
That fork has been deleted along with its package, and this — the from-scratch provider — takes
the name.

Consequences worth knowing:

- New releases publish to `oci://ghcr.io/krateo-blueprints/charts/github-provider-kog`. The old
  `charts/krateo-github-provider-kog` package (one version, `0.1.11`) is now stale. Nothing
  references it; it can be deleted whenever someone wants to.
- **The plugin image deliberately keeps its old name**, `krateo-github-provider-kog-plugin`. The
  plugin is on its way out — every kind it serves is being moved to native RestDefinition features
  — so renaming it would publish a second package only to delete it again, and orphan the versions
  already pushed. When the plugin goes, its Deployment, Service and image go together.
- Rendered values are unchanged except the `app.kubernetes.io/part-of` label. The `pluginName`
  helper builds its name from `.Release.Name`, not the chart name, so
  `spec.selector.matchLabels` — which Kubernetes treats as immutable on a Deployment — is
  byte-identical. The rename is safe to roll onto an existing install.
- The Go module path moved with the repo
  (`github.com/krateo-blueprints/github-provider-kog/plugin`). Nothing imports it; the plugin is a
  single `main` package.

## 2026-09-09 — `Repository`: create the destination repo, not just write into it

A fourth kind, `Repository`, maps GitHub's repository API onto `github.krateo.io`: create
on `POST /orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}`. All four verbs
are **native** — `Repository` never touches the companion plugin, so its ConfigMap is
copied verbatim rather than `tpl`-rendered (the other three are `tpl`-rendered only
because they carry per-operation `servers` overrides pointing at the plugin).

It is ordered first in the authoring chain — `Repository` → `GitRef` → `RepoContent` (per
file) → `PullRequest`. Until now a blueprint could only be published into a repository
someone had already created by hand. `auto_init` defaults to `true` in the OAS, and that
default is load-bearing: a repository created without it has no commit and therefore no
default branch, so a `GitRef` has no base sha to branch from and a `RepoContent` has
nothing to commit against.

**`compareScope: identifiersAndStatus`, and what it costs.** Three fields in the create
body — `auto_init`, `gitignore_template`, `license_template` — are create-only: GitHub
accepts them on `POST` and never echoes them back on `GET`. Under the default `fullSpec`,
Observe compares every spec field against the GET response, so those three would read as
permanent drift and the controller would `PATCH` the repository on every single reconcile,
forever, against an API with a 5000 req/hr budget. `identifiersAndStatus` compares only
`name` plus the `additionalStatusFields`, which ends the loop — and its cost is real and
accepted: editing `description` or `private` on an existing CR is **not** pushed to
GitHub. For a create-once destination repository that trade is right. At the version
available when this was written the enum had only these two values, so the alternative
was not a narrower compare but dropping the three create-only fields from the create body
— which means losing `auto_init`, the thing that guarantees a default branch.

> **Superseded the same day** — see *oasgen-provider 0.23.0* below. `updatable` compares
> exactly what `PATCH` can send, which ends the loop *and* keeps mutable fields
> reconciled, so the cost recorded above no longer applies.

> **Corrected the same day** — there was no loop to end. The "permanent drift, `PATCH` on
> every single reconcile forever" reasoning above is wrong: the comparison skips a spec key
> the GET response does not carry, so the three create-only fields could not have drifted
> under `fullSpec` at all. Full correction, with the controller code, under *oasgen-provider
> 0.23.0*. The setting recorded here was already superseded, and no `compareScope` value
> changed because of the correction.

Two smaller decisions. The path parameters are named `org` and `name`, not GitHub's
`owner`/`repo`: the same two CR fields then serve the create path (`/orgs/{org}/repos`),
the create body (`name`) and the get/update/delete path (`/repos/{org}/{name}`), so the
generated CRD carries one pair of fields instead of an `org`/`owner` duplicate the author
has to keep in sync. And `POST /user/repos` is deliberately not modelled: a
`RestDefinition` has one create verb and cannot choose between two paths, and Krateo
destinations are org-owned.

`Repository` also asks more of the PAT than the other three — repository creation in the
org (classic token `repo`; fine-grained token org **Administration: read & write**) on top
of the contents/refs/pulls scopes. Its own `RepositoryConfiguration` joins the set in
`chart/samples/configurations.yaml`; all four may share a name.

Verified so far: `helm lint` clean; `helm template` renders 4 ConfigMaps + 4
RestDefinitions; every RD path and method cross-checked against its own OAS document; the
identifiers and `additionalStatusFields` confirmed present in the `Repository` response
schema; and the rendered RestDefinition accepted by the deployed
`restdefinitions.ogen.krateo.io` CRD on krateo-057 via `kubectl apply --dry-run=server`
under a throwaway name (nothing created, absence verified afterwards). There is **no**
live end-to-end run of `Repository` against GitHub yet.

Unrelated to the kind, and recorded here because this is the change set it landed in: the
GitHub repo is now `krateo-blueprints/github-provider-kog`. The Helm chart is still named
`github-provider-kog` and still publishes to `charts/github-provider-kog`;
that rename is deferred because the shorter name is currently held by another published
package.

## 2026-08-11 — Documentation Standard adoption

The repo adopts the Krateo Documentation Standard (OKF): the invariant docs bundle
(`index`/`overview`/`usage`/`configuration`/`api`/`examples`/`release`/`log` +
`llms.txt`), a runnable `examples/blueprint-authoring`, a rewritten six-section
`README.md`, and the shared `lint-docs` check wired into a new `lint.yaml`. Part of
krateo-platformops/installer#52.

## Design decisions worth keeping

- **KOG, not a forked provider.** Every kind is a pure OpenAPI mapping
  (`RestDefinition` + trimmed spec); oasgen-provider (≥ 0.23.0, for `compareScope:
  updatable`) generates the CRDs and auto-deploys a `rest-dynamic-controller` per kind.
  The chart ships no controller of its own — and since the plugin's removal, no runtime
  component of any kind.
- **No proxy.** All 28 kinds are native: every verb goes straight to GitHub. The
  companion plugin existed for exactly three kinds and was deleted with them. When a kind
  needs more than a plain OpenAPI mapping, the answer is a 0.23.0 RestDefinition feature —
  `responseTransform`, `fieldMapping`, `compareScope` — not a service; where even that is
  not enough, the gap is written down (`docs/design-*.md`) instead of coded around.
- **The chart carries no credential.** The token lives in an out-of-band Secret
  referenced by the oasgen-generated `<Kind>Configuration` CRs, which whatever drives the
  kinds only references.
- **One tag, one artifact.** A bare-semver tag drives `release-oci.yaml`, which packages
  the chart. There is nothing else to publish and nothing to co-version.
