---
type: Configuration
title: krateo-github-provider-kog — configuration
description: The whole config surface — the single chart value resourceGroup, the three RestDefinition mappings and their per-verb tables, the OpenAPI ConfigMaps and plugin servers overrides, the plugin routes and env, and the invariants that must hold.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [krateo, values, restdefinition, oasgen-provider, plugin]
timestamp: 2026-08-11T00:00:00Z
---

# Configuration

The chart surface is deliberately tiny — one scalar. Everything else is fixed mapping
(`chart/assets/`, `chart/templates/`).

## Chart values

`chart/values.yaml`, typed by `chart/values.schema.json`
(`additionalProperties: false` — an unknown key fails the schema):

| key | default | effect |
|---|---|---|
| `resourceGroup` | `github.krateo.io` | the API group the generated CRDs (`RepoContent`/`GitRef`/`PullRequest` + their `<Kind>Configuration`) land under. Referenced by every RestDefinition's `spec.resourceGroup`. |
| `global` | `{}` (object) | Helm global values, injected by the chart-inspector / when used as a subchart. |

The schema declares **only** a single top-level scalar on purpose: when the chart is
installed as a Krateo component the CDC derives the CompositionDefinition CRD from this
schema, and a scalar default materializes cleanly in the component CR (nested-object
toggles would not) ([api](./api.md)).

## The RestDefinition mappings

Each `chart/templates/rd-<kind>.yaml` declares the API mapping oasgen-provider consumes.
The pieces that matter per kind:

| kind | identifiers | key mapping facts |
|---|---|---|
| `RepoContent` | `path` | create/update/get/delete all on `/repos/{owner}/{repo}/contents/{path}`; status carries `sha`, `html_url`. |
| `GitRef` | `ref` | create on `git/refs`, but **get** on the plugin's `/gitref/{owner}/{repo}/{ref}` (fixes GitHub's git/ref-vs-git/refs asymmetry); status carries `node_id`, `url`. |
| `PullRequest` | `number` | `pull_number` is `excludedSpecFields` (GitHub assigns it on create); get/update source it from `status.number` via `requestFieldMapping`. Status carries `number`, `html_url`, `state`. |

`configurationFields` is empty for all three; the token wiring comes from the
oasgen-generated `<Kind>Configuration` + `spec.configurationRef`, not from spec fields.

## The OpenAPI specs and the plugin `servers` overrides

Each RestDefinition references a trimmed OpenAPI 3.0 spec (`chart/assets/<kind>.yaml`)
carried as a ConfigMap (`chart/templates/configmap-<kind>.yaml`). The ConfigMaps are
`tpl`-rendered so the per-operation `servers` overrides resolve to the plugin's
in-cluster URL via the `webServiceUrl` helper (`chart/templates/_helpers.tpl`):

```
http://<release>-plugin.<namespace>.svc:8080
```

Only the operations that need normalization carry that override; every other verb keeps
`https://api.github.com`. A notable OpenAPI subtlety: on `git/update-ref`, `sha` is
intentionally **not** required — oasgen unions `required` across all verbs into one
CRD `spec.required`, so requiring it on update would force it back onto the create path
(which auto-resolves it). Similarly the RepoContent get operation names its query param
`branch` (not GitHub's `ref`) so the controller — which only fills a query param whose
name matches a CR spec field — populates it from `spec.branch`; the plugin forwards it
to GitHub as `?ref`.

## The plugin

`plugin/main.go`, a stdlib-only Go service; `plugin/Dockerfile` builds it on a
distroless `nonroot` base (UID/GID 65532). It exposes:

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

- **The plugin image tag equals the chart version.** The Deployment pins
  `:{{ .Chart.Version }}`, and `release-image.yaml` publishes the plugin image on the
  same bare-semver tag `release-oci.yaml` uses for the chart, so one tag push publishes
  both and they line up ([release](./release.md)).
- **`webServiceUrl` must resolve to the plugin Service.** The ConfigMaps are
  `tpl`-rendered for exactly this reason; a plain `.Files.Get` would leave the template
  literal in the OpenAPI and the controller would call GitHub for the plugin-only verbs
  (breaking observe on GitRef/PullRequest and idempotent write on RepoContent).
- **The token is provisioned out-of-band.** The chart holds no credential; the portal
  write-path only references the `<Kind>Configuration` CRs ([usage](./usage.md)).
