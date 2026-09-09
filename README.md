# github-provider-kog

## What is this

A Krateo **KOG** (Krateo OpenAPI Generation) provider, built on
[`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider) 0.9.x, that
exposes GitHub's **repository** and **git-write** REST API as Kubernetes kinds under the
`github.krateo.io` group:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Repository` | `POST /orgs/{org}/repos` | create the destination repository itself |
| `RepoContent` | `PUT /repos/{owner}/{repo}/contents/{path}` | create/update a file in a repo |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | create a branch/ref |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | open a pull request |

It is the in-cluster git transport for **Krateo portal blueprint authoring**: the
Autopilot blueprint builder writes a chart tree to a repo (`GitRef` → `RepoContent` per
file → `PullRequest`) entirely as `github.krateo.io` apiserver CRs, so external CI can
package and push the OCI chart on merge.

`Repository` closes the gap at the front of that chain. Until it existed, a blueprint
could only be published into a repository someone had already created by hand — which is
backwards for a brand-new blueprint. It is deliberately ordered first: a repository
created with `auto_init: false` has no commit and therefore no default branch, so a
`GitRef` has no base sha to branch from and a `RepoContent` has nothing to commit
against. The OAS defaults `auto_init` to `true` for exactly that reason.

The chart ships four `RestDefinition`s + the trimmed OpenAPI spec each references (as a
`ConfigMap`), plus a small companion **plugin** (`Deployment` + `Service`).
`oasgen-provider` watches the RestDefinitions, generates the CRDs under
`github.krateo.io`, and auto-deploys a `rest-dynamic-controller` per kind. The plugin
handles only the GitHub REST inconsistencies the pure OpenAPI mapping cannot express;
every other verb goes straight to GitHub. `Repository` needs none of it — all four of its
verbs are native. See [docs/overview.md](docs/overview.md).

## Install

Prerequisite: a Krateo cluster with `oasgen-provider` **≥ 0.9.x** (it provides
`restdefinitions.ogen.krateo.io`).

Per the Krateo "everything is a Composition" rule, this chart is installed as a
**component** — a `component-pins` entry that the core-provider CDC turns into a
`CompositionDefinition` — not via `helm install`. See [docs/usage.md](docs/usage.md).

For local development against a kind cluster only:

```console
$ helm upgrade --install krateo-github-provider-kog ./chart --namespace krateo-system
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
    --from-literal=token=<YOUR_GITHUB_PAT>   # scopes: repo (contents/refs/pulls write)
$ kubectl apply -f chart/samples/configurations.yaml
```

The Krateo portal write-path only **references** these Configuration CRs; it never
creates them or the Secret. Full surface: [docs/configuration.md](docs/configuration.md).

## Examples

- [examples/blueprint-authoring](examples/blueprint-authoring/README.md) — the
  end-to-end git-write flow (`GitRef` → `RepoContent` → `PullRequest`) applied as three
  `github.krateo.io` CRs against a scratch repo.
- `chart/samples/` — the `<Kind>Configuration` set and one test CR per kind.

## Docs

The full documentation bundle follows the Krateo Documentation Standard (OKF):

- [docs/index.md](docs/index.md) — the map of the bundle.
- [docs/overview.md](docs/overview.md) — how it works: RestDefinitions → CRDs +
  controllers, and the plugin.
- [docs/usage.md](docs/usage.md) — install, provision auth, drive the three kinds,
  verify.
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
