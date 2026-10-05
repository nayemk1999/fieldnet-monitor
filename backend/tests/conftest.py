import pytest
from rest_framework.test import APIClient

from tests.harness import Harness


@pytest.fixture
def h(db):
    return Harness(APIClient())
