#!/usr/bin/env python3
"""
Simple SeedCore Database Pooling & Feature Test Script

This script provides lightweight testing of the SeedCore system with focus on:
- Database connection pooling (PostgreSQL via PgBouncer, MySQL, Neo4j)
- Database connection health and staleness monitoring
- API endpoints and health checks
- Energy system monitoring
- Ray cluster functionality
- Monitoring services (Prometheus, Grafana)
- Connection pool statistics and validation

Uses only subprocess and requests libraries (no docker Python library required).
"""

import json
import subprocess
import sys
import time
from typing import Dict, Any
import requests
from datetime import datetime

class SimpleSeedCoreTester:
    def __init__(self):
        self.base_url = "http://localhost:8002"
        self.results = {}
        
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
    def test_docker_services(self) -> Dict[str, Any]:
        """Test all Docker services are running and healthy"""
        self.log("Testing Docker services...")
        results = {}
        
        expected_services = [
            "seedcore-postgres", "seedcore-mysql", "seedcore-neo4j",
            "seedcore-pgbouncer", "seedcore-api", "seedcore-ray-head",
            "seedcore-prometheus", "seedcore-grafana"
        ]
        
        for service in expected_services:
            try:
                cmd = ["docker", "ps", "--filter", f"name={service}", "--format", "{{.Status}}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0 and result.stdout.strip():
                    status_line = result.stdout.strip()
                    is_running = "Up" in status_line
                    is_healthy = "healthy" in status_line.lower()
                    
                    results[service] = {
                        "status": status_line,
                        "running": is_running,
                        "healthy": is_healthy
                    }
                    self.log(f"  {service}: {'✅' if is_running and is_healthy else '⚠️'} {status_line}")
                else:
                    results[service] = {
                        "status": "not found",
                        "running": False,
                        "healthy": False
                    }
                    self.log(f"  {service}: ❌ not found", "ERROR")
                    
            except Exception as e:
                results[service] = {
                    "status": "error",
                    "running": False,
                    "healthy": False,
                    "error": str(e)
                }
                self.log(f"  {service}: ❌ ERROR - {e}", "ERROR")
                
        return results
    
    def test_database_connections(self) -> Dict[str, Any]:
        """Test database connections and pooling"""
        self.log("Testing database connections...")
        results = {}
        
        # Test PostgreSQL via PgBouncer
        try:
            cmd = [
                "docker", "exec", "-e", "PGPASSWORD=password", 
                "seedcore-pgbouncer", "psql", "-h", "localhost", "-p", "6432", 
                "-U", "postgres", "-d", "postgres", "-c", "SELECT 1 as test;"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            results["postgres_pgbouncer"] = {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None
            }
            self.log(f"  PostgreSQL via PgBouncer: {'✅' if result.returncode == 0 else '❌'}")
        except Exception as e:
            results["postgres_pgbouncer"] = {"success": False, "error": str(e)}
            self.log(f"  PostgreSQL via PgBouncer: ❌ - {e}", "ERROR")
        
        # Test MySQL
        try:
            cmd = ["docker", "exec", "seedcore-mysql", "mysql", "-u", "seedcore", "-ppassword", "-e", "SELECT 1 as test;"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            results["mysql"] = {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None
            }
            self.log(f"  MySQL: {'✅' if result.returncode == 0 else '❌'}")
        except Exception as e:
            results["mysql"] = {"success": False, "error": str(e)}
            self.log(f"  MySQL: ❌ - {e}", "ERROR")
        
        # Test Neo4j
        try:
            response = requests.get("http://localhost:7474/browser/", timeout=10)
            results["neo4j"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code
            }
            self.log(f"  Neo4j: {'✅' if response.status_code == 200 else '❌'}")
        except Exception as e:
            results["neo4j"] = {"success": False, "error": str(e)}
            self.log(f"  Neo4j: ❌ - {e}", "ERROR")
            
        return results
    
    def test_api_endpoints(self) -> Dict[str, Any]:
        """Test API endpoints"""
        self.log("Testing API endpoints...")
        results = {}
        
        endpoints = [
            ("health", "/health"),
            ("system_status", "/system/status"),
            ("organism_status", "/organism/status"),
            ("tier0_summary", "/tier0/summary"),
            ("ray_status", "/ray/status")
        ]
        
        for name, endpoint in endpoints:
            try:
                response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                results[name] = {
                    "success": response.status_code == 200,
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None
                }
                self.log(f"  {name}: {'✅' if response.status_code == 200 else '❌'}")
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}
                self.log(f"  {name}: ❌ - {e}", "ERROR")
            
        return results
    
    def test_energy_system(self) -> Dict[str, Any]:
        """Test energy system endpoints"""
        self.log("Testing energy system...")
        results = {}
        
        energy_endpoints = [
            ("gradient", "GET"),
            ("monitor", "GET"), 
            ("calibrate", "GET"),
            ("logs", "GET")
        ]
        
        for endpoint, method in energy_endpoints:
            try:
                url = f"{self.base_url}/energy/{endpoint}"
                # Use longer timeout for energy endpoints due to heavy computation
                timeout = 30 if endpoint in ["gradient", "monitor", "calibrate"] else 10
                if method == "GET":
                    response = requests.get(url, timeout=timeout)
                else:
                    response = requests.post(url, timeout=timeout)
                
                results[f"energy_{endpoint}"] = {
                    "success": response.status_code == 200,
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None
                }
                self.log(f"  Energy {endpoint}: {'✅' if response.status_code == 200 else '❌'}")
            except Exception as e:
                results[f"energy_{endpoint}"] = {"success": False, "error": str(e)}
                self.log(f"  Energy {endpoint}: ❌ - {e}", "ERROR")
        
        # Test energy log POST endpoint
        try:
            response = requests.post(
                f"{self.base_url}/energy/log",
                json={"event": "test", "timestamp": time.time()},
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            results["energy_log_post"] = {
                "success": response.status_code in [200, 201],
                "status_code": response.status_code,
                "data": response.json() if response.status_code in [200, 201] else None
            }
            self.log(f"  Energy log POST: {'✅' if response.status_code in [200, 201] else '❌'}")
        except Exception as e:
            results["energy_log_post"] = {"success": False, "error": str(e)}
            self.log(f"  Energy log POST: ❌ - {e}", "ERROR")
            
        return results
    
    def test_ray_cluster(self) -> Dict[str, Any]:
        """Test Ray cluster functionality"""
        self.log("Testing Ray cluster...")
        results = {}
        
        # Test Ray Dashboard
        try:
            response = requests.get("http://localhost:8265", timeout=10)
            results["ray_dashboard"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code
            }
            self.log(f"  Ray Dashboard: {'✅' if response.status_code == 200 else '❌'}")
        except Exception as e:
            results["ray_dashboard"] = {"success": False, "error": str(e)}
            self.log(f"  Ray Dashboard: ❌ - {e}", "ERROR")
            
        return results
    
    def test_monitoring_services(self) -> Dict[str, Any]:
        """Test monitoring services"""
        self.log("Testing monitoring services...")
        results = {}
        
        # Test Prometheus
        try:
            response = requests.get("http://localhost:9090/api/v1/status/config", timeout=10)
            results["prometheus"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code
            }
            self.log(f"  Prometheus: {'✅' if response.status_code == 200 else '❌'}")
        except Exception as e:
            results["prometheus"] = {"success": False, "error": str(e)}
            self.log(f"  Prometheus: ❌ - {e}", "ERROR")
        
        # Test Grafana
        try:
            response = requests.get("http://localhost:3000/api/health", timeout=10)
            results["grafana"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "data": response.json() if response.status_code == 200 else None
            }
            self.log(f"  Grafana: {'✅' if response.status_code == 200 else '❌'}")
        except Exception as e:
            results["grafana"] = {"success": False, "error": str(e)}
            self.log(f"  Grafana: ❌ - {e}", "ERROR")
        
        # Test API metrics
        try:
            response = requests.get(f"{self.base_url}/metrics", timeout=10)
            results["api_metrics"] = {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "has_prometheus_format": "python_gc_objects_collected_total" in response.text
            }
            self.log(f"  API Metrics: {'✅' if response.status_code == 200 else '❌'}")
        except Exception as e:
            results["api_metrics"] = {"success": False, "error": str(e)}
            self.log(f"  API Metrics: ❌ - {e}", "ERROR")
            
        return results
    
    def test_database_pooling(self) -> Dict[str, Any]:
        """Test database connection pooling"""
        self.log("Testing database connection pooling...")
        results = {}
        
        # Test health endpoint for mw_staleness
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            if response.status_code == 200:
                data = response.json()
                mw_staleness = data.get("mw_staleness", None)
                results["pooling_health"] = {
                    "success": True,
                    "mw_staleness": mw_staleness,
                    "pooling_healthy": mw_staleness == 0.0
                }
                self.log(f"  Database pooling: {'✅' if mw_staleness == 0.0 else '❌'} (staleness: {mw_staleness})")
            else:
                results["pooling_health"] = {"success": False, "status_code": response.status_code}
                self.log(f"  Database pooling: ❌ - Status {response.status_code}", "ERROR")
        except Exception as e:
            results["pooling_health"] = {"success": False, "error": str(e)}
            self.log(f"  Database pooling: ❌ - {e}", "ERROR")
            
        return results
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all tests and return comprehensive results"""
        self.log("Starting comprehensive SeedCore feature testing...")
        
        all_results = {
            "timestamp": datetime.now().isoformat(),
            "docker_services": self.test_docker_services(),
            "database_connections": self.test_database_connections(),
            "api_endpoints": self.test_api_endpoints(),
            "energy_system": self.test_energy_system(),
            "ray_cluster": self.test_ray_cluster(),
            "monitoring_services": self.test_monitoring_services(),
            "database_pooling": self.test_database_pooling()
        }
        
        # Calculate summary statistics
        total_tests = 0
        passed_tests = 0
        
        for category, tests in all_results.items():
            if category == "timestamp":
                continue
            for test_name, result in tests.items():
                total_tests += 1
                if result.get("success", False) or result.get("running", False):
                    passed_tests += 1
        
        all_results["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0
        }
        
        return all_results
    
    def print_summary(self, results: Dict[str, Any]):
        """Print a summary of test results"""
        summary = results.get("summary", {})
        
        print("\n" + "="*60)
        print("SEEDCORE FEATURE TEST SUMMARY")
        print("="*60)
        print(f"Timestamp: {results.get('timestamp', 'Unknown')}")
        print(f"Total Tests: {summary.get('total_tests', 0)}")
        print(f"Passed: {summary.get('passed_tests', 0)}")
        print(f"Failed: {summary.get('failed_tests', 0)}")
        print(f"Success Rate: {summary.get('success_rate', 0):.1f}%")
        print("="*60)
        
        # Print detailed results by category
        for category, tests in results.items():
            if category in ["timestamp", "summary"]:
                continue
                
            print(f"\n{category.upper().replace('_', ' ')}:")
            print("-" * 40)
            
            for test_name, result in tests.items():
                success = result.get("success", False) or result.get("running", False)
                status = "✅ PASS" if success else "❌ FAIL"
                print(f"  {test_name}: {status}")
                
                if not success and "error" in result:
                    print(f"    Error: {result['error']}")

def main():
    """Main test runner"""
    tester = SimpleSeedCoreTester()
    
    try:
        results = tester.run_all_tests()
        tester.print_summary(results)
        
        # Save results to file
        with open("test_results_simple.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\nDetailed results saved to: test_results_simple.json")
        
        # Exit with appropriate code
        summary = results.get("summary", {})
        success_rate = summary.get("success_rate", 0)
        
        if success_rate >= 90:
            print("🎉 All critical features are working!")
            sys.exit(0)
        elif success_rate >= 70:
            print("⚠️  Most features are working, but some issues detected.")
            sys.exit(1)
        else:
            print("❌ Significant issues detected. Please check the results.")
            sys.exit(2)
            
    except KeyboardInterrupt:
        print("\n⚠️  Testing interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Testing failed with error: {e}")
        sys.exit(2)

if __name__ == "__main__":
    main() 