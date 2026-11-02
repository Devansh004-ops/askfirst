import pytest

from askfirst import Engine, ReadOnlyDB, load_domain
from askfirst.domains.library.seed import generate
from askfirst.model import SQLRequest


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "library.db"
    generate(path, seed=7, today="2026-01-15")
    return path


@pytest.fixture(scope="session")
def domain():
    return load_domain("library")


@pytest.fixture
def db(demo_db):
    handle = ReadOnlyDB(demo_db)
    yield handle
    handle.close()


class FakeProvider:
    """Returns scripted SQL and records every request it receives."""

    name = "fake"

    def __init__(self, *sqls, probe_rule=None):
        self.sqls = list(sqls)
        self.requests: list = []
        self.probe_rule = probe_rule

    def generate_sql(self, request: SQLRequest) -> str:
        self.requests.append(request)
        item = self.sqls.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def probe(self, question, schema):
        return self.probe_rule


@pytest.fixture
def make_engine(domain, db):
    def _make(provider, **kwargs):
        return Engine(domain, db, provider, **kwargs)
    return _make
