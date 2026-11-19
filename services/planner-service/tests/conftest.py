import pytest


@pytest.fixture
def anyio_backend() -> str:
    # The async tests run on asyncio only.
    return "asyncio"
