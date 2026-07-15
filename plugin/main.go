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

// stripUncomparable removes response fields the controller cannot reliably diff against the
// CR spec. GitHub's get-content returns the file `content` as base64 with embedded RFC-2045
// newlines ("\n" every 60 chars); the CR's spec.content is newline-free base64, so a
// byte-IDENTICAL file still string-differs — and the controller's spec-vs-response compare
// (compareExisting, keys present in BOTH) would then flag drift and loop "update" forever
// instead of settling Ready. `path` (the identifier) + the additionalStatusFields (sha,
// html_url) are enough to observe identity and status, so `content`/`encoding` are dropped.
func stripUncomparable(body []byte) []byte {
	var m map[string]any
	if json.Unmarshal(body, &m) != nil {
		return body
	}
	delete(m, "content")
	delete(m, "encoding")
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// putRepoContent proxies the create-or-update-file PUT to GitHub and FLATTENS the nested
// content{} response so the controller can observe path/sha at the root.
func putRepoContent(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	path := r.PathValue("path")
	reqBody, _ := io.ReadAll(r.Body)
	status, body, ok := proxy(w, r, http.MethodPut, "https://api.github.com/repos/"+owner+"/"+repo+"/contents/"+path, reqBody)
	if !ok {
		return
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
// GitHub as `?ref`. `?ref` is also accepted as a fallback. The base64 `content`/`encoding`
// are then stripped (see stripUncomparable) so observe settles Ready instead of looping.
func getRepoContent(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	path := r.PathValue("path")
	q := r.URL.Query()
	branch := q.Get("branch")
	if branch == "" {
		branch = q.Get("ref")
	}
	target := "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path
	if branch != "" {
		target += "?ref=" + url.QueryEscape(branch)
	}
	status, body, ok := proxy(w, r, http.MethodGet, target, nil)
	if !ok {
		return
	}
	if status >= 200 && status < 300 {
		body = flattenContent(body)    // no-op for single-file GET (already root-level)
		body = stripUncomparable(body) // drop content/encoding → no base64-newline false diff
	}
	writeJSON(w, status, body)
}
