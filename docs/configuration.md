---
type: Configuration
title: github-provider-kog — configuration
description: The whole config surface — the single chart value resourceGroup, the 31 RestDefinition mappings grouped by area, the compareScope tally and the reasoning behind each non-default choice, the native normalizations that replace a plugin hop, the OpenAPI ConfigMaps and plugin servers overrides, the plugin routes and env, and the invariants that must hold.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, values, restdefinition, oasgen-provider, plugin]
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
| `resourceGroup` | `github.krateo.io` | the API group every generated CRD lands under — 31 resource kinds plus a `<Kind>Configuration` auth kind for each. Referenced by every RestDefinition's `spec.resourceGroup`. |
| `global` | `{}` (object) | Helm global values, injected by the chart-inspector / when used as a subchart. |

The schema declares **only** a single top-level scalar on purpose: when the chart is
installed as a Krateo component the CDC derives the CompositionDefinition CRD from this
schema, and a scalar default materializes cleanly in the component CR (nested-object
toggles would not) ([api](./api.md)).

There is **no per-kind toggle**. All 31 RestDefinitions are always installed; a
RestDefinition costs nothing until a CR of its kind exists, and a per-kind switch would
mean nested-object values the CDC cannot materialize.

## The RestDefinition mappings

Each `chart/templates/rd-<kind>.yaml` declares the API mapping oasgen-provider consumes;
its in-file comments carry the reasoning behind every choice below. `configurationFields`
is empty for all 31 — the token wiring comes from the oasgen-generated
`<Kind>Configuration` + `spec.configurationRef`, never from spec fields. The full
per-kind verb, identifier, `compareScope` and status listing is in [api](./api.md); what
follows is the mapping mechanics.

Three patterns recur across the set and are worth reading once:

- **Server-assigned identifiers.** When GitHub assigns the item key on create, that key
  is `excludedSpecFields` (so it never becomes a required spec field the author has to
  fill in) and each item verb sources it from status via `requestFieldMapping`. This is
  `PullRequest`'s `pull_number` / `status.number` shape, reused by `Release`,
  `Milestone`, `Issue`, `RepoWebhook`, `OrgWebhook`, `DeployKey`, `Autolink`,
  `RunnerGroup`, `DeploymentBranchPolicy`, `RepoRuleset`, `OrgRuleset`,
  `CodeSecurityConfig` and `Deployment`. `Team` uses the same shape on `team_slug`, and
  `fieldMapping` rather than `requestFieldMapping`.
- **PUT as create *and* update.** Where GitHub exposes one idempotent upsert,
  `create` and `update` name the same method and path: `Collaborator`, `OrgMembership`,
  `TeamMembership`, `TeamRepo`, `Environment`, `CustomProperty`, `BranchProtection` —
  the shape `RepoContent` already uses.
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
| `Issue` | `number` | `issue_number` excluded, sourced from `status.number`. No delete verb (GitHub REST has none). `labels`, `assignees` and `milestone` are create-only: GitHub returns them as objects where the request takes strings and an integer. |
| `Release` | `id` | `release_id` excluded, sourced from `status.id`. `generate_release_notes` is create-only. |
| `Deployment` | `id` | `deployment_id` excluded, sourced from `status.id`. No update verb. `auto_merge` is **defaulted `false`** in the asset, against GitHub's own default of `true`; `required_contexts` is create-only; GitHub's `oneOf`-typed `payload` is not modelled. Status carries `original_environment`, not `environment` — see [api](./api.md). |

**Governance**

| kind | identifiers | key mapping facts |
|---|---|---|
| `CustomProperty` | `property_name` | GitHub's `custom_property_name` path parameter is **renamed** `property_name` in the asset so one CR field covers path, identifier and status — the same technique `repository.yaml` uses. PUT is an upsert on the same URL get and delete use, so create and update are the same call. |
| `CodeSecurityConfig` | `id` | `configuration_id` excluded, sourced from `status.id`. GitHub's update accepts everything its create does, so nothing here is create-only. |
| `AutomatedSecurityFixes` | *(none)* | a singleton sub-resource with no identity of its own: the repository is the key and lives in the path. A `notFoundBody` predicate reports `enabled == false` as absent — load-bearing, because a repository with the feature off answers **200**, not 404. `paused` is surfaced on status but excluded from the predicate. |

**Git-write and repository creation**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Repository` | `name` | create on `/orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}` — every verb native, no plugin hop. `compareScope: updatable`, not the default (below); status carries `id`, `node_id`, `full_name`, `html_url`, `clone_url`, `ssh_url`, `default_branch`. |
| `RepoContent` | `path` | create/update/get/delete all on `/repos/{owner}/{repo}/contents/{path}`; status carries `sha`, `html_url`. |
| `GitRef` | `ref` | create on `git/refs`, but **get** on the plugin's `/gitref/{owner}/{repo}/{ref}` (fixes GitHub's git/ref-vs-git/refs asymmetry); status carries `node_id`, `url`. |
| `PullRequest` | `number` | `pull_number` is `excludedSpecFields` (GitHub assigns it on create); get/update source it from `status.number` via `requestFieldMapping`. Status carries `number`, `html_url`, `state`. |

### `compareScope` across the chart

`compareScope` takes one of three values — `fullSpec` (the default),
`identifiersAndStatus`, or `updatable`. Across the 31 kinds:

| value | kinds | count |
|---|---|---|
| `updatable` | `Repository`, `Team`, `TeamRepo`, `TeamMembership`, `Collaborator`, `OrgMembership`, `RepoWebhook`, `OrgWebhook`, `Environment`, `RepoRuleset`, `OrgRuleset`, `BranchProtection`, `ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`, `DeploymentBranchPolicy`, `Label`, `Milestone`, `Issue`, `Release`, `CustomProperty`, `CodeSecurityConfig` | 23 |
| default `fullSpec` (unset) | `RepoContent`, `GitRef`, `PullRequest`, `Workflow`, `AutomatedSecurityFixes` | 5 |
| `fullSpec` (set explicitly) | `Autolink` | 1 |
| `identifiersAndStatus` | `DeployKey`, `Deployment` | 2 |

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

The kinds that are not `updatable` are not oversights. `RepoContent`, `GitRef` and
`PullRequest` leave `compareScope` unset and keep the default; the other five each carry
the reason in their `rd-<kind>.yaml`:

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

`Repository` is the **defensive** case above, and it is written out here because the
rationale attached to it was wrong first and was copied from here into other kinds. The
three create-only fields in its create body — `auto_init`, `gitignore_template`,
`license_template` — are accepted on `POST` and never echoed on `GET`, so the comparison
skips them under `fullSpec` as well. They do not cause a drift loop, and never did.

`updatable` compares exactly the fields the `PATCH` body can express, derived from the OAS
rather than declared by hand: `description`, `homepage`, `private`, `visibility`,
`has_issues`, `has_wiki`, `has_projects`, `default_branch` and `archived`. Every spec
field the GET echoes is also in that PATCH body, so `updatable` and `fullSpec` should
agree today. It is set because it states the intent explicitly and stays correct if a
field the response carries and the PATCH cannot send is ever added. It requires an update
verb, which `Repository` has.

This was `identifiersAndStatus` when the kind was first written, because `updatable` did
not exist below oasgen-provider **0.23.0**. That setting compared only `name` plus the
`additionalStatusFields`, so editing `description` or `private` on an existing CR was
silently never pushed — a real gap, and closing it is what the change was actually for.

### Normalization without a plugin

The three git-write kinds route some verbs through the companion plugin (below). The
other 28 do not, including every one of the 27 kinds added after the original four: where
GitHub's REST API needs normalizing, the RestDefinition expresses it. The mechanisms, and
where each is used:

| mechanism | used by | what it does |
|---|---|---|
| static `queries` on a verb | `Collaborator` (findby) | pins `affiliation=direct` and `per_page=100`; both parameters are `excludedSpecFields` so they cannot become user-settable spec fields. Without the pin the endpoint defaults to `affiliation=all` and reports org/team access as if it were this CR's grant. |
| static `headers` on a verb | `TeamRepo` (get) | `Accept: application/vnd.github.v3.repository+json`; without it the same endpoint answers 204 with nothing to observe. |
| `fieldMapping` with an `alias` valueMapping | `Collaborator` (findby) | translates GitHub's display vocabulary (`read`/`write`) into the request vocabulary (`pull`/`push`) and relocates the value onto `spec.permission`, where the comparison looks for it. A custom repository role has no alias pair and passes through unchanged, which is correct. |
| `requestTransform` (jq) | `BranchProtection` (create, update) | turns omitted controls into the explicit `null` GitHub requires for four members that must be present even when off. |
| `responseTransform` (jq) | `BranchProtection` (get), `TeamRepo` (get) | rewrites the response into the CR domain once, before status population and drift comparison — flattening `{"enabled": bool}` wrappers and sorting every list; deriving `permission` from cumulative booleans. |
| `notFoundBody` (jq predicate) | `Workflow` (get), `AutomatedSecurityFixes` (get) | reports a 200 response as *absent* when the raw body says the feature is off, so the controller re-runs create. Evaluated before any response normalization. |
| declared response codes | `Team` (update) | rest-dynamic-controller accepts only the 2xx codes declared on the operation. `PATCH /orgs/{org}/teams/{team_slug}` answers **201** when it actually changes something and 200 only when the value already matched, so the asset declares both — a document listing 200 alone would turn every real update into `invalid status code: 201`. |

A response `fieldMapping` **removes** its source key from the body unless the mapping is
in-place or another entry writes to that key. That is why `Collaborator` carries a second,
identity mapping from `role_name` to `status.role_name`: without it the alias mapping
would consume the key and `status.role_name` would silently never populate.

## The OpenAPI specs and the plugin `servers` overrides

Each RestDefinition references a trimmed OpenAPI 3.0 spec (`chart/assets/<kind>.yaml`)
carried as a ConfigMap (`chart/templates/configmap-<kind>.yaml`). The RepoContent,
GitRef and PullRequest ConfigMaps are `tpl`-rendered so the per-operation `servers`
overrides resolve to the plugin's in-cluster URL via the `webServiceUrl` helper
(`chart/templates/_helpers.tpl`):

```
http://<release>-plugin.<namespace>.svc:8080
```

The other **28** ConfigMaps are a plain `.Files.Get` instead. Those kinds are fully
native — every verb goes straight to `api.github.com`, so no operation overrides
`servers` — and their assets therefore contain no template action: they are copied
verbatim, with nothing for `tpl` to resolve.

Only the operations that need normalization carry that override; every other verb keeps
`https://api.github.com`. A notable OpenAPI subtlety: on `git/update-ref`, `sha` is
intentionally **not** required — oasgen unions `required` across all verbs into one
CRD `spec.required`, so requiring it on update would force it back onto the create path
(which auto-resolves it). Similarly the RepoContent get operation names its query param
`branch` (not GitHub's `ref`) so the controller — which only fills a query param whose
name matches a CR spec field — populates it from `spec.branch`; the plugin forwards it
to GitHub as `?ref`.

`repository.yaml` renames path parameters for the same class of reason. GitHub
addresses a repository as `/repos/{owner}/{repo}`; the asset declares the parameters
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

## The plugin

`plugin/main.go`, a stdlib-only Go service; `plugin/Dockerfile` builds it on a
distroless `nonroot` base (UID/GID 65532). It serves **only** `RepoContent`, `GitRef` and
`PullRequest` — no kind added after the original four uses it. It exposes:

| route | purpose |
|---|---|
| `GET /healthz`, `GET /readyz` | liveness/readiness (always ok) |
| `POST /repos/{owner}/{repo}/git/refs` | GitRef create — auto-resolve base sha when the CR omits it |
| `GET /gitref/{owner}/{repo}/{ref...}` | GitRef observe — map onto GitHub's `git/ref/{ref}` (no `refs/` prefix) |
| `PUT /repos/{owner}/{repo}/contents/{path...}` | RepoContent write — idempotent create-or-update, flatten `content{}` |
| `GET /repos/{owner}/{repo}/contents/{path...}` | RepoContent observe — read from `?ref=<branch>`, canonicalize base64 `content` |
| `GET /repos/{owner}/{repo}/pulls/{number}` | PullRequest observe — flatten `head`/`base` objects to `ref` strings |

The `Deployment` (`chart/templates/deployment-plugin.yaml`) sets the container's env
and security context:

| setting | value | effect |
|---|---|---|
| `PORT` | `8080` | the plugin listen port (`http`). |
| `image` | `ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:{{ .Chart.Version }}` | the chart version selects the plugin image tag, so chart X.Y.Z asks for plugin X.Y.Z. |
| securityContext | runAsNonRoot 65532, read-only rootfs, drop ALL caps | distroless nonroot; the numeric UID lets the kubelet verify non-root. |
| resources | 10m/32Mi → 128Mi | the plugin is tiny and stateless. |

## Invariants

- **oasgen-provider must be ≥ 0.23.0.** 23 kinds declare `compareScope: updatable`,
  which does not exist below that version, and the CRD rejects it on a kind with no
  update verb.
- **The plugin image tag equals the chart version.** The Deployment pins
  `:{{ .Chart.Version }}`, and `release-image.yaml` publishes the plugin image on the
  same bare-semver tag `release-oci.yaml` uses for the chart, so one tag push publishes
  both and they line up ([release](./release.md)).
- **`webServiceUrl` must resolve to the plugin Service.** The RepoContent, GitRef and
  PullRequest ConfigMaps are `tpl`-rendered for exactly this reason; a plain
  `.Files.Get` would leave the template literal in the OpenAPI and the controller would
  call GitHub for the plugin-only verbs (breaking observe on GitRef/PullRequest and
  idempotent write on RepoContent). The other 28 kinds have no override to resolve and
  are correctly plain `.Files.Get`.
- **`Repository` must exist and be initialised before the kinds that write into it.**
  `auto_init` defaults to `true` so the new repo has a first commit and therefore a
  default branch; without one, `GitRef` has no base sha to branch from and
  `RepoContent` has nothing to commit against. Order: Repository → GitRef →
  RepoContent (per file) → PullRequest.
- **A RestDefinition's declared paths and methods must exist in its own asset.** Every
  verb resolves against the OpenAPI document the ConfigMap named by `oasPath` carries, so
  a path or method that is not in that document is a mapping the controller can never
  execute. Every verb of all 31 was cross-checked against its own asset before shipping.
- **The token is provisioned out-of-band, and its rights are the union of the kinds in
  use.** The chart holds no credential; the portal write-path only references the
  `<Kind>Configuration` CRs ([usage](./usage.md)). One PAT can drive all 31 kinds, and
  `chart/samples/configurations.yaml` ships all 31 Configuration CRs under a single name
  — but the git-write kinds need only contents/refs/pulls write, `Repository` needs
  repository creation in the org (classic `repo` scope, or a fine-grained token with org
  **Administration: read & write**), and the org-scoped kinds — `Team`, `TeamMembership`,
  `TeamRepo`, `OrgMembership`, `OrgWebhook`, `OrgRuleset`, `ActionsVariableOrg`,
  `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` — need organization admin rights.
