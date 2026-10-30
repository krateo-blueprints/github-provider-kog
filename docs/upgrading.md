# Upgrading github-provider-kog

Most upgrades of this chart are a plain `helm upgrade`: the RestDefinitions re-render,
oasgen-provider reconciles them, and the generated CRDs are patched in place. This document
covers the exceptions — upgrades that cross a change oasgen-provider treats as **immutable once a
CRD has been generated**, which it refuses rather than applies. A refused upgrade is **fail-closed**:
the RestDefinition stays at its old shape, the CRD and all custom resources keep serving, and nothing
is destroyed. But the new shape never takes until you perform the migration below.

> **This runbook has been executed end-to-end on two clusters of deliberately different shape** —
> krateo-057 (17 composition-rendered PullRequest CRs across 18 compositions, plus two orphaned RDs from a
> partially-applied upgrade) and krateo-demo (0 PullRequest CRs, 0 owning compositions, the new kinds
> arriving owned). Same ordering, same gates, same halt triggers on both; the shape differences are called
> out inline. Both are now on installer build 0.3.473 at `identifiers: [head, base]`.

## Pre-roll gate: does this release cross an immutable field?

Before rolling a new version onto an existing cluster, check — for **every** RestDefinition in the
release — whether any field oasgen-provider treats as immutable differs between the rendered chart and
the live object. This catches the whole class, not just the field that bit last time. The authoritative
set is **oasgen-provider#290**; as of writing it is seven fields:

| field | rule | effect |
|---|---|---|
| `spec.resource.kind` | strict | no change allowed |
| `spec.resource.identifiers` | strict | no change allowed |
| `spec.resource.configurationFields` | strict | no change allowed |
| `spec.resource.excludedSpecFields` | strict | no change allowed |
| `spec.resourceGroup` | strict | no change allowed |
| `spec.resource.additionalStatusFields` | append-only (prefix) | may append at the end only |
| `spec.resource.includedSpecFields` | append-only (prefix) | may append at the end only |

**Append-only** is a prefix comparison: adding an entry at the end is legal; removing, renaming,
editing, or **reordering** an existing entry is refused. Reordering is the one most likely to look like
a false positive — compare those two fields order-sensitively.

**How to read the live immutability rules** (so the gate tracks the installed oasgen release rather than
a hard-coded list): walk the `x-kubernetes-validations` entries structurally off the **live** generated
CRD. Do **not** grep the CRD for `oldSelf` — the count is unreliable (it appears 9–12 times depending on
the CRD, because each append-only rule mentions `oldSelf` twice and description text adds more), while only
seven are rules. A structural walk gives exactly seven; any grep count is wrong.

An implementation of this gate lives at `hack/rd-immutable-gate.py` (scoped to a helm release; derives all
seven fields structurally from the live CRD's `x-kubernetes-validations`; self-tests five cases including
reorder-with-unchanged-set; and refuses to report a pass when zero RestDefinition names pair or when the
CRD's rule count differs from the expected seven — so a field added by a future oasgen release fails the
gate loudly instead of going unguarded). Against 0.6.0 vs krateo-057 it exits non-zero and names
`pullrequest.identifiers` as the sole violation.

If nothing differs, the upgrade is a plain `helm upgrade`. If a strict field differs, you need the
matching migration. The only strict-field migration shipped so far is the PullRequest identifier change
below; a kind rename (e.g. `Deployment`→`RepoDeployment` in 0.6.0) is a *different* CRD, not a change to
an existing one, so it does not appear in this gate — see `log.md` for that case.

## Orphaned RestDefinitions from a partially-applied upgrade

When an upgrade apply creates some RestDefinitions and then stops on a refused immutable field (the
PullRequest case below), the RestDefinitions it already created are left **unowned**: they carry
`krateo.io/composition-installed-version` but **no** `meta.helm.sh/release-name` and **no**
`ownerReferences`. A `helm rollback` cannot see them (no helm ownership), and the composition's `managed`
rollup cannot either — `status.managed` being **absent** is not evidence that nothing was applied; it is a
*missing record* of what was applied, which is exactly the condition that produces invisible orphans
(core-provider#248: absent ≠ empty). Go look at the objects, don't infer from the rollup.

**krateo-057, as of this writing, is in exactly this state.** The self-heal apply (25s after a cdc
restart) created `github-provider-kog-gitref` and `github-provider-kog-repodeployment` at `v0-6-0` —
both `Ready/Available`, `Synced`, serving `github.krateo.io/v2022-11-28`, **0 instances each** — then hit
the `pullrequest` identifiers refusal and stopped. The helm release stayed at `github-provider-kog-0.3.2`
(rev 37, from October 2) because helm records the release only on a *successful* apply; the two RDs
existing at `v0-6-0` are evidence the apply reached them and then stopped, not that anything owns them.

**These orphans need no action — they are adopted on the next successful apply.** The
composition-dynamic-controller applies via helm's own `Install`/`Upgrade` actions (not direct
server-side-apply) with **`TakeOwnership: true`** set in the shared `ActionConfig` (`composition.go:689`,
plumbed onto the upgrade path at `helm/v3/config.go:62`). `TakeOwnership` skips Helm 3's ownership gate
(`existingResourceConflict` → "invalid ownership metadata"), so a pre-existing object lacking
`meta.helm.sh/release-name` is **adopted into the release** rather than rejected — and this is confirmed on
the **upgrade** path specifically, which is what a release at rev 37 takes. So the completed 0.6.0 apply
adopts `gitref` and `repodeployment` with no "invalid ownership metadata" and nothing to delete or
pre-annotate. (Source: core-provider, verified against the cdc apply code.)

**This orphan state is specific to a *partially-applied* upgrade.** On a cluster where 0.4.0+ was never
partially applied — a fresh install, or any cluster with no pre-existing `pullrequest` CRD to refuse
against — the new kinds (`gitref`, `repodeployment`) are created **owned** on the first successful apply
(`meta.helm.sh/release-name = github-provider-kog`, `Ready=True` directly), and there is nothing for
`TakeOwnership` to adopt because they never existed unowned. Confirmed on krateo-demo: both arrived owned,
no adoption step. So this whole section applies only when you are recovering 057's exact partial-apply
state; on a clean cluster it is a no-op you can read past.

Note the scope of `TakeOwnership`: it governs **only** helm's ownership gate. It does **not** relax
immutable-field refusals — the `cannot patch "github-provider-kog-pullrequest"` error is the apiserver
rejecting a change to an immutable field, well below helm, and is unaffected. That blocker is handled by
the delete-and-recreate below; the orphaned RDs and the immutable field are two independent problems.

## PullRequest: `identifiers` `[number]` → `[head, base]` (crossing into 0.4.0)

### What changed and why the upgrade is refused

0.4.0 (PR #16, closing #14) changed the PullRequest resource's identifiers from `[number]` to
`[head, base]` and added a `findby` verb, so a PullRequest CR re-binds to its GitHub PR by head/base
branch rather than by the PR number it had lost. `spec.resource.identifiers` is strict-immutable
(oasgen-provider#290, `types.go:902`), so on any cluster whose `pullrequests.github.krateo.io` CRD was
generated by a pre-0.4.0 chart (identifiers baked at `[number]`), oasgen-provider refuses to change it.
The RestDefinition reports the refusal and stays at `[number]`; the CRD, its CRs, and the controller keep
serving the old shape. Nothing is destroyed — but 0.4.0+ never converges until you migrate.

Appending (`[number]` → `[number, head, base]`) is **not** a shortcut: `identifiers` drives resolution
under `IdentifiersMatchPolicy` (default `OR`), so broadening the set can re-bind a live CR to a
*different* GitHub object, and `AND` would narrow it to match nothing. The change also *removes* `number`,
so no append-only rule could permit it. Delete-and-recreate is the only sound path.

### Why delete-and-recreate is non-destructive here

Two properties specific to this kind make it safe:

1. **PullRequest has no `delete` verb** (GitHub exposes no REST DELETE for a pull request). When a
   PullRequest CR is deleted, the rest-dynamic-controller runs its finalizer, finds no delete action
   (`restResources.go` `Delete`: apiCall nil → tear down secretRef RBAC → `return nil`), and the runtime
   releases the finalizer with **no external call** — the GitHub PR is untouched, whether or not you strip
   the finalizer first.
2. **`findby` on `head`/`base` re-adopts.** On re-render, each CR matches its existing GitHub PR by head
   and base branch (the 0.4.0 mechanism) and repopulates `status.number`. GitHub is the source of truth;
   the CR→PR binding is rebuilt, not recreated.

So the only state that disappears between delete and re-render is the Kubernetes CR objects, which carry
no unique source of truth. No GitHub PR is ever deleted.

### Are the CRs composition-rendered? (determines whether you must pause)

Check whether the PullRequest CRs are rendered by a composition or hand-applied:

```sh
kubectl get pullrequests.github.krateo.io -A \
  -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels.krateo\.io/composition-name}{"\n"}{end}'
```

- **A `krateo.io/composition-*` label present → composition-rendered.** The owning composition's `Observe`
  actively self-heals a deleted child back (`composition.go:518-525`; `Created` is a re-create counter),
  bounded by the fleet resync interval (**60s**). If you delete the CRs without pausing, they come back
  within the window and you never reach the zero-instance state the CRD delete needs. **You must pause the
  owning compositions first** (step 1 below), and you do **not** hand-re-apply the CRs afterward — you
  unpause and let self-heal re-render them (step 5).
- **No composition label → hand-applied.** Nothing re-renders them; skip the pause (step 1) and re-apply
  them yourself from the backup in step 5.

**On krateo-057 they are composition-rendered:** all 17 PullRequest CRs carry
`krateo.io/composition-kind: BuilderPublish` and are rendered by **17 separate `BuilderPublish`
compositions** (`composition.krateo.io/builderpublishes`, one per `publish-*`, at `v1-8-86`). So the pause
step applies, against all 17.

### Procedure

Run against the target cluster with an explicit `--kubeconfig`/`--context`; do not rely on the ambient
current-context.

**Precondition:** the platform must be able to **render and apply** — the umbrella `Synced=True` and the
cdc controllers healthy — because step 4 relies on the github-provider-kog composition's apply completing
to regenerate the CRD; a migration that deletes the CRD and then cannot re-apply leaves the kind absent.
Do **not** gate on the umbrella's overall `Ready`: a cluster that needs this migration has an umbrella
`Ready=False` *because of this very component* (the identifier refusal is the unhealthy child), and there
may be **other, unrelated** unhealthy children too. Assert the stack can apply (`Synced=True`), not that it
is fully `Ready`. (On krateo-057: the cluster is converged on the 2.13.43 / 0.3.471 roll, umbrella
`Synced=True`; the only unhealthy children are github-provider-kog itself and the unrelated
`krateo-audit-worm` chart defect — neither blocks this migration. The installer confirms 057 readiness.)

> **The destructive steps degenerate to no-ops on an empty population — there is no separate "empty
> cluster" variant.** Re-read the live population at pre-flight (do not carry over an earlier survey). If a
> cluster has **0** PullRequest CRs it has nothing to back up (step 0), no owning compositions to pause
> (step 1a), nothing to delete or reap (step 2), and no re-adoption to assert (step 6) — those steps find
> an empty set and pass. What always runs is the three-step spine: **pause the github-provider-kog
> composition (1b) → delete the RestDefinition (3) → unpause (4)**. krateo-demo ran exactly this reduced
> path (0 CRs, 0 BuilderPublish, 0 `deployments.github.krateo.io`, re-read live at pre-flight) and
> converged in ~2 min; krateo-057 ran all six with the 18-composition pause and 17 per-CR assertions. Walk
> the steps and let the empty ones no-op rather than deciding up front which to skip — the ordering, gates,
> and halt triggers are identical either way.

**0. Capture the baseline** (this is your re-adoption positive control):

```sh
kubectl get pullrequests.github.krateo.io -A -o yaml > pr-backup.yaml

# Per-CR control: namespace, name, head, base, number.
# NOTE: status.number is 1 on most CRs (1 on 15 of 17 on 057), so "the numbers all match" is nearly
# true by accident. spec.head is unique per CR and is the new identifier — assert on head, with number
# as a secondary check.
kubectl get pullrequests.github.krateo.io -A \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,HEAD:.spec.head,BASE:.spec.base,NUMBER:.status.number \
  | tee pr-baseline.txt
```

Confirm `<release>-pullrequest-controller` is `Ready 1/1` (it processes the finalizer releases and the
re-adoption reconciles), and that every CR carries only `composition.krateo.io/finalizer`:

```sh
kubectl get pullrequests.github.krateo.io -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: {.metadata.finalizers}{"\n"}{end}'
```

**1. Pause two sets of compositions.** Pausing stops `Observe` self-healing so deletions stay deleted.
You pause **both**:

- the **owning compositions of the CRs** (on 057: the 17 `BuilderPublish`) — so the PR CRs stay deleted
  and the CRD can reach zero instances;
- the **github-provider-kog composition itself** (`githubproviderkogs.composition.krateo.io/github-provider-kog`)
  — so it does **not** re-create the `pullrequest` RestDefinition *while* step 3 is tearing it down. This
  is what makes step 3→4 deterministic rather than a race: the RD is re-created only when you unpause this
  composition in step 4, by which point the old CRD is gone.

They unpause at **different** points: the github-provider-kog composition in step 4 (to regenerate the
CRD), the owning compositions in step 5 (to re-render the CRs). Pausing requires **both** annotations — a
missing or malformed `-time` (it must be RFC3339) makes `GetGracefullyPausedTime` fail **closed**, i.e.
silently *not* paused, with no error and no condition:

```sh
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# (a) every BuilderPublish that owns a PR CR (on 057, all of them). Derive names from the cluster and
# pipe through `while IFS= read -r` — do NOT write `for x in $names`: in zsh (the macOS default) an
# unquoted parameter expansion is NOT word-split, so the loop silently annotates nothing.
kubectl -n krateo-system get builderpublishes.composition.krateo.io -o name | while IFS= read -r obj; do
  kubectl -n krateo-system annotate "$obj" \
    krateo.io/gracefully-paused=true krateo.io/gracefully-paused-time="$NOW" --overwrite
done

# (b) the github-provider-kog composition itself:
kubectl -n krateo-system annotate githubproviderkogs.composition.krateo.io/github-provider-kog \
  krateo.io/gracefully-paused=true krateo.io/gracefully-paused-time="$NOW" --overwrite
```

The annotation keys are exactly `krateo.io/gracefully-paused` and `krateo.io/gracefully-paused-time`
(`meta.go:31`/`:36`); `-time` is "paused since", so `now` (a past value) is correct — it is never compared
against the clock, only parsed. The pause gates `Observe` upstream of both the helm-client construction and
the drift/self-heal (`composition.go:256` before `:518`), so a paused composition runs zero Helm operations
and cannot self-heal a deleted child — which is the whole point. No flag or version gate; handler-level, so
it holds for every composition kind on cdc ≥ 2.13.40.

**Verify the pause actually took before deleting anything — use the Event, NOT the `Ready` condition.**
A paused `Observe` returns at `composition.go:255-262` *before any status write*, so `Ready` is **never**
rewritten to `ReconcileGracefullyPaused` while the pause is in effect — it stays frozen at whatever it was
(a failing composition stays `False/Unavailable`; a healthy one stays `True/Available`). The condition is
therefore the wrong instrument in **both** directions and will wait forever (**core-provider#258** —
`Ready=…/ReconcileGracefullyPaused` is only written when a pause lands *mid-reconcile*, which is not the
steady-state case). The reliable, positive signal is the `ReconciliationGracefullyPaused`
**Event**, emitted by the paused code path on every resync (~60s):

```sh
# per composition — expect a recurring event, action=Observe, most recent within the last ~60s:
kubectl -n krateo-system get events \
  --field-selector reason=ReconciliationGracefullyPaused,involvedObject.name=<name> \
  --sort-by=.lastTimestamp | tail -3
```

**Do not proceed until a `ReconciliationGracefullyPaused` event (action `Observe`) has fired for every
composition you paused within the last 2 minutes** (two resync intervals) — an event that recent cannot be
stale. Corroborate cheaply: `helm history <release> -n krateo-system` shows no new revision, and
`status.managed` is unchanged (a paused `Observe` cannot self-heal drift). cdc ≥ 2.13.40 emits the event;
057 runs 2.13.43.

> **core-provider 2.13.44 fixes #258:** a paused composition now reports
> `Ready=True/ReconcileGracefullyPaused` even when it was `Unavailable` at pause time — the exact case that
> would have made the condition gate wait forever. So on cdc ≥ 2.13.44 the condition becomes a usable gate
> too. **Keep the Event as the primary gate regardless:** it is positive evidence emitted by the paused code
> path itself and cannot be stale, whereas a condition reflects the last write and can lag. Treat the
> condition as corroboration on ≥ 2.13.44, not a replacement.

> **Announce the maintenance window.** Pausing the existing compositions only stops re-rendering of
> *already-published* artifacts (on 057, all 17 represent completed publishes — `status.number` set, PR
> exists — so nothing in flight is affected). But while a BuilderPublish is paused, a **new** publish
> driven through the portal's Autopilot builders will **not render and will not fail loudly — it just
> sits.** 057 is the cluster the portal demos run against, so announce the window; do not assume nobody
> publishes during it. Record the `builderpublishes` count now (expected 17) to compare against at unpause.

**2. Strip finalizers, then delete each CR.** Stripping first makes the reap synchronous and independent
of the controller; with no delete verb, no external call fires either way.

Fully qualify the resource as `pullrequests.github.krateo.io` — the bare `pullrequest` prefix-matches
`pullrequestconfigurations` too, and `kubectl` then errors `you must specify only one resource`, failing
silently-ish across the whole loop (nothing patched or deleted):

```sh
kubectl get pullrequests.github.krateo.io -A \
  -o jsonpath='{range .items[*]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' \
  | while IFS= read -r ns name; do
      kubectl -n "$ns" patch pullrequests.github.krateo.io "$name" --type=merge -p '{"metadata":{"finalizers":null}}'
      kubectl -n "$ns" delete pullrequests.github.krateo.io "$name" --wait=false
    done

kubectl get pullrequests.github.krateo.io -A   # expect: no resources (and it stays empty — compositions paused)
```

> **Expected (not a failure):** each delete emits one controller log line at `ERROR` —
> `API action delete not found`, `action=delete`. For a kind with no delete verb this is the
> *intended* path (`return nil` on the next line; the runtime then releases the finalizer, no external
> call). You will see **one per CR** (17 on krateo-057). **Do not abort the migration on these.** Tell
> whoever is watching the logs beforehand — the message is accurate but delivered at a level that implies
> something is wrong.

**3. Delete the RestDefinition — NOT the CRD directly.** This is the subtle step. The live RD is pinned at
`identifiers: [number]` (its patch to `[head, base]` was refused), so `kubectl delete crd` alone would just
have oasgen regenerate the CRD *at `[number]` again* from the unchanged RD. You must remove the RD so it
can be re-created fresh at `[head, base]`. Deleting the RD runs oasgen's `deploy.Undeploy`
(`deploy.go:437`), which **drops the generated CRD** — and refuses if the CRD still has live instances,
which is why step 2 (reach zero instances) comes first. The github-provider-kog composition is paused
(step 1b), so nothing re-creates the RD during this.

```sh
kubectl -n krateo-system delete restdefinition github-provider-kog-pullrequest
```

**Wait until BOTH the RD and the CRD are gone** before step 4 — this is the gate that prevents the
re-create from racing the teardown:

```sh
kubectl -n krateo-system get restdefinition github-provider-kog-pullrequest   # expect: NotFound
kubectl get crd pullrequests.github.krateo.io                                 # expect: NotFound
```

> **`Undeploy` drops the CRD *before* the RD's own finalizer clears** (observed on both clusters). So for a
> few seconds you will see `RD=Terminating, CRD=NotFound` — that is the **normal** teardown order, not a
> stall. Wait for the RD to reach `NotFound` too before step 4; only a CRD still present after the RD is
> gone, or a CRD stuck `Terminating`, indicates a blocked Undeploy.

**4. Unpause the github-provider-kog composition — it re-creates the RD at `[head, base]`.** With both the
RD and CRD gone, remove the pause annotations from the `github-provider-kog` composition only. Its next
`Observe` re-applies the 0.6.0 chart: the `pullrequest` RD is created **fresh** at `[head, base]` (no
pre-existing CRD to conflict with, so no immutability refusal), oasgen generates the CRD at `[head, base]`,
and the **same apply adopts the two orphaned `gitref`/`repodeployment` RDs via `TakeOwnership`**
(`composition.go:689`) — no separate action for them.

```sh
kubectl -n krateo-system annotate githubproviderkogs.composition.krateo.io github-provider-kog \
  krateo.io/gracefully-paused- krateo.io/gracefully-paused-time- --overwrite

# Verify before step 5 — the new CRD must be served at [head,base]:
kubectl get restdefinition github-provider-kog-pullrequest -o jsonpath='{.spec.resource.identifiers}'  # -> ["head","base"]
kubectl get restdefinition github-provider-kog-pullrequest -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}'  # True
kubectl get crd pullrequests.github.krateo.io   # exists, served
# orphans adopted — Helm ownership is an ANNOTATION (meta.helm.sh/release-name), NOT a label, plus the
# app.kubernetes.io/managed-by=Helm label; ownerReferences stay empty (normal for these RDs):
kubectl get restdefinition github-provider-kog-gitref github-provider-kog-repodeployment \
  -o jsonpath='{range .items[*]}{.metadata.name}: ann={.metadata.annotations.meta\.helm\.sh/release-name} mgdby={.metadata.labels.app\.kubernetes\.io/managed-by}{"\n"}{end}'
```

**5. Unpause the owning CR compositions — self-heal re-renders the CRs.** Only after step 4 confirms the
CRD is served at `[head, base]` (otherwise the re-rendered CRs would hit a missing CRD). This is the 17
`BuilderPublish` on 057; the github-provider-kog composition was already unpaused in step 4. First
**re-count** them and compare to the number you paused — a new one created during the window must be
unpaused too, rather than silently left paused:

```sh
kubectl -n krateo-system get builderpublishes.composition.krateo.io --no-headers | wc -l   # expect the paused count (17 on 057)
```

Then remove both pause annotations. Each composition's next `Observe` (≤60s) re-renders its PullRequest CR
against the new CRD, and `findby` on `head`/`base` re-adopts the existing GitHub PR and repopulates
`status.number`. Do **not** hand-apply the backup for composition-rendered CRs — the compositions own the
spec. (For *hand-applied* CRs, instead apply the step-0 backup here, stripped of `resourceVersion`, `uid`,
`status`, and `finalizers`.)

```sh
# same zsh caveat as step 1 — derive from the cluster, read-loop (never `for x in $names`):
kubectl -n krateo-system get builderpublishes.composition.krateo.io -o name | while IFS= read -r obj; do
  kubectl -n krateo-system annotate "$obj" \
    krateo.io/gracefully-paused- krateo.io/gracefully-paused-time- --overwrite
done
```

The re-render **is** the self-heal: each composition's `Observe` detects the missing child and re-creates
it, logging `Composition drift detected and self-healed` with a non-zero `created` count
(`composition.go:518`). That log line — which names how many it re-created — is the positive confirmation
the PR CRs came back, better than counting objects yourself. Give it two resync ticks (~2 min) before
concluding.

**6. Verify re-adoption (the control).** Assert per-CR that `spec.head` round-trips and `status.number`
recovers to the baseline — not merely that the right *count* of CRs exists:

```sh
kubectl get pullrequests.github.krateo.io -A \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,HEAD:.spec.head,BASE:.spec.base,NUMBER:.status.number \
  | tee pr-after.txt
diff <(sort pr-baseline.txt) <(sort pr-after.txt)   # expect no differences once reconciled
```

**Success is your component's health, not the umbrella's.** Assert: the `pullrequest` RestDefinition is
`Ready/Synced` at `identifiers: [head, base]`, the CRD is served, and all 17 CRs re-adopted (head + number
match baseline). Do **not** wait for the umbrella to flip `Ready=True` — it may stay `Ready=False` for
unrelated reasons (on 057, the `krateo-audit-worm` chart defect is a separate unhealthy child). Check the
`githubproviderkogs/.../github-provider-kog` child specifically, not the umbrella rollup.

Expect a **one-cycle lag** between the component and the umbrella even on a clean run: on krateo-demo the
`github-provider-kog` composition went `True/Available` while the umbrella still reported `managed children
not healthy: githubproviderkogs/.../github-provider-kog`, and cleared on the next reconcile ~25s later.
Assert on the component reaching `Ready`, then let the umbrella catch up a cycle later — do not read that
transient as a failure.

### Stop conditions — halt and report rather than improvise

- **After step 1:** if any of the 18 compositions (17 BuilderPublish + github-provider-kog) has **not**
  emitted a `ReconciliationGracefullyPaused` event (action `Observe`) within the last 2 minutes, HALT — it
  is not paused and would self-heal a deleted child. Do **not** gate on the `Ready` condition; it never
  shows the pause (see the verify note above). Do not delete anything until all 18 show a fresh event.
- **During step 2:** the 17 `ERROR: API action delete not found` lines are expected. Any **other** error —
  above all any sign of an external GitHub DELETE firing (there must be none; no delete verb) — HALT.
- **After step 2:** if `kubectl get pullrequests.github.krateo.io -A` is not empty, HALT. Either a finalizer
  did not release or a composition was not actually paused and re-created a CR. Do not delete the RD.
- **After step 3:** both the RD and the CRD must reach `NotFound`. The CRD reaches it *first* (Undeploy
  drops the CRD, then the RD finalizer clears), so a brief `RD=Terminating, CRD=NotFound` is normal — wait
  it out. Only a CRD that lingers `Terminating`, or is still present after the RD is gone, means Undeploy is
  blocked (usually a straggler instance or a CRD finalizer) — HALT and investigate; do not proceed to step 4.
- **After step 4:** if within a few minutes the RD is not `Ready` at `identifiers: [head, base]` **and** the
  CRD is not served, HALT **before** unpausing the BuilderPublishes — do not re-render CRs against a
  missing or wrong-shaped CRD. Investigate the github-provider-kog composition's apply.
- **After steps 5–6:** if any CR's `spec.head` does not round-trip or `status.number` does not recover,
  that CR did not re-adopt — investigate the findby match for it. The GitHub PR is unaffected regardless.

### Safety / rollback

Nothing on GitHub is ever at risk: PullRequest has no delete verb, so no step deletes a GitHub PR. Before
step 2 (the first destructive step) nothing irreversible has run — if anything looks wrong, just unpause
everything and you are back to the start. Between step 2 and step 5 there are no PR CR objects, but GitHub
remains the source of truth; if step 4's regeneration does not converge, the PRs persist untouched and you
can retry the github-provider-kog apply, then unpause the BuilderPublishes once the CRD is served so
`findby` rebuilds each binding from head/base.

### Orphan-policy caution (not used by this migration, but read it before adapting the procedure)

This migration does **not** rely on `krateo.io/deletion-policy=orphan`; it strips finalizers explicitly,
and PullRequest's missing delete verb means no external delete fires regardless. If you ever adapt this
procedure for a kind that **does** have a delete verb and you choose to orphan its CRs rather than let the
finalizers fire: `krateo.io/deletion-policy=orphan` was non-deterministic before `unstructured-runtime`
v1.6.1 (shipped in oasgen-provider 0.41.0) — the worker could remove the finalizer and still fall through
to the external delete when its fetch beat the apiserver's reap. (krateo-057 runs oasgen/RDC 0.39.0, which
is *before* that fix — another reason this migration strips finalizers explicitly rather than orphaning.)
Even on 0.41.0+, a single extra finalizer changes the behaviour and nothing warns you. Strip finalizers
explicitly; do not rely on the annotation.
