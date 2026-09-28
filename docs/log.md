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

## 2026-09-28 — `PullRequest` reports `merged`; the group-B findby gap, documented (#14)

`PullRequest.status` gains **`merged`** (a plain boolean, `additionalStatusFields`). `state` collapses
a merged and a closed-but-unmerged PR into the single value `closed`; GitHub reports the difference
only through `merged`, and nothing read it, so the publish chain could not tell an accepted change from
a rejected one without inferring "closed?". `merged` is already in the OpenAPI schema, is safe where
`head`/`base` are not (a boolean in all three responses, never a spec field, so it never enters drift),
and was the option [design-pullrequest §6 note 7](./design-pullrequest.md) already flagged as safe.
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
