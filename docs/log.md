---
type: Log
title: github-provider-kog — log
description: Curated chronological history of github-provider-kog — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [log, history]
timestamp: 2026-09-09T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.

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

The name was not free until now: a forked alternative (`github-provider-kog-chart`, a copy of
`krateoplatformops/github-provider-kog-chart`) already published `charts/github-provider-kog`.
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
  The chart ships no controller of its own.
- **A companion plugin only for what OpenAPI cannot express.** The plugin
  (`plugin/main.go`) is reached solely via per-operation OpenAPI `servers` overrides,
  for exactly the verbs that need it — GitRef create (auto-resolve base sha) and observe
  (git/ref-vs-git/refs asymmetry), RepoContent idempotent write + branch-aware,
  base64-canonicalizing observe, and PullRequest observe (flatten head/base). Every
  other verb goes straight to GitHub.
- **The plugin carries no credential.** It forwards the caller's `Authorization`
  header; the token lives in an out-of-band Secret referenced by the oasgen-generated
  `<Kind>Configuration` CRs, which the portal write-path only references.
- **Chart and plugin image co-version on one tag.** The plugin Deployment pins
  `:{{ .Chart.Version }}`; `release-image.yaml` publishes the image on the same
  bare-semver tag `release-oci.yaml` uses for the chart.
