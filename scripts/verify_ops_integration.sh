#!/bin/bash
"""
Test script for the unified Ops application integration.

This script tests all endpoints of the merged ops application:
- EventizerService: /ops/eventizer/*
- FactManager: /ops/facts/*
- StateService: /ops/state/*
- EnergyService: /ops/energy/*

Usage:
    ./scripts/test_ops_integration.sh [BASE_URL]
    
    BASE_URL defaults to http://localhost:8000
"""

set -e

# Configuration
BASE_URL="${1:-http://localhost:8000}"
OPS_URL="${BASE_URL}/ops"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0
TOTAL_TESTS=0

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

test_endpoint() {
    local method="$1"
    local endpoint="$2"
    local data="$3"
    local expected_status="${4:-200}"
    local description="$5"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    log_info "Testing: $description"
    log_info "  $method $endpoint"
    
    # Make the request
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$endpoint" || echo -e "\n000")
    elif [ "$method" = "POST" ]; then
        response=$(curl -s -w "\n%{http_code}" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$endpoint" || echo -e "\n000")
    else
        log_error "Unsupported method: $method"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
    
    # Extract status code and body
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)
    
    # Check status code
    if [ "$http_code" = "$expected_status" ]; then
        log_success "$description - Status: $http_code"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        
        # Pretty print JSON response if it's valid
        if echo "$response_body" | jq . >/dev/null 2>&1; then
            echo "$response_body" | jq . | head -20
            if [ $(echo "$response_body" | jq . | wc -l) -gt 20 ]; then
                echo "... (truncated)"
            fi
        else
            echo "Response: $response_body"
        fi
        echo
        return 0
    else
        log_error "$description - Expected: $expected_status, Got: $http_code"
        log_error "Response: $response_body"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo
        return 1
    fi
}

# Main test function
main() {
    log_info "Starting Ops Application Integration Tests"
    log_info "Base URL: $BASE_URL"
    log_info "Ops URL: $OPS_URL"
    echo
    
    # Test 1: Overall health check
    test_endpoint "GET" "$OPS_URL/health" "" 200 "Overall ops application health check"
    
    # Test 2: Eventizer health
    test_endpoint "GET" "$OPS_URL/eventizer/health" "" 200 "Eventizer service health check"
    
    # Test 3: Eventizer text processing
    test_endpoint "POST" "$OPS_URL/eventizer/process" \
        '{"text":"Emergency alert: Fire detected in building A","domain":"hotel_ops","language":"en"}' \
        200 "Eventizer text processing"
    
    # Test 4: Eventizer with HVAC text
    test_endpoint "POST" "$OPS_URL/eventizer/process" \
        '{"text":"HVAC temperature in room 1510 is 85°F, urgent maintenance required","domain":"hotel_ops"}' \
        200 "Eventizer HVAC text processing"
    
    # Test 5: Eventizer with VIP text
    test_endpoint "POST" "$OPS_URL/eventizer/process" \
        '{"text":"VIP guest John Doe requests room upgrade to presidential suite","domain":"hotel_ops"}' \
        200 "Eventizer VIP text processing"
    
    # Test 6: Facts health
    test_endpoint "GET" "$OPS_URL/facts/health" "" 200 "Facts service health check"
    
    # Test 7: Create fact
    test_endpoint "POST" "$OPS_URL/facts/create" \
        '{"text":"Room 101 temperature is 72°F","tags":["temperature","room"],"namespace":"hotel_ops"}' \
        200 "Create basic fact"
    
    # Test 8: Query facts
    test_endpoint "POST" "$OPS_URL/facts/query" \
        '{"text_query":"temperature","namespace":"hotel_ops"}' \
        200 "Query facts by text"
    
    # Test 9: State health
    test_endpoint "GET" "$OPS_URL/state/health" "" 200 "State service health check"
    
    # Test 10: Get unified state
    test_endpoint "GET" "$OPS_URL/state" "" 200 "Get unified system state"
    
    # Test 11: Get state with key
    test_endpoint "GET" "$OPS_URL/state?key=unified" "" 200 "Get unified state with explicit key"
    
    # Test 12: Get agent state (placeholder)
    test_endpoint "GET" "$OPS_URL/state/agent/test-agent-123" "" 200 "Get agent-specific state"
    
    # Test 13: Energy health
    test_endpoint "GET" "$OPS_URL/energy/health" "" 200 "Energy service health check"
    
    # Test 14: Energy summary
    test_endpoint "GET" "$OPS_URL/energy/summary" "" 200 "Get energy summary"
    
    # Test 15: Energy metrics
    test_endpoint "GET" "$OPS_URL/energy/metrics" "" 200 "Get energy metrics (default window)"
    
    # Test 16: Energy metrics with window
    test_endpoint "GET" "$OPS_URL/energy/metrics?window=24h" "" 200 "Get energy metrics (24h window)"
    
    # Test 17: Energy metrics with custom window
    test_endpoint "GET" "$OPS_URL/energy/metrics?window=1h" "" 200 "Get energy metrics (1h window)"
    
    # Summary
    echo
    log_info "=== Test Summary ==="
    log_info "Total Tests: $TOTAL_TESTS"
    log_success "Passed: $TESTS_PASSED"
    if [ $TESTS_FAILED -gt 0 ]; then
        log_error "Failed: $TESTS_FAILED"
    else
        log_success "Failed: $TESTS_FAILED"
    fi
    
    # Calculate success rate
    if [ $TOTAL_TESTS -gt 0 ]; then
        success_rate=$((TESTS_PASSED * 100 / TOTAL_TESTS))
        log_info "Success Rate: ${success_rate}%"
        
        if [ $TESTS_FAILED -eq 0 ]; then
            log_success "🎉 All tests passed!"
            exit 0
        else
            log_error "❌ Some tests failed"
            exit 1
        fi
    else
        log_error "No tests were run"
        exit 1
    fi
}

# Check dependencies
check_dependencies() {
    log_info "Checking dependencies..."
    
    if ! command -v curl &> /dev/null; then
        log_error "curl is required but not installed"
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        log_warning "jq is not installed - JSON responses will not be pretty-printed"
    fi
    
    log_success "Dependencies check passed"
    echo
}

# Run the tests
check_dependencies
main "$@"
