import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import random
from urllib.parse import quote
from app.core.config import settings

# Realistic mockup logs that map to classic DevOps failures
MOCK_LOGS = {
    "kubernetes-crash": """
Started by user DevOps-Lead
Running as SYSTEM
Building in workspace /var/jenkins_home/workspace/kubernetes-microservices
[WS-CLEAN] Deleting project workspace...
Cloning the remote Git repository
Cloning repository https://github.com/company/microservices-deploy.git
 > git init /var/jenkins_home/workspace/kubernetes-microservices # timeout=10
Fetching upstream changes from https://github.com/company/microservices-deploy.git
 > git config --local core.worktree /var/jenkins_home/workspace/kubernetes-microservices
Checking out Revision c38290fa83 (origin/main)
[Pipeline] node
[Pipeline] stage (Build Container)
[Pipeline] sh
+ docker build -t DevOps-api:1.4.2 .
Sending build context to Docker daemon  24.5kB
Step 1/8 : FROM python:3.12-alpine
 ---> a9d238a83a00
Step 2/8 : WORKDIR /app
 ---> Using cache
Step 3/8 : COPY requirements.txt .
 ---> Using cache
Step 4/8 : RUN pip install --no-cache-dir -r requirements.txt
 ---> Using cache
Step 5/8 : COPY . .
 ---> 1d2938a192bc
Step 6/8 : EXPOSE 8000
 ---> Running in dfc92c8192a0
 ---> fd29cf291ab2
Step 7/8 : CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
 ---> Running in ffa823ca839a
 ---> ad928c291ba2
Successfully built ad928c291ba2
Successfully tagged DevOps-api:1.4.2
[Pipeline] stage (Push to Local Registry)
[Pipeline] sh
+ docker tag DevOps-api:1.4.2 localhost:5000/DevOps-api:1.4.2
+ docker push localhost:5000/DevOps-api:1.4.2
The push refers to repository [localhost:5000/DevOps-api]
f1ba28d9c283: Pushed
ad928c291ba2: Pushed
1.4.2: digest: sha256:d8c0b78c93a02a83290fb918a280c71a39f1c7901828109bf21a8d019318b762 size: 739
[Pipeline] stage (K8s Rolling Deploy)
[Pipeline] sh
+ kubectl apply -f k8s/deployment.yaml
deployment.apps/DevOps-api-deployment configured
service/DevOps-api-service configured
+ kubectl rollout status deployment/DevOps-api-deployment --timeout=30s
Waiting for deployment "DevOps-api-deployment" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "DevOps-api-deployment" rollout to finish: 1 of 3 updated replicas are available...
ERROR: Deployment rollout failed within timeout!
+ kubectl get pods -l app=DevOps-api
NAME                                    READY   STATUS             RESTARTS   AGE
DevOps-api-deployment-7fbd8928c-abcde    0/1     CrashLoopBackOff   4          2m
DevOps-api-deployment-7fbd8928c-fghij    1/1     Running            0          2m
DevOps-api-deployment-7fbd8928c-klmno    0/1     CrashLoopBackOff   3          1m
+ kubectl logs DevOps-api-deployment-7fbd8928c-abcde --tail=20
Traceback (most recent call last):
  File "/app/main.py", line 14, in <module>
    from app.database import engine
  File "/app/app/database.py", line 8, in <module>
    conn = psycopg2.connect(
  File "/usr/local/lib/python3.12/site-packages/psycopg2/__init__.py", line 122, in connect
    conn = _connect(dsn, connection_factory=connection_factory, **kwasync)
psycopg2.OperationalError: connection to server at "postgres-service.db.svc.cluster.local" (10.96.241.12), port 5432 failed: Connection refused
	Is the server running on that host and accepting TCP/IP connections?

CRITICAL: Application terminated: Database connection failed.
Liveness probe failed: HTTP probe failed with statuscode: 500
Container crashed. CrashLoopBackOff detected.
[Pipeline] }
[Pipeline] // node
[Pipeline] End of Pipeline
ERROR: Build step failed with exit code 1
Finished: FAILURE
""",

    "docker-image-missing": """
Started by webhook git-commit-3f82e
Running as SYSTEM
Building in workspace /var/jenkins_home/workspace/frontend-ci-cd
Cloning remote repository https://github.com/company/frontend-web.git
Checking out Revision 8f921abcf
[Pipeline] stage (Install Tools)
+ npm ci
added 1240 packages in 18s
[Pipeline] stage (Run Tests)
+ npm test -- --watchAll=false
Passes: 42, Failed: 0, Pending: 0
[Pipeline] stage (Build Web Artifacts)
+ npm run build
Vite v5.1.4 building for production...
✓ 412 modules transformed.
dist/index.html                  0.85 kB │ gzip:  0.42 kB
dist/assets/index-D8c12a83.js  340.21 kB │ gzip: 98.41 kB
dist/assets/index-C9a28c29.css  52.12 kB │ gzip: 12.11 kB
[Pipeline] stage (Build Production Container)
[Pipeline] sh
+ docker build --build-arg VITE_API_URL=https://api.copilot.local -t copilot-web:latest .
Sending build context to Docker daemon 4.2MB
Step 1/10 : FROM nginx:alpine
 ---> b12cda12a281
Step 2/10 : COPY dist/ /usr/share/nginx/html/
 ---> 2cf8da29c782
Step 3/10 : FROM my-private-registry.local/security/scanner-base:1.2.0 AS scan
ERROR: Error response from daemon: manifest for my-private-registry.local/security/scanner-base:1.2.0 not found
Failed to resolve image pull target: my-private-registry.local/security/scanner-base:1.2.0
The registry returned 404 Not Found.
ERROR: image pull failed for security scanner image base.
Verify if the image tags on private registry match or check repository visibility settings.
[Pipeline] }
[Pipeline] // node
[Pipeline] End of Pipeline
ERROR: Build step failed with exit code 1
Finished: FAILURE
""",

    "windows-iis-locked": """
Started by user Windows-Deploy-Agent
Running on Windows Server 2022 node WIN-VM-DEPLOY04
Building in workspace C:\\jenkins\\workspace\\iis-dotnet-api
Fetching Git changes...
Checking out revision a39cd7f1
[Pipeline] stage (Nuget Restore)
C:\\jenkins\\workspace\\iis-dotnet-api> nuget restore api.sln
All packages restored successfully.
[Pipeline] stage (MSBuild Build)
C:\\jenkins\\workspace\\iis-dotnet-api> msbuild api.sln /p:Configuration=Release
Build succeeded.
    0 Warning(s)
    0 Error(s)
[Pipeline] stage (Deploy to IIS)
+ powershell -Command "Stop-WebAppPool -Name 'DotnetBackendPool'"
+ powershell -Command "Copy-Item -Path .\\api\\bin\\Release\\* -Destination C:\\inetpub\\wwwroot\\api -Recurse -Force"
Copy-Item : The process cannot access the file 'C:\\inetpub\\wwwroot\\api\\bin\\Release\\core.dll' because it is being used by another process.
At line:1 char:1
+ Copy-Item -Path .\\api\\bin\\Release\\* -Destination C:\\inetpub\\...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : WriteError: (C:\\inetpub\\wwwroot\\api\\bin\\Release\\core.dll:FileInfo) [Copy-Item], IOException
    + FullyQualifiedErrorId : CopyFileInfoItemIOError,Microsoft.PowerShell.Commands.CopyItemCommand

IIS Deployment Failure: Lock conflict detected on core assemblies.
ERROR: The copy target file is locked. Application pool 'DotnetBackendPool' failed to stop within grace period of 15 seconds.
Port lock check: 
Port 443 is currently active and occupied by PID 4410 (w3wp.exe)
Powershell execution failed with exit code 0x80070020
[Pipeline] // node
Finished: FAILURE
""",

    "linux-nginx-port": """
Started by scheduler trigger
Running as SYSTEM
Building on linux-agent-02
[Pipeline] stage (Nginx Deploy)
+ scp config/nginx.conf devops@nginx-lb:/etc/nginx/nginx.conf
+ ssh devops@nginx-lb "sudo systemctl reload nginx"
Job for nginx.service failed because the control process exited with error code.
See "systemctl status nginx.service" and "journalctl -xeu nginx.service" for details.
+ ssh devops@nginx-lb "sudo systemctl status nginx.service"
● nginx.service - A high performance web server and a reverse proxy server
     Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
     Active: failed (Result: exit-code) since Wed 2026-05-20 22:04:12 UTC; 4s ago
    Process: 9140 ExecStartPre=/usr/sbin/nginx -t -q -g daemon on; master_process on; (code=exited, status=1/FAILURE)

May 20 22:04:12 nginx-lb systemd[1]: Starting A high performance web server...
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
May 20 22:04:12 nginx-lb nginx[9140]: nginx: [emerg] still could not bind()
May 20 22:04:12 nginx-lb systemd[1]: nginx.service: Control process exited, code=exited, status=1/FAILURE
May 20 22:04:12 nginx-lb systemd[1]: nginx.service: Failed with result 'exit-code'.
May 20 22:04:12 nginx-lb systemd[1]: Failed to start A high performance web server.

ERROR: Nginx failed to bind to port 80. PID 1822 (apache2) is already listening on port 80.
Port conflict detected. Exiting script.
Finished: FAILURE
""",

    "postgres-timeout": """
Started by user Admin
Running as SYSTEM
[Pipeline] stage (Deploy Service)
+ docker-compose -f docker/docker-compose.prod.yml up -d
Creating network "prod_network" with driver "bridge"
Creating volume "prod_postgres_data" with default driver
Pulling database (postgres:15-alpine)...
15-alpine: Pulling from library/postgres
Digest: sha256:d8c0b78c93a02a83290fb918a280c71a39f1c7901828109bf21a8d019318b762
Status: Downloaded newer image for postgres:15-alpine
Creating prod_db_1 ... done
Creating prod_api_1 ... done
+ docker-compose -f docker/docker-compose.prod.yml ps
NAME         IMAGE                COMMAND                  SERVICE    CREATED        STATUS                  PORTS
prod_api_1   prod-api:latest      "python main.py"         api        3 seconds ago  Up 2 seconds            0.0.0.0:8000->8000/tcp
prod_db_1    postgres:15-alpine   "docker-entrypoint.s…"   db         3 seconds ago  Restarting (1) 1 sec ago
+ docker logs prod_db_1
PostgreSQL Database directory appears to contain a database; Skipping initialization

FATAL:  data directory "/var/lib/postgresql/data" has wrong ownership
DETAIL:  The server must be started by the user that owns the data directory (UID 70) or by root.
Expected owner UID 70, actual owner UID 1000.
ERROR: database container crashed. Disk permission issues or Volume mount owner mismatch.
Finished: FAILURE
"""
}

class JenkinsClient:
    def __init__(self, url: str, username: Optional[str] = None, api_token: Optional[str] = None, use_mock: bool = False):
        self.url = url
        self.username = username
        self.api_token = api_token
        self.use_mock = use_mock
        self.headers = {}
        if username and api_token:
            # Set up HTTP Basic auth headers
            import base64
            auth_str = f"{username}:{api_token}"
            encoded_auth = base64.b64encode(auth_str.encode()).decode()
            self.headers["Authorization"] = f"Basic {encoded_auth}"

    @staticmethod
    def _job_status_from_color(color: Optional[str]) -> str:
        if not color:
            return "UNKNOWN"

        normalized = color.replace("_anime", "").lower()
        if normalized == "blue":
            return "SUCCESS"
        if normalized == "red":
            return "FAILURE"
        if normalized in {"aborted", "disabled"}:
            return "ABORTED"
        if normalized in {"yellow", "notbuilt"}:
            return "UNKNOWN"
        return "RUNNING"

    def _job_api_url(self, job_name: str, job_url: Optional[str] = None) -> str:
        if job_url:
            return f"{job_url.rstrip('/')}/api/json"
        return f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}/api/json"

    def _console_url(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> str:
        if job_url:
            return f"{job_url.rstrip('/')}/{build_number}/logText/progressiveText"
        return f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}/{build_number}/logText/progressiveText"

    def _build_base_url(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> str:
        if job_url:
            return f"{job_url.rstrip('/')}/{build_number}"
        return f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}/{build_number}"

    async def _get_crumb_headers(self, client: httpx.AsyncClient) -> Dict[str, str]:
        try:
            response = await client.get(f"{self.url.rstrip('/')}/crumbIssuer/api/json", timeout=5)
            if response.status_code != 200:
                return {}
            data = response.json()
            field = data.get("crumbRequestField")
            crumb = data.get("crumb")
            if field and crumb:
                return {field: crumb}
        except Exception:
            return {}
        return {}

    async def get_jobs(self) -> List[Dict[str, Any]]:
        """
        Fetches the complete job list from Jenkins.
        Uses mocked metadata if use_mock is active.
        """
        if self.use_mock:
            return [
                {"name": "kubernetes-microservices", "url": f"{self.url}/job/kubernetes-microservices", "last_status": "FAILURE"},
                {"name": "frontend-ci-cd", "url": f"{self.url}/job/frontend-ci-cd", "last_status": "FAILURE"},
                {"name": "iis-dotnet-api", "url": f"{self.url}/job/iis-dotnet-api", "last_status": "FAILURE"},
                {"name": "nginx-loadbalancer", "url": f"{self.url}/job/nginx-loadbalancer", "last_status": "FAILURE"},
                {"name": "production-database-deploy", "url": f"{self.url}/job/production-database-deploy", "last_status": "FAILURE"},
                {"name": "analytics-worker-pipeline", "url": f"{self.url}/job/analytics-worker-pipeline", "last_status": "SUCCESS"}
            ]
        
        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(f"{self.url}/api/json", timeout=settings.JENKINS_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    data = response.json()
                    jobs = []
                    for item in data.get("jobs", []):
                        jobs.append({
                            "name": item.get("name"),
                            "url": item.get("url"),
                            "last_status": self._job_status_from_color(item.get("color"))
                        })
                    return jobs
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out connecting to Jenkins at {self.url}") from e
            except Exception as e:
                raise Exception(f"Failed to connect to Jenkins server: {str(e)}")
        return []

    async def get_builds(self, job_name: str, job_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches the build list for a specific Jenkins job.
        Generates realistic history in mock mode.
        """
        if self.use_mock:
            status_map = {
                "kubernetes-microservices": ["FAILURE", "SUCCESS", "FAILURE", "SUCCESS"],
                "frontend-ci-cd": ["FAILURE", "SUCCESS", "SUCCESS", "SUCCESS"],
                "iis-dotnet-api": ["FAILURE", "FAILURE", "SUCCESS", "SUCCESS"],
                "nginx-loadbalancer": ["FAILURE", "SUCCESS", "FAILURE", "SUCCESS"],
                "production-database-deploy": ["FAILURE", "SUCCESS", "SUCCESS", "SUCCESS"],
                "analytics-worker-pipeline": ["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS"]
            }
            statuses = status_map.get(job_name, ["SUCCESS", "SUCCESS"])
            
            builds = []
            now = datetime.utcnow()
            for idx, status in enumerate(statuses):
                builds.append({
                    "number": 105 - idx,
                    "status": status,
                    "duration": random.randint(15000, 120000), # in ms
                    "timestamp": now - timedelta(days=idx, hours=idx*2)
                })
            return builds

        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(self._job_api_url(job_name, job_url), timeout=settings.JENKINS_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    data = response.json()
                    builds = []
                    for build in data.get("builds", [])[:10]: # Fetch last 10 builds
                        num = build.get("number")
                        # Fetch individual build details to resolve status
                        build_url = build.get("url")
                        detail_url = f"{build_url.rstrip('/')}/api/json" if build_url else f"{self._job_api_url(job_name, job_url).removesuffix('/api/json')}/{num}/api/json"
                        build_response = await client.get(detail_url, timeout=settings.JENKINS_TIMEOUT_SECONDS)
                        status = "RUNNING"
                        duration = 0
                        timestamp = datetime.utcnow()
                        if build_response.status_code == 200:
                            b_data = build_response.json()
                            status = b_data.get("result", "RUNNING")
                            duration = b_data.get("duration", 0)
                            timestamp = datetime.fromtimestamp(b_data.get("timestamp", 0) / 1000.0)
                        
                        builds.append({
                            "number": num,
                            "status": status if status else "RUNNING",
                            "duration": duration,
                            "timestamp": timestamp
                        })
                    return builds
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out fetching builds for job {job_name} from Jenkins at {self.url}") from e
            except Exception as e:
                raise Exception(f"Failed to fetch builds for job {job_name}: {str(e)}")
        return []

    async def get_build_details(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> Dict[str, Any]:
        if self.use_mock:
            return {
                "number": build_number,
                "result": "FAILURE" if build_number == 105 else "SUCCESS",
                "building": False,
                "developer_email": None,
            }

        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(f"{self._build_base_url(job_name, build_number, job_url)}/api/json", timeout=settings.JENKINS_TIMEOUT_SECONDS)
                if response.status_code != 200:
                    return {}
                data = response.json()
                developer_email = None
                change_sets = data.get("changeSets") or []
                if data.get("changeSet"):
                    change_sets.append(data["changeSet"])
                for change_set in change_sets:
                    for item in change_set.get("items", []):
                        author_email = item.get("authorEmail")
                        if author_email:
                            developer_email = author_email
                            break
                    if developer_email:
                        break
                return {
                    "number": data.get("number", build_number),
                    "result": data.get("result"),
                    "building": data.get("building", False),
                    "developer_email": developer_email,
                    "url": data.get("url"),
                }
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out fetching Jenkins build details for {job_name}#{build_number}") from e
            except Exception as e:
                raise Exception(f"Failed to fetch build details for {job_name}#{build_number}: {str(e)}")

    async def trigger_build(self, job_name: str, job_url: Optional[str] = None) -> bool:
        if self.use_mock:
            return True

        target_url = f"{job_url.rstrip('/')}/build" if job_url else f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}/build"
        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                crumb_headers = await self._get_crumb_headers(client)
                response = await client.post(target_url, headers={**self.headers, **crumb_headers}, timeout=settings.JENKINS_TIMEOUT_SECONDS)
                return response.status_code in {200, 201, 202, 302}
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out triggering Jenkins build for {job_name}") from e
            except Exception as e:
                raise Exception(f"Failed to trigger Jenkins build for {job_name}: {str(e)}")

    async def get_console_output(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> str:
        """
        Fetches the raw console log text for a specific build.
        Extracts corresponding DevOps failure logs in mock mode.
        """
        if self.use_mock:
            mapping = {
                "kubernetes-microservices": "kubernetes-crash",
                "frontend-ci-cd": "docker-image-missing",
                "iis-dotnet-api": "windows-iis-locked",
                "nginx-loadbalancer": "linux-nginx-port",
                "production-database-deploy": "postgres-timeout"
            }
            log_key = mapping.get(job_name, "kubernetes-crash")
            # If it's a SUCCESS build, just return standard mock success log
            build_status_map = {
                "kubernetes-microservices": 105, # failure is 105
                "frontend-ci-cd": 105,
                "iis-dotnet-api": 105,
                "nginx-loadbalancer": 105,
                "production-database-deploy": 105
            }
            target_fail_num = build_status_map.get(job_name, 105)
            
            if build_number != target_fail_num:
                return f"""Started by user DevOps-Lead
Running as SYSTEM
Building in workspace /var/jenkins_home/workspace/{job_name}
Cloning git repository... success
Checking out Revision a39bc8b9
[Pipeline] stage (Build)
+ npm run build --prod
Success building assets.
[Pipeline] stage (Deploy)
+ docker stack deploy -c docker-compose.prod.yml webapp
Updating service webapp_frontend (id: 1a2b3c4d5e)
Updating service webapp_backend (id: f6g7h8i9j0)
Deployment complete. Rolling update initiated.
Finished: SUCCESS
"""
            return MOCK_LOGS.get(log_key, "Console output mock log not found.")

        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(self._console_url(job_name, build_number, job_url), timeout=settings.JENKINS_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    return response.text
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out fetching console log for {job_name}#{build_number}") from e
            except Exception as e:
                raise Exception(f"Failed to fetch console log for {job_name}#{build_number}: {str(e)}")
        return ""
