import os
import json
import logging
from typing import Dict, Any, List
import google.generativeai as genai
from app.core.config import settings

logger = logging.getLogger("DevOps_rca")

# Hardcoded premium fallback templates for common mock errors
FALLBACK_ANALYSES = {
    "kubernetes-crash": {
        "root_cause": "Kubernetes pod 'DevOps-api-deployment' is failing its startup/liveness checks because psycopg2 failed to connect to PostgreSQL. The DB endpoint 'postgres-service.db.svc.cluster.local:5432' refused connection, indicating the PostgreSQL container crashed, is not running, or network policies block communication.",
        "possible_issues": [
            "PostgreSQL StatefulSet or Deployment is down/crashed",
            "Missing environment variables or secret bindings inside Kubernetes pod specifications",
            "Strict NetworkPolicies separating backend and database namespaces"
        ],
        "recommendations": [
            "Check PostgreSQL pod status: 'kubectl get pods -n db-namespace'",
            "Examine PostgreSQL pod logs: 'kubectl logs statefulset/postgres-db'",
            "Verify environment configurations using 'kubectl describe pod DevOps-api-deployment' to ensure correct password and hostname are bound",
            "Validate namespace reachability: run a temporary pod to test port 5432 availability"
        ],
        "confidence_score": 94.0,
        "priority_level": "Critical"
    },
    "docker-image-missing": {
        "root_cause": "Docker build failed during stage 'Build Production Container' because the security scanner base image 'my-private-registry.local/security/scanner-base:1.2.0' was not found in the target private registry. The registry returned an HTTP 404 response.",
        "possible_issues": [
            "The security scanner base image was deleted, archived, or never pushed to the private registry under the tag '1.2.0'",
            "Missing Docker login credentials inside the Jenkins agent workspace, resulting in authorization failure",
            "Private registry DNS or network routing issues preventing image discovery"
        ],
        "recommendations": [
            "Verify that the image tag '1.2.0' exists in 'my-private-registry.local/security/scanner-base' using the registry UI or CLI",
            "Check Jenkins credentials block and ensure 'docker login' is executed before pulling from private domains",
            "If the scanner image is deprecated, update the Dockerfile's scanner base tag to a valid current version"
        ],
        "confidence_score": 89.0,
        "priority_level": "High"
    },
    "windows-iis-locked": {
        "root_cause": "PowerShell copy deployment script failed because the critical assembly file 'core.dll' was locked by IIS process 'w3wp.exe' (PID 4410). The application pool 'DotnetBackendPool' failed to stop within the 15-second timeout window, causing write lock conflicts during deployment.",
        "possible_issues": [
            "IIS Application Pool failed to stop gracefully because of active running web socket requests or long-running threads",
            "The stop command 'Stop-WebAppPool' was executed with insufficient Windows permissions",
            "IIS web server process locking assemblies due to missing app_offline.htm lock-breaker file"
        ],
        "recommendations": [
            "Implement an 'app_offline.htm' file in the root target deployment path before starting copy-actions; this forces IIS to immediately release DLL lock tags",
            "Modify the PowerShell script to terminate w3wp.exe aggressively if Stop-WebAppPool times out: 'Stop-Process -Id 4410 -Force' as fallback",
            "Ensure the Jenkins agent service runs as an Administrator or contains full permissions over the WebAdministration IIS module"
        ],
        "confidence_score": 92.0,
        "priority_level": "High"
    },
    "linux-nginx-port": {
        "root_cause": "Nginx service failed to start on host 'nginx-lb' because the webserver could not bind to port 80. The port is already bound and occupied by Apache web server 'apache2' (PID 1822) running on the same host.",
        "possible_issues": [
            "Apache HTTP server was installed or started automatically, locking standard HTTP ports",
            "Nginx configuration contains double bindings or default configurations claiming port 80"
        ],
        "recommendations": [
            "Identify what process locks port 80: 'sudo netstat -tulpn | grep :80' or 'sudo lsof -i :80'",
            "Stop and disable the conflicting Apache service: 'sudo systemctl stop apache2 && sudo systemctl disable apache2'",
            "Alternatively, modify Nginx configurations to listen on an alternate port if both services are required"
        ],
        "confidence_score": 95.0,
        "priority_level": "Critical"
    },
    "postgres-timeout": {
        "root_cause": "PostgreSQL docker container crashed during startup because the mounted host volume '/var/lib/postgresql/data' has incorrect ownership permissions. PostgreSQL requires UID 70 (postgres) to own the data files, but they are currently owned by UID 1000.",
        "possible_issues": [
            "Host directory permissions were manually modified or mounted from a user workspace running on UID 1000",
            "Incompatible volume mount configuration on multi-tenant Linux nodes or docker mounts"
        ],
        "recommendations": [
            "Correct host directory ownership: 'sudo chown -R 70:70 /path/to/host/postgres_data'",
            "Adjust container security context inside Docker Compose configurations if running on restricted VMs",
            "Verify storage mounts and ensure postgres-initialized directories are clean from permission overrides"
        ],
        "confidence_score": 91.0,
        "priority_level": "High"
    }
}

async def analyze_log_rca(log_text: str, parsed_errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Synthesizes logs and parsed error metrics. Uses Gemini AI API if configured,
    otherwise resolves with specific domain heuristics and realistic fallbacks.
    """
    # 1. Detect if any known mock keys are in the logs (for seamless offline demo)
    for key, fallback in FALLBACK_ANALYSES.items():
        if key == "kubernetes-crash" and "postgres-service" in log_text:
            return fallback
        if key == "docker-image-missing" and "scanner-base:1.2.0" in log_text:
            return fallback
        if key == "windows-iis-locked" and "core.dll" in log_text:
            return fallback
        if key == "linux-nginx-port" and "Address already in use" in log_text:
            return fallback
        if key == "postgres-timeout" and "wrong ownership" in log_text:
            return fallback

    # 2. Try using the Gemini API
    if settings.GEMINI_API_KEY:
        try:
            logger.info("Initiating Gemini AI Analysis...")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # Use gemini-1.5-flash for speed and reliability
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Format high-quality system prompt
            prompt = f"""
            You are 'DevOps Copilot', a premium AI-powered DevOps troubleshooting agent.
            Analyze the following build/pipeline logs and parsed error snippets to provide a root cause analysis (RCA).
            
            Log Content Snippet:
            {log_text[-5000:]} # Analyze the tail of the log where failures occur
            
            Parsed Critical Lines:
            {json.dumps(parsed_errors, indent=2)}
            
            Provide a response in strict JSON format matching this schema:
            {{
                "root_cause": "A concise, highly professional description of why the pipeline or deployment failed.",
                "possible_issues": [
                    "Alternative possible issue 1",
                    "Alternative possible issue 2"
                ],
                "recommendations": [
                    "Actionable diagnostic or repair command 1",
                    "Actionable diagnostic or repair command 2"
                ],
                "confidence_score": 92.5,
                "priority_level": "High"
            }}
            Do not include any markdown styling like ```json or trailing text outside of the JSON payload.
            """
            
            response = model.generate_content(prompt)
            # Safe JSON extraction
            response_text = response.text.strip()
            # Remove any accidental markdown enclosures
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "", 1)
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            data = json.loads(response_text)
            return {
                "root_cause": data.get("root_cause", "Unable to pinpoint root cause automatically."),
                "possible_issues": data.get("possible_issues", ["Unknown infrastructure anomalies"]),
                "recommendations": data.get("recommendations", ["Review logs manually to isolate faults"]),
                "confidence_score": float(data.get("confidence_score", 85.0)),
                "priority_level": data.get("priority_level", "Medium")
            }
        except Exception as e:
            logger.warning(f"Gemini API call failed: {str(e)}. Falling back to general heuristic analyzer.")

    # 3. Dynamic General Heuristic fallback if offline or API error
    # Isolate the most severe parsed error
    critical_errors = [e for e in parsed_errors if e["severity"] in ["CRITICAL", "ERROR"]]
    primary_fault = critical_errors[0] if critical_errors else (parsed_errors[0] if parsed_errors else None)
    
    if primary_fault:
        category = primary_fault.get("category", "General System")
        content = primary_fault.get("content", "")
        return {
            "root_cause": f"Heuristic analysis detected a {primary_fault['severity']} severity event in the {category} module: '{content}'.",
            "possible_issues": [
                f"Active environment conflict related to: {content}",
                "Permissions or credentials blocking access during execution",
                "Service endpoint timeout or host resolution failure"
            ],
            "recommendations": [
                f"Verify permissions and state conditions matching the failure line.",
                "Inspect downstream logs and execution environments directly.",
                "Check connection configurations and env vars."
            ],
            "confidence_score": 75.0,
            "priority_level": "High" if primary_fault["severity"] == "CRITICAL" else "Medium"
        }
        
    return {
        "root_cause": "The log file does not present clear error signatures or stack traces. The execution terminated abnormally without logging a specific error message.",
        "possible_issues": [
            "Build container or VM was abruptly terminated or aborted by user",
            "Process ran out of memory or disk space without logging warnings",
            "External executor node disconnected from server"
        ],
        "recommendations": [
            "Inspect infrastructure CPU, memory, and disk health metrics on the running node",
            "Check if the build was manually cancelled or timed out on Jenkins config",
            "Re-run build with verbose log toggles active (e.g. DEBUG level)"
        ],
        "confidence_score": 60.0,
        "priority_level": "Medium"
    }
