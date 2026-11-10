---
type: Configuration
title: github-provider-kog — configuration
description: The whole config surface — the chart values resourceGroup and kinds, the config chart that carries the publishing Configurations, the 32 RestDefinition mappings grouped by area, the compareScope tally and the reasoning behind each non-default choice, the native normalizations GitHub's REST inconsistencies demand, the OpenAPI ConfigMaps, and the invariants that must hold for a chart that ships no runtime component.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, values, restdefinition, oasgen-provider]
timestamp: 2026-09-09T00:00:00Z
---

# Configuration

The chart surface is deliberately tiny — two values. Everything else is fixed mapping
(`chart/assets/`, `chart/templates/`).

## Chart values

`chart/values.yaml`, typed by `chart/values.schema.json`
(`additionalProperties: false` — an unknown key fails the schema):

| key | default | effect |
|---|---|---|
| `resourceGroup` | `github.krateo.io` | the API group every generated CRD lands under — 32 resource kinds plus a `<Kind>Configuration` auth kind for each. Referenced by every RestDefinition's `spec.resourceGroup`. |
| `kinds` | `[]` | which kinds to render, by Kind name. Empty renders all 32. |
| `global` | `{}` (object) | Helm global values, injected by the chart-inspector / when used as a subchart. |

The values stay flat on purpose: when the chart is installed as a Krateo component the
CDC derives the CompositionDefinition CRD from this schema, and a scalar or list default
materializes cleanly in the component CR (nested-object toggles would not)
([api](./api.md)).

### GitHub Enterprise (`githubBaseUrl`)

Empty by default, which means github.com. Set it to the API base URL of a GitHub Enterprise
instance, scheme and path included:

| product | `githubBaseUrl` |
|---|---|
| GitHub Enterprise Server | `https://ghe.corp.example.com/api/v3` |
| GitHub Enterprise Cloud with data residency | `https://api.octocorp.ghe.com` |

Every RestDefinition then carries `spec.serverURL` with that value (oasgen-provider ≥ 0.52.0).
oasgen **replaces** each document's `servers[0]` with it, and the endpoint host policy is built
from the result, so `api.github.com` stops being permitted at all: a misconfigured install fails
closed rather than sending the Enterprise token to the public API. `hack/assert-server-url.py`
(lint job `server-url`) fails if any RestDefinition misses the value, or carries it while unset.

- **Validation** is oasgen's own rule, `^https?://host(/path)?`: a value without a scheme is
  refused at install. A GHES URL without `/api/v3` is accepted but every request 404s, because the
  prefix is part of the base URL, not of the paths.
- **One host per cluster.** The generated CRDs are cluster-wide, so a cluster's kinds all talk to
  one GitHub host. The value can be changed in place; oasgen reads it on the next reconcile.
- **Credentials** are unchanged: each kind's `<Kind>Configuration` points at a token Secret, which
  must hold a token for the Enterprise instance.
- **API coverage follows the instance.** GitHub Enterprise Server versions lag github.com, and some
  of the 32 kinds use endpoints an older GHES lacks; such a kind answers 404 there. Check the REST
  documentation for your GHES version before enabling a kind.
- **Setting it through the installer** needs the installer's component-values schema to declare
  `githubBaseUrl` first: an undeclared key there is pruned silently.

### Choosing kinds

Each RestDefinition runs one controller pod whether or not a CR of its kind exists
([overview](./overview.md)), so `kinds` is what sets the provider's pod count. Each listed
kind renders its RestDefinition and its OpenAPI ConfigMap, and an unknown name fails the
schema:

```yaml
kinds: [Repository, PullRequest]   # 2 controllers instead of 32
```

As a Krateo component, set it on the composition's spec, for example through the installer's
`componentValues.github-provider-kog.kinds`.

- **Empty means all, and that is the default.** A default listing the 32 names would be
  stored on the composition, so an install would never render a kind added by a later chart.
- **Builder publishing needs `Repository` and `PullRequest`.** They are the only
  `github.krateo.io` kinds `builder-publish` creates, and neither depends on another kind.
- **Delete a kind's CRs before you remove it from a running install.** Removing a kind
  deletes its RestDefinition, and oasgen-provider then drops the kind's CRD. While CRs still
  exist it refuses: the RestDefinition stays in deletion and the controller keeps running
  until they are gone. Adding a kind back generates it again.

### The config chart

Builder publishing needs a `RepositoryConfiguration` and a `PullRequestConfiguration` in
the claim namespace. `github-provider-kog-config` is a second chart that renders those two
objects, so a fresh install or a child Krateo does not have to apply them by hand.

They can't go in the main chart. oasgen-provider generates their CRDs from the
RestDefinitions after the main chart installs, and a chart that renders a kind with no CRD
cannot be rendered at all. The config chart therefore installs later, as its own component.

| Value | Default | Meaning |
|---|---|---|
| `resourceGroup` | `github.krateo.io` | must match the main chart's `resourceGroup` |
| `configurationName` | `github-blueprints-config` | the name both objects carry, and the name `builder-publish` references by default |
| `secretName` | `git-provider-credentials` | the Secret holding the token, in the release namespace |
| `secretKey` | `token` | the key in that Secret holding the token |

- **It holds no credential.** It names the Secret and never creates it. `git-provider`
  defaults to `basic` auth, so a Secret shared with it also needs a `username` key.
- **As a Krateo component it needs two pins.** `deps: [github-provider-kog]` holds it until
  the main composition is Ready, which requires every RestDefinition Ready.
  `requiresApiGroups: [github.krateo.io]` holds it when the main chart is switched off, a
  case `deps` skips.
- **`kinds` must include both.** With `kinds` set, the main chart generates only those
  kinds. If `Repository` or `PullRequest` is missing, the group is served, both pins pass,
  and this chart can't render.
- **A cluster with these objects applied by hand has them already.** Installing the chart
  there takes over two existing objects, which hasn't been tried.

## The RestDefinition mappings

Each `chart/templates/rd-<kind>.yaml` declares the API mapping oasgen-provider consumes;
its in-file comments carry the reasoning behind every choice below. `configurationFields`
is empty for all 32 — the token wiring comes from the oasgen-generated
`<Kind>Configuration` + `spec.configurationRef`, never from spec fields. The full
per-kind verb, identifier, `compareScope` and status listing is in [api](./api.md); what
follows is the mapping mechanics.

Three patterns recur across the set and are worth reading once:

- **Server-assigned identifiers.** When GitHub assigns the item key on create, that key is a
  path parameter on the item verbs only, and each item verb sources it from status via
  `requestFieldMapping`. oasgen omits a mapped parameter from the spec entirely, so the matching
  `excludedSpecFields` entry is a redundant no-op, kept because `excludedSpecFields` is immutable
  (#290) and it records that the key is never author-supplied. That is
  `Release`'s `release_id` / `status.id` shape, shared by `Milestone`, `Issue`,
  `RepoWebhook`, `OrgWebhook`, `DeployKey`, `Autolink`, `RunnerGroup`,
  `DeploymentBranchPolicy`, `RepoRuleset`, `OrgRuleset`, `CodeSecurityConfig` and
  `RepoDeployment`. `Team` uses the same shape on `team_slug`, and `fieldMapping` rather than
  `requestFieldMapping`.
- **PUT as create *and* update.** Where GitHub exposes one idempotent upsert,
  `create` and `update` name the same method and path: `Collaborator`, `OrgMembership`,
  `TeamMembership`, `TeamRepo`, `Environment`, `CustomProperty` and `BranchProtection`
  all declare one method and one path for both.
- **The spec is the create body plus the parameters of every verb.** oasgen takes the body from
  the create operation alone, then merges in the parameters of every verb. Authorization headers
  aside, a parameter stays off the spec only if a request-direction mapping supplies it (on any
  verb) or `excludedSpecFields` names it. So a query parameter of a `findby` or `get` verb becomes a
  spec field unless it is excluded or mapped, and that exclusion is load-bearing, not a formality:
  `Collaborator`'s `affiliation`/`per_page` and `UserRepository`'s `affiliation`/`sort`/`direction`/
  `per_page`/`page` stay off the CRD only because of theirs. A verb's static `queries` win over
  spec, so a pinned parameter left unexcluded becomes a field that is silently ignored, while one
  not pinned is sent as the user set it. **When adding a kind, exclude or map every parameter a user
  must not set.** A non-create path parameter is filled by name from a
  same-named spec field, or sourced from status via a mapping. That is why several assets rename
  parameters so the
  create-derived fields can fill the item paths (see `Repository`'s `org`/`name` below, and
  `CustomProperty`'s `property_name`), and why a server-assigned id that no create field can supply
  is sourced from status instead.

**Access**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Team` | `slug` | `team_slug` is `excludedSpecFields`; get/update/delete source it from `status.slug` via `fieldMapping`. `chart/assets/team.yaml` declares **both** `201` and `200` on the PATCH — see below. |
| `TeamRepo` | `full_name` | one PUT for create and update. The get verb carries a static `Accept: application/vnd.github.v3.repository+json` header (without it GitHub answers 204) and a `responseTransform` that derives the CR-domain `permission` from the cumulative `permissions` booleans — highest true flag wins, floor `pull`. |
| `TeamMembership` | `url` | one PUT for create and update; a real get with a body. `url` is the only response property that names the membership — `username` is never echoed. |
| `Collaborator` | `login` | observe is a **findby** over the collaborator list, pinned by a static `query` (`affiliation=direct`) and a `pageNumber` `pagination` block that walks every page (setting `per_page`); `affiliation` and `per_page` are both `excludedSpecFields`. A `fieldMapping` alias maps GitHub's `read`/`write` onto the body's `pull`/`push` and relocates the value onto `spec.permission`; a second identity entry re-writes `role_name` to `status.role_name`, without which the first mapping would consume the key and status would never populate. |
| `OrgMembership` | `url` | one PUT for create and update; a real get with a body and a real 404 for a non-member (verified live), so no `notFoundBody` and no findby are needed. |

**Repository configuration**

| kind | identifiers | key mapping facts |
|---|---|---|
| `RepoWebhook` | `id` | `hook_id` excluded, sourced from `status.id`. `chart/assets/repowebhook.yaml` keeps `secret` (and the create-only `name`) **out of the update body**, which is what keeps the masked `********` out of the comparison; the PATCH still sends the whole `config` map. |
| `OrgWebhook` | `id` | identical to `RepoWebhook`, org-scoped. Org hooks have no `test_url` (that is repository-only), so the two status lists coincide. |
| `DeployKey` | `id` | `key_id` excluded, sourced from `status.id`. `additionalStatusFields` is server-side facts only (`url`, `verified`, `created_at`) so that the compared set under `identifiersAndStatus` contains no spec field at all. |
| `Environment` | `name` | no server-assigned key and no create/item path split, so no `excludedSpecFields` and no `requestFieldMapping`: every verb addresses the environment by the same three spec fields. |
| `RepoRuleset` | `id` | `ruleset_id` excluded, sourced from `status.id`. `rules` and `bypass_actors` are compared element-by-element **in order**. `rules` models **all 23** of GitHub's rule types as one `{type, parameters}` union; set only the keys for your chosen `type`. Caveats: a `merge_queue` rule needs a concrete ref condition, the four push rules need `target: push`, and `workflows`/`code_scanning` take hand-supplied identifiers. |
| `OrgRuleset` | `id` | same as `RepoRuleset`, org-scoped. |
| `Autolink` | `id` | `autolink_id` excluded, sourced from `status.id`. `additionalStatusFields` is empty — the response carries only `id` plus the three create-body fields and a nullable `updated_at` the asset does not declare. |
| `BranchProtection` | `url` | a `requestTransform` on both PUT verbs turns four omitted members into the explicit `null` GitHub requires, and a whole-document `responseTransform` on get rewrites GitHub's differently-shaped answer back into the CR domain — including the review object's `dismissal_restrictions` / `bypass_pull_request_allowances`, normalised to login/slug string lists the same way as `restrictions`. The `required_status_checks` `checks` (app_id) form is **not** modelled yet — held until oasgen can reject a both-`checks`-and-`contexts` CR at admission (see the whole-value section). `additionalStatusFields` is empty on purpose. |

**CI/CD**

| kind | identifiers | key mapping facts |
|---|---|---|
| `ActionsVariableRepo` | `name` | the item is addressed by `{name}`, so `name` is trimmed from the update body — a rename could never converge, and leaving it uncompared also neutralises GitHub's case-insensitive variable naming. |
| `ActionsVariableOrg` | `name` | as above, plus `selected_repository_ids` confined to the create body (GitHub's read side returns only `selected_repositories_url`). |
| `EnvironmentVariable` | `name` | as `ActionsVariableRepo`, one scope deeper — `environment_name` is a third path parameter. |
| `RunnerGroup` | `id` | `runner_group_id` excluded, sourced from `status.id` — deliberately **not** the upstream `findby`-by-name approach, since create already returns the id and a findby would page a list endpoint on every reconcile. `selected_repository_ids` and `runners` are create-only. `network_configuration_id` (a hosted compute network) is set at create and compared like `visibility`: GitHub returns it on GET. `name` **stays** in the update body here: keyed by id, a rename is a real convergent update. |
| `DeploymentBranchPolicy` | `id` | `branch_policy_id` excluded, sourced from `status.id`. Create body `{name, type}`, update body `{name}` alone. |
| `Workflow` | `id` | create is `PUT .../enable`, delete is `PUT .../disable`; there is no update verb. A `notFoundBody` predicate on get reports `disabled_manually`, `disabled_inactivity` and `deleted` as absent — the whole reconciliation loop of this kind. `disabled_fork` is deliberately excluded. |

**Work tracking**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Label` | `name` | one CR field serves identity, item path and create body. **Rename is not modelled**: GitHub's PATCH takes `new_name` while the path addresses the current name, which needs two names in one CR field and is not derivable by the controller's only request-side transform (`alias`). |
| `Milestone` | `number` | `milestone_number` excluded, sourced from `status.number`. `due_on` is **create-only** — kept out of the update body because GitHub re-times it per token timezone; `status.due_on` shows what was stored. |
| `PullRequest` | `head`, `base` | Identity is head+base (#14), so a `findby` can recover a CR that lost `status.number`. `pull_number` excluded, sourced from `status.number`; get/update bind it from there, so group-A (number present) still observes via `get` — identifiers drive findby MATCHING only. No delete verb (GitHub REST has none), and no close-from-spec either (`state` is PATCH-body-only, so it never reaches the spec). Every verb (create/get/update/findby) carries the SAME `responseTransform` that rewrites GitHub's `head`/`base` objects to their branch strings — `base` always `.ref`, `head` `.label` for a cross-repo (fork) PR and `.ref` otherwise — applied before each response populates status, so `status.head`/`status.base` are always strings. `status` also carries `merged` (a plain boolean) and `merged_at` (an RFC3339 timestamp, null until merged) via `additionalStatusFields`: `merged` distinguishes a merged PR from a closed-but-unmerged one, which `state` alone cannot, and `merged_at` carries when it merged. All only update while the CR keeps being re-observed. A CR that never recorded `status.number` recovers on its next reconcile via the `findby` on head/base (`GET /repos/{owner}/{repo}/pulls`, `identifiersMatchPolicy: AND`), which normalizes each list item before matching — requires **oasgen-provider >= 0.25.0**; see [design-pullrequest §8](./design-pullrequest.md). `head_repo` and `issue` are create-only; `title` is optional because GitHub accepts `issue` instead (a cross-field rule the CRD cannot state). `maintainer_can_modify` is create-only: on a same-repo PR GitHub stores `false` and refuses a PATCH to `true` (422, measured 2026-11-10). |
| `Issue` | `number` | `issue_number` excluded, sourced from `status.number`. No delete verb (GitHub REST has none). `labels`, `assignees` and `milestone` are create-only: GitHub returns them as objects where the request takes strings and an integer. `assignee`, `type` and `parent_issue_id` are create-only too (not in the PATCH body). `issue_field_values` is not modelled yet: its `value` is a string/number/array union that oasgen renders as an object (oasgen-provider#563). |
| `Release` | `id` | `release_id` excluded, sourced from `status.id`. `generate_release_notes`, `discussion_category_name` and `make_latest` are create-only. |
| `RepoDeployment` | `id` | `deployment_id` excluded, sourced from `status.id`. No update verb. `auto_merge` is **defaulted `false`** in the asset, against GitHub's own default of `true`; `required_contexts` is create-only; GitHub's `oneOf`-typed `payload` is not modelled. Status carries `original_environment`, not `environment` — see [api](./api.md). |
| `RepoContent` | `path` | create and update are the same `PUT /repos/{owner}/{repo}/contents/{path}`. The get verb relocates `spec.branch` onto GitHub's `?ref` query via `fieldMapping` (the parameter is declared `ref` and `excludedSpecFields`), and a `responseTransform` strips GitHub's RFC-2045 line-wrapping from `content` so a byte-identical file does not loop — plus a `del(.content)` guard for the `encoding: none` case GitHub returns for files ≥ 1 MB. `create` carries `requestTransform: del(.sha)` (a create only ever runs against an absent file); `update` and `delete` auto-source `sha` from `status.sha`. `compareScope` is left at the default `fullSpec` — see below. `author`/`committer` follow GitHub: when set, each needs `name` and `email` (GitHub answers 422 otherwise) and may carry `date`; the delete sends the same two objects, so the deleting commit has the CR's identity. |

**Governance**

| kind | identifiers | key mapping facts |
|---|---|---|
| `CustomProperty` | `property_name` | GitHub's `custom_property_name` path parameter is **renamed** `property_name` in the asset so one CR field covers path, identifier and status — the same technique `repository.yaml` uses. PUT is an upsert on the same URL get and delete use, so create and update are the same call. `regex` (RE2, string properties only) is carried as GitHub publishes it. |
| `CodeSecurityConfig` | `id` | `configuration_id` excluded, sourced from `status.id`. GitHub's update accepts everything its create does, so nothing here is create-only. |
| `AutomatedSecurityFixes` | *(none)* | a singleton sub-resource with no identity of its own: the repository is the key and lives in the path. A `notFoundBody` predicate reports `enabled == false` as absent — load-bearing, because a repository with the feature off answers **200**, not 404. `paused` is surfaced on status but excluded from the predicate. |

**Repository creation**

| kind | identifiers | key mapping facts |
|---|---|---|
| `Repository` | `name` | create on `/orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}` (deleting the CR deletes the repository unless it is annotated `krateo.io/deletion-policy: orphan`) — the parameters are renamed `org`/`name` so one pair of spec fields serves the create path, the create body and the item path. The item path `name` is sourced from **`status.name`** via `fieldMapping` (the name GitHub assigned), not `spec.name`: GitHub normalises a disallowed character on create (`"my repo"` → `my-repo`), and a `GET` by `spec.name` would 404 while the repo exists and loop on re-create (oasgen #386). Pre-create, `status.name` is absent and the parameter falls back to `spec.name`, which 404s correctly (the repo does not exist yet) → one create → status set. `compareScope: updatable`, not the default (below); status carries `id`, `node_id`, `full_name`, `html_url`, `clone_url`, `ssh_url`, `default_branch`. The merge settings GitHub's create and update bodies share (`allow_*_merge`, `delete_branch_on_merge`, `is_template`, the merge/squash commit title and message enums, `use_squash_pr_title_as_default`) are compared and fixable when the CR sets them; `has_downloads`, `custom_properties` and `team_id` act once, at create. GitHub's defaults are not copied. |
| `UserRepository` | `name` | the user-owned sibling of `Repository`: create is `POST /user/repos` (owned by the token account), get/update address `/repos/{owner}/{name}` with `owner` sourced from `status.owner.login` (`excludedSpecFields` — never hand-set, since GitHub assigns the owner from the token) and `name` sourced from `status.name` (the name GitHub assigned, the same oasgen #386 fix as `Repository`). Before that status exists, observe is a **findby** over `GET /user/repos` pinned to `affiliation=owner` (owned repos, so names are unique) and walked with `pageNumber` pagination (short-page end rule), so a same-name repo already in the token's account is adopted rather than duplicated. **Deleting the CR deletes the repository**, an adopted one included, unless the CR is annotated `krateo.io/deletion-policy: orphan` (as for `Repository`). `name`/`private`/`visibility` are kept out of the PATCH body for the identical reasons (below); `compareScope: updatable`; status as `Repository` plus `owner.login`. Same merge settings as `Repository` (here `use_squash_pr_title_as_default` is update-only, since GitHub's `POST /user/repos` lacks it); `has_downloads`, `has_discussions` and `team_id` act once, at create. |

### `compareScope` across the chart

`compareScope` takes one of three values — `fullSpec` (the default),
`identifiersAndStatus`, or `updatable`. Across the 32 kinds:

| value | kinds | count |
|---|---|---|
| `updatable` | `Repository`, `UserRepository`, `Team`, `TeamRepo`, `TeamMembership`, `Collaborator`, `OrgMembership`, `RepoWebhook`, `OrgWebhook`, `Environment`, `RepoRuleset`, `OrgRuleset`, `BranchProtection`, `ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`, `DeploymentBranchPolicy`, `Label`, `Milestone`, `Issue`, `PullRequest`, `Release`, `CustomProperty`, `CodeSecurityConfig` | 25 |
| default `fullSpec` (unset) | `Workflow`, `AutomatedSecurityFixes`, `RepoContent` | 3 |
| `fullSpec` (set explicitly) | `Autolink` | 1 |
| `identifiersAndStatus` | `DeployKey`, `RepoDeployment`, `GitRef` | 3 |

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
budget. That is the case `updatable` exists for, and it splits the 24 kinds in two:

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
  compare are create-only fields or path parameters: `Repository`'s and `UserRepository`'s
  `auto_init` / `gitignore_template` / `license_template`, `Release`'s `generate_release_notes` / `discussion_category_name` / `make_latest`,
  `RunnerGroup`'s `selected_repository_ids` / `runners`,
  `ActionsVariableOrg`'s `selected_repository_ids`, plus `Team`, `TeamMembership`,
  `OrgMembership`, `Label`, `BranchProtection`, `RepoRuleset`, `OrgRuleset`,
  `CodeSecurityConfig`, `CustomProperty` and `Environment`, whose surplus is path
  parameters alone. The response carries none of them, so the comparison skips them and
  `updatable` and `fullSpec` should agree today. It is set anyway because it states the
  intent by construction and stays correct if a field the response *does* carry and the
  update *cannot* fix is added later — not because it is preventing a loop.

The kinds that are not `updatable` are not oversights; each carries the reason in
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
- **`RepoDeployment`** has no update verb because a deployment is an immutable historical
  record. Its create-only `auto_merge` and `required_contexts` are never echoed and are
  therefore skipped, but the fields the GET *does* echo would be compared under `fullSpec`
  with no update call to fix a difference — `environment` above all, which a CI job
  posting a deployment status can rewrite. `identifiersAndStatus` is the honest model: the
  only thing worth reconciling is whether the deployment this CR created still exists.
  `additionalStatusFields` lists `original_environment` rather than `environment`
  specifically to keep the projected compared set empty.
- **`RepoContent`** is the one non-`updatable` kind that *does* have an update verb (and a
  delete). It keeps the default `fullSpec` deliberately: its get response carries only
  `path`, `content` and an optional `sha`, so the compared set is exactly `content` — the
  one thing the kind manages — and `updatable` would derive the same set minus the `path`
  identifier, changing nothing.

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

`updatable` compares exactly the fields the `PATCH` body can express that are also spec
fields, derived from the OAS rather than declared by hand: `description`, `homepage`,
`has_issues`, `has_wiki` and `has_projects`. The `PATCH` body also carries `default_branch`
and `archived`, but the spec body comes from the create verb alone, so those two are not
spec fields and are never compared or sent. It requires an update verb, which `Repository`
has.

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
  repository, which GitHub's rename redirect surfaced as a 307. Keeping it out of the body is
  also what makes the item verbs safe to key on `status.name` (the oasgen #386 fix above):
  addressing tracks the name GitHub assigned, and because `name` is never in the compare set,
  tracking it can never PATCH it back to `spec.name`.

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

`UserRepository`, the user-owned sibling, takes this subsection's reasoning verbatim: the same
`updatable`-is-load-bearing requirement, the same `name`/`private`/`visibility` kept out of the
PATCH body, and the same no-delete-verb orphan-not-destroy stance. It differs only in its create
path (`POST /user/repos` rather than `/orgs/{org}/repos`) and its item path, whose `owner` is read back from GitHub (`status.owner.login`) rather than set
in the spec, since GitHub assigns it from the token.

### Updates send whole values — what a CR owns

`compareScope` governs what is **compared** (what can *trigger* an update); it does not
govern what is **sent**. Those are two different layers, and conflating them hides a real
hazard. When `rest-dynamic-controller` assembles an update/PUT body it does so **by
top-level spec key** (`internal/tools/client/builder`, `processFields`): for every
top-level key present in spec it forwards the key's **whole value**. So an object, map or
array spec field is sent **entire on every update**, regardless of scope — once an update
fires for any reason, the complete value from spec goes on the wire. `compareScope:
updatable` narrows what can *start* that update; it cannot make the update send a subset.

The consequence is a single rule: **a CR-managed object/array is OWNED by the CR.** Where
GitHub *replaces* that value rather than merging it (a PUT on the whole resource, or
GitHub's wholesale-replace of a nested object such as a webhook `config`), anything present
on GitHub but absent from the CR is removed the moment an update fires. And because arrays
are compared **positionally** (length + order — see the `RepoRuleset`/`OrgRuleset` note
above and [api](./api.md)), an element added out-of-band does not slip past the comparison:
it lengthens the array, reads as drift, and triggers the very replacing PUT that deletes
it. (The opposite direction is quiet — a response key *absent from spec* is skipped by the
comparison, so GitHub-side extras that the CR does not name do not by themselves loop.)

This is distinct from the false-drift-loop reasoning that fills most of this page. A false
drift loop is an update that *cannot converge*; this is an update that converges by
**deleting** state the CR never knew about. The exposed kinds, by what the loss means:

| class | kind — field | what is lost |
|---|---|---|
| **DATA LOSS — capability gap** (the CR cannot express it, so it is removed on the next update) | `BranchProtection` — the `required_status_checks` `checks` (context + `app_id`) form | not modelled; set in the UI, the app_id pinning is lost when any modelled field drifts and fires the whole-document PUT. **Held, not oversight:** `checks` and `contexts` are two representations of one list that GitHub keeps derived from each other, so a CR that set both would drift-loop, and that misconfiguration cannot be rejected at admission — oasgen carries no `oneOf`/`not`/`x-kubernetes-validations` into the generated CRD (the OAS→domain conversion reads only `allOf`; `libopenapi_adapter.go:450`, `types.go:186-227`). It will be modelled once oasgen supports admission-time cross-field validation (CEL passthrough requested in [oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396)). Until then, manage status checks with `contexts` (modelled). |
| | `RepoWebhook` / `OrgWebhook` — unmodelled `config` keys | `config.token` / `config.digest` (RepoWebhook) and `config.username` / `config.password` (OrgWebhook) are not modelled; set out-of-band, they are cleared by the wholesale `config` replace. |
| **SILENT** (expressible, but invisible when reverted) | `RepoWebhook` / `OrgWebhook` — `config.secret` | **the most important case.** A secret set outside the CR — GitHub UI, Terraform, a secret manager — is **cleared** on any `config` PATCH, because GitHub replaces the `config` object wholesale and the forwarded `spec.config` does not carry it. The field reads back masked (`********`), so the operator cannot even observe the drift. See the webhook-secret guidance below. |
| **Declarative by design** (the CR CAN express it; a revert is normal Kubernetes behaviour, visible and intended) | ruleset `rules` (all 23 rule types modelled), `bypass_actors` / `conditions.ref_name`; `BranchProtection` `restrictions` (users/teams/apps), `required_status_checks.contexts`, and the review object's `dismissal_restrictions` / `bypass_pull_request_allowances`; `Environment` `reviewers` / `wait_timer` / `prevent_self_review`; webhook `events`; `RunnerGroup` `selected_workflows`; `CustomProperty` `allowed_values` | an out-of-band addition is reverted to the CR's declared set on the next reconcile. This is ordinary declarative management — the CR is the source of truth — not a capability gap. (Ruleset `rules` moved here from the capability-gap class now that **all 23** GitHub rule types are modelled — see [api](./api.md); usage caveats: a `merge_queue` rule's ruleset needs a concrete ref, the four push rules need `target: push`, and `workflows`/`code_scanning` take hand-supplied identifiers. `BranchProtection`'s review sub-restrictions are also modelled, so they moved here too. `Environment`'s `reviewers` / `wait_timer` / `prevent_self_review` left the SILENT class once the get verb's responseTransform began flattening GitHub's `protection_rules` array into them — they are now observed and reverted. Its protection-rule PUT is a **merge** (verified live 2026-11-03): a key the CR omits is left untouched (and not compared), while an explicit `reviewers: []` / `wait_timer: 0` actively clears — so Environment does **not** silently overwrite, correcting this row's earlier "re-sent from spec, overwriting out-of-band" claim. Write `reviewers` sorted by `(type, id)`. Set `prevent_self_review: true` only with a non-empty `reviewers` list: GitHub carries it inside the required-reviewers rule, so with no reviewers it stores nothing and such a CR never converges (re-applies forever) — unenforceable at admission until [oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396), the same blocker as the BranchProtection `checks` form. One nuance for `BranchProtection`, **verified live 2026-11-03**: omitting `dismissal_restrictions` / `bypass_pull_request_allowances` from the review object does **not** clear previously-set actors — unlike the four top-level controls, these two nested lists are not part of the wholesale replace; a CR clears them by sending explicit empty `users`/`teams`/`apps`.) |

So the practical guidance for the first two classes is the same as for any declaratively
managed resource, sharpened: **do not keep, on a CR-managed branch protection / webhook,
state that the CR cannot express.** `Environment` no longer belongs in that list — its
`reviewers` / `wait_timer` / `prevent_self_review` are now observed and reconciled. Rulesets
no longer have this gap either — all 23
GitHub rule types are modelled, so a CR-managed ruleset can express every rule and an
out-of-band one is simply reverted (declarative-by-design) rather than deleted-unrecoverable.
A CR-managed object does not share ownership of its array fields with the UI.

> Confidence: the top-level-key body assembly and the positional array comparison are
> asserted by [api](./api.md) and the `rd-<kind>.yaml` comments (rest-dynamic-controller
> internals). The webhook-`config.secret` **clearing** specifically is **MEDIUM-HIGH**
> confidence — grounded in GitHub's documented wholesale-replace model for the webhook
> `config` object and the asset authors' explicit statement, **not** live-verified here.

#### The webhook secret: the CR is authoritative

Because the whole `spec.config` map is forwarded on every webhook update and GitHub
replaces `config` wholesale, the secret survives **only if the CR carries it**. Therefore:

- **Treat the CR as the single source of truth for the webhook secret.** Set it in
  `spec.config.secret` and never rotate it out-of-band (UI, Terraform, a secret manager) —
  an out-of-band value is cleared on the next `config` PATCH, silently disabling HMAC
  signing on a live hook with nothing failing and nothing logged.
- **Treat `RepoWebhook` / `OrgWebhook` CRs as sensitive:** RBAC on the kind, encryption at
  rest for etcd, and never the plaintext secret in Git. The value lives in the CR in clear
  text (see [usage](./usage.md)).

Why it is not sourced from a Kubernetes `Secret` today: `rest-dynamic-controller`'s
`secretRef` resolver *could* inject `config.secret` from a Secret (it is stripped from the
outgoing body before send, and it is re-injected into every write body, so it would
actually be immune to this whole-config hazard). The blocker is **optionality, not
capability**: the resolver is all-or-nothing — it errors when the pointer path is absent on
the CR, with no absent/`when` guard (unlike `dependentLookup`, which has one) — so declaring
it would make the secret **mandatory** and break both secretless webhooks and existing
plaintext CRs. An upstream absent-guard (parity with `dependentLookup`'s
`when.customResourceFieldAbsent`) is tracked in
[krateo-platformops/oasgen-provider#383](https://github.com/krateo-platformops/oasgen-provider/issues/383),
**held** until a constraint on which Secrets a resolver may read is designed — an
implementation exists on a branch (it would wire the existing `guardSkips(r.When, mg)`,
today used only by `dependentLookup`, into the `secretRef` branch), with no PR and no
release. Once it ships, an **optional**
`config.secretRef` can be added additively, with no immutable-field change (the pointer is
not in the update body schema, so it is never compared). That planned optional
`config.secretRef` will document the **namespace as the trust boundary** — as
`configurationRef` already is for the GitHub token: anyone who can create a webhook CR in
namespace *N* can make GitHub sign with any Secret in *N*. No timeline or version is
promised.

Regardless of how the secret is supplied, use a **random secret of at least 32 bytes**:
that defeats *offline guessing* of the secret from captured signed deliveries. It does
**not** stop *replay* of genuine signed deliveries — entropy does not cover that — so the
receiver must also verify `repository.full_name` in the payload (and may pin the
`X-GitHub-Hook-ID` header) to reject deliveries replayed from, or meant for, another hook.

### Normalization in the RestDefinition

All 32 kinds are native: every verb goes straight to `api.github.com`, and where GitHub's
REST API needs normalizing, the RestDefinition expresses it rather than a hop through
something the chart would have to run. The mechanisms, and where each is used:

| mechanism | used by | what it does |
|---|---|---|
| static `queries` on a verb | `Collaborator` (findby) | pins `affiliation=direct` (`per_page` is now set by the verb's `pagination` block, which walks every page); both parameters are `excludedSpecFields` so they cannot become user-settable spec fields. Without the pin the endpoint defaults to `affiliation=all` and reports org/team access as if it were this CR's grant. |
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
carried as a ConfigMap (`chart/templates/configmap-<kind>.yaml`). All **32** ConfigMaps
are a plain `.Files.Get`: the assets contain no template action, so nothing is
`tpl`-rendered and each spec is copied verbatim. No operation anywhere in the set
overrides `servers` — every verb of every kind keeps `https://api.github.com`.

What the assets do carry is parameter naming, and `repository.yaml` is the clearest case.
GitHub addresses a repository as `/repos/{owner}/{repo}`; the asset declares those path
parameters as `org` and `name`. The spec fields come from the create operation: `org` is the
create path parameter (`/orgs/{org}/repos`) and `name` is a create-body field. A non-create path
parameter is filled by name from a same-named spec field, so naming the item-path parameters `org`
and `name` lets that **one** pair of create-derived fields serve the create path, the create body
and the get/update/delete path. Had the asset kept GitHub's `owner`/`repo` instead, oasgen — which
merges the parameters of every verb into the spec — would have added `spec.owner` and `spec.repo`
as a second, independent pair naming the same repository, free to disagree with `org`/`name`.
`customproperty.yaml` applies the same rename, turning GitHub's `custom_property_name` into
`property_name`.

`repository.yaml` models only the org-scoped create: GitHub's user-scoped create,
`POST /user/repos`, is a **separate kind**, `UserRepository`. A RestDefinition has exactly one
create verb and cannot pick between two paths at runtime, so the user-owned variant is its own
RestDefinition rather than a branch of this one ([api](./api.md)).

Two capabilities are absent from the asset set because no RestDefinition can express
them, not because they were overlooked ([api](./api.md)): **secrets** at any scope, which
need a LibSodium sealed box plus a prior public-key fetch, and **`VulnerabilityAlerts`**,
whose GET returns 404 or a bodiless 204 and therefore yields no status schema. Variables
are not secrets and are covered at all three scopes.

### Adherence to GitHub's description

The assets follow GitHub's REST description (`github/rest-api-description`, pinned by commit
and SHA-256 in `hack/github_oas.py`). Where a kind's request differs from it, the difference
is listed with its reason in `hack/oas-adherence-exceptions.yaml`, and
`hack/assert-oas-adherence.py` (the `oas-adherence` lint job) compares every verb of every
kind against GitHub's operation: path and query parameters, and request-body properties and
`required`, recursing into nested objects. A difference with no entry fails, and so does an
entry that no longer matches one, so the file is always the complete list. Restoring a field
means deleting its entry. Types and enums are not compared yet.

Each entry has a category: **A** safety (restoring it would let drift damage live objects),
**B** drift (GitHub does not echo it as sent, so a compared field would update forever),
**C** a deliberate modelling choice (a renamed parameter, a flattened union), or **D**
unmodelled, with `restore` naming the PR restoring it or the issue holding it.

**Defaults are frozen.** The assets never copy GitHub's request `default`s into new fields.
A CRD default is written by the apiserver into every CR, existing ones included, and cannot
be withdrawn later (oasgen-provider#562), while GitHub applies its default only to a create
that omits the field; leaving the field out keeps GitHub's behaviour. The defaults the chart
already had stay, each listed under `defaults:` with its value and GitHub's own; three of
them contradict GitHub on purpose (`auto_init: true` on Repository and UserRepository,
`auto_merge: false` on RepoDeployment), for the reasons given there.

## No runtime component

The chart renders 32 ConfigMaps and 32 RestDefinitions, and nothing else — no Deployment,
no Service, no image, no proxy, and no `_helpers.tpl` (it held only the two helpers the
proxy needed). Installing the chart puts data in the cluster; the only workloads are the
`rest-dynamic-controller` deployments oasgen-provider creates per kind.

That became true when `GitRef`, `RepoContent` and `PullRequest` were removed — the three
kinds whose verbs routed through a companion proxy, and the only users of it, so the plugin
went with them. The frontend now publishes through a `BuilderPublish` claim over
`git-provider` — `AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"` in the frontend
chart's `values.yaml` and `values.schema.json` — and the `github.krateo.io` route is the
`"false"` fallback. All three have since returned **natively**, with no proxy:
`PullRequest` (a `responseTransform` flattening `head`/`base`, plus a findby for group-B
recovery), `GitRef` (a `requestTransform` for the `refs/` prefix plus a `dependentLookups`
chain for the base sha, oasgen-provider ≥ 0.36.0), and `RepoContent` (`status.sha`
auto-populating the update/delete body, plus `responseTransform`s that canonicalize the
base64 `content` and lift `sha`/`html_url` to the root after a write).

What each did, and what a native return takes, is written down per kind:

| document | kind | native-return state |
|---|---|---|
| [design-gitref](./design-gitref.md) | `GitRef` | **returned** (appVersion 0.1.3). The base-HEAD-sha pre-call read — oasgen-provider **#120** — shipped as dependent lookups in **0.36.0**, so a sha-less create is native; `spec.sha` stays optional. |
| [design-repocontent](./design-repocontent.md) | `RepoContent` | **returned** — `status.sha` auto-sources the update/delete body, a `responseTransform` canonicalizes the base64 `content` (with a `del(.content)` guard for files ≥ 1 MB), and `del(.sha)` on create removes a stale-sha wedge; the `%252F` double-escape was fixed upstream. |
| [design-pullrequest](./design-pullrequest.md) | `PullRequest` | **returned** — a `responseTransform` flattening `head`/`base` to `ref` strings. |

## Invariants

- **oasgen-provider must be ≥ 0.52.0.** 0.52.0 adds `RestDefinition.spec.serverURL`, which
  `githubBaseUrl` sets on every RestDefinition for GitHub Enterprise; below it the field would be
  dropped silently and requests would reach api.github.com. Earlier floors: 0.38.0 is where the `GitRef` pattern admission
  guard reaches the generated CRD — the fix that makes the OpenAPI validation keywords
  land on the CRD ([#249](https://github.com/krateo-platformops/oasgen-provider/issues/249),
  merged as #250). `GitRef`'s create resolves its base sha with **dependent lookups**, a
  primitive that landed in 0.36.0 ([#120](https://github.com/krateo-platformops/oasgen-provider/issues/120),
  merged as #239), and the `compareScope: updatable` that 25 kinds declare does not exist
  below 0.23.0 — all still hold, now subsumed by 0.52.0.
- **The chart stays free of a runtime component.** It renders one ConfigMap and one
  RestDefinition per selected kind, 32 of each by default, and nothing else; every kind reaches `api.github.com` directly, no
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
  (`kubectl apply --dry-run=server`); `GitRef`, the 30th, was validated live end-to-end on
  oasgen-provider 0.36.0 (lookup mechanics) and 0.38.0 (the `spec.ref.pattern` admission guard),
  its `dependentLookups` + `dependentLookup` resolver shape accepted and the sha-less/explicit-sha
  paths and delete round-trip all confirmed against the real GitHub API.
- **The token is provisioned out-of-band, and its rights are the union of the kinds in
  use.** The chart holds no credential; the portal write-path only references the
  `<Kind>Configuration` CRs ([usage](./usage.md)). One PAT can drive all 32 kinds, and
  `chart/samples/configurations.yaml` ships 31 of the 32 Configuration CRs under a single name
  (`UserRepository`'s has its own, since its repositories are created in the token's account)
  — but `Repository` needs repository creation in the org (classic `repo` scope, or a
  fine-grained token with org **Administration: read & write**), and the org-scoped kinds — `Team`, `TeamMembership`,
  `TeamRepo`, `OrgMembership`, `OrgWebhook`, `OrgRuleset`, `ActionsVariableOrg`,
  `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` — need organization admin rights.
