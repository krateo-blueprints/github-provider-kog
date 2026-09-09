# github-provider-kog

## What is this

A Krateo **KOG** (Krateo OpenAPI Generation) provider, built on
[`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider) **≥ 0.23.0**,
that exposes 31 GitHub REST resources as Kubernetes kinds under the `github.krateo.io`
group. Each kind is listed by its create endpoint; get/update/delete sit on the matching
item path.

**Git transport** — the blueprint-authoring chain:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Repository` | `POST /orgs/{org}/repos` | create the destination repository itself |
| `RepoContent` | `PUT /repos/{owner}/{repo}/contents/{path}` | create/update a file in a repo |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | create a branch/ref |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | open a pull request |

**Access** — who can reach what:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Team` | `POST /orgs/{org}/teams` | create an org team (addressed by its server-derived `slug`) |
| `TeamRepo` | `PUT /orgs/{org}/teams/{team_slug}/repos/{owner}/{repo}` | grant a team access to a repo |
| `TeamMembership` | `PUT /orgs/{org}/teams/{team_slug}/memberships/{username}` | put a user in a team as member or maintainer |
| `Collaborator` | `PUT /repos/{owner}/{repo}/collaborators/{login}` | grant a user direct access to one repo |
| `OrgMembership` | `PUT /orgs/{org}/memberships/{username}` | set a user's org membership and role |

**Repository configuration**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `RepoWebhook` | `POST /repos/{owner}/{repo}/hooks` | deliver a repo's events to an endpoint |
| `OrgWebhook` | `POST /orgs/{org}/hooks` | the same, at org scope |
| `DeployKey` | `POST /repos/{owner}/{repo}/keys` | add an SSH deploy key (immutable — no update verb) |
| `Environment` | `PUT /repos/{owner}/{repo}/environments/{environment_name}` | a deployment environment, its reviewers and branch policy |
| `RepoRuleset` | `POST /repos/{owner}/{repo}/rulesets` | branch/tag rules for one repo |
| `OrgRuleset` | `POST /orgs/{org}/rulesets` | the same ruleset document, org-wide |
| `Autolink` | `POST /repos/{owner}/{repo}/autolinks` | map a ticket prefix to an external URL (immutable) |
| `BranchProtection` | `PUT /repos/{owner}/{repo}/branches/{branch}/protection` | the protection document of one branch |

**CI/CD**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `ActionsVariableRepo` | `POST /repos/{owner}/{repo}/actions/variables` | a plaintext Actions variable on a repo |
| `ActionsVariableOrg` | `POST /orgs/{org}/actions/variables` | the same, at org scope |
| `EnvironmentVariable` | `POST /repos/{owner}/{repo}/environments/{environment_name}/variables` | the same, scoped to an environment |
| `RunnerGroup` | `POST /orgs/{org}/actions/runner-groups` | an org self-hosted runner group |
| `DeploymentBranchPolicy` | `POST /repos/{owner}/{repo}/environments/{environment_name}/deployment-branch-policies` | which branches/tags may deploy to an environment |
| `Workflow` | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` | enable (create) / disable (delete) an existing workflow file |

**Work tracking**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Label` | `POST /repos/{owner}/{repo}/labels` | an issue/PR label |
| `Milestone` | `POST /repos/{owner}/{repo}/milestones` | a milestone (`due_on` is create-only — see below) |
| `Issue` | `POST /repos/{owner}/{repo}/issues` | open and update an issue (no delete — REST has none) |
| `Release` | `POST /repos/{owner}/{repo}/releases` | a release |
| `Deployment` | `POST /repos/{owner}/{repo}/deployments` | an immutable deployment record |

**Governance**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `CustomProperty` | `PUT /orgs/{org}/properties/schema/{property_name}` | define an org custom property |
| `CodeSecurityConfig` | `POST /orgs/{org}/code-security/configurations` | an org code-security configuration |
| `AutomatedSecurityFixes` | `PUT /repos/{owner}/{repo}/automated-security-fixes` | the Dependabot security-updates toggle for one repo |

The per-kind verbs, identifiers and `compareScope` are in
[docs/configuration.md](docs/configuration.md); the reasoning behind each choice is in the
`chart/templates/rd-<kind>.yaml` comments.

**Not covered, deliberately.** GitHub Actions, Dependabot and Codespaces *secrets* are not
expressible here: writing one takes an `encrypted_value` (a LibSodium sealed box) plus the
`key_id` of a repository public key fetched beforehand, and a `RestDefinition` can do
neither client-side crypto nor a dependent lookup. Variables are **not** secrets — GitHub
stores and returns `value` verbatim — and are covered at repo, org and environment scope.
`VulnerabilityAlerts` was evaluated and dropped: `GET
/repos/{owner}/{repo}/vulnerability-alerts` answers 404 when the feature is off and 204
with **no body** when it is on, so it never returns anything a status schema could be
derived from. `AutomatedSecurityFixes` is covered for exactly the opposite reason — its
GET does return a body (`enabled`, `paused`).

The git-transport four are why the chart exists — they are the in-cluster transport for
**Krateo portal blueprint authoring**: the
Autopilot blueprint builder writes a chart tree to a repo (`GitRef` → `RepoContent` per
file → `PullRequest`) entirely as `github.krateo.io` apiserver CRs, so external CI can
package and push the OCI chart on merge.

`Repository` closes the gap at the front of that chain. Until it existed, a blueprint
could only be published into a repository someone had already created by hand — which is
backwards for a brand-new blueprint. It is deliberately ordered first: a repository
created with `auto_init: false` has no commit and therefore no default branch, so a
`GitRef` has no base sha to branch from and a `RepoContent` has nothing to commit
against. The OAS defaults `auto_init` to `true` for exactly that reason.

The chart ships 31 `RestDefinition`s + the trimmed OpenAPI spec each references (as a
`ConfigMap`), plus a small companion **plugin** (`Deployment` + `Service`).
`oasgen-provider` watches the RestDefinitions, generates the CRDs under
`github.krateo.io`, and auto-deploys a `rest-dynamic-controller` per kind. The plugin
handles only the GitHub REST inconsistencies the pure OpenAPI mapping cannot express, and
serves exactly three kinds — `GitRef`, `RepoContent` and `PullRequest`. The other 28 are
**native**: every one of their verbs goes straight to GitHub. See
[docs/overview.md](docs/overview.md).

## Install

Prerequisite: a Krateo cluster with `oasgen-provider` **≥ 0.23.0** — it provides
`restdefinitions.ogen.krateo.io`, and 0.23.0 is where `compareScope: updatable` arrives,
which 23 of the 31 kinds declare.

Per the Krateo "everything is a Composition" rule, this chart is installed as a
**component** — a `component-pins` entry that the core-provider CDC turns into a
`CompositionDefinition` — not via `helm install`. See [docs/usage.md](docs/usage.md).

For local development against a kind cluster only:

```console
$ helm upgrade --install github-provider-kog ./chart --namespace krateo-system
```

## Configure

The chart surface is one scalar, `resourceGroup` (default `github.krateo.io`) — the API
group the generated CRDs land under. Everything else is fixed mapping in `chart/assets/`
and `chart/templates/`.

Authentication is provisioned **out-of-band**. Each RestDefinition's OpenAPI declares a
bearer `securityScheme`, so oasgen generates a per-kind `<Kind>Configuration` CRD and
adds `spec.configurationRef` to every resource CR. Create a token Secret and one
Configuration per kind pointing at it:

```console
$ kubectl create secret generic gh-token -n krateo-system \
    --from-literal=token=<YOUR_GITHUB_PAT>
$ kubectl apply -f chart/samples/configurations.yaml   # all 31 <Kind>Configuration CRs
```

One PAT can drive the whole chart: all 31 Configurations may share a single name
(`github-blueprints-config`), since the kind is implied by the resource that references
it. What the PAT must be *allowed* to do differs by kind, though — the git-write kinds
need only contents/refs/pulls, `Repository` also needs repository creation in the org
(classic `repo`; fine-grained org **Administration: read & write**), and the org-scoped
kinds such as `Team` and `OrgMembership` need org admin rights. You only need the
Configurations for the kinds you actually use; the rest are inert. (`CodeSecurityConfig`
is named that rather than `CodeSecurityConfiguration` so its generated auth kind is
`CodeSecurityConfigConfiguration`, not a doubled `…ConfigurationConfiguration`.)

The Krateo portal write-path only **references** these Configuration CRs; it never
creates them or the Secret. Full surface: [docs/configuration.md](docs/configuration.md).

## Examples

- [examples/blueprint-authoring](examples/blueprint-authoring/README.md) — the
  end-to-end git-write flow (`GitRef` → `RepoContent` → `PullRequest`) applied as three
  `github.krateo.io` CRs against a scratch repo.
- `chart/samples/` — the 31 `<Kind>Configuration` CRs and one applyable test CR per kind
  (`test-<kind>.yaml`).

## Docs

The full documentation bundle follows the Krateo Documentation Standard (OKF):

- [docs/index.md](docs/index.md) — the map of the bundle.
- [docs/overview.md](docs/overview.md) — how it works: RestDefinitions → CRDs +
  controllers, and the plugin.
- [docs/usage.md](docs/usage.md) — install, provision auth, drive the kinds, verify.
- [docs/configuration.md](docs/configuration.md) — values, mappings, plugin routes,
  invariants.
- [docs/api.md](docs/api.md) — the generated CRDs and the CompositionDefinition.
- [docs/examples.md](docs/examples.md) — the runnable examples.
- [docs/release.md](docs/release.md) — how a release ships.
- [docs/log.md](docs/log.md) — curated history.
- [docs/llms.txt](docs/llms.txt) — the file-by-file index.

## Develop & release

- **Chart** — `chart/` is the single first-class chart; `chart/values.schema.json` types
  its values (and is what the CDC derives the component CRD from).
- **Plugin** — `plugin/main.go` is a stdlib-only Go service; `plugin/Dockerfile` builds
  it on a distroless `nonroot` base.
- **Release** — one plain-semver tag (`X.Y.Z`, no `v`) drives both `release-oci.yaml`
  (packages `chart/` to `oci://ghcr.io/krateo-blueprints/charts`) and `release-image.yaml`
  (publishes `ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:X.Y.Z`). The
  plugin Deployment pins `:{{ .Chart.Version }}`, so the two always line up. Details:
  [docs/release.md](docs/release.md).
- **CI** — `lint.yaml` runs the shared `lint-docs` docs-standard check; `security.yml`
  runs the shared org security workflow.
