---
type: Configuration
title: github-provider-kog — configuration
description: The whole config surface — the single chart value resourceGroup, the 30 RestDefinition mappings grouped by area, the compareScope tally and the reasoning behind each non-default choice, the native normalizations GitHub's REST inconsistencies demand, the OpenAPI ConfigMaps, and the invariants that must hold for a chart that ships no runtime component.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, values, restdefinition, oasgen-provider]
timestamp: 2026-09-09T00:00:00Z
---

# Configuration

The chart surface is deliberately tiny — one scalar. Everything else is fixed mapping
(`chart/assets/`, `chart/templates/`).

## Chart values

`chart/values.yaml`, typed by `chart/values.schema.json`
(`additionalProperties: false` — an unknown key fails the schema):

| key | default | effect |
|---|---|---|
| `resourceGroup` | `github.krateo.io` | the API group every generated CRD lands under — 30 resource kinds plus a `<Kind>Configuration` auth kind for each. Referenced by every RestDefinition's `spec.resourceGroup`. |
| `global` | `{}` (object) | Helm global values, injected by the chart-inspector / when used as a subchart. |

The schema declares **only** a single top-level scalar on purpose: when the chart is
installed as a Krateo component the CDC derives the CompositionDefinition CRD from this
schema, and a scalar default materializes cleanly in the component CR (nested-object
toggles would not) ([api](./api.md)).

There is **no per-kind toggle**. All 30 RestDefinitions are always installed; a
RestDefinition costs nothing until a CR of its kind exists, and a per-kind switch would
mean nested-object values the CDC cannot materialize.

## The RestDefinition mappings

Each `chart/templates/rd-<kind>.yaml` declares the API mapping oasgen-provider consumes;
its in-file comments carry the reasoning behind every choice below. `configurationFields`
is empty for all 30 — the token wiring comes from the oasgen-generated
`<Kind>Configuration` + `spec.configurationRef`, never from spec fields. The full
per-kind verb, identifier, `compareScope` and status listing is in [api](./api.md); what
follows is the mapping mechanics.

Three patterns recur across the set and are worth reading once:

- **Server-assigned identifiers.** When GitHub assigns the item key on create, that key
  is `excludedSpecFields` (so it never becomes a required spec field the author has to
  fill in) and each item verb sources it from status via `requestFieldMapping`. That is
  `Release`'s `release_id` / `status.id` shape, shared by `Milestone`, `Issue`,
  `RepoWebhook`, `OrgWebhook`, `DeployKey`, `Autolink`, `RunnerGroup`,
  `DeploymentBranchPolicy`, `RepoRuleset`, `OrgRuleset`, `CodeSecurityConfig` and
  `Deployment`. `Team` uses the same shape on `team_slug`, and `fieldMapping` rather than
  `requestFieldMapping`.
- **PUT as create *and* update.** Where GitHub exposes one idempotent upsert,
  `create` and `update` name the same method and path: `Collaborator`, `OrgMembership`,
  `TeamMembership`, `TeamRepo`, `Environment`, `CustomProperty` and `BranchProtection`
  all declare one method and one path for both.
- **Path parameters are spec fields.** Every OAS parameter of every verb becomes a CR
  spec field of the same name, which is why several assets rename or exclude parameters
  rather than accept GitHub's naming (see `Repository`'s `org`/`name` below, and
  `CustomProperty`'s `property_name`).

**Access**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Team` | `slug` | `team_slug` is `excludedSpecFields`; get/update/delete source it from `status.slug` via `fieldMapping`. `chart/assets/team.yaml` declares **both** `201` and `200` on the PATCH — see below. |
| `TeamRepo` | `full_name` | one PUT for create and update. The get verb carries a static `Accept: application/vnd.github.v3.repository+json` header (without it GitHub answers 204) and a `responseTransform` that derives the CR-domain `permission` from the cumulative `permissions` booleans — highest true flag wins, floor `pull`. |
| `TeamMembership` | `url` | one PUT for create and update; a real get with a body. `url` is the only response property that names the membership — `username` is never echoed. |
| `Collaborator` | `login` | observe is a **findby** over the collaborator list, pinned by static `queries` (`affiliation=direct`, `per_page=100`), both `excludedSpecFields`. A `fieldMapping` alias maps GitHub's `read`/`write` onto the body's `pull`/`push` and relocates the value onto `spec.permission`; a second identity entry re-writes `role_name` to `status.role_name`, without which the first mapping would consume the key and status would never populate. |
| `OrgMembership` | `url` | one PUT for create and update; a real get with a body and a real 404 for a non-member (verified live), so no `notFoundBody` and no findby are needed. |

**Repository configuration**

| kind | identifiers | key mapping facts |
|---|---|---|
| `RepoWebhook` | `id` | `hook_id` excluded, sourced from `status.id`. `chart/assets/repowebhook.yaml` keeps `secret` (and the create-only `name`) **out of the update body**, which is what keeps the masked `********` out of the comparison; the PATCH still sends the whole `config` map. |
| `OrgWebhook` | `id` | identical to `RepoWebhook`, org-scoped. Org hooks have no `test_url` (that is repository-only), so the two status lists coincide. |
| `DeployKey` | `id` | `key_id` excluded, sourced from `status.id`. `additionalStatusFields` is server-side facts only (`url`, `verified`, `created_at`) so that the compared set under `identifiersAndStatus` contains no spec field at all. |
| `Environment` | `name` | no server-assigned key and no create/item path split, so no `excludedSpecFields` and no `requestFieldMapping`: every verb addresses the environment by the same three spec fields. |
| `RepoRuleset` | `id` | `ruleset_id` excluded, sourced from `status.id`. `rules` and `bypass_actors` are compared element-by-element **in order**. |
| `OrgRuleset` | `id` | same as `RepoRuleset`, org-scoped. |
| `Autolink` | `id` | `autolink_id` excluded, sourced from `status.id`. `additionalStatusFields` is empty — the response carries only `id` plus the three create-body fields and a nullable `updated_at` the asset does not declare. |
| `BranchProtection` | `url` | a `requestTransform` on both PUT verbs turns four omitted members into the explicit `null` GitHub requires, and a whole-document `responseTransform` on get rewrites GitHub's differently-shaped answer back into the CR domain. `additionalStatusFields` is empty on purpose. |

**CI/CD**

| kind | identifiers | key mapping facts |
|---|---|---|
| `ActionsVariableRepo` | `name` | the item is addressed by `{name}`, so `name` is trimmed from the update body — a rename could never converge, and leaving it uncompared also neutralises GitHub's case-insensitive variable naming. |
| `ActionsVariableOrg` | `name` | as above, plus `selected_repository_ids` confined to the create body (GitHub's read side returns only `selected_repositories_url`). |
| `EnvironmentVariable` | `name` | as `ActionsVariableRepo`, one scope deeper — `environment_name` is a third path parameter. |
| `RunnerGroup` | `id` | `runner_group_id` excluded, sourced from `status.id` — deliberately **not** the upstream `findby`-by-name approach, since create already returns the id and a findby would page a list endpoint on every reconcile. `selected_repository_ids` and `runners` are create-only. `name` **stays** in the update body here: keyed by id, a rename is a real convergent update. |
| `DeploymentBranchPolicy` | `id` | `branch_policy_id` excluded, sourced from `status.id`. Create body `{name, type}`, update body `{name}` alone. |
| `Workflow` | `id` | create is `PUT .../enable`, delete is `PUT .../disable`; there is no update verb. A `notFoundBody` predicate on get reports `disabled_manually`, `disabled_inactivity` and `deleted` as absent — the whole reconciliation loop of this kind. `disabled_fork` is deliberately excluded. |

**Work tracking**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Label` | `name` | one CR field serves identity, item path and create body. **Rename is not modelled**: GitHub's PATCH takes `new_name` while the path addresses the current name, which needs two names in one CR field and is not derivable by the controller's only request-side transform (`alias`). |
| `Milestone` | `number` | `milestone_number` excluded, sourced from `status.number`. `due_on` is **create-only** — kept out of the update body because GitHub re-times it per token timezone; `status.due_on` shows what was stored. |
| `PullRequest` | `head`, `base` | Identity is head+base (#14), so a `findby` can recover a CR that lost `status.number`. `pull_number` excluded, sourced from `status.number`; get/update bind it from there, so group-A (number present) still observes via `get` — identifiers drive findby MATCHING only. No delete verb (GitHub REST has none), and no close-from-spec either (`state` is PATCH-body-only, so it never reaches the spec). Every verb (create/get/update/findby) carries the SAME `responseTransform` that rewrites GitHub's `head`/`base` objects to their branch strings — `base` always `.ref`, `head` `.label` for a cross-repo (fork) PR and `.ref` otherwise — applied before each response populates status, so `status.head`/`status.base` are always strings. `status` also carries `merged` (a plain boolean) and `merged_at` (an RFC3339 timestamp, null until merged) via `additionalStatusFields`: `merged` distinguishes a merged PR from a closed-but-unmerged one, which `state` alone cannot, and `merged_at` carries when it merged. All only update while the CR keeps being re-observed. A CR that never recorded `status.number` recovers on its next reconcile via the `findby` on head/base (`GET /repos/{owner}/{repo}/pulls`, `identifiersMatchPolicy: AND`), which normalizes each list item before matching — requires **oasgen-provider >= 0.25.0**; see [design-pullrequest §8](./design-pullrequest.md). |
| `Issue` | `number` | `issue_number` excluded, sourced from `status.number`. No delete verb (GitHub REST has none). `labels`, `assignees` and `milestone` are create-only: GitHub returns them as objects where the request takes strings and an integer. |
| `Release` | `id` | `release_id` excluded, sourced from `status.id`. `generate_release_notes` is create-only. |
| `Deployment` | `id` | `deployment_id` excluded, sourced from `status.id`. No update verb. `auto_merge` is **defaulted `false`** in the asset, against GitHub's own default of `true`; `required_contexts` is create-only; GitHub's `oneOf`-typed `payload` is not modelled. Status carries `original_environment`, not `environment` — see [api](./api.md). |

**Governance**

| kind | identifiers | key mapping facts |
|---|---|---|
| `CustomProperty` | `property_name` | GitHub's `custom_property_name` path parameter is **renamed** `property_name` in the asset so one CR field covers path, identifier and status — the same technique `repository.yaml` uses. PUT is an upsert on the same URL get and delete use, so create and update are the same call. |
| `CodeSecurityConfig` | `id` | `configuration_id` excluded, sourced from `status.id`. GitHub's update accepts everything its create does, so nothing here is create-only. |
| `AutomatedSecurityFixes` | *(none)* | a singleton sub-resource with no identity of its own: the repository is the key and lives in the path. A `notFoundBody` predicate reports `enabled == false` as absent — load-bearing, because a repository with the feature off answers **200**, not 404. `paused` is surfaced on status but excluded from the predicate. |

**Repository creation**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Repository` | `name` | create on `/orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}` — the parameters are renamed `org`/`name` so one pair of spec fields serves the create path, the create body and the item path. `compareScope: updatable`, not the default (below); status carries `id`, `node_id`, `full_name`, `html_url`, `clone_url`, `ssh_url`, `default_branch`. |

### `compareScope` across the chart

`compareScope` takes one of three values — `fullSpec` (the default),
`identifiersAndStatus`, or `updatable`. Across the 30 kinds:

| value | kinds | count |
|---|---|---|
| `updatable` | `Repository`, `Team`, `TeamRepo`, `TeamMembership`, `Collaborator`, `OrgMembership`, `RepoWebhook`, `OrgWebhook`, `Environment`, `RepoRuleset`, `OrgRuleset`, `BranchProtection`, `ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`, `DeploymentBranchPolicy`, `Label`, `Milestone`, `Issue`, `PullRequest`, `Release`, `CustomProperty`, `CodeSecurityConfig` | 24 |
| default `fullSpec` (unset) | `Workflow`, `AutomatedSecurityFixes` | 2 |
| `fullSpec` (set explicitly) | `Autolink` | 1 |
| `identifiersAndStatus` | `DeployKey`, `Deployment`, `GitRef` | 3 |

`updatable` requires **oasgen-provider ≥ 0.23.0** and an update verb; it derives the
compared set from the OAS update body, so a field the update cannot send is never
compared.

#### What can actually loop

This is the rule the rest of this page and the `rd-<kind>.yaml` comments depend on, and
an earlier version of it here was wrong in a way that got copied around, so it is stated
once with its evidence. **A spec key the observe response does not carry is skipped by
the comparison**, under every scope — `rest-dynamic-controller` 0.23.0,
`internal/tools/comparison`:

```go
rmValue, ok := rm[key]
if !ok {
    // Key does not exist in rm, ignore and continue
    continue
}
```

`isCRUpdated` (`internal/controllers/helpers.go`) takes the CR's `spec`, projects it down
to `scopeFields` when the scope is `identifiersAndStatus` or `updatable`, and hands the
result to that comparison. So an absent key contributes nothing whatever the scope is:
**create-only fields and path parameters cannot produce drift at all**, and `updatable`
is not a rescue from them.

What genuinely loops is a spec key the response **does** carry, in a different shape or
a server-normalised value, that the update verb cannot fix. The controller sees a
difference, issues an update, the update cannot touch that field, the next observe sees
the same difference — an update on every reconcile, forever, against a 5000 req/hr
budget. That is the case `updatable` exists for, and it splits the 23 kinds in two:

- **Load-bearing** — the response carries the key, nothing can reconcile it, so it has to
  leave the compared set. `TeamRepo`'s `owner` (a user object against a spec string —
  under `fullSpec` that kind is not merely imprecise but broken); `Issue`'s `labels` /
  `assignees` / `milestone` (objects, where the request takes strings and an integer);
  `Milestone`'s `due_on` (echoed, but re-timed by the server per token timezone);
  `RepoWebhook` and `OrgWebhook`'s `config.secret` (echoed as the literal `********`, so
  it can never equal the real value); `DeploymentBranchPolicy`'s `type` (echoed, but
  unfixable, since the PUT body is `{name}` alone); the three variable kinds' `name`,
  which GitHub stores case-insensitively — create `my_var`, read back `MY_VAR` — and
  which is also the *address* of the item, so a rename could never converge; and
  `Collaborator`'s `role_name`, the highest *effective* role, which can exceed the grant
  this CR sets. In each of these but `Collaborator` the field is kept out of the OAS
  update body, which is what takes it out of the compared set; `Collaborator`'s
  `permission` genuinely *is* updatable and stays compared, which is why its loop is only
  narrowed and not closed (below).
- **Defensive** — every other `updatable` kind, where the extra keys `fullSpec` would
  compare are create-only fields or path parameters: `Repository`'s `auto_init` /
  `gitignore_template` / `license_template`, `Release`'s `generate_release_notes`,
  `RunnerGroup`'s `selected_repository_ids` / `runners`,
  `ActionsVariableOrg`'s `selected_repository_ids`, plus `Team`, `TeamMembership`,
  `OrgMembership`, `Label`, `BranchProtection`, `RepoRuleset`, `OrgRuleset`,
  `CodeSecurityConfig`, `CustomProperty` and `Environment`, whose surplus is path
  parameters alone. The response carries none of them, so the comparison skips them and
  `updatable` and `fullSpec` should agree today. It is set anyway because it states the
  intent by construction and stays correct if a field the response *does* carry and the
  update *cannot* fix is added later — not because it is preventing a loop.

The five kinds that are not `updatable` are not oversights; each carries the reason in
its `rd-<kind>.yaml`:

- **`Workflow` and `AutomatedSecurityFixes`** have no update verb (enable/disable are the
  create and the delete, and a toggle has only on and off), so `updatable` is rejected at
  admission — with no update verb the updatable set is empty and nothing would ever be
  compared. The default `fullSpec` is safe for both because their generated spec holds
  nothing but path parameters: the enable endpoints take no request body, and no path
  parameter name is a property of the response, so `fullSpec` compares nothing and cannot
  report false drift. The drift that matters for both is caught by a `notFoundBody`
  predicate instead.
- **`Autolink`** likewise has no update verb, so the choice is `fullSpec` vs
  `identifiersAndStatus`, and it turns on whether `fullSpec` can produce *false* drift.
  It cannot: the GET response is the whole resource — `key_prefix`, `url_template`,
  `is_alphanumeric`, all three echoed verbatim, all short scalars with no normalization
  to get wrong, and `is_alphanumeric` carries GitHub's own default in the OAS. So a synced
  autolink never drifts, and the only way to make it drift is to edit one of those fields
  on a live CR — precisely the case where the operator *should* be told, because GitHub
  cannot change an autolink in place and the CR must be recreated. It is set explicitly
  rather than left to the default so the reasoning is attached to a value.
- **`DeployKey`** has no update verb either, and here `fullSpec` is what is ruled out.
  With no update verb, any difference the comparison finds is unfixable: the controller
  marks the resource not-up-to-date, calls Update, finds no update action, and returns —
  the CR parks Ready=False forever with no remedy but editing it back. The field being
  compared would be `key`, a multi-hundred-character SSH public key pasted into YAML,
  whose byte-identical echo (trailing newline from a block scalar, optional trailing
  comment) could not be verified read-only. `identifiersAndStatus` with a status list
  containing no spec field makes the projected compared set empty: a key that exists is a
  key that is up to date, and a deleted one is still detected because the GET 404s.
- **`Deployment`** has no update verb because a deployment is an immutable historical
  record. Its create-only `auto_merge` and `required_contexts` are never echoed and are
  therefore skipped, but the fields the GET *does* echo would be compared under `fullSpec`
  with no update call to fix a difference — `environment` above all, which a CI job
  posting a deployment status can rewrite. `identifiersAndStatus` is the honest model: the
  only thing worth reconciling is whether the deployment this CR created still exists.
  `additionalStatusFields` lists `original_environment` rather than `environment`
  specifically to keep the projected compared set empty.

One limitation `compareScope` cannot reach is documented rather than papered over:
**`Collaborator` has a residual drift loop.** `role_name` is the highest *effective* role
across repository, team, org and enterprise grants, and GitHub exposes no way to read the
repository-level grant alone — so a user whose effective role exceeds `spec.permission`
produces one findby plus one PUT every reconcile, indefinitely. `identifiersAndStatus`
would silence it only by projecting the spec down to `login` alone, which would also mean
an edited `spec.permission` was never pushed at all. Full account in [api](./api.md).

### `compareScope` on `Repository`

`Repository` is written out here because the rationale attached to it was wrong twice, and
the wrong version was copied from here into other kinds.

`updatable` compares exactly the fields the `PATCH` body can express, derived from the OAS
rather than declared by hand: `description`, `homepage`, `has_issues`, `has_wiki`,
`has_projects`, `default_branch` and `archived`. It requires an update verb, which
`Repository` has.

Three fields are create-only because GitHub simply never echoes them — `auto_init`,
`gitignore_template`, `license_template`. The comparison skips a spec key the response does
not carry, so they are equally inert under `fullSpec`. They do not cause a drift loop and
never did.

**Three more are create-only because the asset deliberately keeps them out of the `PATCH`
body**, and those are the load-bearing ones:

- `private` and `visibility` (#11, 0.3.1). Compared, they made a consumer's rendered value
  retroactive: consumers render a `Repository` on every composition and core-provider's
  default `UpgradePolicy` is `Automatic`, so changing the value re-rendered every live CR
  and the next reconcile PATCHed repositories that already existed. For exposure that is
  unrecoverable — forks, clones, caches and search indexing survive a flip back.
- `name` (0.2.2). Compared, it made drift reconciliation willing to *rename* a live
  repository, which GitHub's rename redirect surfaced as a 307.

GitHub echoes all three on every `GET`. So for this kind `updatable` is **load-bearing, not
defensive**: under the default `fullSpec` they would be compared back into the drift set
regardless of the `PATCH` body, and the hazard would return in full. Setting `Repository`
to `fullSpec`, or deleting the `compareScope` line at all, is the same regression as
re-adding the fields — silent, with nothing failing. `hack/assert-drift-invariants.py`
(run by the `lint` workflow) asserts both halves for exactly that reason.

This was `identifiersAndStatus` when the kind was first written, because `updatable` did
not exist below oasgen-provider **0.23.0**. That setting compared only `name` plus the
`additionalStatusFields`, so editing `description` on an existing CR was silently never
pushed — a real gap, and closing it is what the change was actually for.

### Normalization in the RestDefinition

All 30 kinds are native: every verb goes straight to `api.github.com`, and where GitHub's
REST API needs normalizing, the RestDefinition expresses it rather than a hop through
something the chart would have to run. The mechanisms, and where each is used:

| mechanism | used by | what it does |
|---|---|---|
| static `queries` on a verb | `Collaborator` (findby) | pins `affiliation=direct` and `per_page=100`; both parameters are `excludedSpecFields` so they cannot become user-settable spec fields. Without the pin the endpoint defaults to `affiliation=all` and reports org/team access as if it were this CR's grant. |
| static `headers` on a verb | `TeamRepo` (get) | `Accept: application/vnd.github.v3.repository+json`; without it the same endpoint answers 204 with nothing to observe. |
| `fieldMapping` with an `alias` valueMapping | `Collaborator` (findby) | translates GitHub's display vocabulary (`read`/`write`) into the request vocabulary (`pull`/`push`) and relocates the value onto `spec.permission`, where the comparison looks for it. A custom repository role has no alias pair and passes through unchanged, which is correct. |
| `requestTransform` (jq) | `BranchProtection` (create, update), `GitRef` (create) | for `BranchProtection`, turns omitted controls into the explicit `null` GitHub requires for four members that must be present even when off. For `GitRef`, adds the `refs/` prefix the create-ref body wants onto the short-form `spec.ref` (idempotent, so an author who wrote the full form is tolerated). |
| `responseTransform` (jq) | `BranchProtection` (get), `TeamRepo` (get), `PullRequest` (create/get/update/findby), `GitRef` (create/get/update) | rewrites the response into the CR domain once, before status population and drift comparison — trimming GitHub's full-form `refs/...` ref back to the short form the `GitRef` spec carries (on every status-writing verb, or `status.ref` would flap between forms); flattening `{"enabled": bool}` wrappers and sorting every list; deriving `permission` from cumulative booleans; replacing `PullRequest`'s `head`/`base` objects with the branch strings the spec carries. The last is what lets `PullRequest` be native at all: compared raw, a string spec field against an object response field is permanent drift, and the PATCH body does not even contain `head`. `PullRequest` carries it on ALL FOUR verbs (not just get) because head/base are identifiers and status is written from every response — see [design-pullrequest §8.2](./design-pullrequest.md). Every one of these programs is type-guarded rather than `//`-defaulted, because gojq does not swallow the indexing error of `.ref` on an already-normalized string — and a jq runtime error fails the reconcile outright rather than degrading. |
| `dependentLookups` (pre-call GET chain) | `GitRef` (create) | resolves the base commit for a sha-less create: repo → `default_branch` → that branch's `git/ref/{ref}` → `object.sha`, fed into the create body's `sha` only `when.customResourceFieldAbsent: spec.sha` (an explicit `spec.sha` wins and skips the calls). The one mechanism in this chart that needs **oasgen-provider ≥ 0.36.0** ([#120](https://github.com/krateo-platformops/oasgen-provider/issues/120), merged as #239); it is what let `GitRef` return without the companion plugin. |
| `notFoundBody` (jq predicate) | `Workflow` (get), `AutomatedSecurityFixes` (get) | reports a 200 response as *absent* when the raw body says the feature is off, so the controller re-runs create. Evaluated before any response normalization. |
| declared response codes | `Team` (update) | rest-dynamic-controller accepts only the 2xx codes declared on the operation. `PATCH /orgs/{org}/teams/{team_slug}` answers **201** when it actually changes something and 200 only when the value already matched, so the asset declares both — a document listing 200 alone would turn every real update into `invalid status code: 201`. |

A response `fieldMapping` **removes** its source key from the body unless the mapping is
in-place or another entry writes to that key. That is why `Collaborator` carries a second,
identity mapping from `role_name` to `status.role_name`: without it the alias mapping
would consume the key and `status.role_name` would silently never populate.

## The OpenAPI specs

Each RestDefinition references a trimmed OpenAPI 3.0 spec (`chart/assets/<kind>.yaml`)
carried as a ConfigMap (`chart/templates/configmap-<kind>.yaml`). All **30** ConfigMaps
are a plain `.Files.Get`: the assets contain no template action, so nothing is
`tpl`-rendered and each spec is copied verbatim. No operation anywhere in the set
overrides `servers` — every verb of every kind keeps `https://api.github.com`.

What the assets do carry is parameter naming, and `repository.yaml` is the clearest case.
GitHub addresses a repository as `/repos/{owner}/{repo}`; the asset declares the parameters
as `org` and `name`. A path parameter becomes a CR spec field of the same name, so
naming them after GitHub would give the CRD an `owner` alongside the `org` the create
path (`/orgs/{org}/repos`) needs, and a `repo` alongside the `name` the create body
needs — a duplicate pair the author has to keep in sync by hand. Naming them `org` and
`name` lets **one** pair of fields serve the create path, the create body and the
get/update/delete path. `customproperty.yaml` applies the same rename, turning GitHub's
`custom_property_name` into `property_name`.

The same asset trims one endpoint away on purpose: GitHub's user-scoped create,
`POST /user/repos`, is not modelled. A RestDefinition has exactly one create verb and
cannot pick between two paths at runtime, and Krateo destination repositories are
org-owned, so only the org-scoped create is supported ([api](./api.md)).

Two capabilities are absent from the asset set because no RestDefinition can express
them, not because they were overlooked ([api](./api.md)): **secrets** at any scope, which
need a LibSodium sealed box plus a prior public-key fetch, and **`VulnerabilityAlerts`**,
whose GET returns 404 or a bodiless 204 and therefore yields no status schema. Variables
are not secrets and are covered at all three scopes.

## No runtime component

The chart renders 30 ConfigMaps and 30 RestDefinitions, and nothing else — no Deployment,
no Service, no image, no proxy, and no `_helpers.tpl` (it held only the two helpers the
proxy needed). Installing the chart puts data in the cluster; the only workloads are the
`rest-dynamic-controller` deployments oasgen-provider creates per kind.

That became true when `GitRef`, `RepoContent` and `PullRequest` were removed — the three
kinds whose verbs routed through a companion proxy, and the only users of it, so the plugin
went with them. The frontend now publishes through a `BuilderPublish` claim over
`git-provider` — `AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"` in the frontend
chart's `values.yaml` and `values.schema.json` — and the `github.krateo.io` route is the
`"false"` fallback. Two of the three have since returned **natively**, with no proxy:
`PullRequest` (a `responseTransform` flattening `head`/`base`, plus a findby for group-B
recovery) and `GitRef` (a `requestTransform` for the `refs/` prefix plus a `dependentLookups`
chain for the base sha, oasgen-provider ≥ 0.36.0). `RepoContent` is the one still out.

What each did, and what a native return takes, is written down per kind:

| document | kind | native-return state |
|---|---|---|
| [design-gitref](./design-gitref.md) | `GitRef` | **returned** (appVersion 0.1.3). The base-HEAD-sha pre-call read — oasgen-provider **#120** — shipped as dependent lookups in **0.36.0**, so a sha-less create is native; `spec.sha` stays optional. |
| [design-repocontent](./design-repocontent.md) | `RepoContent` | expressible today — `status.sha` plus a `responseTransform`, now that the `%252F` double-escape is fixed. Not yet shipped. |
| [design-pullrequest](./design-pullrequest.md) | `PullRequest` | **returned** — a `responseTransform` flattening `head`/`base` to `ref` strings. |

## Invariants

- **oasgen-provider must be ≥ 0.36.0.** `GitRef`'s create resolves its base sha with
  **dependent lookups**, a primitive that landed in 0.36.0 ([#120](https://github.com/krateo-platformops/oasgen-provider/issues/120),
  merged as #239); the CRD rejects a RestDefinition that declares them below that version.
  The prior floor was 0.23.0 — for the `compareScope: updatable` that 24 kinds declare and
  which does not exist below it — and that requirement still holds, now subsumed by 0.36.0.
- **The chart stays free of a runtime component.** It renders 30 ConfigMaps and 30
  RestDefinitions and nothing else; every kind reaches `api.github.com` directly, no
  asset overrides `servers`, and every ConfigMap is a plain `.Files.Get` with nothing for
  `tpl` to resolve. A kind that needed a hop would reintroduce a Deployment, a Service and
  an image to release — which is why the kinds that could return natively (`PullRequest`
  and `GitRef` already have) are worth the transforms their design docs specify.
- **`Repository` must exist and be initialised before anything writes into it.**
  `auto_init` defaults to `true` so the new repo has a first commit and therefore a
  default branch; without one there is no base sha to branch from and nothing to commit
  against, whether the writer is the `BuilderPublish` path over `git-provider` or a CI
  job.
- **A RestDefinition's declared paths and methods must exist in its own asset.** Every
  verb resolves against the OpenAPI document the ConfigMap named by `oasPath` carries, so
  a path or method that is not in that document is a mapping the controller can never
  execute. Every verb of the original 29 was cross-checked against its own asset and
  accepted by the deployed `restdefinitions.ogen.krateo.io` CRD at oasgen-provider 0.23.0
  (`kubectl apply --dry-run=server`); `GitRef`, the 30th, is cross-checked the same way,
  and its `dependentLookups` + `dependentLookup` resolver shape is pending acceptance by
  the 0.36.0 CRD plus an end-to-end check (those primitives post-date 0.23.0).
- **The token is provisioned out-of-band, and its rights are the union of the kinds in
  use.** The chart holds no credential; the portal write-path only references the
  `<Kind>Configuration` CRs ([usage](./usage.md)). One PAT can drive all 30 kinds, and
  `chart/samples/configurations.yaml` ships all 30 Configuration CRs under a single name
  — but `Repository` needs repository creation in the org (classic `repo` scope, or a
  fine-grained token with org **Administration: read & write**), and the org-scoped kinds — `Team`, `TeamMembership`,
  `TeamRepo`, `OrgMembership`, `OrgWebhook`, `OrgRuleset`, `ActionsVariableOrg`,
  `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` — need organization admin rights.
