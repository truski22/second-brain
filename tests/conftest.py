import httpx
import pytest


from tenet_harness.testing import FakeModel, FakeProvider  # noqa: F401


class FakeMemory:
    def __init__(self, *args):
        self.items = []

    def search(self, query, minimum=0.5):
        return self.items

    def list(self, offset=0, limit=50):
        return self.items[offset:offset + limit]

    def delete(self, memory_id):
        self.items = [item for item in self.items if item["id"] != memory_id]

    def memorize(self, job):
        return []


@pytest.fixture
def provider():
    return FakeProvider()


# Fake GitLab REST API shared by unit and API tests.
TOKEN = "glpat-test-token-000000"
MR = {"iid": 7, "title": "Fix login", "state": "opened", "draft": False, "author": {"username": "ana"},
      "reviewers": [{"username": "me"}], "detailed_merge_status": "mergeable", "source_branch": "fix",
      "target_branch": "main", "updated_at": "2026-09-29T10:11:12Z", "web_url": "https://git.example/g/app/-/merge_requests/7",
      "references": {"full": "g/sub/app!7"}, "description": "d" * 3000,
      "head_pipeline": {"id": 99, "status": "failed"}}


def gitlab_api(requests: list[httpx.Request]):
    def handler(request: httpx.Request):
        requests.append(request)
        if request.headers.get("PRIVATE-TOKEN") != TOKEN:
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        path = request.url.raw_path.decode().split("?")[0]
        if path == "/api/v4/user":
            return httpx.Response(200, json={"id": 1, "username": "me"})
        if path == "/api/v4/merge_requests":
            return httpx.Response(200, json=[MR])
        if path == "/api/v4/projects/g%2Fsub%2Fapp/merge_requests/7":
            return httpx.Response(200, json=MR)
        return httpx.Response(404, json={"message": "404 Not found"})
    return httpx.MockTransport(handler)
