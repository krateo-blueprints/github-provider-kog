// Command github-provider-kog-plugin is a tiny rest-dynamic-controller plugin: a web
// service that normalizes GitHub REST API inconsistencies the pure OpenAPI mapping
// cannot express, so the generated CRs settle to Ready instead of looping create->422.
//
// It is invoked by the rest-dynamic-controller ONLY for the verbs whose RestDefinition
// path points at a plugin route (via a per-operation `servers` override in the OAS →
// this service's ClusterIP DNS); every other verb still goes straight to GitHub.
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", ok)
	mux.HandleFunc("GET /readyz", ok)
	// GitRef observe (get-after-create) — fixes the git/ref-vs-git/refs path asymmetry.
	mux.HandleFunc("GET /gitref/{owner}/{repo}/{ref...}", logReq(getGitRef))
	// RepoContent create/update + get (same path shape as GitHub, reached via the OAS
	// per-operation servers override) — flattens GitHub's nested content{} response to the
	// root so the controller's same-level field comparison succeeds (no spurious re-PUT).
	mux.HandleFunc("PUT /repos/{owner}/{repo}/contents/{path...}", logReq(putRepoContent))
	mux.HandleFunc("GET /repos/{owner}/{repo}/contents/{path...}", logReq(getRepoContent))
	// PullRequest observe (get-after-create) — flattens GitHub's head/base OBJECTS to their
	// ref STRINGS so the controller's spec(string)-vs-response(object) compare stops looping.
	mux.HandleFunc("GET /repos/{owner}/{repo}/pulls/{number}", logReq(getPullRequest))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("github-provider-kog-plugin listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}

func ok(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

// logReq logs the method + path + query of each proxied request (health checks excluded).
// Cheap and permanently useful: it makes the controller's observe/create URLs (and any
// missing query params) visible in `kubectl logs deploy/...-plugin` for diagnosis.
func logReq(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if q := r.URL.RawQuery; q != "" {
			log.Printf("%s %s?%s", r.Method, r.URL.Path, q)
		} else {
			log.Printf("%s %s", r.Method, r.URL.Path)
		}
		next(w, r)
	}
}

// proxy performs the upstream GitHub request, forwarding the Authorization header, and
// returns the response status + body (never throws — errors become a 5xx to the caller).
func proxy(w http.ResponseWriter, r *http.Request, method, url string, body []byte) (int, []byte, bool) {
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, url, rdr)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return 0, nil, false
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if auth := r.Header.Get("Authorization"); auth != "" {
		req.Header.Set("Authorization", auth)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return 0, nil, false
	}
	defer func() { _ = resp.Body.Close() }()
	out, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, out, true
}

func writeJSON(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// getGitRef fixes GitHub's git-ref path asymmetry. Create/update/delete use
// /repos/{owner}/{repo}/git/refs[/{ref}] with the FULL "refs/heads/x", but GET uses
// /repos/{owner}/{repo}/git/ref/{ref} with the ref WITHOUT the "refs/" prefix. The
// controller observes (get-after-create) through this route, so a just-created ref is
// actually FOUND — instead of a 404 that makes the controller re-issue the create and
// hit "422 Reference already exists" forever (the CR never goes Ready). GitHub's get-ref
// body already exposes {ref, node_id, url, object} at the root (ref carries the full
// "refs/..." matching the CR identifier), so it is passed through verbatim.
func getGitRef(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	ref := strings.TrimPrefix(r.PathValue("ref"), "refs/") // "refs/heads/x" -> "heads/x"
	status, body, ok := proxy(w, r, http.MethodGet, "https://api.github.com/repos/"+owner+"/"+repo+"/git/ref/"+ref, nil)
	if !ok {
		return
	}
	writeJSON(w, status, body)
}

// flattenPRRefs lifts a GitHub PR's head/base branch names up to the response ROOT as strings.
// GitHub's get-PR returns head/base as OBJECTS ({ref, sha, repo, ...}); the CR's spec.head /
// spec.base are the plain branch-name STRINGS the create body carried. The controller's
// spec-vs-response compare (compareExisting) then hits "types differ" (string vs map) at head,
// decides the CR needs an update, and issues a PATCH — which 422s on an already-merged/closed PR
// (and is spurious even on an open one) — so the CR loops "Creating" forever even though the pull
// request was created (and possibly merged) successfully. Replacing head/base with head.ref /
// base.ref makes the compare string-vs-string → equal → the CR settles Ready with no PATCH.
func flattenPRRefs(body []byte) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	for _, k := range []string{"head", "base"} {
		if obj, isObj := m[k].(map[string]any); isObj {
			if ref, ok := obj["ref"].(string); ok {
				m[k] = ref
			}
		}
	}
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// getPullRequest proxies the get-PR GET and flattens head/base objects → ref strings (see
// flattenPRRefs) so the controller's observe compare settles Ready instead of looping update->422.
// Only the GET (observe) is routed here; create (POST) and update (PATCH) still go to GitHub.
func getPullRequest(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	number := r.PathValue("number")
	status, body, ok := proxy(w, r, http.MethodGet, "https://api.github.com/repos/"+owner+"/"+repo+"/pulls/"+number, nil)
	if !ok {
		return
	}
	if status >= 200 && status < 300 {
		body = flattenPRRefs(body)
	}
	writeJSON(w, status, body)
}

// flattenContent lifts the fields the controller compares (path, sha, html_url, name,
// size, type) out of GitHub's nested `content` object up to the response ROOT, so the
// rest-dynamic-controller's same-level comparison of the CR against the response body
// succeeds and it does not re-issue a PUT (which would 422 without a sha). A body without
// a `content` object (e.g. a single-file GET, already root-level) is returned unchanged.
func flattenContent(body []byte) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	content, isObj := m["content"].(map[string]any)
	if !isObj {
		return body
	}
	for _, k := range []string{"path", "sha", "html_url", "name", "size", "type"} {
		if v, ok := content[k]; ok {
			m[k] = v
		}
	}
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// normalizeContent rewrites the response's base64 `content` into canonical, newline-free
// StdEncoding base64 so it byte-matches the CR's spec.content (which the frontend/builder emits
// via standard base64, no line wrapping). GitHub's get-content returns the file `content` as
// base64 with embedded RFC-2045 soft newlines ("\n" every 60 chars); leaving them in makes a
// byte-IDENTICAL file string-DIFFER from spec.content, so the controller's spec-vs-response
// compare (compareExisting → compareAny on the string leaf) flags drift and loops "update"
// forever instead of settling Ready.
//
// The earlier fix DROPPED content/encoding to break that loop — but compareExisting skips any
// spec key the response omits (`rmValue, ok := rm[key]; if !ok { continue }`), so a stripped
// `content` made observe CONTENT-BLIND: a genuine content change was never detected and
// RepoContent could not UPDATE a file in place (only create). Normalizing instead of stripping
// keeps observe able to detect REAL drift — spec.content != normalized-response.content → the
// controller issues the update PUT, which putRepoContent auto-shas — while the newline-only
// difference of an unchanged file no longer false-flags. `encoding` is still dropped (the CR
// spec carries no `encoding` field, so it is never on the compare's spec side anyway).
func normalizeContent(body []byte) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	delete(m, "encoding")
	raw, ok := m["content"].(string)
	if !ok {
		return body // no content (e.g. a create/PUT response already flattened) — nothing to do
	}
	// Strip RFC-2045 soft line breaks, then re-encode canonically so padding/wrapping match
	// spec.content regardless of how GitHub wrapped it.
	compact := strings.NewReplacer("\n", "", "\r", "").Replace(raw)
	if decoded, err := base64.StdEncoding.DecodeString(compact); err == nil {
		m["content"] = base64.StdEncoding.EncodeToString(decoded)
	} else {
		m["content"] = compact // not decodable as StdEncoding — at least drop the newlines
	}
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// jsonStringField returns body[key] iff it is a non-empty JSON string, else "".
func jsonStringField(body []byte, key string) string {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return ""
	}
	if s, ok := m[key].(string); ok {
		return s
	}
	return ""
}

// withJSONField returns body with key set to val (best-effort — original bytes on any error).
func withJSONField(body []byte, key, val string) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	m[key] = val
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// currentFileSha best-effort GETs a file's current blob sha on `branch` (forwarding the caller's
// Authorization). Returns "" on any failure, so the caller leaves the original response intact.
func currentFileSha(r *http.Request, owner, repo, path, branch string) string {
	target := "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path
	if branch != "" {
		v := url.Values{}
		v.Set("ref", branch)
		target += "?" + v.Encode()
	}
	req, err := http.NewRequest(http.MethodGet, target, nil)
	if err != nil {
		return ""
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	if auth := r.Header.Get("Authorization"); auth != "" {
		req.Header.Set("Authorization", auth)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return ""
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ""
	}
	b, _ := io.ReadAll(resp.Body)
	return jsonStringField(b, "sha")
}

// putRepoContent proxies the create-or-update-file PUT to GitHub, FLATTENS the nested content{}
// response, and makes the write IDEMPOTENT create-OR-update: GitHub's PUT /contents 422s if the
// file already exists and the body omits `sha`. When that happens (and the CR did not supply a
// sha), fetch the file's current sha on the target branch and retry the PUT once — so RepoContent
// can UPDATE an existing file (e.g. append a nav entry, re-publish a changed chart file), not only
// create it. A CR that DOES carry a sha, or a genuine other-422, is passed through unchanged.
func putRepoContent(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	path := r.PathValue("path")
	reqBody, _ := io.ReadAll(r.Body)
	target := "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path
	status, body, ok := proxy(w, r, http.MethodPut, target, reqBody)
	if !ok {
		return
	}
	if status == http.StatusUnprocessableEntity && jsonStringField(reqBody, "sha") == "" {
		if sha := currentFileSha(r, owner, repo, path, jsonStringField(reqBody, "branch")); sha != "" {
			status, body, ok = proxy(w, r, http.MethodPut, target, withJSONField(reqBody, "sha", sha))
			if !ok {
				return
			}
		}
	}
	if status >= 200 && status < 300 {
		body = flattenContent(body)
	}
	writeJSON(w, status, body)
}

// getRepoContent proxies the get-file GET, reading from the CR's BRANCH. GitHub's contents
// GET defaults to the repo's default branch, so a file created on a builder/* branch 404s
// there and the controller never observes it (stuck "Creating"). The OAS get operation's
// query param is named `branch` to match the CR's spec.branch (the controller only fills a
// query param whose name matches a spec field — support.go processFields); forward it to
// GitHub as `?ref`. `?ref` is also accepted as a fallback. The base64 `content` is then
// CANONICALIZED (see normalizeContent) so observe detects real drift yet never false-loops
// on GitHub's newline-wrapped base64.
func getRepoContent(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	path := r.PathValue("path")
	q := r.URL.Query()
	branch := q.Get("branch")
	if branch == "" {
		branch = q.Get("ref")
	}
	// The controller url-encodes query values when it builds the observe request, and the
	// value arrives percent-encoded MORE THAN ONCE (a "builder/x" branch reaches us as
	// "builder%252Fx"). Fully decode it — loop until stable — so GitHub gets a clean ref;
	// otherwise GitHub 404s on a literally-%-named ref and the CR loops "Creating". Use
	// PathUnescape (not QueryUnescape) so a '+' in a ref name is not turned into a space.
	for {
		dec, err := url.PathUnescape(branch)
		if err != nil || dec == branch {
			break
		}
		branch = dec
	}
	target := "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path
	if branch != "" {
		// url.Values.Encode re-encodes the fully-decoded ref exactly once (slash -> %2F),
		// which GitHub decodes back to the real branch name.
		v := url.Values{}
		v.Set("ref", branch)
		target += "?" + v.Encode()
	}
	status, body, ok := proxy(w, r, http.MethodGet, target, nil)
	if !ok {
		return
	}
	if status >= 200 && status < 300 {
		body = flattenContent(body)   // no-op for single-file GET (already root-level)
		body = normalizeContent(body) // canonicalize content base64 → accurate drift detection, no newline false diff
	}
	writeJSON(w, status, body)
}
