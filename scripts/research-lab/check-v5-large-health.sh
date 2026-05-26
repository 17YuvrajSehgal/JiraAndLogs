#!/bin/bash
#
# check-v5-large-health.sh — run all 3 critical health checks on the GCP
# VM that's collecting v5-large. Designed to be cheap (~10s) so it can run
# daily during the 4-5 day collection.
#
# Verified GREEN on v5-large 2026-05-26 — captures the same checks that
# confirmed the v5-large collection was producing valid raw data.
#
# Usage (on the GCP VM):
#   bash scripts/research-lab/check-v5-large-health.sh
#
# Exit code:
#   0 — all checks passed
#   1 — at least one check failed (output explains which)
#
# Documentation: docs/results-v5-quick.md §6d + todo-v5available.md

set -e
set -o pipefail

KUBECTL=${KUBECTL:-kubectl}
NAMESPACE_APP=${NAMESPACE_APP:-online-boutique-research}
NAMESPACE_OBS=${NAMESPACE_OBS:-observability}
PROM_PF_PORT=${PROM_PF_PORT:-19099}

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass=0
fail=0
warn=0

pass()  { echo -e "  ${GREEN}PASS${NC} $1"; pass=$((pass+1)); }
fail()  { echo -e "  ${RED}FAIL${NC} $1"; fail=$((fail+1)); }
warn()  { echo -e "  ${YELLOW}WARN${NC} $1"; warn=$((warn+1)); }

echo "========================================================="
echo "  v5-large collection health check ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo "========================================================="

# ---------------------------------------------------------------------------
# Check 1: M0–M5 instrumented images deployed (NOT upstream v0.10.5)
# ---------------------------------------------------------------------------
echo ""
echo "=== Check 1: deployed images ==="
deploys=$("${KUBECTL}" -n "${NAMESPACE_APP}" get deploy \
  -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image}{"\n"}{end}' \
  2>/dev/null)
if [ -z "${deploys}" ]; then
  fail "could not query deployments in namespace ${NAMESPACE_APP}"
else
  bad_count=0
  while IFS= read -r line; do
    name="${line%%=*}"
    image="${line#*=}"
    # loadgenerator and redis-cart intentionally use upstream
    if [[ "${name}" == "loadgenerator" || "${name}" == "redis-cart" ]]; then
      continue
    fi
    if [[ "${image}" == *"v5.0.0-otel-pilot"* ]]; then
      pass "${name}: ${image}"
    else
      fail "${name}: ${image} (expected v5.0.0-otel-pilot*)"
      bad_count=$((bad_count+1))
    fi
  done <<< "${deploys}"
  if [ "${bad_count}" -gt 0 ]; then
    echo ""
    echo "  ${bad_count} services NOT on M0–M5 image. Those services are emitting"
    echo "  zero new telemetry. Re-apply kustomize overlay and restart their pods."
  fi
fi

# ---------------------------------------------------------------------------
# Check 2: M0–M5 metrics flowing into Prometheus
# ---------------------------------------------------------------------------
echo ""
echo "=== Check 2: M0–M5 metrics in Prometheus ==="
PROM_POD=$("${KUBECTL}" -n "${NAMESPACE_OBS}" get pod \
  -l app.kubernetes.io/name=prometheus \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "${PROM_POD}" ]; then
  fail "could not find Prometheus pod in namespace ${NAMESPACE_OBS}"
else
  # Set up port-forward (background, kill on exit)
  "${KUBECTL}" -n "${NAMESPACE_OBS}" port-forward "${PROM_POD}" \
    "${PROM_PF_PORT}":9090 >/dev/null 2>&1 &
  PF_PID=$!
  trap "kill ${PF_PID} 2>/dev/null || true" EXIT
  sleep 3

  metrics=(payments_total cart_operations_total orders_placed_total
           recommendations_served_total catalog_lookups_total
           rpc_server_requests_total rpc_server_duration_seconds_count
           http_server_request_duration_seconds_count
           go_goroutines
           process_runtime_dotnet_gc_collections_count_total)
  present_count=0
  for m in "${metrics[@]}"; do
    v=$(curl -s --max-time 10 \
      "http://127.0.0.1:${PROM_PF_PORT}/api/v1/query?query=count(${m})" \
      2>/dev/null \
      | jq -r '.data.result[0].value[1] // "ABSENT"' 2>/dev/null \
      || echo "ERR")
    if [[ "${v}" == "ABSENT" || "${v}" == "ERR" || -z "${v}" ]]; then
      warn "${m}: not flowing"
    else
      pass "${m}: ${v} series"
      present_count=$((present_count+1))
    fi
  done
  echo ""
  if [ "${present_count}" -ge 8 ]; then
    echo "  ${present_count}/10 metrics flowing — healthy (≥8 required)"
  else
    fail "only ${present_count}/10 metrics flowing — investigate ServiceMonitor + scrape config"
  fi
fi

# ---------------------------------------------------------------------------
# Check 3: Prometheus retention covers collection + post-process window
# ---------------------------------------------------------------------------
echo ""
echo "=== Check 3: Prometheus retention ==="
retention=$("${KUBECTL}" -n "${NAMESPACE_OBS}" get prometheus -o yaml 2>/dev/null \
  | grep -E "^\s+retention:" | head -1 | awk '{print $2}')
if [ -z "${retention}" ]; then
  warn "could not parse Prometheus retention setting; check 'kubectl get prometheus -o yaml | grep retention'"
else
  # Parse "Nd" → integer days
  if [[ "${retention}" =~ ^([0-9]+)d$ ]]; then
    days="${BASH_REMATCH[1]}"
    if [ "${days}" -ge 15 ]; then
      pass "retention=${retention} (>=15d — safe for 5d collection + 10d post-process)"
    elif [ "${days}" -ge 10 ]; then
      warn "retention=${retention} — tight; commit to running supplement script within ${days} days of collection ending"
    else
      fail "retention=${retention} — too short for safe post-process"
    fi
  else
    warn "retention=${retention} — non-standard format; verify manually"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================================="
echo "  Summary: ${pass} pass, ${warn} warn, ${fail} fail"
echo "========================================================="
if [ "${fail}" -gt 0 ]; then
  echo "${RED}One or more checks failed.${NC} See output above. The collection may"
  echo "be producing incomplete/incorrect raw data — investigate before"
  echo "letting the run continue further."
  exit 1
elif [ "${warn}" -gt 0 ]; then
  echo "${YELLOW}Collection is healthy with warnings.${NC} See output above. Likely"
  echo "OK to continue but address the warnings opportunistically."
  exit 0
else
  echo "${GREEN}All checks PASS.${NC} v5-large collection is producing valid raw data."
  echo "Every fix from the v5-quick session will apply via post-collection"
  echo "re-derivation. See todo-v5available.md §2 for the workflow."
  exit 0
fi
