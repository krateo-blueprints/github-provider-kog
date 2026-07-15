# krateo-github-provider-kog

A Krateo **KOG** provider (built on [`oasgen-provider`](https://github.com/krateoplatformops/oasgen-provider) 0.9.x) that exposes GitHub's **git-write** API as Kubernetes kinds under the `github.krateo.io` group:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `RepoContent` | `PUT /repos/{owner}/{repo}/contents/{path}` | create/update a file in a repo |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | create a branch/ref |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | open a pull request |

It is the in-cluster git transport for **Krateo portal blueprint authoring** — the Autopilot blueprint builder writes a chart tree to a repo (GitRef → RepoContent per file → PullRequest) entirely as `github.krateo.io` apiserver CRs, so external CI can package + push the OCI chart on merge. It is also the live path for the KOG API-mapping builder.

## How it works

This chart ships **only**:
- three `RestDefinition`s (`ogen.krateo.io/v1alpha1`), one per kind, and
- the trimmed OpenAPI 3.0 spec each references (as a `ConfigMap`).

`oasgen-provider` (installed cluster-wide) watches the RestDefinitions, generates the CRDs under `github.krateo.io`, and **auto-deploys a `rest-dynamic-controller` Deployment per kind**. There is **no provider image in this chart** — the git-write kinds are handled purely from their OpenAPI mapping (no plugin web service, unlike the `collaborator`/`teamRepo` kinds of the older `github-provider-kog-chart`).

## Prerequisites

- A Krateo cluster with `oasgen-provider` **≥ 0.9.x** running (provides `restdefinitions.ogen.krateo.io`).

## Authentication

Each RestDefinition's OpenAPI declares a bearer `securityScheme`, so `oasgen-provider` also mints a **`BearerAuth`** CRD in the `github.krateo.io` group. Provision, out-of-band, a token Secret + a `BearerAuth` CR that points at it:

```bash
kubectl create secret generic gh-token \
  --namespace krateo-system \
  --from-literal=token=<YOUR_GITHUB_PAT>   # PAT scopes: repo (+ contents:write, pull_requests:write)
```

```yaml
# a BearerAuth CR the resource CRs reference via spec.authenticationRefs.bearerAuthRef
apiVersion: github.krateo.io/v1alpha1
kind: BearerAuth
metadata:
  name: github-blueprints-token
  namespace: krateo-system
spec:
  tokenRef:
    name: gh-token
    namespace: krateo-system
    key: token
```

> The Krateo portal write-path **references** this `BearerAuth`/Secret; it never creates it. The PAT is created and stored by an operator (never handled by the browser or snowplow).

## Install

Per the Krateo "everything is a Composition" rule, this chart is installed as a **component** (a `component-pins` entry → a `CompositionDefinition` reconciled by the core-provider CDC), **not** via `helm install`. See `docs/install.md`.

For local development against a kind cluster only:

```bash
helm upgrade --install krateo-github-provider-kog ./chart --namespace krateo-system
```

## Samples

- `chart/samples/bearerauth.yaml` — the auth CR wiring above.
- `chart/samples/test-gitref.yaml`, `test-repocontent.yaml`, `test-pullrequest.yaml` — one CR per kind against a scratch repo.

## Verify

```bash
# oasgen should generate the CRDs + a controller per kind
kubectl get crd | grep github.krateo.io
kubectl get deploy -n krateo-system | grep -E 'repocontent|gitref|pullrequest'
```
