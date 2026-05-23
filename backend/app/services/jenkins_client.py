import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import random
from urllib.parse import quote
from app.core.config import settings

class JenkinsClient:
    def __init__(self, url: str, username: Optional[str] = None, api_token: Optional[str] = None):
        self.url = url
        self.username = username
        self.api_token = api_token
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
        """
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
        """
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

    async def get_latest_build(
        self, job_name: str, job_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch *only* the latest build of a job in a single HTTP call.

        Hits Jenkins's `lastBuild/api/json` shortcut which already includes
        result + duration + timestamp, so we don't need a second per-build
        round-trip. Used by the 10-second poll loop where the cheaper path
        matters.

        Returns a dict with the same shape as items in get_builds() output,
        or None if Jenkins has no builds for this job yet.
        """
        base = job_url.rstrip("/") if job_url else f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}"
        target = f"{base}/lastBuild/api/json"
        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(target, timeout=settings.JENKINS_TIMEOUT_SECONDS)
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out fetching latest build for {job_name} from Jenkins at {self.url}") from e
            except Exception as e:
                raise Exception(f"Failed to fetch latest build for {job_name}: {str(e)}")
            if response.status_code == 404:
                # Job exists but has never built — Jenkins returns 404 on lastBuild.
                return None
            if response.status_code != 200:
                raise Exception(
                    f"Jenkins returned {response.status_code} fetching latest build for {job_name}"
                )
            data = response.json()
            return {
                "number": data.get("number"),
                "status": data.get("result") or "RUNNING",
                "duration": data.get("duration", 0),
                "timestamp": datetime.fromtimestamp(data.get("timestamp", 0) / 1000.0)
                if data.get("timestamp")
                else datetime.utcnow(),
            }

    async def get_build_details(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch build metadata + the full list of commit authors that went into
        this build.

        `developer_emails` is a list of all unique authorEmails across every
        commit in `changeSets[].items`, preserved in commit order. If a build
        had 3 commits from 3 different developers, all 3 appear here — and the
        NOTIFY stage emails all of them. The list is empty when Jenkins
        couldn't resolve authors (manual builds, cron triggers, missing git
        plugin data).
        """
        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                response = await client.get(f"{self._build_base_url(job_name, build_number, job_url)}/api/json", timeout=settings.JENKINS_TIMEOUT_SECONDS)
                if response.status_code != 200:
                    return {}
                data = response.json()

                # Walk every commit and collect unique author emails in order.
                developer_emails: List[str] = []
                seen: set[str] = set()
                change_sets = list(data.get("changeSets") or [])
                if data.get("changeSet"):
                    change_sets.append(data["changeSet"])
                for change_set in change_sets:
                    for item in change_set.get("items", []):
                        author_email = (item.get("authorEmail") or "").strip()
                        if author_email and author_email not in seen:
                            developer_emails.append(author_email)
                            seen.add(author_email)

                return {
                    "number": data.get("number", build_number),
                    "result": data.get("result"),
                    "building": data.get("building", False),
                    "developer_emails": developer_emails,
                    "url": data.get("url"),
                }
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out fetching Jenkins build details for {job_name}#{build_number}") from e
            except Exception as e:
                raise Exception(f"Failed to fetch build details for {job_name}#{build_number}: {str(e)}")

    async def trigger_build(self, job_name: str, job_url: Optional[str] = None) -> bool:
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

    async def wipe_workspace(self, job_name: str, job_url: Optional[str] = None) -> bool:
        """
        Ask Jenkins to wipe out the job's workspace via the
        `doWipeOutWorkspace` endpoint. Used by the agent's
        WORKSPACE_LOCKED playbook before a retry. Same crumb-auth pattern
        as trigger_build.
        """
        target_url = (
            f"{job_url.rstrip('/')}/doWipeOutWorkspace"
            if job_url
            else f"{self.url.rstrip('/')}/job/{quote(job_name, safe='')}/doWipeOutWorkspace"
        )
        async with httpx.AsyncClient(headers=self.headers, verify=False) as client:
            try:
                crumb_headers = await self._get_crumb_headers(client)
                response = await client.post(
                    target_url,
                    headers={**self.headers, **crumb_headers},
                    timeout=settings.JENKINS_TIMEOUT_SECONDS,
                )
                return response.status_code in {200, 201, 202, 302}
            except httpx.ConnectTimeout as e:
                raise Exception(f"Timed out wiping workspace for {job_name}") from e
            except Exception as e:
                raise Exception(f"Failed to wipe workspace for {job_name}: {str(e)}")

    async def get_console_output(self, job_name: str, build_number: int, job_url: Optional[str] = None) -> str:
        """
        Fetches the raw console log text for a specific build.
        """
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
